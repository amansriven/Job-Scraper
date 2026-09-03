#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.registry import COLLECTORS, get_collector
from app.config import load_companies
from app.http import HttpClient
from app.models import Company


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Live-verify ATS candidates found by browser discovery")
    parser.add_argument("browser_report", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("config/companies.yaml"))
    parser.add_argument("--output", type=Path, default=Path("verified-browser-candidates.json"))
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    known = {company.name: company for company in load_companies(args.registry)}
    discovered = json.loads(args.browser_report.read_text(encoding="utf-8"))["results"]
    candidates = [row for row in discovered if (row.get("detected") or {}).get("ats") in COLLECTORS]
    http = HttpClient(concurrency=args.concurrency, per_domain=1, timeout=25, retries=3)
    limit = asyncio.Semaphore(args.concurrency)

    async def verify(row):
        async with limit:
            source = known[row["name"]]
            found = row["detected"]
            candidate = Company(source.name, source.career_url, found["ats"], found.get("ats_identifier"),
                                source.tier, False, found.get("config", {}))
            try:
                jobs = await get_collector(candidate.ats, http).fetch_jobs(candidate)
                return {"name": source.name, "status": "verified", "ats": candidate.ats,
                        "ats_identifier": candidate.ats_identifier, "config": candidate.config,
                        "jobs_returned": len(jobs)}
            except Exception as exc:
                return {"name": source.name, "status": "failed", "ats": candidate.ats,
                        "ats_identifier": candidate.ats_identifier, "config": candidate.config,
                        "error": f"{type(exc).__name__}: {exc}"}

    try:
        results = await asyncio.gather(*(verify(row) for row in candidates))
    finally:
        await http.close()
    summary = Counter(row["status"] for row in results)
    args.output.write_text(json.dumps({"summary": dict(summary), "results": results}, indent=2) + "\n",
                           encoding="utf-8")
    print(f"Candidate verification: {len(results)} | {dict(summary)}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    asyncio.run(main_async())
