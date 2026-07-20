"""Rule-based pre-filters. Free to run — they must cut most volume
so the LLM only sees plausible candidates.

Each filter returns (passed: bool, reason: str).
"""
from __future__ import annotations

import re

from models import JobPosting

# Dutch function words that almost never appear in English-language ads.
_DUTCH_MARKERS = re.compile(
    r"\b(wij zoeken|werkzaamheden|vereisten|jouw|onze|binnen ons team|"
    r"salarisindicatie|dienstverband|uur per week)\b",
    re.IGNORECASE,
)

# Hard negative keywords in the title → not the target role.
_TITLE_BLOCKLIST = re.compile(
    r"\b(intern|internship|stage|werkstudent|principal|architect|manager|"
    r"wordpress|php|drupal)\b",
    re.IGNORECASE,
)

# At least one of these must appear somewhere, title or description.
_STACK_SIGNALS = re.compile(
    r"\b(angular|typescript|\.net|c#|csharp|azure|frontend|front-end|"
    r"full[ -]?stack)\b",
    re.IGNORECASE,
)


def check(job: JobPosting) -> tuple[bool, str]:
    if _TITLE_BLOCKLIST.search(job.title):
        return False, "title_blocklist"

    text = f"{job.title}\n{job.description}"

    if not _STACK_SIGNALS.search(text):
        return False, "no_stack_signal"

    # Count Dutch markers; one hit can be noise, several means Dutch-language ad.
    if len(_DUTCH_MARKERS.findall(job.description)) >= 2:
        return False, "dutch_language"

    if len(job.description) < 200:
        return False, "description_too_short"  # can't score what we can't read

    return True, "ok"
