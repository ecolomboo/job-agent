"""Core data models. Every pipeline stage consumes and produces these."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    NEW = "new"
    FILTERED_OUT = "filtered_out"
    SCORED = "scored"
    LETTER_DRAFTED = "letter_drafted"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class JobPosting(BaseModel):
    """Normalized job listing, source-agnostic."""

    id: str  # stable hash, primary key
    source: str  # "indeed", "linkedin", "glassdoor", "google"
    title: str
    company: str
    location: str = ""
    is_remote: bool = False
    description: str = ""
    url: str
    posted_date: date | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    status: JobStatus = JobStatus.NEW

    @staticmethod
    def make_id(company: str, title: str) -> str:
        """Stable dedup key: same job cross-posted on two boards collapses."""
        key = f"{company.strip().lower()}|{title.strip().lower()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


class MatchResult(BaseModel):
    """LLM scoring output. Sub-scores are 0-5; total computed in Python."""

    job_id: str
    stack_match: int = Field(ge=0, le=5)
    seniority_fit: int = Field(ge=0, le=5)
    location_fit: int = Field(ge=0, le=5)
    key_requirements: list[str] = Field(default_factory=list, max_length=3)
    reasoning: str = ""

    @property
    def total(self) -> float:
        # stack weighs double: it is the main relevance signal
        return (2 * self.stack_match + self.seniority_fit + self.location_fit) / 4


class CoverLetter(BaseModel):
    job_id: str
    body: str
    model: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
