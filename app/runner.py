from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.collectors.registry import get_collector
from app.config import Settings, load_companies
from app.database import Database
from app.filters.rules import evaluate
from app.http import HttpClient
from app.models import TIER_WEIGHT
from app.notifications.discord import DiscordNotifier

log = logging.getLogger("internship_monitor")


@dataclass
class Stats:
    checked: int = 0; successful: int = 0; failed: int = 0; fetched: int = 0
    internships: int = 0; matching: int = 0; new: int = 0; alerts: int = 0


async def run(settings: Settings) -> Stats:
    started = time.monotonic()
    companies = [c for c in load_companies(settings.companies_file) if c.enabled and TIER_WEIGHT[c.tier] >= TIER_WEIGHT[settings.minimum_tier]]
    db, stats = Database(settings.database_url), Stats(checked=len(companies))
    http = HttpClient(settings.concurrency, settings.per_domain_concurrency, settings.request_timeout, settings.retries)
    notifier = DiscordNotifier(settings.discord_webhook_url, http, settings.dry_run)
    scan_limit = asyncio.Semaphore(settings.concurrency)

    async def scan(company):
        async with scan_limit:
            try:
                jobs = await get_collector(company.ats, http).fetch_jobs(company)
                db.record_health(company.name, True, len(jobs))
                stats.successful += 1; stats.fetched += len(jobs)
                candidates = 0; matched = 0; new_count = 0
                for job in jobs:
                    result = evaluate(job, company, settings.minimum_tier)
                    lowered_title = job.title.lower()
                    if any(x in lowered_title for x in ("intern", "co-op", "coop", "summer analyst", "student program")):
                        candidates += 1
                    if result.accepted:
                        matched += 1
                    is_new, job_id = db.upsert_job(job, result)
                    if is_new and result.accepted:
                        new_count += 1
                        try:
                            await notifier.send(job, company, result)
                            db.mark_notified(job_id, True)
                            if settings.discord_webhook_url and not settings.dry_run: stats.alerts += 1
                        except Exception as exc:
                            db.mark_notified(job_id, False, str(exc)); log.error("%s: notification failed: %s", company.name, exc)
                stats.internships += candidates; stats.matching += matched; stats.new += new_count
                log.info("%s: fetched %d jobs, %d internship candidates, %d new matching", company.name, len(jobs), candidates, new_count)
            except Exception as exc:
                stats.failed += 1; db.record_health(company.name, False, error=str(exc))
                log.error("%s: scraper unavailable: %s", company.name, exc)

    try:
        await asyncio.gather(*(scan(c) for c in companies))
    finally:
        db.close()
        await http.close()
    elapsed = time.monotonic() - started
    log.info("Run summary | Companies checked: %d | Successful: %d | Failed: %d | Jobs fetched: %d | "
             "Internships found: %d | Matching internships: %d | New jobs: %d | Alerts sent: %d | Runtime: %.1fs",
             stats.checked, stats.successful, stats.failed, stats.fetched, stats.internships, stats.matching, stats.new, stats.alerts, elapsed)
    return stats
