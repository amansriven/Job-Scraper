from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from app.models import Job, MatchResult, utcnow

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 company TEXT NOT NULL, title TEXT NOT NULL, location TEXT, apply_url TEXT NOT NULL, source_url TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', posted_at TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active', match_category TEXT, match_score INTEGER NOT NULL DEFAULT 0,
 match_reasons TEXT NOT NULL DEFAULT '[]', notification_status TEXT NOT NULL DEFAULT 'not_applicable', notified_at TEXT,
 UNIQUE(source, external_id));
CREATE INDEX IF NOT EXISTS ix_jobs_fingerprint ON jobs(fingerprint);
CREATE TABLE IF NOT EXISTS collector_health (
 company TEXT PRIMARY KEY, last_success_at TEXT, last_failure_at TEXT, consecutive_failures INTEGER NOT NULL DEFAULT 0,
 most_recent_error TEXT, last_job_count INTEGER NOT NULL DEFAULT 0);
"""
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 company TEXT NOT NULL, title TEXT NOT NULL, location TEXT, apply_url TEXT NOT NULL, source_url TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', posted_at TIMESTAMPTZ, first_seen_at TIMESTAMPTZ NOT NULL,
 last_seen_at TIMESTAMPTZ NOT NULL, status TEXT NOT NULL DEFAULT 'active', match_category TEXT,
 match_score INTEGER NOT NULL DEFAULT 0, match_reasons TEXT NOT NULL DEFAULT '[]',
 notification_status TEXT NOT NULL DEFAULT 'not_applicable', notified_at TIMESTAMPTZ,
 UNIQUE(source, external_id));
CREATE INDEX IF NOT EXISTS ix_jobs_fingerprint ON jobs(fingerprint);
CREATE TABLE IF NOT EXISTS collector_health (
 company TEXT PRIMARY KEY, last_success_at TIMESTAMPTZ, last_failure_at TIMESTAMPTZ,
 consecutive_failures INTEGER NOT NULL DEFAULT 0, most_recent_error TEXT, last_job_count INTEGER NOT NULL DEFAULT 0);
"""


class Persistence(Protocol):
    def upsert_job(self, job: Job, match: MatchResult) -> tuple[bool, int]: ...
    def mark_notified(self, job_id: int, success: bool, error: str | None = None) -> None: ...
    def record_health(self, company: str, success: bool, count: int = 0, error: str | None = None) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


class SQLiteDatabase:
    def __init__(self, url: str):
        self.path = Path(url.removeprefix("sqlite:///"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SQLITE_SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30); conn.row_factory = sqlite3.Row
        try:
            yield conn; conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def upsert_job(self, job: Job, match: MatchResult) -> tuple[bool, int]:
        now = utcnow().isoformat(); posted = job.posted_at.isoformat() if job.posted_at else None
        with self.connection() as conn:
            existing = conn.execute("SELECT id FROM jobs WHERE source=? AND external_id=?", (job.source, job.external_id)).fetchone()
            if not existing:
                existing = conn.execute("SELECT id FROM jobs WHERE fingerprint=?", (job.fingerprint,)).fetchone()
            if existing:
                conn.execute("""UPDATE jobs SET last_seen_at=?,status='active',title=?,location=?,apply_url=?,source_url=?,
                    description=?,posted_at=COALESCE(?,posted_at),match_category=?,match_score=?,match_reasons=? WHERE id=?""",
                    (now, job.title, job.location, job.apply_url, job.source_url, job.description, posted,
                     match.category, match.score, json.dumps(match.reasons), existing["id"]))
                return False, int(existing["id"])
            cur = conn.execute("""INSERT INTO jobs(source,external_id,fingerprint,company,title,location,apply_url,source_url,
                description,posted_at,first_seen_at,last_seen_at,match_category,match_score,match_reasons,notification_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (job.source, job.external_id, job.fingerprint, job.company,
                job.title, job.location, job.apply_url, job.source_url, job.description, posted, now, now,
                match.category, match.score, json.dumps(match.reasons), "pending" if match.accepted else "not_applicable"))
            return True, int(cur.lastrowid)

    def mark_notified(self, job_id: int, success: bool, error: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE jobs SET notification_status=?,notified_at=? WHERE id=?",
                         (_notification_status(success, error), utcnow().isoformat() if success else None, job_id))

    def record_health(self, company: str, success: bool, count: int = 0, error: str | None = None) -> None:
        now = utcnow().isoformat()
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO collector_health(company) VALUES(?)", (company,))
            if success:
                conn.execute("UPDATE collector_health SET last_success_at=?,consecutive_failures=0,most_recent_error=NULL,last_job_count=? WHERE company=?", (now, count, company))
            else:
                conn.execute("UPDATE collector_health SET last_failure_at=?,consecutive_failures=consecutive_failures+1,most_recent_error=? WHERE company=?", (now, (error or "")[:1000], company))

    def close(self) -> None:
        pass

    def flush(self) -> None:
        pass


class PostgresDatabase:
    def __init__(self, url: str):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires psycopg; install requirements.txt") from exc
        self.psycopg, self.url = psycopg, url
        self.conn = psycopg.connect(url, connect_timeout=15)
        with self.connection() as conn:
            for statement in filter(str.strip, POSTGRES_SCHEMA.split(";")):
                conn.execute(statement)
        rows = self.conn.execute("SELECT id,source,external_id,fingerprint FROM jobs").fetchall()
        self.by_key = {(row[1], row[2]): int(row[0]) for row in rows}
        self.by_fingerprint = {row[3]: int(row[0]) for row in rows}

    @contextmanager
    def connection(self):
        try:
            yield self.conn
        except Exception:
            self.conn.rollback(); raise

    def upsert_job(self, job: Job, match: MatchResult) -> tuple[bool, int]:
        now = utcnow()
        with self.connection() as conn:
            existing_id = self.by_key.get((job.source, job.external_id)) or self.by_fingerprint.get(job.fingerprint)
            if existing_id:
                conn.execute("""UPDATE jobs SET last_seen_at=%s,status='active',title=%s,location=%s,apply_url=%s,
                    source_url=%s,description=%s,posted_at=COALESCE(%s,posted_at),match_category=%s,match_score=%s,
                    match_reasons=%s WHERE id=%s""", (now, job.title, job.location, job.apply_url, job.source_url,
                    job.description, job.posted_at, match.category, match.score, json.dumps(match.reasons), existing_id))
                return False, existing_id
            row = conn.execute("""INSERT INTO jobs(source,external_id,fingerprint,company,title,location,apply_url,source_url,
                description,posted_at,first_seen_at,last_seen_at,match_category,match_score,match_reasons,notification_status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (job.source,
                job.external_id, job.fingerprint, job.company, job.title, job.location, job.apply_url, job.source_url,
                job.description, job.posted_at, now, now, match.category, match.score, json.dumps(match.reasons),
                "pending" if match.accepted else "not_applicable")).fetchone()
            job_id = int(row[0])
            self.by_key[(job.source, job.external_id)] = job_id
            self.by_fingerprint[job.fingerprint] = job_id
            return True, job_id

    def mark_notified(self, job_id: int, success: bool, error: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE jobs SET notification_status=%s,notified_at=%s WHERE id=%s",
                         (_notification_status(success, error), utcnow() if success else None, job_id))

    def record_health(self, company: str, success: bool, count: int = 0, error: str | None = None) -> None:
        now = utcnow()
        with self.connection() as conn:
            if success:
                conn.execute("""INSERT INTO collector_health(company,last_success_at,last_job_count)
                    VALUES(%s,%s,%s) ON CONFLICT(company) DO UPDATE SET last_success_at=EXCLUDED.last_success_at,
                    consecutive_failures=0,most_recent_error=NULL,last_job_count=EXCLUDED.last_job_count""", (company, now, count))
            else:
                conn.execute("""INSERT INTO collector_health(company,last_failure_at,consecutive_failures,most_recent_error)
                    VALUES(%s,%s,1,%s) ON CONFLICT(company) DO UPDATE SET last_failure_at=EXCLUDED.last_failure_at,
                    consecutive_failures=collector_health.consecutive_failures+1,
                    most_recent_error=EXCLUDED.most_recent_error""", (company, now, (error or "")[:1000]))

    def flush(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()


def _notification_status(success: bool, error: str | None) -> str:
    return "sent" if success else f"failed:{(error or 'unknown')[:180]}"


def Database(url: str) -> Persistence:
    if url.startswith("sqlite:///"):
        return SQLiteDatabase(url)
    if url.startswith(("postgresql://", "postgres://")):
        return PostgresDatabase(url)
    raise ValueError("DATABASE_URL must use sqlite:/// or postgresql://")
