from __future__ import annotations

from typing import cast

from packages.research.discovery.ranking import rank_and_dedupe_candidates
from packages.research.models import CandidateOrigin, ResearchBrief, SourceCandidate
from packages.search import SearchResult


def search_result_candidates(
    brief: ResearchBrief,
    results: list[SearchResult],
    *,
    origin: str,
    query: str | None = None,
) -> list[SourceCandidate]:
    candidate_origin = _candidate_origin(origin)
    candidates = [
        SourceCandidate(
            title=result.title,
            url=result.url,
            snippet=result.snippet,
            origin=candidate_origin,
            competitor=brief.competitor,
            dimension=brief.dimension,
            rank=index,
            confidence=_search_confidence(candidate_origin, result, competitor=brief.competitor),
            query=query,
            date=result.date,
            last_updated=result.last_updated,
        )
        for index, result in enumerate(results)
    ]
    return rank_and_dedupe_candidates(
        candidates,
        competitor=brief.competitor,
        dimension=brief.dimension,
        homepage_hint=brief.homepage_hint,
    )

def _candidate_origin(origin: str) -> CandidateOrigin:
    normalized = origin.strip().casefold()
    if normalized in {
        "trusted_registry",
        "perplexity",
        "web_search",
        "homepage_derived",
        "llm_fallback",
        "manual",
    }:
        return cast(CandidateOrigin, normalized)
    return "web_search"


def _search_confidence(
    origin: CandidateOrigin,
    result: SearchResult,
    *,
    competitor: str,
) -> float:
    url = result.url.casefold()
    if origin == "perplexity":
        base = 0.72
    elif origin == "web_search":
        base = 0.66
    else:
        base = 0.6
    if any(token in url for token in ("docs.", "developer", "cloud.google", "help.")):
        return min(0.9, base + 0.16)
    if any(token in url for token in ("medium.com", "youtube.com", "reddit.com", "wikipedia")):
        base = max(0.35, base - 0.18)
    if not _mentions_competitor(result, competitor):
        base = max(0.35, base - 0.24)
    return base


def _mentions_competitor(result: SearchResult, competitor: str) -> bool:
    tokens = [
        token
        for token in competitor.casefold().replace("(", " ").replace(")", " ").split()
        if len(token) >= 4
    ]
    if not tokens:
        return True
    haystack = f"{result.title} {result.url} {result.snippet}".casefold()
    return any(token in haystack for token in tokens)
