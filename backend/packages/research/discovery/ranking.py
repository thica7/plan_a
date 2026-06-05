from __future__ import annotations

from urllib.parse import urlparse

from packages.business_intel.entity_resolver import is_trusted_url_for_competitor
from packages.research.discovery.constants import SOURCE_ORIGIN_PRIORITY
from packages.research.models import SourceCandidate


def rank_and_dedupe_candidates(
    candidates: list[SourceCandidate],
    *,
    competitor: str,
    dimension: str,
    homepage_hint: str | None = None,
) -> list[SourceCandidate]:
    best_by_url: dict[str, SourceCandidate] = {}
    for candidate in candidates:
        key = canonical_url(candidate.url)
        existing = best_by_url.get(key)
        if existing is None or _score(
            candidate,
            competitor=competitor,
            dimension=dimension,
            homepage_hint=homepage_hint,
        ) > _score(
            existing,
            competitor=competitor,
            dimension=dimension,
            homepage_hint=homepage_hint,
        ):
            best_by_url[key] = candidate
    return sorted(
        best_by_url.values(),
        key=lambda candidate: _score(
            candidate,
            competitor=competitor,
            dimension=dimension,
            homepage_hint=homepage_hint,
        ),
        reverse=True,
    )


def canonical_url(url: str) -> str:
    return str(url).strip().rstrip("/")


def _score(
    candidate: SourceCandidate,
    *,
    competitor: str,
    dimension: str,
    homepage_hint: str | None,
) -> tuple[int, float, int, int, int, str]:
    url = candidate.url.casefold()
    host = _host(candidate.url)
    homepage_host = _host(homepage_hint or "")
    origin_score = SOURCE_ORIGIN_PRIORITY.get(candidate.origin, 0)
    trust_score = 1 if is_trusted_url_for_competitor(competitor, candidate.url) else 0
    homepage_score = 1 if homepage_host and host.endswith(homepage_host) else 0
    dimension_score = 1 if _dimension_hint_present(dimension, url, candidate.snippet) else 0
    return (
        origin_score,
        candidate.confidence,
        trust_score + homepage_score,
        dimension_score,
        -candidate.rank,
        candidate.url,
    )


def _dimension_hint_present(dimension: str, url: str, snippet: str) -> bool:
    haystack = f"{url} {snippet}".casefold()
    key = dimension.casefold()
    if "pricing" in key:
        terms = ("pricing", "price", "plans", "billing", "cost", "usage")
    elif "persona" in key or "user" in key:
        terms = ("customer", "case", "use-case", "use case", "enterprise", "solutions")
    elif "security" in key or "trust" in key:
        terms = ("security", "trust", "compliance", "privacy", "soc", "iso")
    else:
        terms = ("docs", "features", "models", "product", "api", "capabilities")
    return any(term in haystack for term in terms)


def _host(url: str) -> str:
    if not url:
        return ""
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")
