from app.collectors.base import JobCollector
from app.models import Company, Job


class SmartRecruitersCollector(JobCollector):
    source = "smartrecruiters"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        tenant = company.ats_identifier
        if not tenant:
            raise ValueError("SmartRecruiters requires ats_identifier")
        base = f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings"
        jobs, offset = [], 0
        while True:
            data = (await self.http.get(base, params={"limit": 100, "offset": offset})).json()
            batch = data.get("content", [])
            for item in batch:
                jid = item.get("id")
                detail = (await self.http.get(f"{base}/{jid}")).json()
                loc = detail.get("location") or {}
                location = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
                sections = detail.get("jobAd", {}).get("sections", {})
                desc = " ".join(str(v.get("text", "")) for v in sections.values() if isinstance(v, dict))
                jobs.append(self.job(company, jid, detail.get("name", ""), location, desc,
                                     detail.get("applyUrl") or f"https://jobs.smartrecruiters.com/{tenant}/{jid}", base,
                                     detail.get("releasedDate"), detail))
            offset += len(batch)
            if not batch or offset >= data.get("totalFound", 0):
                break
        return jobs

