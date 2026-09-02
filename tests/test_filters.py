from app.filters.rules import evaluate
from app.models import Company, Job, Tier


def company(tier=Tier.HIGH):
    return Company("Acme", "https://example.com/jobs", "greenhouse", "acme", tier)


def job(title, location="New York, NY", description="Python software development and APIs"):
    return Job("1", "Acme", title, location, description, "https://example.com/1", "https://example.com", "test")


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

