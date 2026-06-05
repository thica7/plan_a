from __future__ import annotations

from typing import cast

from packages.research.discovery.ranking import rank_and_dedupe_candidates
from packages.research.models import CandidateOrigin, ResearchBrief, SourceCandidate
from packages.search import SearchResult
from packages.tools.official_docs import find_official_docs


def trusted_registry_candidates(brief: ResearchBrief) -> list[SourceCandidate]:
    return _official_candidates_by_origin(brief, "trusted_registry")


def homepage_candidates(brief: ResearchBrief) -> list[SourceCandidate]:
    return _official_candidates_by_origin(brief, "homepage_derived")


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
            confidence=_search_confidence(candidate_origin, result),
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


def _official_candidates_by_origin(
    brief: ResearchBrief,
    origin: CandidateOrigin,
) -> list[SourceCandidate]:
    candidates = [
        SourceCandidate(
            title=candidate.title,
            url=candidate.url,
            snippet=candidate.rationale,
            origin=candidate.origin,
            competitor=brief.competitor,
            dimension=brief.dimension,
            rank=candidate.rank,
            confidence=candidate.confidence,
            reason=candidate.rationale,
        )
        for candidate in find_official_docs(
            competitor=brief.competitor,
            dimension=brief.dimension,
            homepage_hint=brief.homepage_hint,
        )
        if candidate.origin == origin
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


def _search_confidence(origin: CandidateOrigin, result: SearchResult) -> float:
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
        return max(0.35, base - 0.18)
    return base
