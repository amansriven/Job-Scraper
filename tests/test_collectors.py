import httpx
import pytest

from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.jibe import JibeCollector
from app.collectors.simplify import SimplifyCollector
from app.collectors.workday import WorkdayCollector
from app.models import Company


class FakeHttp:
    async def get(self, url, **kwargs):
        return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Software Intern", "location": {"name": "NY"}, "content": "Python", "absolute_url": "https://x/1", "first_published": "2026-09-02T12:00:00Z", "updated_at": "2026-09-03T12:00:00Z"}]})


@pytest.mark.asyncio
async def test_greenhouse_normalizes():
    jobs = await GreenhouseCollector(FakeHttp()).fetch_jobs(Company("Acme", "https://x", "greenhouse", "acme"))
    assert jobs[0].external_id == "1" and jobs[0].company == "Acme" and jobs[0].description == "Python"
    assert jobs[0].posted_at.isoformat() == "2026-09-02T12:00:00+00:00"


class FakeWorkdayHttp:
    def __init__(self):
        self.detail_urls = []

    async def post(self, url, **kwargs):
        if kwargs["json"]["offset"]:
            return httpx.Response(200, json={"jobPostings": [], "total": 2})
        return httpx.Response(200, json={"jobPostings": [
            {"title": "Software Engineer Intern", "externalPath": "/job/R1"},
            {"title": "International Sales Manager", "externalPath": "/job/R2"},
        ], "total": 2})

    async def get(self, url, **kwargs):
        self.detail_urls.append(url)
        return httpx.Response(200, json={"jobPostingInfo": {
            "jobReqId": "R1", "title": "Software Engineer Intern",
            "location": "Austin, TX", "jobDescription": "Summer role",
            "externalUrl": "https://example.com/R1", "startDate": "2026-09-02",
        }})


@pytest.mark.asyncio
async def test_workday_filters_substring_false_positives_before_details():
    http = FakeWorkdayHttp()
    company = Company("Acme", "https://example.com", "workday", "acme", config={
        "host": "acme.wd1.myworkdayjobs.com", "site": "External", "search_terms": ["intern"],
    })
    jobs = await WorkdayCollector(http).fetch_jobs(company)
    assert [job.external_id for job in jobs] == ["R1"]
    assert len(http.detail_urls) == 1
    assert http.detail_urls[0].endswith("/job/R1")


class FakeJibeHttp:
    async def get(self, url, **kwargs):
        return httpx.Response(200, json={"totalCount": 2, "jobs": [
            {"data": {"req_id": "J1", "title": "Machine Learning Intern", "full_location": "Austin, Texas",
                      "description": "Build Python systems", "apply_url": "https://example.com/J1",
                      "posted_date": "2026-09-03T08:00:00+0000"}},
            {"data": {"req_id": "J2", "title": "International Sales Lead", "description": "Sales"}},
        ]})


@pytest.mark.asyncio
async def test_jibe_normalizes_and_filters_titles():
    company = Company("Acme", "https://careers.example.com", "jibe", config={
        "api_base": "https://careers.example.com", "search_terms": ["intern"], "page_size": 100,
    })
    jobs = await JibeCollector(FakeJibeHttp()).fetch_jobs(company)
    assert [job.external_id for job in jobs] == ["J1"]
    assert jobs[0].posted_at.isoformat() == "2026-09-03T08:00:00+00:00"


class FakeSimplifyHttp:
    async def get(self, url, **kwargs):
        now = int(__import__("time").time())
        return httpx.Response(200, json=[
            {"id": "S1", "active": True, "is_visible": True, "date_posted": now,
             "company_name": "Example Corp", "title": "Software Engineer Intern",
             "locations": ["Chicago, IL"], "url": "https://example.com/jobs/S1",
             "category": "Software", "terms": ["Summer 2027"], "degrees": ["Bachelor's"]},
            {"id": "S2", "active": False, "date_posted": now, "company_name": "Closed",
             "title": "Developer Intern", "locations": ["Austin, TX"], "url": "https://example.com/S2"},
        ])


@pytest.mark.asyncio
async def test_simplify_keeps_recent_active_roles_and_real_company():
    company = Company("Aggregate", "https://example.com/feed", "simplify", config={"lookback_hours": 72})
    jobs = await SimplifyCollector(FakeSimplifyHttp()).fetch_jobs(company)
    assert len(jobs) == 1
    assert jobs[0].company == "Example Corp"
    assert jobs[0].external_id == "S1"
