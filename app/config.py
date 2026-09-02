from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models import Company, Tier


@dataclass(frozen=True, slots=True)
class Settings:
    companies_file: Path = Path(os.getenv("COMPANIES_FILE", "config/companies.yaml"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/internships.db")
    discord_webhook_url: str | None = os.getenv("DISCORD_WEBHOOK_URL")
    concurrency: int = int(os.getenv("SCRAPER_CONCURRENCY", "12"))
    per_domain_concurrency: int = int(os.getenv("PER_DOMAIN_CONCURRENCY", "2"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
    retries: int = int(os.getenv("HTTP_RETRIES", "3"))
    minimum_tier: Tier = Tier(os.getenv("MINIMUM_TIER", "baseline"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    dry_run: bool = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}


def load_companies(path: Path) -> list[Company]:
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or []
    companies = raw.get("companies", raw) if isinstance(raw, dict) else raw
    result = []
    known = set()
    for item in companies:
        company = Company(
            name=item["name"].strip(), career_url=item["career_url"], ats=item.get("ats", "generic").lower(),
            ats_identifier=item.get("ats_identifier"), tier=Tier(item.get("tier", "target")),
            enabled=bool(item.get("enabled", True)), config=item.get("config", {}),
        )
        key = company.name.casefold()
        if key in known:
            raise ValueError(f"Duplicate company: {company.name}")
        known.add(key)
        result.append(company)
    return result

