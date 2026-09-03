#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml

PATTERNS = {
    "jibe": [r"app\.jibecdn\.com/prod/search/"],
    "greenhouse": [
        r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)",
        r"boards\.greenhouse\.io/embed/job_board\?for=([\w-]+)",
        r"(?:boards|job-boards)\.greenhouse\.io/([\w-]+)",
    ],
    "lever": [r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?([\w-]+)"],
    "ashby": [r"jobs\.ashbyhq\.com/([\w-]+)"],
    "workday": [r"https?://([\w-]+)\.(wd\d+\.)?myworkdayjobs\.com/(?:[\w-]+/)?([\w-]+)"],
    "smartrecruiters": [r"jobs\.smartrecruiters\.com/([\w-]+)"],
    "icims": [r"([\w-]+)\.icims\.com/jobs"],
    "successfactors": [r"career[s]?\d*\.successfactors\.(?:com|eu)/career"],
}


def detect_text(career_url: str, resolved_url: str, html: str, resources: list[str] | None = None) -> dict | None:
    links = [urljoin(resolved_url, x) for x in re.findall(r'''(?:href|src)=["']([^"']+)["']''', html, re.I)]
    text = "\n".join((resolved_url, html, *links, *(resources or [])))
    for ats, patterns in PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            groups = [x for x in match.groups() if x and not x.startswith("wd")]
            identifier = groups[0] if groups else None
            if ats == "greenhouse" and identifier in {"embed", "jobs", "job", "boards"}:
                continue
            if ats == "lever" and identifier in {"v0", "v1", "postings", "jobs"}:
                continue
            result = {"career_url": career_url, "ats": ats, "ats_identifier": identifier, "resolved_url": resolved_url}
            if ats == "jibe":
                parsed = urlparse(resolved_url)
                result["config"] = {"api_base": f"{parsed.scheme}://{parsed.netloc}"}
            if ats == "workday" and groups:
                host = urlparse(match.group(0)).netloc
                result["config"] = {"host": host, "tenant": groups[0], "site": groups[-1]}
            if ats == "successfactors":
                job_link = re.search(r'href=["\'][^"\']*/job/[^"\']+/(\d+)/(?:\d+)["\']', html, re.I)
                form = re.search(r'<form[^>]+action=["\']([^"\']*search-jobs)["\']', html, re.I)
                if job_link and form:
                    parsed = urlparse(resolved_url)
                    result["config"] = {"base_url": f"{parsed.scheme}://{parsed.netloc}",
                                        "search_prefix": form.group(1), "organization_id": job_link.group(1)}
            return result
    # Recruiting Marketing pages do not always expose a successfactors.com URL.
    if "data-organization-ids=" in html and "search-jobs" in html:
        org = re.search(r'data-organization-ids=["\'](\d+)["\']', html, re.I)
        form = re.search(r'<form[^>]+action=["\']([^"\']*search-jobs)["\']', html, re.I)
        if org and form:
            parsed = urlparse(resolved_url)
            return {"career_url": career_url, "ats": "successfactors", "ats_identifier": None,
                    "resolved_url": resolved_url,
                    "config": {"base_url": f"{parsed.scheme}://{parsed.netloc}",
                               "search_prefix": form.group(1), "organization_id": org.group(1)}}
    return None


async def discover(url: str, client: httpx.AsyncClient, max_pages: int = 4) -> dict:
    queue, visited, last_url = [url], set(), url
    first_error = None
    while queue and len(visited) < max_pages:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        try:
            response = await client.get(current)
            response.raise_for_status()
        except Exception as exc:
            first_error = first_error or exc
            continue
        last_url = str(response.url)
        detected = detect_text(url, last_url, response.text)
        if detected:
            detected["pages_checked"] = len(visited)
            return detected
        origin = urlparse(last_url).netloc.lower().removeprefix("www.")
        links = [urljoin(last_url, x) for x in re.findall(r'''href=["']([^"'#]+)["']''', response.text, re.I)]
        candidates = []
        for link in links:
            parsed = urlparse(link)
            external_ats = any(token in parsed.netloc for token in (
                "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com",
                "icims.com", "successfactors.com", "jobs2web.com",
            ))
            same_org = parsed.netloc.lower().removeprefix("www.").endswith(origin)
            career_path = re.search(r"(?:career|job|opening|opportunit|search)", parsed.path, re.I)
            if parsed.scheme in {"http", "https"} and (external_ats or (same_org and career_path)):
                candidates.append(link)
        queue.extend(link for link in candidates if link not in visited and link not in queue)
    if len(visited) == 1 and first_error:
        return {"career_url": url, "ats": "error", "error": str(first_error), "pages_checked": len(visited)}
    return {"career_url": url, "ats": "unknown", "resolved_url": last_url, "pages_checked": len(visited)}


def load_urls(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text())
        rows = data.get("companies", data)
        return [(x.get("name", ""), x["career_url"]) for x in rows]
    with path.open(newline="", encoding="utf-8") as handle:
        return [(row.get("name", ""), row["career_url"]) for row in csv.DictReader(handle)]


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Detect ATS providers from one URL or a YAML/CSV registry")
    parser.add_argument("target"); parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path, help="Write YAML results to a file instead of stdout")
    parser.add_argument("--summary", action="store_true", help="Print provider counts after discovery")
    args = parser.parse_args()
    path = Path(args.target)
    rows = load_urls(path) if path.exists() else [("", args.target)]
    limit = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "InternshipMonitorDiscovery/1.0"}) as client:
        async def one(name, url):
            async with limit:
                return {"name": name, **await discover(url, client)}
        results = await asyncio.gather(*(one(*row) for row in rows))
    rendered = yaml.safe_dump(results, sort_keys=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {len(results)} results to {args.output}")
    else:
        print(rendered)
    if args.summary:
        counts = {}
        for result in results:
            counts[result["ats"]] = counts.get(result["ats"], 0) + 1
        print("ATS summary:", counts)


if __name__ == "__main__":
    asyncio.run(main_async())
