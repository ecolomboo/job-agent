"""SQLite storage. Single file, no ORM — sqlite3 stdlib is enough for v1."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from models import CoverLetter, JobPosting, JobStatus, MatchResult

DB_PATH = Path(__file__).parent / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    is_remote   INTEGER DEFAULT 0,
    description TEXT,
    url         TEXT,
    posted_date TEXT,
    fetched_at  TEXT,
    status      TEXT DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS matches (
    job_id           TEXT PRIMARY KEY REFERENCES jobs(id),
    stack_match      INTEGER,
    seniority_fit    INTEGER,
    location_fit     INTEGER,
    total            REAL,
    key_requirements TEXT,   -- JSON array
    reasoning        TEXT
);
CREATE TABLE IF NOT EXISTS letters (
    job_id     TEXT PRIMARY KEY REFERENCES jobs(id),
    body       TEXT,
    model      TEXT,
    created_at TEXT
);
"""


@contextmanager
def get_conn(path: Path = DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_job(conn: sqlite3.Connection, job: JobPosting) -> bool:
    """Insert if new. Returns True if inserted, False if already known.

    Never overwrites an existing row: re-runs must not reset status.
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO jobs
           (id, source, title, company, location, is_remote,
            description, url, posted_date, fetched_at, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job.id, job.source, job.title, job.company, job.location,
            int(job.is_remote), job.description, job.url,
            job.posted_date.isoformat() if job.posted_date else None,
            job.fetched_at.isoformat(), job.status.value,
        ),
    )
    return cur.rowcount > 0


def set_status(conn: sqlite3.Connection, job_id: str, status: JobStatus) -> None:
    conn.execute("UPDATE jobs SET status=? WHERE id=?", (status.value, job_id))


def jobs_with_status(conn: sqlite3.Connection, status: JobStatus) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jobs WHERE status=? ORDER BY posted_date DESC", (status.value,)
    ).fetchall()


def save_match(conn: sqlite3.Connection, m: MatchResult) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?)""",
        (m.job_id, m.stack_match, m.seniority_fit, m.location_fit,
         m.total, json.dumps(m.key_requirements), m.reasoning),
    )


def save_letter(conn: sqlite3.Connection, letter: CoverLetter) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO letters VALUES (?,?,?,?)",
        (letter.job_id, letter.body, letter.model, letter.created_at.isoformat()),
    )
