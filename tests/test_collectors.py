import httpx
import pytest

from app.collectors.amazon import AmazonCollector, parse_amazon_date
from app.collectors.apple import AppleCollector, parse_apple_date
from app.collectors.eightfold import EightfoldCollector
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.jibe import JibeCollector
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



class FakeAmazonHttp:
    async def get(self, url, **kwargs):
        return httpx.Response(200, json={"hits": 1, "jobs": [{
            "id_icims": "10418355",
            "title": "2027 Software Dev Engineer Intern",
            "normalized_location": "Seattle, WA, USA",
            "description": "Build systems.",
            "basic_qualifications": "Enrolled in a Bachelor's degree",
            "preferred_qualifications": "Distributed systems",
            "job_path": "/en/jobs/10418355/intern",
            "posted_date": "May 13, 2026",
        }]})


@pytest.mark.asyncio
async def test_amazon_normalizes_postings_and_dates():
    company = Company("Amazon", "https://www.amazon.jobs", "amazon", None,
                      config={"search_terms": ["intern"]})
    jobs = await AmazonCollector(FakeAmazonHttp()).fetch_jobs(company)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.external_id == "10418355"
    assert job.posted_at.isoformat() == "2026-05-13T00:00:00+00:00"
    assert "Distributed systems" in job.description
    assert job.apply_url == "https://www.amazon.jobs/en/jobs/10418355/intern"


def test_amazon_rejects_unparseable_dates():
    assert parse_amazon_date("not a date") is None
    assert parse_amazon_date(None) is None


class FakeEightfoldHttp:
    def __init__(self, variant):
        self.variant = variant

    async def get(self, url, **kwargs):
        if self.variant == "pcsx":
            if "position_details" in url:
                return httpx.Response(200, json={"data": {"jobDescription": "Build the future."}})
            return httpx.Response(200, json={"data": {"positions": [{
                "id": 42, "name": "Software Engineer Intern", "standardizedLocations": ["Redmond, WA, US"],
                "postedTs": 1780000000, "positionUrl": "/careers/job/42"}], "count": 1}})
        if "/jobs/42" in url:
            return httpx.Response(200, json={"job_description": "Entertain the world.",
                                             "canonicalPositionUrl": "https://x/careers/job/42"})
        return httpx.Response(200, json={"positions": [{
            "id": 42, "name": "Software Engineer Intern", "location": "Los Gatos, CA, US",
            "t_create": 1780000000}], "count": 1})


@pytest.mark.asyncio
async def test_eightfold_pcsx_variant():
    company = Company("Microsoft", "https://careers.microsoft.com", "eightfold", config={
        "variant": "pcsx", "base_url": "https://apply.careers.microsoft.com", "domain": "microsoft.com",
        "search_terms": ["intern"]})
    jobs = await EightfoldCollector(FakeEightfoldHttp("pcsx")).fetch_jobs(company)
    assert len(jobs) == 1
    assert jobs[0].description == "Build the future."
    assert jobs[0].apply_url == "https://apply.careers.microsoft.com/careers/job/42"


@pytest.mark.asyncio
async def test_eightfold_apply_v2_variant():
    company = Company("Netflix", "https://jobs.netflix.com", "eightfold", config={
        "variant": "apply_v2", "base_url": "https://explore.jobs.netflix.net", "domain": "netflix.com",
        "search_terms": ["intern"]})
    jobs = await EightfoldCollector(FakeEightfoldHttp("apply_v2")).fetch_jobs(company)
    assert len(jobs) == 1
    assert jobs[0].description == "Entertain the world."
    assert jobs[0].apply_url == "https://x/careers/job/42"


class FakeAppleHttp:
    async def get(self, url, **kwargs):
        if "page=2" in url:
            return httpx.Response(200, text="<div></div>", request=httpx.Request("GET", url))
        html = """
        <div class="job-list-item">
          <div class="job-title-link"><a href="/en-us/details/200999-1/software-engineering-intern">Software Engineering Intern</a></div>
          <span class="job-posted-date">Sep 03, 2026</span>
          <div class="job-title-location"><span class="a11y">Location</span><span>Cupertino</span></div>
        </div>
        <div class="job-list-item">
          <div class="job-title-link"><a href="/en-us/details/200999-2/international-sales-manager">International Sales Manager</a></div>
          <span class="job-posted-date">Sep 03, 2026</span>
          <div class="job-title-location"><span class="a11y">Location</span><span>London</span></div>
        </div>
        """
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_apple_filters_title_and_skips_empty_page():
    company = Company("Apple", "https://jobs.apple.com", "apple", config={
        "search_terms": ["intern"], "max_pages_per_term": 3})
    jobs = await AppleCollector(FakeAppleHttp()).fetch_jobs(company)
    assert len(jobs) == 1
    assert jobs[0].title == "Software Engineering Intern"
    assert jobs[0].location == "Cupertino"
    assert jobs[0].apply_url == "https://jobs.apple.com/en-us/details/200999-1/software-engineering-intern"


def test_apple_rejects_unparseable_dates():
    assert parse_apple_date("not a date") is None
    assert parse_apple_date(None) is None
