from __future__ import annotations

from datetime import datetime, timezone

from app.collectors.base import JobCollector
from app.models import Company, Job

SEARCH = "https://www.amazon.jobs/en/search.json"


def parse_amazon_date(value: str | None) -> datetime | None:
    """Amazon publishes a day-granularity string such as "May 13, 2026"."""
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class AmazonCollector(JobCollector):
    """amazon.jobs exposes a public search endpoint rather than a hosted ATS."""

    source = "amazon"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        terms = cfg.get("search_terms", ["intern", "co-op", "student programs"])
        page_size = int(cfg.get("page_size", 100))
        max_per_term = int(cfg.get("max_jobs_per_term", 500))
        seen: dict[str, dict] = {}
        for term in terms:
            offset = 0
            while offset < max_per_term:
                params = {"base_query": term, "result_limit": page_size, "offset": offset,
                          "sort": "recent"}
                data = (await self.http.get(SEARCH, params=params)).json()
                batch = data.get("jobs", [])
                for item in batch:
                    key = str(item.get("id_icims") or item.get("id") or item.get("job_path"))
                    seen.setdefault(key, item)
                offset += len(batch)
                if not batch or offset >= int(data.get("hits", 0)):
                    break
        jobs = []
        for key, item in seen.items():
            description = " ".join(str(item.get(field) or "") for field in
                                   ("description", "basic_qualifications", "preferred_qualifications"))
            apply_url = item.get("url_next_step") or f"https://www.amazon.jobs{item.get('job_path', '')}"
            jobs.append(self.job(company, key, item.get("title", ""),
                                 item.get("normalized_location") or item.get("location"),
                                 description, apply_url, SEARCH,
                                 parse_amazon_date(item.get("posted_date")), item))
        return jobs
