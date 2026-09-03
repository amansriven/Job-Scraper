#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.registry import COLLECTORS
from app.config import load_companies


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("path", nargs="?", default="config/companies.yaml")
    args = parser.parse_args(); companies = load_companies(Path(args.path)); errors = []
    for c in companies:
        if c.enabled and c.ats not in COLLECTORS:
            errors.append(f"{c.name}: unsupported enabled ATS {c.ats}")
        if c.enabled and c.ats in {"greenhouse", "lever", "ashby", "smartrecruiters"} and not c.ats_identifier:
            errors.append(f"{c.name}: missing ats_identifier")
        if c.enabled and c.ats == "jibe" and not c.config.get("api_base"):
            errors.append(f"{c.name}: Jibe collector missing config.api_base")
        if c.enabled and c.ats == "successfactors" and not c.config.get("organization_id"):
            errors.append(f"{c.name}: SuccessFactors collector missing config.organization_id")
        if c.enabled and c.ats in {"generic", "custom"} and not c.config.get("job_selector"):
            errors.append(f"{c.name}: generic collector missing job_selector")
    counts = Counter(c.ats for c in companies)
    print(f"Companies: {len(companies)}; enabled: {sum(c.enabled for c in companies)}; ATS: {dict(counts)}")
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__": main()
