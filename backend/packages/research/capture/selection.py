from __future__ import annotations

from dataclasses import dataclass

from packages.research.capture.policy import (
    fallback_candidate_reason,
    invalid_candidate_reason,
)
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
        invalid_reason = invalid_candidate_reason(candidate)
        if invalid_reason:
            skipped[candidate.id] = invalid_reason
            continue
        fallback_reason = fallback_candidate_reason(candidate)
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
