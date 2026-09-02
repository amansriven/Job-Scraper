from app.collectors.base import JobCollector
from app.models import Company, Job


class AshbyCollector(JobCollector):
    source = "ashby"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        board = company.ats_identifier
        if not board:
            raise ValueError("Ashby requires ats_identifier")
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        data = (await self.http.get(url)).json()
        return [self.job(company, j.get("id"), j.get("title", ""), j.get("location"),
                         j.get("descriptionPlain") or j.get("descriptionHtml", ""),
                         j.get("applyUrl") or j.get("jobUrl"), url, j.get("publishedAt"), j)
                for j in data.get("jobs", []) if j.get("isListed", True)]

