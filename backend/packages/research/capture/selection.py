from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from packages.research.models import ResearchBrief, SourceCandidate


@dataclass(frozen=True)
class CaptureCandidateSelection:
    selected: list[SourceCandidate]
    skipped_reasons: dict[str, str]


def select_capture_candidates(
    brief: ResearchBrief,
    candidates: list[SourceCandidate],
) -> CaptureCandidateSelection:
    preferred: list[SourceCandidate] = []
    fallback: list[tuple[SourceCandidate, str]] = []
    skipped: dict[str, str] = {}

    for candidate in candidates:
        invalid_reason = _invalid_candidate_reason(candidate)
        if invalid_reason:
            skipped[candidate.id] = invalid_reason
            continue
        fallback_reason = _fallback_candidate_reason(candidate)
        if fallback_reason:
            fallback.append((candidate, fallback_reason))
            continue
        preferred.append(candidate)

    if len(preferred) >= brief.target_source_count:
        selected = preferred[: brief.max_fetches]
        selected_ids = {candidate.id for candidate in selected}
        skipped.update(
            {
                candidate.id: reason
                for candidate, reason in fallback
                if candidate.id not in selected_ids
            }
        )
        return CaptureCandidateSelection(selected=selected, skipped_reasons=skipped)

    selected = [*preferred, *[candidate for candidate, _ in fallback]][: brief.max_fetches]
    selected_ids = {candidate.id for candidate in selected}
    skipped.update(
        {
            candidate.id: reason
            for candidate, reason in fallback
            if candidate.id not in selected_ids
        }
    )
    return CaptureCandidateSelection(selected=selected, skipped_reasons=skipped)


def _invalid_candidate_reason(candidate: SourceCandidate) -> str:
    parsed = urlparse(candidate.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid_url"
    host = (parsed.hostname or "").casefold()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local_url_not_allowed"
    return ""


def _fallback_candidate_reason(candidate: SourceCandidate) -> str:
    if candidate.origin == "homepage_derived" and candidate.confidence < 0.6:
        return "deferred_low_confidence_homepage_derived"
    if candidate.origin in {"perplexity", "web_search"} and candidate.confidence < 0.5:
        return "deferred_low_confidence_search_result"
    return ""
