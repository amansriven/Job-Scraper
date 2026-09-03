#!/usr/bin/env python3
"""Verify every enabled company's board actually belongs to that company.

Slug-guessing and crawl-based discovery can both land on a real, healthy board
that simply belongs to someone else (e.g. "Sentry" the software company
matching "sentryinsurance" the Workday tenant of an unrelated insurer). This
re-fetches each enabled board and checks the postings' own text against the
registered company name so mismatches can be disabled before they cause a
wrong-company alert.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_companies
from app.http import HttpClient
from app.collectors.registry import get_collector
from scripts.probe_ats import looks_like_company, name_matches

# Collectors whose raw job payload carries the employer's own name, distinct
# from Ashby/Lever/Workday postings that only ever describe the role itself.
DIRECT_NAME_FIELDS = {
    "greenhouse": lambda j: "",  # verified separately via the /boards/{slug} endpoint
    "smartrecruiters": lambda j: (j.get("company") or {}).get("name", ""),
}


async def board_org_name(http: HttpClient, ats: str, identifier: str) -> str:
    if ats != "greenhouse":
        return ""
    try:
        data = (await http.get(f"https://boards-api.greenhouse.io/v1/boards/{identifier}")).json()
        return data.get("name", "")
    except Exception:
        return ""


async def smartrecruiters_org_name(http: HttpClient, identifier: str) -> str:
    try:
        data = (await http.get(f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings",
                               params={"limit": 1})).json()
        return (data.get("content") or [{}])[0].get("company", {}).get("name", "")
    except Exception:
        return ""


def posting_texts(jobs) -> list[str]:
    """Full text of up to 10 postings, where a company self-describes itself
    (Ashby/Lever descriptions, Workday/SuccessFactors detail pages). A single
    posting rarely repeats the employer's name, so several are pooled."""
    return [f"{job.title} {job.description or ''}" for job in jobs[:10]]


async def verify_one(http: HttpClient, company) -> dict:
    try:
        collector = get_collector(company.ats, http)
        jobs = await collector.fetch_jobs(company)
    except Exception as exc:
        return {"name": company.name, "ats": company.ats, "status": "error", "error": str(exc)[:200]}
    if not jobs:
        return {"name": company.name, "ats": company.ats, "status": "empty"}

    org_name = await board_org_name(http, company.ats, company.ats_identifier or "")
    if not org_name and company.ats == "smartrecruiters":
        org_name = await smartrecruiters_org_name(http, company.ats_identifier or "")
    if org_name:
        return {"name": company.name, "ats": company.ats, "status": "ok" if name_matches(company.name, org_name) else "mismatch",
                "evidence": org_name, "jobs": len(jobs)}

    texts = posting_texts(jobs)
    if looks_like_company(company.name, texts):
        return {"name": company.name, "ats": company.ats, "status": "ok", "jobs": len(jobs)}
    return {"name": company.name, "ats": company.ats, "status": "mismatch",
            "evidence": " ".join(texts)[:250], "jobs": len(jobs)}


async def main_async() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("registry", type=Path, default=Path("config/companies.yaml"), nargs="?")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--ats", action="append", help="Restrict to these ATS types (repeatable)")
    args = ap.parse_args()

    companies = [c for c in load_companies(args.registry) if c.enabled and c.ats not in {"generic", "custom"}]
    if args.ats:
        companies = [c for c in companies if c.ats in set(args.ats)]

    http = HttpClient(concurrency=args.concurrency, per_domain=2, timeout=25, retries=2)
    limit = asyncio.Semaphore(args.concurrency)
    done = 0

    async def one(company):
        nonlocal done
        async with limit:
            result = await verify_one(http, company)
        done += 1
        print(f"[{done}/{len(companies)}] {company.name}: {result['status']}", file=sys.stderr, flush=True)
        return result

    results = await asyncio.gather(*(one(c) for c in companies))
    await http.close()

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    args.output.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"Verified {len(results)} companies -> {args.output}")
    print("By status:", by_status)
    mismatches = [r for r in results if r["status"] == "mismatch"]
    if mismatches:
        print("\nMISMATCHES:")
        for r in mismatches:
            print(f"  {r['name']} ({r['ats']}): {r.get('evidence', '')[:120]}")


if __name__ == "__main__":
    asyncio.run(main_async())
