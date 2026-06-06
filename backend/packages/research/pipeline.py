from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from packages.research.assembly import assemble_research_summary
from packages.research.capture import CaptureCache, capture_candidate, select_capture_candidates
from packages.research.discovery import (
    build_search_queries,
    homepage_candidates,
    rank_and_dedupe_candidates,
    search_result_candidates,
    trusted_registry_candidates,
)
from packages.research.evaluation import quality_gaps_from_extractions
from packages.research.evidence import evidence_items_from_extractions
from packages.research.extraction import extract_page
from packages.research.models import (
    CapturedPage,
    EvidenceItem,
    ExtractionResult,
    QualityGap,
    RepairTask,
    ResearchBrief,
    ResearchResult,
    SourceCandidate,
)
from packages.research.repair import repair_tasks_from_gaps
from packages.search import SearchResult

FetchCallable = Callable[[str], Awaitable[Any]]
SearchCallable = Callable[[str, int], Awaitable[list[SearchResult]]]
T = TypeVar("T")


@dataclass
class ResearchPass:
    candidates: list[SourceCandidate]
    captured_pages: list[CapturedPage]
    extractions: list[ExtractionResult]
    evidence_items: list[EvidenceItem]
    gaps: list[QualityGap]
    capture_metrics: dict[str, Any]


async def run_research_pipeline(
    brief: ResearchBrief,
    *,
    fetch: FetchCallable,
    search: SearchCallable | None = None,
    seed_candidates: list[SourceCandidate] | None = None,
    repair_tasks: list[RepairTask] | None = None,
    capture_cache: CaptureCache | None = None,
) -> ResearchResult:
    cache = capture_cache or CaptureCache()
    first_pass = await _run_research_pass(
        brief,
        fetch=fetch,
        search=search,
        seed_candidates=seed_candidates or [],
        repair_tasks=repair_tasks or [],
        capture_cache=cache,
    )

    candidates = first_pass.candidates
    captured_pages = first_pass.captured_pages
    extractions = first_pass.extractions
    evidence_items = first_pass.evidence_items
    gaps = first_pass.gaps
    capture_metrics = dict(first_pass.capture_metrics)
    planned_repairs = repair_tasks_from_gaps(gaps)

    repair_round_count = 0
    repair_candidate_count = 0
    repair_capture_count = 0
    initial_gap_count = len(gaps)
    for round_index in range(brief.max_repair_rounds):
        active_repairs = _same_branch_repairs(brief, planned_repairs)
        if not active_repairs:
            break
        repair_brief = _repair_brief(brief, active_repairs, round_index=round_index + 1)
        repair_pass = await _run_research_pass(
            repair_brief,
            fetch=fetch,
            search=search,
            seed_candidates=[],
            repair_tasks=active_repairs,
            capture_cache=cache,
        )
        candidates = _dedupe_by_id([*candidates, *repair_pass.candidates])
        captured_pages = _dedupe_by_id([*captured_pages, *repair_pass.captured_pages])
        extractions = _dedupe_by_id([*extractions, *repair_pass.extractions])
        evidence_items = evidence_items_from_extractions(extractions)
        gaps = quality_gaps_from_extractions(brief, extractions)
        planned_repairs = repair_tasks_from_gaps(gaps)
        repair_round_count += 1
        repair_candidate_count += len(repair_pass.candidates)
        repair_capture_count += len(repair_pass.captured_pages)
        capture_metrics = _merge_numeric_metrics(capture_metrics, repair_pass.capture_metrics)
        if not gaps:
            break

    assembly = assemble_research_summary(
        brief,
        evidence_items=evidence_items,
        gaps=gaps,
        repair_tasks=planned_repairs,
    )
    return ResearchResult(
        brief=brief,
        candidates=candidates,
        captured_pages=captured_pages,
        extractions=extractions,
        evidence_items=evidence_items,
        gaps=gaps,
        repair_tasks=planned_repairs,
        assembly=assembly,
        metrics={
            **_metrics(candidates, captured_pages, extractions, evidence_items, gaps, brief),
            **capture_metrics,
            "initial_gap_count": initial_gap_count,
            "remaining_gap_count": len(gaps),
            "repair_round_count": repair_round_count,
            "repair_task_count": len(planned_repairs),
            "repair_candidate_count": repair_candidate_count,
            "repair_capture_count": repair_capture_count,
            "gap_resolution_rate": _gap_resolution_rate(initial_gap_count, len(gaps)),
        },
    )


async def _run_research_pass(
    brief: ResearchBrief,
    *,
    fetch: FetchCallable,
    search: SearchCallable | None,
    seed_candidates: list[SourceCandidate],
    repair_tasks: list[RepairTask],
    capture_cache: CaptureCache,
) -> ResearchPass:
    candidates = await _discover_candidates(
        brief,
        search=search,
        seed_candidates=seed_candidates,
        repair_tasks=repair_tasks,
    )
    captured_pages, capture_metrics = await _capture_candidates(
        brief,
        candidates,
        fetch,
        capture_cache=capture_cache,
    )
    extractions = [
        extract_page(brief, page)
        for page in captured_pages
        if page.status == "ok" and (page.text or page.markdown or page.snippet)
    ]
    evidence_items = evidence_items_from_extractions(extractions)
    gaps = quality_gaps_from_extractions(brief, extractions)
    return ResearchPass(
        candidates=candidates,
        captured_pages=captured_pages,
        extractions=extractions,
        evidence_items=evidence_items,
        gaps=gaps,
        capture_metrics=capture_metrics,
    )


async def _discover_candidates(
    brief: ResearchBrief,
    *,
    search: SearchCallable | None,
    seed_candidates: list[SourceCandidate],
    repair_tasks: list[RepairTask],
) -> list[SourceCandidate]:
    candidates = [
        *seed_candidates,
        *trusted_registry_candidates(brief),
    ]
    if search is not None:
        for query in build_search_queries(brief, repair_tasks=repair_tasks):
            results = await search(query, brief.max_candidates)
            candidates.extend(
                search_result_candidates(
                    brief,
                    results,
                    origin="perplexity",
                    query=query,
                )
            )
    candidates.extend(homepage_candidates(brief))
    return rank_and_dedupe_candidates(
        candidates,
        competitor=brief.competitor,
        dimension=brief.dimension,
        homepage_hint=brief.homepage_hint,
    )[: brief.max_candidates]


async def _capture_candidates(
    brief: ResearchBrief,
    candidates: list[SourceCandidate],
    fetch: FetchCallable,
    *,
    capture_cache: CaptureCache | None = None,
) -> tuple[list[CapturedPage], dict[str, Any]]:
    pages: list[CapturedPage] = []
    cache = CaptureCache()
    selection = select_capture_candidates(brief, candidates)
    stats = {
        "capture_cache_hits": 0,
        "capture_fetch_count": 0,
        "capture_selected_candidate_count": len(selection.selected),
        "capture_skipped_candidate_count": len(selection.skipped_reasons),
        "capture_skipped_reasons": selection.skipped_reasons,
    }
    for candidate in selection.selected:
        cached = (capture_cache or cache).get(candidate)
        if cached is not None:
            stats["capture_cache_hits"] += 1
            pages.append(cached)
            continue
        page = await capture_candidate(candidate, fetch)
        (capture_cache or cache).put(candidate, page)
        stats["capture_fetch_count"] += 1
        pages.append(page)
    return pages, stats


def _repair_brief(
    brief: ResearchBrief,
    repair_tasks: list[RepairTask],
    *,
    round_index: int,
) -> ResearchBrief:
    return brief.model_copy(
        update={
            "max_search_queries": max(
                brief.max_search_queries,
                max((task.max_queries for task in repair_tasks), default=brief.max_search_queries),
            ),
            "max_candidates": max(
                brief.max_candidates,
                max((task.max_candidates for task in repair_tasks), default=brief.max_candidates),
            ),
            "max_fetches": max(
                brief.max_fetches,
                max((task.max_fetches for task in repair_tasks), default=brief.max_fetches),
            ),
            "gap_ids": [task.gap_id for task in repair_tasks],
            "required_fields": _dedupe_strings(
                [field for task in repair_tasks for field in task.target_fields]
            ),
            "metadata": {
                **brief.metadata,
                "repair_round": round_index,
                "repair_task_ids": [task.id for task in repair_tasks],
            },
        }
    )


def _same_branch_repairs(brief: ResearchBrief, repair_tasks: list[RepairTask]) -> list[RepairTask]:
    return [
        task
        for task in repair_tasks
        if task.dimension == brief.dimension and task.competitor in {None, brief.competitor}
    ]


def _dedupe_by_id(items: list[T]) -> list[T]:
    seen: set[str] = set()
    deduped: list[T] = []
    for item in items:
        item_id = str(getattr(item, "id", "") or "")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        deduped.append(item)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _merge_numeric_metrics(
    current: dict[str, Any],
    addition: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(current)
    for key, value in addition.items():
        if isinstance(value, int | float) and isinstance(merged.get(key), int | float):
            merged[key] += value
        elif key not in merged:
            merged[key] = value
    return merged


def _gap_resolution_rate(initial_gap_count: int, remaining_gap_count: int) -> float:
    if initial_gap_count <= 0:
        return 1.0 if remaining_gap_count == 0 else 0.0
    resolved = max(0, initial_gap_count - remaining_gap_count)
    return resolved / initial_gap_count


def _metrics(
    candidates: list[SourceCandidate],
    pages: list[CapturedPage],
    extractions: list[object],
    evidence_items: list[object],
    gaps: list[object],
    brief: ResearchBrief,
) -> dict[str, Any]:
    ok_pages = [page for page in pages if page.status == "ok"]
    accepted_items = [
        item
        for item in evidence_items
        if getattr(item, "status", None) == "accepted"
    ]
    return {
        "candidate_count": len(candidates),
        "captured_page_count": len(pages),
        "captured_ok_count": len(ok_pages),
        "extraction_count": len(extractions),
        "evidence_item_count": len(evidence_items),
        "accepted_evidence_item_count": len(accepted_items),
        "gap_count": len(gaps),
        "verified_capture_rate": len(ok_pages) / max(1, len(pages)),
        "source_saturation_reached": (
            len(ok_pages) >= brief.target_source_count and len(gaps) == 0
        ),
    }
