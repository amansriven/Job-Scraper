from app.collectors.base import JobCollector
from app.models import Company, Job


class WorkdayCollector(JobCollector):
    source = "workday"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        tenant = cfg.get("tenant") or company.ats_identifier
        site = cfg.get("site", "External")
        host = cfg.get("host", f"{tenant}.wd5.myworkdayjobs.com")
        if not tenant:
            raise ValueError("Workday requires ats_identifier/tenant")
        api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        jobs, offset, limit = [], 0, 20
        while True:
            payload = {"appliedFacets": cfg.get("facets", {}), "limit": limit, "offset": offset, "searchText": ""}
            data = (await self.http.post(api, json=payload)).json()
            batch = data.get("jobPostings", [])
            for j in batch:
                path = j.get("externalPath", "")
                detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{path}"
                detail = (await self.http.get(detail_url)).json().get("jobPostingInfo", {})
                apply_url = detail.get("externalUrl") or f"https://{host}/en-US/{site}{path}"
                jobs.append(self.job(company, detail.get("jobReqId") or path, detail.get("title") or j.get("title", ""),
                                     detail.get("location") or j.get("locationsText"), detail.get("jobDescription", ""),
                                     apply_url, detail_url, detail.get("startDate"), detail))
            offset += len(batch)
            if not batch or offset >= data.get("total", 0) or offset >= int(cfg.get("max_jobs", 2000)):
                break
        return jobs

