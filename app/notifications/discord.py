from __future__ import annotations

import asyncio
from datetime import timezone

from app.http import HttpClient
from app.models import Company, Job, MatchResult


class DiscordNotifier:
    def __init__(self, webhook_url: str | None, http: HttpClient, dry_run: bool = False):
        self.webhook_url, self.http, self.dry_run = webhook_url, http, dry_run

    async def send(self, job: Job, company: Company, match: MatchResult) -> None:
        if not self.webhook_url or self.dry_run:
            return
        high = match.category == "HIGH MATCH"
        title = f"🔥 HIGH MATCH — NEW INTERNSHIP" if high else "🚨 REPUTABLE SWE — NEW INTERNSHIP"
        fields = [
            {"name": "Company", "value": company.name, "inline": True},
            {"name": "Location", "value": job.location or "Not specified", "inline": True},
            {"name": "Tier / Score", "value": f"{company.tier.value.title()} · {match.score}/100", "inline": True},
            {"name": "Why it matched", "value": "\n".join(f"• {x}" for x in match.reasons), "inline": False},
        ]
        if job.posted_at:
            fields.append({"name": "Posted", "value": job.posted_at.astimezone(timezone.utc).strftime("%Y-%m-%d"), "inline": True})
        payload = {"embeds": [{"title": title, "description": f"**{job.title}**\n[Apply directly]({job.apply_url})",
                               "color": 0xF04B32 if high else 0x5865F2, "fields": fields}]}
        await self.http.post(self.webhook_url, json=payload)
        await asyncio.sleep(0.35)

