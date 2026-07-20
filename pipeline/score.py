"""v2 — LLM scoring. Iterates NEW jobs, scores via chat_structured, saves results.

Budget for num_ctx=8192 (~6000 usable tokens):
  - system prompt (rubric + CV): ~1500 tokens
  - job description: truncated to ~3500 chars (~1000 tokens)
  - output: ~200 tokens
"""
from __future__ import annotations

import json
import logging
import sqlite3

import yaml
from pydantic import BaseModel, Field

import db
from llm import client
from models import JobStatus, MatchResult

log = logging.getLogger(__name__)

# Truncation limit for job descriptions (chars, not tokens — conservative)
MAX_DESC_CHARS = 3500

RUBRIC_SYSTEM = """\
You are a job-match evaluator. Given a candidate's CV and a job listing,
score the match on three axes. Return ONLY a JSON object with these fields:

  stack_match    (int 0-5)
  seniority_fit  (int 0-5)
  location_fit   (int 0-5)
  key_requirements (list of 2-3 strings: the most specific requirements from the listing)
  reasoning      (string: 2-3 sentences explaining your scores)

### Scoring anchors (use these — do not compress toward the middle)

**stack_match** — how well the candidate's tech stack covers what the listing asks for:
  0 = zero overlap (e.g. listing wants Java/Spring, candidate has Angular/.NET)
  1 = tangential overlap only (e.g. both use JavaScript but different ecosystems)
  2 = same language family but different frameworks (e.g. candidate has Angular, listing wants React — both TypeScript but different ecosystems, muscle memory, and patterns)
  3 = solid overlap on ~half the stack OR strong match on the primary skill
  4 = covers most listed technologies with minor gaps (same frameworks, not just same language)
  5 = near-perfect coverage of the required AND preferred stack

  IMPORTANT: Angular and React are DIFFERENT frameworks. Knowing one does NOT mean knowing the other. Same for Vue. Score framework mismatches as 2, not 3+.

**seniority_fit** — does the candidate's experience level match what the role expects:
  0 = massive mismatch (e.g. junior applying to staff/principal)
  1 = 2+ levels off in either direction
  2 = one level off (e.g. mid applying to senior, or senior to mid)
  3 = plausible fit with some stretch
  4 = good fit — experience matches well
  5 = exact match in years, scope, and responsibility level

**location_fit** — logistics: remote, relocation, visa:
  0 = role in a country candidate cannot work in, no remote option
  1 = wrong country, remote possible but not stated
  2 = right country but role requires on-site in a different city, or unclear remote policy
  3 = right country and city, or confirmed hybrid/remote in the right country
  4 = explicitly remote-friendly within the candidate's target country
  5 = fully remote OR based in the exact target city with relocation support mentioned

Be precise and discriminating. A 3 is average, not a default.
"""


class _LLMScoreOutput(BaseModel):
    """What we ask the LLM to return. No job_id — it doesn't know it."""
    stack_match: int = Field(ge=0, le=5)
    seniority_fit: int = Field(ge=0, le=5)
    location_fit: int = Field(ge=0, le=5)
    key_requirements: list[str] = Field(default_factory=list, max_length=3)
    reasoning: str = ""


def _build_cv_block(cfg: dict) -> str:
    cv = cfg["cv"]
    lines = [
        f"Name: {cv['name']}",
        f"Headline: {cv['headline']}",
        f"Experience: {cv['years_experience']} years",
        f"Stack: {', '.join(cv['stack'])}",
        f"Certs: {', '.join(cv['certifications'])}",
        f"Current role: {cv['current']}",
        f"Previous: {cv['previous']}",
        f"Education: {cv['education']}",
        f"Languages: {', '.join(cv['languages'])}",
    ]
    for note in cv.get("notes", []):
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def _truncate(text: str, limit: int = MAX_DESC_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[...truncated]"


def score_jobs(
    cfg: dict,
    model: str | None = None,
    limit: int | None = None,
) -> None:
    """Score all NEW jobs. Failures logged and skipped — job stays NEW."""
    model = model or cfg["scoring_model"]
    cv_block = _build_cv_block(cfg)

    with db.get_conn() as conn:
        rows = db.jobs_with_status(conn, JobStatus.NEW)
        if limit:
            rows = rows[:limit]

        if not rows:
            log.info("no NEW jobs to score")
            return

        log.info("scoring %d jobs with %s", len(rows), model)

        for row in rows:
            job_id = row["id"]
            title = row["title"]
            company = row["company"]
            desc = _truncate(row["description"] or "")

            user_content = (
                f"## Candidate CV\n{cv_block}\n\n"
                f"## Job Listing\n"
                f"Title: {title}\n"
                f"Company: {company}\n"
                f"Location: {row['location']}\n"
                f"Remote: {'yes' if row['is_remote'] else 'not stated'}\n\n"
                f"### Description\n{desc}"
            )

            try:
                out = client.chat_structured(
                    model=model,
                    system=RUBRIC_SYSTEM,
                    user=user_content,
                    schema=_LLMScoreOutput,
                    timeout=600,  # large models w/ CPU offload need time
                )
            except Exception:
                log.exception("scoring failed for %s (%s @ %s)", job_id, title, company)
                continue

            match = MatchResult(
                job_id=job_id,
                stack_match=out.stack_match,
                seniority_fit=out.seniority_fit,
                location_fit=out.location_fit,
                key_requirements=out.key_requirements,
                reasoning=out.reasoning,
            )
            db.save_match(conn, match)
            db.set_status(conn, job_id, JobStatus.SCORED)
            log.info(
                "  %s @ %s → stack=%d senior=%d loc=%d total=%.2f",
                title, company,
                match.stack_match, match.seniority_fit, match.location_fit,
                match.total,
            )

        conn.commit()
