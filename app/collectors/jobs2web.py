from __future__ import annotations

import json
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from app.collectors.base import JobCollector
from app.collectors.workday import INTERNSHIP_TITLE
from app.models import Company, Job


class Jobs2WebCollector(JobCollector):
    """Collector for SAP SuccessFactors Recruiting Marketing career sites."""

    source = "successfactors"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        base = cfg.get("base_url", company.career_url).rstrip("/")
        prefix = cfg.get("search_prefix", "/search-jobs")
        org_id = str(cfg["organization_id"])
        terms = cfg.get("search_terms", ["intern", "co-op", "summer analyst", "student"])
        summaries: dict[str, tuple[str, str | None]] = {}

        for term in terms:
            page = 1
            while True:
                path = f"{prefix}/{quote(term, safe='')}/{org_id}/{page}"
                response = await self.http.get(urljoin(base + "/", path.lstrip("/")))
                soup = BeautifulSoup(response.text, "html.parser")
                section = soup.select_one("#search-results")
                if section is None:
                    raise ValueError("SuccessFactors search results were not present")
                for link in section.select("a[data-job-id][href]"):
                    title = link.get_text(" ", strip=True)
                    if INTERNSHIP_TITLE.search(title):
                        parent = link.find_parent("li")
                        location_node = parent.select_one(".job-location") if parent else None
                        summaries[str(link["data-job-id"])] = (
                            urljoin(str(response.url), link["href"]),
                            location_node.get_text(" ", strip=True) if location_node else None,
                        )
                total_pages = int(section.get("data-total-pages", "1"))
                if page >= total_pages:
                    break
                page += 1

        jobs = []
        for job_id, (url, fallback_location) in summaries.items():
            response = await self.http.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            script = soup.select_one('script[type="application/ld+json"]')
            if script is None:
                raise ValueError(f"SuccessFactors job {job_id} has no structured posting data")
            detail = json.loads(script.string or script.get_text())
            address = detail.get("jobLocation", [{}])[0].get("address", {}) if detail.get("jobLocation") else {}
            location = ", ".join(filter(None, (
                address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")
            ))) or fallback_location
            jobs.append(self.job(
                company, detail.get("identifier") or job_id, detail.get("title", ""), location,
                detail.get("description", ""), detail.get("url") or url, url, detail.get("datePosted"), detail,
            ))
        return jobs
