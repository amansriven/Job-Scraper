#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.registry import COLLECTORS, get_collector
from app.config import load_companies
from app.http import HttpClient
from app.models import Company
from scripts.discover_ats import discover


async def audit_company(company: Company, discovery: httpx.AsyncClient, http: HttpClient) -> dict:
    candidate = company
    detected = None
    if company.ats not in COLLECTORS:
        detected = await discover(company.career_url, discovery)
        ats = detected.get("ats")
        if ats not in COLLECTORS:
            return {
                "name": company.name,
                "enabled": company.enabled,
                "status": "unresolved" if ats == "unknown" else ats,
                "career_url": company.career_url,
                "detected": detected,
            }
        candidate = Company(
            name=company.name,
            career_url=company.career_url,
            ats=ats,
            ats_identifier=detected.get("ats_identifier"),
            tier=company.tier,
            enabled=company.enabled,
            config=detected.get("config", {}),
        )

    try:
        jobs = await get_collector(candidate.ats, http).fetch_jobs(candidate)
        result = {
            "name": company.name,
            "enabled": company.enabled,
            "status": "verified",
            "career_url": company.career_url,
            "ats": candidate.ats,
            "ats_identifier": candidate.ats_identifier,
            "config": candidate.config,
            "jobs_returned": len(jobs),
        }
        if detected:
            result["detected"] = detected
        return result
    except Exception as exc:
        return {
            "name": company.name,
            "enabled": company.enabled,
            "status": "failed",
            "career_url": company.career_url,
            "ats": candidate.ats,
            "ats_identifier": candidate.ats_identifier,
            "config": candidate.config,
            "error": f"{type(exc).__name__}: {exc}",
            **({"detected": detected} if detected else {}),
        }


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Discover and live-verify every company ATS endpoint")
    parser.add_argument("registry", nargs="?", type=Path, default=Path("config/companies.yaml"))
    parser.add_argument("--output", type=Path, default=Path("endpoint-audit.json"))
    parser.add_argument("--scope", choices=("all", "enabled", "disabled"), default="all")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--fail-enabled", action="store_true", help="Exit nonzero if an enabled endpoint fails")
    args = parser.parse_args()

    companies = load_companies(args.registry)
    if args.scope != "all":
        want_enabled = args.scope == "enabled"
        companies = [company for company in companies if company.enabled is want_enabled]

    limit = asyncio.Semaphore(args.concurrency)
    http = HttpClient(concurrency=args.concurrency, per_domain=1, timeout=25, retries=3)
    async with httpx.AsyncClient(
        timeout=25,
        follow_redirects=True,
        headers={"User-Agent": "InternshipMonitorEndpointAudit/1.0"},
    ) as discovery:
        async def one(company: Company) -> dict:
            async with limit:
                return await audit_company(company, discovery, http)

        try:
            results = await asyncio.gather(*(one(company) for company in companies))
        finally:
            await http.close()

    statuses = Counter(result["status"] for result in results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry": str(args.registry),
        "scope": args.scope,
        "total": len(results),
        "summary": dict(sorted(statuses.items())),
        "results": results,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Endpoint audit: {len(results)} companies | {dict(statuses)}")
    print(f"Report: {args.output}")
    failed_enabled = [result["name"] for result in results if result["enabled"] and result["status"] != "verified"]
    if args.fail_enabled and failed_enabled:
        raise SystemExit("Enabled endpoints failed verification: " + ", ".join(failed_enabled))


if __name__ == "__main__":
    asyncio.run(main_async())
