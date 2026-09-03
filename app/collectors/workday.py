import re

from app.collectors.base import JobCollector
from app.models import Company, Job


INTERNSHIP_TITLE = re.compile(
    r"(?:\bintern(?:ship)?s?\b|\bco[\s-]?op\b|\bsummer\s+analyst\b|"
    r"\bstudent\b|\buniversity\s+(?:graduate|program|recruiting|talent)\b)",
    re.IGNORECASE,
)


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
        # Workday tenants can contain tens of thousands of roles. Search every
        # internship-equivalent term, fully paginate each result set, and merge
        # requisitions before fetching details. This preserves target coverage
        # without downloading every unrelated full-time description.
        terms = cfg.get("search_terms", ["intern", "co-op", "summer analyst", "student", "university"])
        postings: dict[str, dict] = {}
        limit = int(cfg.get("page_size", 20))
        for term in terms:
            offset = 0
            while True:
                payload = {"appliedFacets": cfg.get("facets", {}), "limit": limit, "offset": offset, "searchText": term}
                data = (await self.http.post(api, json=payload)).json()
                batch = data.get("jobPostings", [])
                for posting in batch:
                    # Workday search is substring-based: `intern` also returns
                    # `internal` and `international`. Filter the cheap summary
                    # records before making one detail request per requisition.
                    if not INTERNSHIP_TITLE.search(posting.get("title", "")):
                        continue
                    key = posting.get("externalPath") or posting.get("title")
                    if key:
                        postings[key] = posting
                offset += len(batch)
                if not batch or offset >= data.get("total", 0) or offset >= int(cfg.get("max_jobs_per_term", 1000)):
                    break
        jobs = []
        for j in postings.values():
            path = j.get("externalPath", "")
            detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{path}"
            detail = (await self.http.get(detail_url)).json().get("jobPostingInfo", {})
            apply_url = detail.get("externalUrl") or f"https://{host}/en-US/{site}{path}"
            jobs.append(self.job(company, detail.get("jobReqId") or path, detail.get("title") or j.get("title", ""),
                                 detail.get("location") or j.get("locationsText"), detail.get("jobDescription", ""),
                                 apply_url, detail_url, detail.get("startDate"), detail))
        return jobs
