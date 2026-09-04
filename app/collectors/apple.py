from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from app.collectors.base import JobCollector
from app.collectors.workday import INTERNSHIP_TITLE
from app.models import Company, Job

BASE = "https://jobs.apple.com"


def parse_apple_date(value: str | None) -> datetime | None:
    """Apple publishes a day-granularity string such as "Sep 03, 2026"."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%b %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class AppleCollector(JobCollector):
    """jobs.apple.com server-renders search results (no public JSON API for
    listings). Detail pages exist but their description content loads only
    through a CSRF-token-gated API (`/api/v1/rolesearch`) that plain HTTP
    requests can't complete without replicating Apple's anti-automation
    handshake, so this collector does not attempt it — postings carry no
    description text, and matching relies on the title alone.

    The `search` query does full-text substring matching, not a title
    filter, so "intern" also returns "International"/"Internal" roles; the
    same INTERNSHIP_TITLE regex other collectors use narrows results.
    """

    source = "apple"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        terms = cfg.get("search_terms", ["intern", "co-op"])
        max_pages = int(cfg.get("max_pages_per_term", 30))
        jobs: dict[str, Job] = {}

        for term in terms:
            page = 1
            while page <= max_pages:
                url = f"{BASE}/en-us/search?search={quote(term)}&page={page}"
                response = await self.http.get(url)
                soup = BeautifulSoup(response.text, "html.parser")
                rows = soup.select(".job-list-item")
                if not rows:
                    break
                for row in rows:
                    link = row.select_one(".job-title-link a")
                    if not link:
                        continue
                    title = link.get_text(strip=True)
                    if not INTERNSHIP_TITLE.search(title):
                        continue
                    href = link.get("href", "")
                    if "/details/" not in href:
                        continue
                    job_id = href.split("/details/", 1)[1].split("/", 1)[0]
                    date_el = row.select_one(".job-posted-date")
                    loc_el = row.select_one(".job-title-location span:not(.a11y)")
                    apply_url = urljoin(str(response.url), href)
                    jobs[job_id] = self.job(
                        company, job_id, title,
                        loc_el.get_text(strip=True) if loc_el else None, "",
                        apply_url, apply_url,
                        parse_apple_date(date_el.get_text(strip=True) if date_el else None), {},
                    )
                page += 1
        return list(jobs.values())
