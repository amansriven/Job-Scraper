from __future__ import annotations

from urllib.parse import urljoin

from app.collectors.base import JobCollector
from app.collectors.workday import INTERNSHIP_TITLE
from app.models import Company, Job


class JibeCollector(JobCollector):
    """Public iCIMS Career Site Builder (Jibe) `/api/jobs` collector."""

    source = "jibe"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        base = company.config.get("api_base", company.career_url).rstrip("/")
        terms = company.config.get("search_terms", ["intern", "co-op", "summer analyst", "student"])
        page_size = int(company.config.get("page_size", 100))
        records: dict[str, dict] = {}
        for term in terms:
            page = 1
            while True:
                payload = (await self.http.get(
                    f"{base}/api/jobs", params={"keywords": term, "page": page, "limit": page_size}
                )).json()
                batch = payload.get("jobs", [])
                for wrapper in batch:
                    item = wrapper.get("data", wrapper)
                    if INTERNSHIP_TITLE.search(item.get("title", "")):
                        key = str(item.get("req_id") or item.get("slug") or "")
                        if key:
                            records[key] = item
                if not batch or page * page_size >= int(payload.get("totalCount", 0)):
                    break
                page += 1
        jobs = []
        for item in records.values():
            job_id = str(item.get("req_id") or item.get("slug"))
            apply_url = item.get("apply_url") or urljoin(base + "/", f"jobs/{job_id}")
            jobs.append(self.job(
                company, job_id, item.get("title", ""),
                item.get("full_location") or item.get("location_name"), item.get("description", ""),
                apply_url, f"{base}/api/jobs", item.get("posted_date"), item,
            ))
        return jobs
