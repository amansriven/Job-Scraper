from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class Tier(StrEnum):
    ELITE = "elite"
    HIGH = "high"
    TARGET = "target"
    BASELINE = "baseline"


TIER_WEIGHT = {Tier.ELITE: 20, Tier.HIGH: 16, Tier.TARGET: 12, Tier.BASELINE: 8}


@dataclass(slots=True)
class Company:
    name: str
    career_url: str
    ats: str
    ats_identifier: str | None = None
    tier: Tier = Tier.TARGET
    enabled: bool = True
    config: dict = field(default_factory=dict)


@dataclass(slots=True)
class Job:
    external_id: str
    company: str
    title: str
    location: str | None
    description: str
    apply_url: str
    source_url: str
    source: str
    posted_at: datetime | None = None
    first_seen_at: datetime | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        url = canonical_url(self.apply_url or self.source_url)
        raw = "|".join(normalize(x) for x in (self.company, self.title, self.location or "", url))
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(slots=True)
class MatchResult:
    accepted: bool
    category: str | None
    score: int
    reasons: list[str]
    rejection: str | None = None


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "gh_src"))]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))
    except ValueError:
        return url


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

