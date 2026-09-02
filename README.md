# Internship Monitor

A no-UI, personal internship monitoring service. One invocation scans all enabled companies, normalizes jobs, applies deterministic U.S. technical-internship rules, stores results in SQLite, and sends Discord alerts only for newly discovered matches.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Export values from .env with your preferred environment manager.
python scripts/validate_companies.py
DRY_RUN=true python -m app.main
```

Set `DISCORD_WEBHOOK_URL`, then schedule `python -m app.main` every 30–60 minutes using cron, Railway, Render, GitHub Actions, or another external scheduler. The application deliberately performs one scan and exits. With SQLite, persist the `data/` directory; use a single scheduled instance to avoid concurrent writers.

## Registry policy

`config/companies.yaml` contains more than 300 reputable U.S. internship targets. Entries with a verified structured collector configuration are enabled. The broader curated universe is deliberately disabled and marked `ats: unknown` until its career URL and ATS identifier are verified; this prevents hundreds of predictable failures and false confidence. Enable companies incrementally:

```bash
python scripts/discover_ats.py https://company.example/careers
python scripts/discover_ats.py config/companies.yaml > discovery.yaml
```

Transfer the detected ATS fields into the registry, verify with a dry run, then set `enabled: true`. For custom sites, use `ats: generic` with `config.job_selector`, `title_selector`, `link_selector`, and optionally `location_selector` and `fetch_detail`.

Workday entries also need `config.host`, `config.tenant`, and `config.site`; Workday tenants vary by cluster. SmartRecruiters, Ashby, Lever, and Greenhouse use `ats_identifier` as their tenant/board slug. iCIMS and SuccessFactors are detected by discovery but intentionally require a custom adapter because public endpoints and tenant configuration vary substantially.

## Matching and safety

Eligibility requires student/internship evidence, software/ML/infrastructure/security/data engineering evidence, and a U.S. or explicitly U.S.-remote location. Graduate-only, senior, obvious business, support, sales, and non-U.S. roles are rejected. Ambiguous titles such as “Technology Summer Analyst” must have technical evidence in their descriptions.

Scores combine company tier, role confidence, background signals, and freshness. A strong generic role remains `REPUTABLE SWE`; infrastructure, distributed systems, cloud, ML systems, observability, backend, networking, and relevant language signals can elevate it to `HIGH MATCH`. Rules live in `app/filters/rules.py` and are intentionally easy to tune.

Jobs are unique by `(source, external_id)`, with a normalized company/title/location/canonical-URL fingerprint fallback. Reappearing stable IDs are updated without another alert. Collector health stores success/failure timestamps, consecutive failures, the latest error, and job counts.

## Operations

- Back up `data/internships.db` and persist it across deployments.
- Alert on growing `collector_health.consecutive_failures` values.
- Run `python scripts/validate_companies.py` in CI after registry edits.
- Use `DRY_RUN=true` for first scans. It records matches but does not send webhooks; use a fresh test database if you later want those same findings to alert.
- A company failure is isolated; the rest of the run continues.
- The persistence class isolates SQLite-specific code, providing a clear seam for a future PostgreSQL adapter.

## Tests

```bash
pytest -q
```

