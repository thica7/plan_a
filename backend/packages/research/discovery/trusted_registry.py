from __future__ import annotations

from packages.research.discovery.ranking import rank_and_dedupe_candidates
from packages.research.models import CandidateOrigin, ResearchBrief, SourceCandidate
from packages.tools.official_docs import find_official_docs


def trusted_registry_candidates(brief: ResearchBrief) -> list[SourceCandidate]:
    return official_candidates_by_origin(brief, "trusted_registry")


def homepage_candidates(brief: ResearchBrief) -> list[SourceCandidate]:
    return official_candidates_by_origin(brief, "homepage_derived")


def official_candidates_by_origin(
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
