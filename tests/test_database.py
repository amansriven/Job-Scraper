from app.database import Database
from app.models import Job, MatchResult


def test_stable_id_and_fingerprint_deduplicate(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    match = MatchResult(True, "REPUTABLE SWE", 70, ["Software"])
    first = Job("req-1", "Acme", "SWE Intern", "Austin, TX", "code", "https://x/jobs/1?utm_source=a", "https://x", "test")
    assert db.upsert_job(first, match)[0]
    assert not db.upsert_job(first, match)[0]
    same_fingerprint = Job("changed-id", "Acme", "SWE Intern", "Austin, TX", "code", "https://x/jobs/1?utm_source=b", "https://x", "other")
    assert not db.upsert_job(same_fingerprint, match)[0]

