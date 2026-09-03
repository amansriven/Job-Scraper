import pytest

from app.database import Database, POSTGRES_SCHEMA, SQLiteDatabase
from app.models import Job, MatchResult


def test_stable_id_and_fingerprint_deduplicate(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    match = MatchResult(True, "REPUTABLE SWE", 70, ["Software"])
    first = Job("req-1", "Acme", "SWE Intern", "Austin, TX", "code", "https://x/jobs/1?utm_source=a", "https://x", "test")
    assert db.upsert_job(first, match)[0]
    assert not db.upsert_job(first, match)[0]
    same_fingerprint = Job("changed-id", "Acme", "SWE Intern", "Austin, TX", "code", "https://x/jobs/1?utm_source=b", "https://x", "other")
    assert not db.upsert_job(same_fingerprint, match)[0]


def test_database_factory_selects_sqlite(tmp_path):
    assert isinstance(Database(f"sqlite:///{tmp_path / 'factory.db'}"), SQLiteDatabase)


def test_database_factory_rejects_unknown_scheme():
    with pytest.raises(ValueError):
        Database("mysql://localhost/jobs")


def test_postgres_schema_has_required_constraints():
    assert "UNIQUE(source, external_id)" in POSTGRES_SCHEMA
    assert "collector_health" in POSTGRES_SCHEMA
