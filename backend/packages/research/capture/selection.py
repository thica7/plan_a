from __future__ import annotations

from dataclasses import dataclass
import re

from packages.research.capture.policy import (
    fallback_candidate_reason,
    invalid_candidate_reason,
)
from packages.research.models import ResearchBrief, SourceCandidate
from packages.research.source_fitness import candidate_intent


@dataclass(frozen=True)
class CaptureCandidateSelection:
    selected: list[SourceCandidate]
    overflow_queue: list[SourceCandidate]
    skipped_reasons: dict[str, str]
    selected_intents: dict[str, list[str]]


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

    if "pricing" not in brief.dimension.casefold():
        if brief.product_name or brief.product_category:
            ordered = [*preferred, *[candidate for candidate, _ in fallback]]
            from packages.research.evidence.operations import required_operations
            if brief.dimension == 'feature' and required_operations(brief.topic, brief.product_use_cases):
                def operation_priority(candidate):
                    text = candidate.title + ' ' + candidate.url
                    targets = brief.metadata.get('operation_repair_targets', [])
                    terms = {'read':r'view|read|阅读', 'comment':r'comment|评论',
                             'create':r'creat|publish|创建', 'edit':r'edit|编辑',
                             'share':r'shar(?:e|ing)|分享', 'manage_access':r'permissions?|roles?|access|权限|角色'}
                    return (sum(bool(re.search(terms[op], text, re.I)) for op in targets if op in terms),
                            10 if re.search(r'permissions?|roles?|access|权限|角色', text, re.I) else
                            5 if re.search(r'shar(?:e|ing)|分享', text, re.I) else
                            4 if re.search(r'creat|publish|edit|协作|创建|编辑', text, re.I) else
                            1 if re.search(r'comments?|评论', text, re.I) else 0)
                ordered.sort(key=operation_priority, reverse=True)
            initial_limit = min(brief.max_fetches, brief.target_source_count)
            selected = ordered[:initial_limit]
            # Cached candidates do not consume network fetches; the capture loop
            # enforces the fetch budget while walking this bounded candidate list.
            overflow = ordered[initial_limit:]
            queued_ids = {candidate.id for candidate in [*selected, *overflow]}
            skipped.update(
                {
                    candidate.id: reason
                    for candidate, reason in fallback
                    if candidate.id not in queued_ids
                }
            )
            return CaptureCandidateSelection(
                selected=selected,
                overflow_queue=overflow,
                skipped_reasons=skipped,
                selected_intents=_selected_intents(brief, [*selected, *overflow]),
            )
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
            return CaptureCandidateSelection(
                selected=selected,
                overflow_queue=[],
                skipped_reasons=skipped,
                selected_intents=_selected_intents(brief, selected),
            )
        selected = [*preferred, *[candidate for candidate, _ in fallback]][: brief.max_fetches]
        selected_ids = {candidate.id for candidate in selected}
        skipped.update(
            {
                candidate.id: reason
                for candidate, reason in fallback
                if candidate.id not in selected_ids
            }
        )
        return CaptureCandidateSelection(
            selected=selected,
            overflow_queue=[],
            skipped_reasons=skipped,
            selected_intents=_selected_intents(brief, selected),
        )

    ordered = _intent_ordered_candidates(brief, [*preferred, *[candidate for candidate, _ in fallback]])
    initial_limit = min(brief.max_fetches, max(brief.target_source_count, 1))
    selected = ordered[:initial_limit]
    overflow = ordered[initial_limit: brief.max_fetches]
    selected_ids = {candidate.id for candidate in selected}
    skipped.update(
        {
            candidate.id: reason
            for candidate, reason in fallback
            if candidate.id not in selected_ids and candidate not in overflow
        }
    )
    return CaptureCandidateSelection(
        selected=selected,
        overflow_queue=overflow,
        skipped_reasons=skipped,
        selected_intents=_selected_intents(brief, [*selected, *overflow]),
    )


def _intent_ordered_candidates(
    brief: ResearchBrief,
    candidates: list[SourceCandidate],
) -> list[SourceCandidate]:
    if "pricing" not in brief.dimension.casefold():
        return candidates
    ordered = list(candidates)
    protected_window = max(1, brief.max_fetches)
    for intent in (
        "official_pricing_page",
        "official_billing_or_usage_docs",
        "current_plan_price_support",
    ):
        existing_index = next(
            (
                index
                for index, candidate in enumerate(ordered)
                if candidate_intent(brief, candidate) == intent
            ),
            None,
        )
        if existing_index is None or existing_index < protected_window:
            continue
        candidate = ordered.pop(existing_index)
        ordered.insert(protected_window - 1, candidate)
    return ordered


def _selected_intents(
    brief: ResearchBrief,
    candidates: list[SourceCandidate],
) -> dict[str, list[str]]:
    intents: dict[str, list[str]] = {}
    for candidate in candidates:
        intent = candidate_intent(brief, candidate)
        intents.setdefault(intent, []).append(candidate.id)
    return intents
