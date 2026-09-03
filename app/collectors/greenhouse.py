from app.collectors.base import JobCollector
from app.models import Company, Job


class GreenhouseCollector(JobCollector):
    source = "greenhouse"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        token = company.ats_identifier or company.config.get("board_token")
        if not token:
            raise ValueError("Greenhouse requires ats_identifier")
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        data = (await self.http.get(url)).json()
        return [self.job(company, j.get("id"), j.get("title", ""), (j.get("location") or {}).get("name"),
                         j.get("content", ""), j.get("absolute_url", company.career_url), url, j.get("first_published"), j)
                for j in data.get("jobs", [])]
