from __future__ import annotations

from packages.research.models import SourceCandidate
from packages.search import SearchResult

SOURCE_ORIGIN_PRIORITY: dict[str, int] = {
    "trusted_registry": 400,
    "perplexity": 300,
    "web_search": 280,
    "homepage_derived": 120,
    "llm_fallback": 40,
}


def source_candidate_from_search_result(
    result: SearchResult,
    *,
    origin: str,
    rank: int,
    confidence: float,
    competitor: str = "",
    dimension: str = "",
    query: str | None = None,
) -> SourceCandidate:
    return SourceCandidate(
        title=result.title,
        url=result.url,
        snippet=result.snippet,
        origin=origin,
        rank=rank,
        confidence=confidence,
        competitor=competitor,
        dimension=dimension,
        query=query,
        date=result.date,
        last_updated=result.last_updated,
    )


def canonical_candidate_url(url: str) -> str:
    return str(url).strip().rstrip("/")


def dedupe_source_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    best_by_url: dict[str, SourceCandidate] = {}
    for candidate in candidates:
        key = canonical_candidate_url(candidate.url)
        existing = best_by_url.get(key)
        if existing is None or _candidate_sort_key(candidate) > _candidate_sort_key(existing):
            best_by_url[key] = candidate
    return sorted(best_by_url.values(), key=_candidate_sort_key, reverse=True)


def _candidate_sort_key(candidate: SourceCandidate) -> tuple[int, float, int, str]:
    return (
        SOURCE_ORIGIN_PRIORITY.get(candidate.origin, 0),
        candidate.confidence,
        -candidate.rank,
        str(candidate.url),
    )
