#!/usr/bin/env python3
"""Merge verified probe results from scripts/probe_ats.py into the registry.

Only companies whose board passed verification are rewritten, and only when
they are not already configured, so hand-tuned entries are never clobbered.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

CONFIGURED = {"greenhouse", "lever", "ashby", "workday", "smartrecruiters",
              "jibe", "successfactors", "amazon"}


def render(companies: list[dict]) -> str:
    lines = [
        "# Registry policy: enabled entries have a verified structured collector.",
        "# Disabled entries are reputable seed candidates awaiting ATS verification",
        "# via scripts/probe_ats.py and scripts/audit_endpoints.py.",
        "companies:",
    ]
    for c in companies:
        lines.append(f'  - name: "{c["name"]}"')
        lines.append(f'    career_url: "{c["career_url"]}"')
        lines.append(f'    ats: {c.get("ats", "unknown")}')
        if c.get("ats_identifier"):
            lines.append(f'    ats_identifier: "{c["ats_identifier"]}"')
        if c.get("config"):
            lines.append("    config:")
            for key, value in c["config"].items():
                # JSON is a YAML subset, so this stays valid for scalars,
                # lists and nested mappings alike.
                lines.append(f"      {key}: {json.dumps(value)}")
        lines.append(f'    tier: {c.get("tier", "target")}')
        lines.append(f'    enabled: {"true" if c.get("enabled") else "false"}')
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("registry", type=Path)
    ap.add_argument("probe_report", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = yaml.safe_load(args.registry.read_text())
    companies = data["companies"] if isinstance(data, dict) else data
    found = {r["name"]: r for r in json.loads(args.probe_report.read_text())["results"]
             if r.get("status") == "found"}

    applied = []
    for company in companies:
        hit = found.get(company["name"])
        if not hit or company.get("ats") in CONFIGURED:
            continue
        company["ats"] = hit["ats"]
        company["ats_identifier"] = hit["ats_identifier"]
        if hit.get("config"):
            company["config"] = hit["config"]
        company["enabled"] = True
        applied.append(f'{company["name"]} -> {hit["ats"]}:{hit["ats_identifier"]} ({hit["jobs"]} postings)')

    print(f"Applying {len(applied)} newly verified boards")
    for line in applied:
        print(f"  {line}")
    if args.dry_run:
        return
    args.registry.write_text(render(companies), encoding="utf-8")
    enabled = sum(1 for c in companies if c.get("enabled"))
    print(f"Wrote {args.registry}: {len(companies)} companies, {enabled} enabled")


if __name__ == "__main__":
    main()
