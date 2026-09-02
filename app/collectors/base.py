from __future__ import annotations

import hashlib
import html
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.http import HttpClient
from app.models import Company, Job


class JobCollector(ABC):
    source = "unknown"

    def __init__(self, http: HttpClient):
        self.http = http

    @abstractmethod
    async def fetch_jobs(self, company: Company) -> list[Job]: ...

    def job(self, company: Company, external_id: Any, title: str, location: str | None,
            description: str, apply_url: str, source_url: str | None = None, posted_at: Any = None,
            metadata: dict | None = None) -> Job:
        clean = strip_html(description or "")
        stable_id = str(external_id or "").strip()
        if not stable_id:
            stable_id = hashlib.sha256(f"{title}|{location}|{apply_url}".encode()).hexdigest()
        return Job(stable_id, company.name, title.strip(), location.strip() if location else None, clean,
                   apply_url, source_url or company.career_url, self.source, parse_date(posted_at), metadata=metadata or {})


def strip_html(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
        return result.replace(tzinfo=result.tzinfo or timezone.utc)
    except ValueError:
        return None

