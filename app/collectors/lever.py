from app.collectors.base import JobCollector
from app.models import Company, Job


class LeverCollector(JobCollector):
    source = "lever"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        site = company.ats_identifier
        if not site:
            raise ValueError("Lever requires ats_identifier")
        url = f"https://api.lever.co/v0/postings/{site}?mode=json"
        data = (await self.http.get(url)).json()
        jobs = []
        for j in data:
            categories = j.get("categories", {})
            description = " ".join([j.get("descriptionPlain", ""), *(x.get("content", "") for x in j.get("lists", [])), j.get("additionalPlain", "")])
            jobs.append(self.job(company, j.get("id"), j.get("text", ""), categories.get("location"), description,
                                 j.get("applyUrl") or j.get("hostedUrl"), url, j.get("createdAt"), j))
        return jobs

