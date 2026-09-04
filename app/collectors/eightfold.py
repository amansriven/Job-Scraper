from __future__ import annotations

from datetime import datetime, timezone

from app.collectors.base import JobCollector
from app.models import Company, Job


def epoch_to_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


class EightfoldCollector(JobCollector):
    """Eightfold.ai talent-platform career sites (Microsoft, Netflix, and
    others) expose a public search + detail JSON API, but the vendor has
    shipped at least two incompatible URL/response shapes across customers.
    `config.variant` picks which one a given tenant uses:

    - "pcsx": search/detail responses are nested under a `data` key
      (observed on apply.careers.microsoft.com).
    - "apply_v2": search/detail fields are top-level (observed on
      explore.jobs.netflix.net, likely the more common shape).
    """

    source = "eightfold"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        variant = cfg.get("variant", "apply_v2")
        base = cfg["base_url"].rstrip("/")
        domain = cfg["domain"]
        terms = cfg.get("search_terms", ["intern"])
        page_size = int(cfg.get("page_size", 50))
        max_per_term = int(cfg.get("max_jobs_per_term", 500))

        if variant == "pcsx":
            search_url, detail_url = f"{base}/api/pcsx/search", f"{base}/api/pcsx/position_details"
        else:
            search_url, detail_url = f"{base}/api/apply/v2/jobs", f"{base}/api/apply/v2/jobs"

        positions: dict[str, dict] = {}
        for term in terms:
            start = 0
            while start < max_per_term:
                payload = (await self.http.get(search_url, params={
                    "domain": domain, "query": term, "location": "", "start": start, "num": page_size,
                })).json()
                data = payload.get("data", payload) if variant == "pcsx" else payload
                batch = data.get("positions", [])
                for item in batch:
                    positions[str(item["id"])] = item
                start += len(batch)
                if not batch or start >= int(data.get("count", 0)):
                    break

        jobs = []
        for position_id, item in positions.items():
            if variant == "pcsx":
                detail_payload = (await self.http.get(
                    detail_url, params={"position_id": position_id, "domain": domain, "hl": "en"})).json()
                detail = detail_payload.get("data", detail_payload)
                apply_url = f"{base}{item.get('positionUrl', '')}"
                location = ", ".join(item.get("standardizedLocations") or item.get("locations") or [])
                posted = item.get("postedTs") or item.get("creationTs")
            else:
                detail = (await self.http.get(f"{detail_url}/{position_id}", params={"domain": domain})).json()
                apply_url = detail.get("canonicalPositionUrl") or f"{base}/careers/job/{position_id}"
                location = item.get("location") or ", ".join(item.get("locations") or [])
                posted = item.get("t_create") or item.get("t_update")
            jobs.append(self.job(
                company, position_id, item.get("name", ""), location,
                detail.get("job_description") or detail.get("jobDescription", ""),
                apply_url, search_url, epoch_to_datetime(posted), detail,
            ))
        return jobs
