from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.models import Job, MatchResult, utcnow


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
  company TEXT NOT NULL, title TEXT NOT NULL, location TEXT, apply_url TEXT NOT NULL, source_url TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', posted_at TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', match_category TEXT, match_score INTEGER NOT NULL DEFAULT 0,
  match_reasons TEXT NOT NULL DEFAULT '[]', notification_status TEXT NOT NULL DEFAULT 'not_applicable', notified_at TEXT,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS ix_jobs_fingerprint ON jobs(fingerprint);
CREATE TABLE IF NOT EXISTS collector_health (
  company TEXT PRIMARY KEY, last_success_at TEXT, last_failure_at TEXT, consecutive_failures INTEGER NOT NULL DEFAULT 0,
  most_recent_error TEXT, last_job_count INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, url: str):
        if not url.startswith("sqlite:///"):
            raise ValueError("This release supports sqlite:/// URLs; persistence API is isolated for a PostgreSQL adapter")
        self.path = Path(url.removeprefix("sqlite:///"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_job(self, job: Job, match: MatchResult) -> tuple[bool, int]:
        now = utcnow().isoformat()
        posted = job.posted_at.isoformat() if job.posted_at else None
        with self.connection() as conn:
            existing = conn.execute("SELECT id FROM jobs WHERE source=? AND external_id=?", (job.source, job.external_id)).fetchone()
            if not existing:
                existing = conn.execute("SELECT id FROM jobs WHERE fingerprint=?", (job.fingerprint,)).fetchone()
            if existing:
                conn.execute("""UPDATE jobs SET last_seen_at=?, status='active', title=?, location=?, apply_url=?,
                    source_url=?, description=?, posted_at=COALESCE(?, posted_at), match_category=?, match_score=?, match_reasons=? WHERE id=?""",
                    (now, job.title, job.location, job.apply_url, job.source_url, job.description, posted,
                     match.category, match.score, json.dumps(match.reasons), existing["id"]))
                return False, existing["id"]
            cur = conn.execute("""INSERT INTO jobs(source,external_id,fingerprint,company,title,location,apply_url,source_url,
                description,posted_at,first_seen_at,last_seen_at,match_category,match_score,match_reasons,notification_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (job.source, job.external_id, job.fingerprint, job.company,
                job.title, job.location, job.apply_url, job.source_url, job.description, posted, now, now,
                match.category, match.score, json.dumps(match.reasons), "pending" if match.accepted else "not_applicable"))
            return True, int(cur.lastrowid)

    def mark_notified(self, job_id: int, success: bool, error: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE jobs SET notification_status=?, notified_at=? WHERE id=?",
                         ("sent" if success else f"failed:{(error or 'unknown')[:180]}", utcnow().isoformat() if success else None, job_id))

    def record_health(self, company: str, success: bool, count: int = 0, error: str | None = None) -> None:
        now = utcnow().isoformat()
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO collector_health(company) VALUES(?)", (company,))
            if success:
                conn.execute("UPDATE collector_health SET last_success_at=?,consecutive_failures=0,most_recent_error=NULL,last_job_count=? WHERE company=?", (now, count, company))
            else:
                conn.execute("UPDATE collector_health SET last_failure_at=?,consecutive_failures=consecutive_failures+1,most_recent_error=? WHERE company=?", (now, (error or "")[:1000], company))

