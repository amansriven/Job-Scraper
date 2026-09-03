from app.filters.rules import evaluate
from datetime import timedelta

from app.models import Company, Job, Tier, utcnow


def company(tier=Tier.HIGH):
    return Company("Acme", "https://example.com/jobs", "greenhouse", "acme", tier)


def job(title, location="New York, NY", description="Python software development and APIs", posted_at=None):
    return Job("1", "Acme", title, location, description, "https://example.com/1", "https://example.com", "test",
               posted_at=posted_at or utcnow())


def test_accepts_generic_swe_internship():
    result = evaluate(job("Software Engineer Intern"), company())
    assert result.accepted and result.category in {"HIGH MATCH", "REPUTABLE SWE"}


def test_ambiguous_technology_role_uses_description():
    assert evaluate(job("Technology Summer Analyst", description="Build backend APIs using Python and cloud infrastructure"), company()).accepted


def test_rejects_non_us_and_nontechnical():
    assert not evaluate(job("Software Engineer Intern", "London, United Kingdom"), company()).accepted
    assert not evaluate(job("Product Management Intern"), company()).accepted


def test_rejects_phd_only():
    assert not evaluate(job("Machine Learning Intern", description="Currently pursuing a PhD. PhD required."), company()).accepted


def test_high_match_background():
    result = evaluate(job("Platform Engineering Intern", description="Build distributed systems with Kubernetes, Go, Prometheus and AWS"), company(Tier.ELITE))
    assert result.accepted and result.category == "HIGH MATCH" and result.score >= 80


def test_rejects_postings_older_than_two_days():
    result = evaluate(job("Software Engineer Intern", posted_at=utcnow() - timedelta(hours=49)), company())
    assert not result.accepted and result.rejection == "posting is older than 48 hours"


def test_rejects_missing_posting_date():
    candidate = job("Software Engineer Intern")
    candidate.posted_at = None
    result = evaluate(candidate, company())
    assert not result.accepted and result.rejection == "posting date unavailable"
