#!/usr/bin/env python3
"""Probe public ATS APIs directly to find each company's job board.

Careers landing pages are frequently JavaScript-only, bot-protected, or simply
not where the jobs live. The ATS APIs themselves are public, cheap, and stable,
so deriving candidate slugs from the company name and probing those APIs finds
far more boards than crawling marketing pages does.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

WORKDAY_HOSTS = ["wd1", "wd2", "wd3", "wd5", "wd10", "wd12", "wd101", "wd103"]
# Ordered by observed frequency: the first hit wins, so common names go first.
WORKDAY_SITES = [
    "External", "Careers", "careers", "External_Career_Site", "ExternalCareerSite",
    "{slug}careers", "{Slug}Careers", "{Slug}_Careers", "{Slug}ExternalCareerSite",
    "{Slug}_External_Career_Site", "CareerSite", "Global_Careers", "GlobalCareers",
    "External_Careers", "{Slug}Careers_External", "jobs", "Search", "Professional",
    "{Slug}JobSite", "{Slug}_Careers_Site", "Corporate", "US_Careers",
]


def slug_candidates(name: str, career_url: str) -> list[str]:
    """Candidate board slugs, most likely first, de-duplicated."""
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    hyphen = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]
    host = urlparse(career_url).netloc.lower().removeprefix("www.")
    domain = host.split(".")[0] if host else ""
    out = [compact, domain, hyphen]
    if len(words) > 1:
        out += [words[0], "".join(words) + "inc"]
    # Common suffix conventions on Greenhouse/Lever boards.
    out += [f"{compact}inc", f"{compact}careers"]
    seen, result = set(), []
    for s in out:
        if s and len(s) > 2 and s not in seen:
            seen.add(s)
            result.append(s)
    return result


TEST_TITLE = re.compile(
    r"\b(?:test|testing|bug\s*bash|do\s*not\s*apply|demo|sample|dummy|uat|placeholder)\b|^\W*\d+\W*$",
    re.IGNORECASE,
)


def tokens(value: str) -> set[str]:
    stop = {"inc", "corp", "corporation", "the", "co", "company", "labs", "technologies", "group"}
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t and t not in stop}


def acronym(company: str) -> str:
    """"Hudson River Trading" -> "hrt": companies are often known by initials."""
    return "".join(t[0] for t in sorted(tokens(company)) if t)


def name_matches(company: str, board_name: str) -> bool:
    """True when a board's declared org name plausibly belongs to the company.

    Requires every significant token of the shorter name to appear in the
    longer one. A single shared token is not enough: "Applied Materials"
    and "Applied Intuition" both contain "applied", but guessing the slug
    `applied` on Ashby resolves to the latter, an unrelated company. A
    3+ letter acronym match ("HRT" for Hudson River Trading) is accepted
    too, since companies often refer to themselves that way in postings.
    """
    a, b = tokens(company), tokens(board_name)
    if not a or not b:
        return True  # nothing to contradict
    if a.issubset(b) or b.issubset(a):
        return True
    flat_a, flat_b = "".join(sorted(a)), "".join(sorted(b))
    if flat_a in flat_b or flat_b in flat_a:
        return True
    short = acronym(company)
    return len(short) >= 3 and short in b


def looks_like_company(company: str, texts: list[str]) -> bool:
    """Loose identity check over free-form posting text (Lever/Ashby/Workday
    expose no org-name field, so a job's own self-description is the only
    signal). Any one text matching is enough, since not every posting
    repeats the employer's name."""
    combined = tokens(" ".join(texts))
    if not combined:
        return True
    return name_matches(company, " ".join(combined))


ROLE_WORD = re.compile(
    r"\b(?:engineer|engineering|developer|scientist|analyst|manager|director|designer|"
    r"architect|specialist|consultant|administrator|technician|associate|assistant|"
    r"intern|internship|co-?op|lead|head|officer|coordinator|recruiter|counsel|"
    r"accountant|marketing|sales|support|operations|product|program|project|research|"
    r"data|software|security|principal|senior|staff|vp|president|representative|"
    r"strategist|advisor|partner|writer|editor|producer|nurse|physician|driver|"
    r"technologist|apprentice|fellow|trainee|supervisor|controller|auditor|buyer)\b",
    re.IGNORECASE,
)


def looks_like_sandbox(titles: list[str]) -> bool:
    """Reject boards whose postings are test scaffolding rather than real roles.

    Vendors leave demo tenants on guessable slugs (`linkedin` on Lever is a QA
    board of "Deauth Test" and "BO Prim"). Real boards are dominated by titles
    containing an occupational noun; sandboxes are not.
    """
    titles = [t for t in titles if t and t.strip()]
    if not titles:
        return True
    if sum(1 for t in titles if TEST_TITLE.search(t)) / len(titles) >= 0.3:
        return True
    return sum(1 for t in titles if ROLE_WORD.search(t)) / len(titles) < 0.5


async def _json(client: httpx.AsyncClient, url: str, **kw) -> tuple[int, object]:
    try:
        r = await client.get(url, **kw)
    except Exception:
        return 0, None
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


async def probe_greenhouse(client, company, slug):
    code, data = await _json(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    jobs = (data or {}).get("jobs") if isinstance(data, dict) else None
    if code != 200 or not jobs:
        return None
    _, meta = await _json(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}")
    board_name = (meta or {}).get("name", "") if isinstance(meta, dict) else ""
    if board_name and not name_matches(company, board_name):
        return {"rejected": f"board name {board_name!r} does not match"}
    if looks_like_sandbox([j.get("title", "") for j in jobs[:25]]):
        return {"rejected": "board looks like a test sandbox"}
    return {"ats": "greenhouse", "ats_identifier": slug, "jobs": len(jobs), "board_name": board_name}


async def probe_lever(client, company, slug):
    code, data = await _json(client, f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if code != 200 or not isinstance(data, list) or not data:
        return None
    if looks_like_sandbox([j.get("text", "") for j in data[:25]]):
        return {"rejected": "board looks like a test sandbox"}
    texts = [j.get("descriptionPlain") or j.get("description", "") for j in data[:8]]
    if not looks_like_company(company, texts):
        return {"rejected": "postings do not self-describe as this company"}
    return {"ats": "lever", "ats_identifier": slug, "jobs": len(data)}


async def probe_ashby(client, company, slug):
    code, data = await _json(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = (data or {}).get("jobs") if isinstance(data, dict) else None
    if code != 200 or not jobs:
        return None
    if looks_like_sandbox([j.get("title", "") for j in jobs[:25]]):
        return {"rejected": "board looks like a test sandbox"}
    texts = [j.get("descriptionPlain") or j.get("descriptionHtml", "") for j in jobs[:8]]
    if not looks_like_company(company, texts):
        return {"rejected": "postings do not self-describe as this company"}
    return {"ats": "ashby", "ats_identifier": slug, "jobs": len(jobs)}


async def probe_smartrecruiters(client, company, slug):
    code, data = await _json(
        client, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 25})
    if code != 200 or not isinstance(data, dict):
        return None
    total, content = data.get("totalFound", 0), data.get("content", [])
    if not total or not content:
        return None
    board_name = (content[0].get("company") or {}).get("name", "")
    if board_name and not name_matches(company, board_name):
        return {"rejected": f"board name {board_name!r} does not match"}
    if looks_like_sandbox([j.get("name", "") for j in content]):
        return {"rejected": "board looks like a test sandbox"}
    return {"ats": "smartrecruiters", "ats_identifier": slug, "jobs": total, "board_name": board_name}


async def workday_identity_ok(client: httpx.AsyncClient, company: str, base: str, site: str) -> bool:
    """Fetch one job's detail page and check its own description text.

    Workday search results carry no org-name field (just title/location), so
    a wrong tenant guess (e.g. a Workday customer that happens to share a
    slug) would otherwise be indistinguishable from a real match.
    """
    try:
        listing = await client.post(f"{base}/{site}/jobs", json={"limit": 1, "offset": 0, "searchText": ""})
        path = listing.json()["jobPostings"][0]["externalPath"]
        detail = await client.get(f"{base}/{site}{path}")
        text = detail.json().get("jobPostingInfo", {}).get("jobDescription", "")
    except Exception:
        return True  # can't fetch detail; don't block on an unrelated failure
    return looks_like_company(company, [text])


async def probe_workday(client: httpx.AsyncClient, company: str, slug: str) -> dict | None:
    """Find a Workday tenant, then its site name.

    The CXS API answers 422 for an unknown tenant but 404 for a known tenant
    with an unknown site, so one request per host settles tenant existence
    before any site names are searched. Hosts are probed concurrently because
    a miss still costs a full round trip.
    """
    payload = {"limit": 1, "offset": 0, "searchText": ""}

    async def attempt(base: str, site: str) -> tuple[int, int]:
        # Workday throttles bursts, so a dropped connection is retried once
        # before the tenant is written off as missing.
        for delay in (0, 1.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await client.post(f"{base}/{site}/jobs", json=payload)
            except Exception:
                continue
            if response.status_code != 200:
                return response.status_code, 0
            try:
                return 200, int(response.json().get("total", 0))
            except Exception:
                return 200, 0
        return 0, 0

    def base_for(host: str) -> str:
        return f"https://{slug}.{host}.myworkdayjobs.com/wday/cxs/{slug}"

    probes = await asyncio.gather(*(attempt(base_for(h), "External") for h in WORKDAY_HOSTS))
    for host, (status, total) in zip(WORKDAY_HOSTS, probes):
        # Only 404 means "tenant exists, wrong site name". Sweeping site names
        # on any other status turns one throttled response into 20 more
        # requests per host, which is what makes a full run unbounded.
        if status not in {200, 404}:
            continue
        base = base_for(host)
        if status == 200 and total:
            if not await workday_identity_ok(client, company, base, "External"):
                continue
            return {"ats": "workday", "ats_identifier": slug, "jobs": total,
                    "config": {"host": f"{slug}.{host}.myworkdayjobs.com",
                               "tenant": slug, "site": "External"}}
        sites = [t.format(slug=slug, Slug=slug.capitalize())
                 for t in WORKDAY_SITES if t != "External"]
        results = await asyncio.gather(*(attempt(base, s) for s in sites))
        for site, (site_status, site_total) in zip(sites, results):
            if site_status == 200 and site_total:
                if not await workday_identity_ok(client, company, base, site):
                    continue
                return {"ats": "workday", "ats_identifier": slug, "jobs": site_total,
                        "config": {"host": f"{slug}.{host}.myworkdayjobs.com",
                                   "tenant": slug, "site": site}}
    return None


PROBES = [probe_greenhouse, probe_lever, probe_ashby, probe_smartrecruiters]


async def probe_company(client: httpx.AsyncClient, name: str, career_url: str,
                        workday: bool, min_jobs: int) -> dict:
    """Return the first candidate board that passes verification."""
    slugs = slug_candidates(name, career_url)
    rejections: list[str] = []
    for slug in slugs:
        for probe in PROBES:
            hit = await probe(client, name, slug)
            if not hit:
                continue
            if "rejected" in hit:
                rejections.append(f"{slug}: {hit['rejected']}")
                continue
            if hit["jobs"] < min_jobs:
                rejections.append(f"{slug}: only {hit['jobs']} postings")
                continue
            return {"name": name, "career_url": career_url, "status": "found", **hit}
    if workday:
        for slug in slugs[:3]:
            hit = await probe_workday(client, name, slug)
            if hit and hit["jobs"] >= min_jobs:
                return {"name": name, "career_url": career_url, "status": "found", **hit}
    return {"name": name, "career_url": career_url, "status": "not_found",
            "slugs_tried": slugs, "rejections": rejections}


async def main_async() -> None:
    ap = argparse.ArgumentParser(description="Probe ATS APIs for company job boards")
    ap.add_argument("registry", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--only-unknown", action="store_true", help="Skip companies that already have an ATS")
    ap.add_argument("--no-workday", action="store_true", help="Skip the slower Workday tenant search")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-jobs", type=int, default=10,
                    help="Reject boards with fewer postings than this")
    args = ap.parse_args()

    rows = yaml.safe_load(args.registry.read_text())
    rows = rows.get("companies", rows) if isinstance(rows, dict) else rows
    if args.only_unknown:
        rows = [r for r in rows if r.get("ats", "unknown") in {"unknown", "generic", "custom"}]
    if args.limit:
        rows = rows[: args.limit]

    limit = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
        done = 0

        async def one(row):
            nonlocal done
            async with limit:
                result = await probe_company(client, row["name"], row.get("career_url", ""),
                                             not args.no_workday, args.min_jobs)
            done += 1
            mark = result["ats"] if result["status"] == "found" else "-"
            print(f"[{done}/{len(rows)}] {row['name']}: {mark}", file=sys.stderr, flush=True)
            return result
        results = await asyncio.gather(*(one(r) for r in rows))

    found = [r for r in results if r["status"] == "found"]
    args.output.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    by_ats: dict[str, int] = {}
    for r in found:
        by_ats[r["ats"]] = by_ats.get(r["ats"], 0) + 1
    print(f"Probed {len(results)} companies; found {len(found)} boards -> {args.output}")
    print("By ATS:", by_ats)


if __name__ == "__main__":
    asyncio.run(main_async())
