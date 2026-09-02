from __future__ import annotations

import re
from datetime import timedelta

from app.models import Company, Job, MatchResult, TIER_WEIGHT, Tier, normalize, utcnow

INTERNSHIP = ("intern", "internship", "co-op", "coop", "summer analyst", "summer 2027", "summer 2026", "student program", "university program")
TECH_TITLE = ("software", "developer", "backend", "front end", "frontend", "full stack", "fullstack", "platform",
              "infrastructure", "site reliability", "sre", "distributed systems", "machine learning", " ml ",
              "artificial intelligence", " ai ", "data engineer", "security engineer", "systems engineer", "cloud engineer")
AMBIGUOUS_TITLE = ("engineering intern", "technology intern", "technology summer analyst", "developer intern", "technical intern")
TECH_BODY = ("software development", "software engineering", "programming", "computer science", "write code", "coding",
             "backend", "api", "distributed system", "machine learning", "data pipeline", "cloud", "python", "java", "c++", "golang")
EXCLUDED = ("product management", "product manager", "business analyst", "sales engineer", "sales engineering",
            "it support", "help desk", "marketing intern", "recruiting intern", "accounting intern")
GRAD_ONLY = ("phd required", "ph.d. required", "currently pursuing a phd", "doctoral students only", "graduate students only")
SENIORITY = ("5+ years", "five years of professional", "7+ years", "10+ years", "staff software", "senior software")
US_MARKERS = ("united states", "u.s.", "usa", "us remote", "remote - us", "remote, us", "remote (us)")
NON_US = ("canada", "united kingdom", "london", "india", "singapore", "australia", "germany", "france", "ireland",
          "netherlands", "poland", "israel", "japan", "china", "mexico", "brazil")
US_STATES = ("alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida",
             "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
             "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska",
             "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
             "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
             "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia")
US_CODES = {"AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"}
BACKGROUND = {
    "Distributed systems": ("distributed system", "distributed computing"),
    "Infrastructure": ("infrastructure", "platform engineering", "site reliability", "reliability engineering"),
    "Cloud": ("kubernetes", "docker", "cloud", "aws", "azure", "gcp"),
    "ML/AI systems": ("ml infrastructure", "machine learning system", "ai infrastructure", "llm", "model serving", "inference"),
    "Observability": ("observability", "prometheus", "opentelemetry", "grafana"),
    "Backend/API": ("backend", "microservices", "api gateway"),
    "Systems/networking": ("systems programming", "networking"),
    "Languages": ("python", "golang", " go ", "c++"),
    "AI agents": ("multi-agent", "ai agent", "agentic"),
}


def _has(text: str, terms: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(normalize(term) in padded for term in terms)


def evaluate(job: Job, company: Company, minimum_tier: Tier = Tier.BASELINE) -> MatchResult:
    title, body = normalize(job.title), normalize(job.description)
    combined = f" {title} {body} "
    if TIER_WEIGHT[company.tier] < TIER_WEIGHT[minimum_tier]:
        return MatchResult(False, None, 0, [], "company below reputation threshold")
    # Descriptions and equal-opportunity footers often mention interns. The role's
    # own title must carry student-program evidence to avoid alerting on full-time jobs.
    if not _has(title, INTERNSHIP):
        return MatchResult(False, None, 0, [], "not an internship/student program")
    if _has(title, EXCLUDED):
        return MatchResult(False, None, 0, [], "excluded role family")
    technical_title = _has(title, TECH_TITLE)
    ambiguous = _has(title, AMBIGUOUS_TITLE)
    body_signals = sum(term in body for term in TECH_BODY)
    if not technical_title and not (ambiguous and body_signals >= 2):
        return MatchResult(False, None, 0, [], "insufficient software/technical evidence")
    if _has(combined, GRAD_ONLY) and not any(x in combined for x in ("bachelor", "undergraduate")):
        return MatchResult(False, None, 0, [], "graduate-only role")
    if _has(title, SENIORITY) or _has(body, SENIORITY):
        return MatchResult(False, None, 0, [], "professional experience/seniority requirement")
    location = normalize(job.location or "")
    remote = "remote" in location or "remote" in body[:1500]
    explicit_us = _has(location, US_MARKERS) or _has(location, US_STATES) or any(code in US_CODES for code in re.findall(r"\b[A-Z]{2}\b", job.location or ""))
    explicit_non_us = _has(location, NON_US)
    if explicit_non_us and not explicit_us:
        return MatchResult(False, None, 0, [], "non-U.S. location")
    if remote and not (explicit_us or _has(body, US_MARKERS)):
        return MatchResult(False, None, 0, [], "remote geography is not explicitly U.S.")
    if not location and not _has(body, US_MARKERS):
        return MatchResult(False, None, 0, [], "location is missing and description does not establish U.S. eligibility")
    if location and not (explicit_us or remote) and location.lower() not in {"multiple locations", "various locations"}:
        return MatchResult(False, None, 0, [], "location is not identifiable as U.S.")

    reasons = []
    background_score = 0
    for label, terms in BACKGROUND.items():
        hits = sum(normalize(term) in combined for term in terms)
        if hits:
            reasons.append(label)
            background_score += min(6, 2 + hits)
    role_score = 28 if technical_title else 20
    internship_score = 18
    freshness = 4
    if job.posted_at:
        age = utcnow() - job.posted_at
        freshness = 10 if age <= timedelta(days=2) else 7 if age <= timedelta(days=7) else 3
    score = min(100, TIER_WEIGHT[company.tier] + role_score + internship_score + freshness + background_score)
    category = "HIGH MATCH" if background_score >= 10 or score >= 85 else "REPUTABLE SWE"
    if not reasons:
        reasons = ["Technical software internship", f"{company.tier.value.title()} company"]
    return MatchResult(True, category, score, reasons[:4])
