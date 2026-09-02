from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.collectors.base import JobCollector
from app.models import Company, Job


class GenericCollector(JobCollector):
    source = "generic"

    async def fetch_jobs(self, company: Company) -> list[Job]:
        cfg = company.config
        selector = cfg.get("job_selector")
        if not selector:
            raise ValueError("Generic collector requires config.job_selector; use discovery to add a structured ATS when possible")
        response = await self.http.get(company.career_url)
        soup = BeautifulSoup(response.text, "html.parser")
        result = []
        for node in soup.select(selector):
            link = node.select_one(cfg.get("link_selector", "a"))
            if not link or not link.get("href"):
                continue
            title_node = node.select_one(cfg.get("title_selector", "h2,h3,a"))
            location_node = node.select_one(cfg.get("location_selector", ".location"))
            url = urljoin(str(response.url), link["href"])
            title = title_node.get_text(" ", strip=True) if title_node else link.get_text(" ", strip=True)
            description = node.get_text(" ", strip=True)
            if cfg.get("fetch_detail", True):
                detail = await self.http.get(url)
                description = BeautifulSoup(detail.text, "html.parser").get_text(" ", strip=True)
            result.append(self.job(company, node.get(cfg.get("id_attribute", "data-id")), title,
                                   location_node.get_text(" ", strip=True) if location_node else None,
                                   description, url, company.career_url))
        return result

