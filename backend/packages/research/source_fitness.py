from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from packages.business_intel.entity_resolver import is_trusted_url_for_competitor
from packages.research.models import (
    CandidateIntent,
    CapturedPage,
    ResearchBrief,
    SourceCandidate,
    SourceFitness,
)


@dataclass(frozen=True)
class SourceFitnessResult:
    fitness: SourceFitness
    reason: str
    coverage_intents: list[CandidateIntent] = field(default_factory=list)


def classify_source_fitness(
    brief: ResearchBrief,
    candidate: SourceCandidate,
    page: CapturedPage,
) -> SourceFitnessResult:
    dimension = brief.dimension.casefold()
    url = (page.final_url or candidate.url).casefold()
    title = (page.title or candidate.title).casefold()
    text = f"{page.title} {page.snippet} {page.text} {page.markdown}".casefold()
    official = _official_url(brief, candidate, page)

    if _community_url(url) or candidate.origin == "community_search":
        return SourceFitnessResult(
            fitness="community",
            reason="community_or_discussion_source",
            coverage_intents=["community_or_conflict_signal"],
        )
    if _contains_any(f"{url} {title}", ("changelog", "release-notes", "release notes")):
        return SourceFitnessResult(fitness="changelog", reason="changelog_url_or_title")
    if "pricing" in dimension:
        return _classify_pricing(official=official, url=url, title=title, text=text)
    if official and _contains_any(f"{url} {title}", ("docs", "features", "product", "api")):
        return SourceFitnessResult(
            fitness="product_docs",
            reason="official_product_or_docs_source",
            coverage_intents=["official_docs", "product_page"],
        )
    if official:
        return SourceFitnessResult(
            fitness="product_docs",
            reason="official_domain_source",
            coverage_intents=["official_docs"],
        )
    return SourceFitnessResult(
        fitness="third_party",
        reason="non_official_source",
        coverage_intents=["third_party_context"],
    )


def candidate_intent(
    brief: ResearchBrief,
    candidate: SourceCandidate,
) -> CandidateIntent:
    key = brief.dimension.casefold()
    haystack = f"{candidate.url} {candidate.title} {candidate.snippet}".casefold()
    if "pricing" not in key:
        if candidate.origin == "community_search" or _community_url(candidate.url):
            return "community_or_conflict_signal"
        if _official_candidate(brief, candidate):
            return "official_docs"
        return "third_party_context"
    if candidate.origin == "community_search" or _community_url(candidate.url):
        return "community_or_conflict_signal"
    if _contains_any(haystack, ("/pricing", "/plans", " pricing", " plans")):
        return "official_pricing_page" if _official_candidate(brief, candidate) else "third_party_context"
    if _contains_any(haystack, ("/billing", "/accounts/usage", "/usage", "billing", "credits")):
        return "official_billing_or_usage_docs" if _official_candidate(brief, candidate) else "third_party_context"
    if _contains_price_signal(haystack):
        return "current_plan_price_support"
    if _official_candidate(brief, candidate):
        return "official_docs"
    return "third_party_context"


def _classify_pricing(
    *,
    official: bool,
    url: str,
    title: str,
    text: str,
) -> SourceFitnessResult:
    path_title = f"{url} {title}"
    has_price = _contains_price_signal(text)
    if _contains_any(path_title, ("/pricing", "/plans", " pricing", " plans")):
        intents: list[CandidateIntent] = ["official_pricing_page"]
        if has_price:
            intents.append("current_plan_price_support")
        return SourceFitnessResult(
            fitness="official_pricing" if official else "third_party",
            reason="pricing_path_or_title",
            coverage_intents=intents if official else ["third_party_context"],
        )
    if _contains_any(path_title, ("/billing", "/accounts/usage", "/usage", "billing", "credits")):
        intents = ["official_billing_or_usage_docs"]
        if has_price and _contains_any(text, ("plan", "tier", "seat", "month", "annual")):
            intents.append("current_plan_price_support")
        return SourceFitnessResult(
            fitness="official_billing_docs" if official else "third_party",
            reason="billing_or_usage_source",
            coverage_intents=intents if official else ["third_party_context"],
        )
    if official and _contains_any(text, ("usage", "credits", "rate limit", "limits")):
        return SourceFitnessResult(
            fitness="official_usage_limits",
            reason="official_usage_limits_without_pricing_path",
            coverage_intents=["official_billing_or_usage_docs"],
        )
    if official and _contains_any(path_title, ("docs", "plugin", "cascade", "overview", "api")):
        return SourceFitnessResult(fitness="product_docs", reason="official_product_docs")
    if official:
        return SourceFitnessResult(fitness="unknown", reason="official_source_without_pricing_signal")
    return SourceFitnessResult(
        fitness="third_party",
        reason="non_official_pricing_context",
        coverage_intents=["third_party_context"],
    )


def _official_url(brief: ResearchBrief, candidate: SourceCandidate, page: CapturedPage) -> bool:
    url = page.final_url or candidate.url
    return _official_candidate(brief, candidate) or _host_matches_homepage(
        url,
        brief.homepage_hint,
    )


def _official_candidate(brief: ResearchBrief, candidate: SourceCandidate) -> bool:
    if candidate.origin in {"trusted_registry", "homepage_derived", "manual"}:
        return True
    if is_trusted_url_for_competitor(brief.competitor, candidate.url):
        return True
    return _host_matches_homepage(candidate.url, brief.homepage_hint)


def _host_matches_homepage(url: str, homepage_hint: str | None) -> bool:
    if not url or not homepage_hint:
        return False
    host = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    homepage_host = (urlparse(homepage_hint).hostname or "").casefold().removeprefix("www.")
    return bool(host and homepage_host and (host == homepage_host or host.endswith(f".{homepage_host}")))


def _community_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return any(token in host for token in ("reddit.", "news.ycombinator.", "forum.", "community."))


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _contains_price_signal(value: str) -> bool:
    return bool(
        re.search(r"\$\s*\d+|\b\d+\s*(?:usd|/mo|per month|monthly|credits?|seats?)\b", value)
    )
