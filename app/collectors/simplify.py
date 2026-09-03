from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.collectors.base import JobCollector
from app.models import Company, Job


DEFAULT_FEED = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"


class SimplifyCollector(JobCollector):
    """High-coverage internship feed maintained by Simplify and Pitt CSC."""

    source = "simplify"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        feed_url = cfg.get("feed_url", DEFAULT_FEED)
        lookback = timedelta(hours=int(cfg.get("lookback_hours", 72)))
        cutoff = datetime.now(timezone.utc) - lookback
        records = (await self.http.get(feed_url)).json()
        jobs = []
        for item in records:
            if not item.get("active") or not item.get("is_visible", True):
                continue
            posted_raw = item.get("date_posted")
            if not posted_raw:
                continue
            posted = datetime.fromtimestamp(float(posted_raw), tz=timezone.utc)
            if posted < cutoff:
                continue
            locations = item.get("locations") or []
            context = " ".join(filter(None, (
                item.get("category"), " ".join(item.get("terms") or []),
                " ".join(item.get("degrees") or []), item.get("sponsorship"),
            )))
            jobs.append(Job(
                external_id=str(item.get("id") or item.get("url")),
                company=(item.get("company_name") or "Unknown company").strip(),
                title=(item.get("title") or "").strip(),
                location="; ".join(locations) if locations else None,
                description=context,
                apply_url=item.get("url") or item.get("company_url"),
                source_url=feed_url,
                source=self.source,
                posted_at=posted,
                metadata=item,
            ))
        return jobs
