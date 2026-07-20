"""Entry point.

    python run.py fetch                  # scrape + filter + store
    python run.py score [--limit N] [--model M]  # LLM scoring
    python run.py list                   # show pipeline state
    python run.py list scored            # scored jobs sorted by total desc
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import yaml

# Windows console: force UTF-8 so Unicode in job descriptions doesn't crash
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import db
from models import JobStatus
from pipeline import filters
from pipeline import score as scoring
from sources import jobspy_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run")


def load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def cmd_fetch(cfg: dict) -> None:
    new, dupes, filtered = 0, 0, 0
    with db.get_conn() as conn:
        for search in cfg["searches"]:
            postings = jobspy_source.fetch(
                search_term=search["term"],
                location=search["location"],
                sites=cfg["sites"],
                results_per_site=cfg["results_per_site"],
                hours_old=cfg["hours_old"],
            )
            for job in postings:
                passed, reason = filters.check(job)
                if not passed:
                    job.status = JobStatus.FILTERED_OUT
                inserted = db.upsert_job(conn, job)
                if not inserted:
                    dupes += 1
                elif passed:
                    new += 1
                else:
                    filtered += 1
                    log.debug("filtered %s @ %s (%s)", job.title, job.company, reason)
    log.info("fetch done: %d new, %d filtered out, %d duplicates", new, filtered, dupes)


def cmd_score(cfg: dict, limit: int | None, model: str | None) -> None:
    scoring.score_jobs(cfg, model=model, limit=limit)


def cmd_list(status_name: str | None) -> None:
    with db.get_conn() as conn:
        if status_name == "scored":
            # Special display: join matches, sort by total descending
            rows = conn.execute(
                """SELECT j.id, j.title, j.company, j.location,
                          m.stack_match, m.seniority_fit, m.location_fit,
                          m.total, m.key_requirements, m.reasoning
                   FROM jobs j JOIN matches m ON j.id = m.job_id
                   WHERE j.status = 'scored'
                   ORDER BY m.total DESC"""
            ).fetchall()
            if not rows:
                print("no scored jobs")
                return
            print(f"\n== scored ({len(rows)}) — sorted by total desc ==")
            for r in rows:
                reqs = json.loads(r["key_requirements"]) if r["key_requirements"] else []
                print(
                    f"\n  [{r['id']}] {r['title']} — {r['company']} ({r['location']})\n"
                    f"    stack={r['stack_match']}  seniority={r['seniority_fit']}  "
                    f"location={r['location_fit']}  TOTAL={r['total']:.2f}\n"
                    f"    reqs: {', '.join(reqs)}\n"
                    f"    reasoning: {r['reasoning']}"
                )
            return

        statuses = [JobStatus(status_name)] if status_name else list(JobStatus)
        for status in statuses:
            rows = db.jobs_with_status(conn, status)
            if not rows:
                continue
            print(f"\n== {status.value} ({len(rows)}) ==")
            for r in rows:
                print(f"  [{r['id']}] {r['title']} — {r['company']} ({r['location']})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="job-agent pipeline")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("fetch", help="scrape + filter + store")

    sp_score = sub.add_parser("score", help="LLM scoring of NEW jobs")
    sp_score.add_argument("--limit", type=int, default=None, help="max jobs to score")
    sp_score.add_argument("--model", type=str, default=None, help="override scoring model")

    sp_list = sub.add_parser("list", help="show pipeline state")
    sp_list.add_argument("status", nargs="?", default=None, help="filter by status")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cmd = args.cmd or "fetch"

    if cmd == "fetch":
        cmd_fetch(load_config())
    elif cmd == "score":
        cmd_score(load_config(), limit=args.limit, model=args.model)
    elif cmd == "list":
        cmd_list(args.status)
    else:
        parse_args().print_help()
