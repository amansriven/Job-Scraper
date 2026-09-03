#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from app.config import load_companies
from scripts.discover_ats import detect_text


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Render JavaScript career sites and discover their job APIs")
    parser.add_argument("registry", nargs="?", type=Path, default=Path("config/companies.yaml"))
    parser.add_argument("--audit-report", type=Path, help="Only inspect unresolved/error entries in an HTTP audit")
    parser.add_argument("--output", type=Path, default=Path("browser-discovery.json"))
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    args = parser.parse_args()

    companies = load_companies(args.registry)
    if args.audit_report:
        audit = json.loads(args.audit_report.read_text(encoding="utf-8"))
        unresolved = {row["name"] for row in audit["results"] if row["status"] != "verified"}
        companies = [company for company in companies if company.name in unresolved]

    limit = asyncio.Semaphore(args.concurrency)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        async def inspect(company):
            async with limit:
                page = await browser.new_page()
                resources = []
                page.on("response", lambda response: resources.append(response.url))
                try:
                    await page.goto(company.career_url, wait_until="domcontentloaded",
                                    timeout=args.timeout_seconds * 1000)
                    await page.wait_for_timeout(3000)
                    html = await page.content()
                    detected = detect_text(company.career_url, page.url, html, resources)
                    return {"name": company.name, "status": "detected" if detected else "unresolved",
                            "detected": detected, "rendered_url": page.url,
                            "network_hosts": sorted({urlparse(x).netloc for x in resources})}
                except Exception as exc:
                    return {"name": company.name, "status": "error", "career_url": company.career_url,
                            "error": f"{type(exc).__name__}: {exc}"}
                finally:
                    await page.close()

        results = await asyncio.gather(*(inspect(company) for company in companies))
        await browser.close()

    statuses = Counter(row["status"] for row in results)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "total": len(results),
              "summary": dict(sorted(statuses.items())), "results": results}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Browser discovery: {len(results)} companies | {dict(statuses)}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    asyncio.run(main_async())
