"""Ingestion via python-jobspy (Indeed, LinkedIn, Glassdoor, Google Jobs).

Design notes:
- Each site scraped independently: one blocked site must not kill the run.
- Defensive column access: jobspy's DataFrame schema shifts between versions.
- Be gentle: low results_wanted, hours_old window instead of full history.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from jobspy import scrape_jobs

from models import JobPosting

log = logging.getLogger(__name__)


def _row_to_posting(row: pd.Series) -> JobPosting | None:
    title = str(row.get("title") or "").strip()
    company = str(row.get("company") or "").strip()
    if not title or not company:
        return None

    posted = row.get("date_posted")
    posted_date: date | None = None
    if pd.notna(posted):
        posted_date = posted if isinstance(posted, date) else pd.to_datetime(posted).date()

    return JobPosting(
        id=JobPosting.make_id(company, title),
        source=str(row.get("site") or "unknown"),
        title=title,
        company=company,
        location=str(row.get("location") or ""),
        is_remote=bool(row.get("is_remote") or False),
        description=str(row.get("description") or ""),
        url=str(row.get("job_url") or ""),
        posted_date=posted_date,
    )


def fetch(
    search_term: str,
    location: str,
    sites: list[str],
    results_per_site: int = 25,
    hours_old: int = 72,
    country_indeed: str = "netherlands",
) -> list[JobPosting]:
    """Scrape one search term across sites. Returns normalized postings."""
    postings: list[JobPosting] = []
    for site in sites:  # one site at a time → isolated failures
        try:
            df = scrape_jobs(
                site_name=[site],
                search_term=search_term,
                location=location,
                results_wanted=results_per_site,
                hours_old=hours_old,
                country_indeed=country_indeed,
                linkedin_fetch_description=(site == "linkedin"),
                description_format="markdown",
                verbose=0,
            )
        except Exception as exc:  # noqa: BLE001 — scraping fails in creative ways
            log.warning("source %s failed for '%s': %s", site, search_term, exc)
            continue

        if df is None or df.empty:
            log.info("source %s: 0 results for '%s'", site, search_term)
            continue

        for _, row in df.iterrows():
            p = _row_to_posting(row)
            if p:
                postings.append(p)
        log.info("source %s: %d results for '%s'", site, len(df), search_term)

    return postings
