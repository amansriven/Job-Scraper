from types import SimpleNamespace

import pytest

from app.models import Company, Job, Tier, utcnow
from app.runner import run


class FakeCollector:
    async def fetch_jobs(self, company):
        return [
            Job("one", company.name, "Software Engineer Intern", "Austin, TX",
                "Build Python backend APIs", "https://example.com/one", "https://example.com", "test", utcnow()),
            Job("two", company.name, "Platform Engineer Intern", "Seattle, WA",
                "Build Kubernetes cloud infrastructure", "https://example.com/two", "https://example.com", "test", utcnow()),
            Job("three", company.name, "Machine Learning Engineer Intern", "New York, NY",
                "Build model serving systems", "https://example.com/three", "https://example.com", "test", utcnow()),
        ]


class FakeDatabase:
    def __init__(self):
        self.next_id = 0

    def upsert_job(self, job, match):
        self.next_id += 1
        return True, self.next_id

    def mark_notified(self, job_id, success, error=None): pass
    def record_health(self, company, success, count=0, error=None): pass
    def flush(self): pass
    def close(self): pass


class FakeHttp:
    async def close(self): pass


class FakeNotifier:
    sent = []

    def __init__(self, *args, **kwargs):
        type(self).sent = []

    async def send(self, job, company, match):
        type(self).sent.append(job.external_id)


@pytest.mark.asyncio
async def test_run_alerts_every_new_matching_job(monkeypatch, tmp_path):
    company = Company("Acme", "https://example.com", "test", "acme", Tier.HIGH)
    monkeypatch.setattr("app.runner.load_companies", lambda path: [company])
    monkeypatch.setattr("app.runner.get_collector", lambda name, http: FakeCollector())
    monkeypatch.setattr("app.runner.Database", lambda url: FakeDatabase())
    monkeypatch.setattr("app.runner.HttpClient", lambda *args: FakeHttp())
    monkeypatch.setattr("app.runner.DiscordNotifier", FakeNotifier)
    settings = SimpleNamespace(
        companies_file=tmp_path / "unused.yaml", database_url="sqlite:///unused.db",
        discord_webhook_url="https://discord.invalid", concurrency=4, per_domain_concurrency=2,
        request_timeout=10, retries=1, minimum_tier=Tier.BASELINE,
        max_posting_age_hours=48, dry_run=False,
    )

    stats = await run(settings)

    assert FakeNotifier.sent == ["one", "two", "three"]
    assert stats.new == 3
    assert stats.alerts == 3
