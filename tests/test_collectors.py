import httpx
import pytest

from app.collectors.greenhouse import GreenhouseCollector
from app.models import Company


class FakeHttp:
    async def get(self, url, **kwargs):
        return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Software Intern", "location": {"name": "NY"}, "content": "Python", "absolute_url": "https://x/1"}]})


@pytest.mark.asyncio
async def test_greenhouse_normalizes():
    jobs = await GreenhouseCollector(FakeHttp()).fetch_jobs(Company("Acme", "https://x", "greenhouse", "acme"))
    assert jobs[0].external_id == "1" and jobs[0].company == "Acme" and jobs[0].description == "Python"

