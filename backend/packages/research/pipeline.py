from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from packages.research.assembly import assemble_research_summary
from packages.research.capture import CaptureCache, capture_candidate, select_capture_candidates
from packages.research.discovery import (
    build_search_queries,
    homepage_candidates,
    rank_and_dedupe_candidates,
    search_result_candidates,
    trusted_registry_candidates,
)
from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.evaluation import evaluate_research_quality
from packages.research.evidence import (
    admit_evidence_items,
    dedupe_by_id,
    normalized_fields_from_evidence_items,
)
from packages.research.extraction import extract_page
from packages.research.models import (
    CandidateLedgerEntry,
    CapturedPage,
    CoverageContractResult,
    EvidenceItem,
    ExtractionResult,
    QualityGap,
    RepairTask,
    ResearchBrief,
    ResearchResult,
    SourceCandidate,
)
from packages.research.repair import repair_tasks_from_gaps
from packages.research.source_fitness import candidate_intent, classify_source_fitness
from packages.search import SearchResult

FetchCallable = Callable[[str], Awaitable[Any]]
SearchCallable = Callable[[str, int], Awaitable[list[SearchResult]]]


@dataclass
class ResearchPass:
    candidates: list[SourceCandidate]
    captured_pages: list[CapturedPage]
    extractions: list[ExtractionResult]
    evidence_items: list[EvidenceItem]
    gaps: list[QualityGap]
    coverage: CoverageContractResult
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
    coverage = first_pass.coverage
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
        candidates = dedupe_by_id([*candidates, *repair_pass.candidates])
        captured_pages = dedupe_by_id([*captured_pages, *repair_pass.captured_pages])
        extractions = dedupe_by_id([*extractions, *repair_pass.extractions])
        evidence_items = admit_evidence_items(
            extractions,
            captured_pages=captured_pages,
            candidates=candidates,
        )
        gaps = evaluate_research_quality(brief, extractions, evidence_items)
        candidate_ledger = _candidate_ledger(
            brief,
            candidates=candidates,
            pages=captured_pages,
            evidence_items=evidence_items,
            capture_metrics=capture_metrics,
        )
        coverage = evaluate_coverage_contract(
            brief,
            candidates=candidates,
            pages=captured_pages,
            evidence_items=evidence_items,
            ledger=candidate_ledger,
        )
        planned_repairs = repair_tasks_from_gaps(gaps)
        repair_round_count += 1
        repair_candidate_count += len(repair_pass.candidates)
        repair_capture_count += len(repair_pass.captured_pages)
        capture_metrics = _merge_numeric_metrics(capture_metrics, repair_pass.capture_metrics)
        if not gaps and coverage.passed:
            break

    normalized_fields = normalized_fields_from_evidence_items(evidence_items)
    candidate_ledger = _candidate_ledger(
        brief,
        candidates=candidates,
        pages=captured_pages,
        evidence_items=evidence_items,
        capture_metrics=capture_metrics,
    )
    coverage = evaluate_coverage_contract(
        brief,
        candidates=candidates,
        pages=captured_pages,
        evidence_items=evidence_items,
        ledger=candidate_ledger,
    )
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
        candidate_ledger=candidate_ledger,
        coverage=coverage,
        normalized_fields=normalized_fields,
        gaps=gaps,
        repair_tasks=planned_repairs,
        assembly=assembly,
        metrics={
            **_metrics(candidates, captured_pages, extractions, evidence_items, gaps, brief),
            **capture_metrics,
            **_ledger_metrics(candidate_ledger),
            **_coverage_metrics(coverage),
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
    captured_pages, capture_metrics, overflow_queue = await _capture_candidates(
        brief,
        candidates,
        fetch,
        capture_cache=capture_cache,
    )
    extractions, evidence_items, gaps, ledger, coverage = _evaluate_capture_set(
        brief,
        candidates=candidates,
        pages=captured_pages,
        capture_metrics=capture_metrics,
    )
    while (
        not coverage.passed
        and overflow_queue
        and capture_metrics["capture_fetch_count"] < brief.max_fetches
    ):
        candidate = overflow_queue.pop(0)
        page = await _capture_one(candidate, fetch, capture_cache)
        captured_pages.append(page)
        capture_metrics["capture_fetch_count"] += 1
        capture_metrics["adaptive_backfill_fetch_count"] = (
            capture_metrics.get("adaptive_backfill_fetch_count", 0) + 1
        )
        extractions, evidence_items, gaps, ledger, coverage = _evaluate_capture_set(
            brief,
            candidates=candidates,
            pages=captured_pages,
            capture_metrics=capture_metrics,
        )
    return ResearchPass(
        candidates=candidates,
        captured_pages=captured_pages,
        extractions=extractions,
        evidence_items=evidence_items,
        gaps=gaps,
        coverage=coverage,
        capture_metrics=capture_metrics,
    )


async def _discover_candidates(
    brief: ResearchBrief,
    *,
    search: SearchCallable | None,
    seed_candidates: list[SourceCandidate],
    repair_tasks: list[RepairTask],
) -> list[SourceCandidate]:
    candidates = list(seed_candidates)
    if brief.include_trusted_sources:
        candidates.extend(trusted_registry_candidates(brief))
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
    if brief.include_homepage_candidates:
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
) -> tuple[list[CapturedPage], dict[str, Any], list[SourceCandidate]]:
    pages: list[CapturedPage] = []
    cache = CaptureCache()
    selection = select_capture_candidates(brief, candidates)
    stats = {
        "capture_cache_hits": 0,
        "capture_fetch_count": 0,
        "adaptive_backfill_fetch_count": 0,
        "capture_selected_candidate_count": len(selection.selected),
        "capture_overflow_candidate_count": len(selection.overflow_queue),
        "capture_skipped_candidate_count": len(selection.skipped_reasons),
        "capture_skipped_reasons": selection.skipped_reasons,
        "capture_selected_intents": selection.selected_intents,
    }
    for candidate in selection.selected:
        active_cache = capture_cache or cache
        cached = active_cache.get(candidate)
        if cached is not None:
            stats["capture_cache_hits"] += 1
            pages.append(cached)
            continue
        page = await capture_candidate(candidate, fetch)
        active_cache.put(candidate, page)
        stats["capture_fetch_count"] += 1
        pages.append(page)
    return pages, stats, list(selection.overflow_queue)


async def _capture_one(
    candidate: SourceCandidate,
    fetch: FetchCallable,
    capture_cache: CaptureCache | None,
) -> CapturedPage:
    cache = capture_cache or CaptureCache()
    cached = cache.get(candidate)
    if cached is not None:
        return cached
    page = await capture_candidate(candidate, fetch)
    cache.put(candidate, page)
    return page


def _evaluate_capture_set(
    brief: ResearchBrief,
    *,
    candidates: list[SourceCandidate],
    pages: list[CapturedPage],
    capture_metrics: dict[str, Any],
) -> tuple[
    list[ExtractionResult],
    list[EvidenceItem],
    list[QualityGap],
    list[CandidateLedgerEntry],
    CoverageContractResult,
]:
    extractions = [
        extract_page(brief, page)
        for page in pages
        if page.status == "ok" and (page.text or page.markdown or page.snippet)
    ]
    evidence_items = admit_evidence_items(
        extractions,
        captured_pages=pages,
        candidates=candidates,
    )
    gaps = evaluate_research_quality(brief, extractions, evidence_items)
    ledger = _candidate_ledger(
        brief,
        candidates=candidates,
        pages=pages,
        evidence_items=evidence_items,
        capture_metrics=capture_metrics,
    )
    coverage = evaluate_coverage_contract(
        brief,
        candidates=candidates,
        pages=pages,
        evidence_items=evidence_items,
        ledger=ledger,
    )
    return extractions, evidence_items, gaps, ledger, coverage


def _candidate_ledger(
    brief: ResearchBrief,
    *,
    candidates: list[SourceCandidate],
    pages: list[CapturedPage],
    evidence_items: list[EvidenceItem],
    capture_metrics: dict[str, Any],
) -> list[CandidateLedgerEntry]:
    page_by_candidate = {page.candidate_id: page for page in pages}
    skipped_reasons = capture_metrics.get("capture_skipped_reasons")
    if not isinstance(skipped_reasons, dict):
        skipped_reasons = {}
    items_by_page: dict[str, list[EvidenceItem]] = {}
    for item in evidence_items:
        items_by_page.setdefault(item.captured_page_id, []).append(item)

    ledger: list[CandidateLedgerEntry] = []
    for candidate in candidates:
        page = page_by_candidate.get(candidate.id)
        intent = candidate_intent(brief, candidate)
        if page is None:
            reason = str(skipped_reasons.get(candidate.id) or "not_selected_for_capture")
            ledger.append(
                CandidateLedgerEntry(
                    candidate_id=candidate.id,
                    url=candidate.url,
                    origin=candidate.origin,
                    intent=intent,
                    status="skipped",
                    reason=reason,
                )
            )
            continue

        page_items = items_by_page.get(page.id, [])
        accepted_items = [item for item in page_items if item.status == "accepted"]
        rejected_items = [item for item in page_items if item.status == "rejected"]
        fitness = classify_source_fitness(brief, candidate, page)
        evidence_status = (
            "accepted" if accepted_items else "rejected" if rejected_items else "unreviewed"
        )
        if page.status == "failed":
            status = "fetch_failed"
            reason = page.failure_reason or page.error or "fetch_failed"
        elif page.status == "rejected":
            status = "raw_source_rejected"
            reason = page.failure_reason or "capture_rejected"
        elif accepted_items:
            status = "accepted"
            reason = "accepted_evidence"
        elif rejected_items:
            status = "evidence_rejected"
            reason = "; ".join(
                sorted({item.rejection_reason or "evidence_rejected" for item in rejected_items})
            )
        else:
            status = "fetched"
            reason = "captured_without_field_evidence"

        ledger.append(
            CandidateLedgerEntry(
                candidate_id=candidate.id,
                url=candidate.url,
                origin=candidate.origin,
                intent=intent,
                status=status,
                reason=reason,
                selected=True,
                fetched=page.status == "ok",
                source_fitness=fitness.fitness,
                coverage_intent=fitness.coverage_intents[0] if fitness.coverage_intents else intent,
                requested_url=page.requested_url,
                final_url=page.final_url,
                page_status=page.status,
                evidence_status=evidence_status,
                metadata={"source_fitness_reason": fitness.reason},
            )
        )
    return ledger


def _ledger_metrics(ledger: list[CandidateLedgerEntry]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    fitness_counts: dict[str, int] = {}
    for entry in ledger:
        status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
        fitness_counts[entry.source_fitness] = fitness_counts.get(entry.source_fitness, 0) + 1
    return {
        "candidate_ledger_count": len(ledger),
        "candidate_ledger_status_counts": status_counts,
        "source_fitness_counts": fitness_counts,
    }


def _coverage_metrics(coverage: CoverageContractResult) -> dict[str, Any]:
    return {
        "coverage_contract_passed": coverage.passed,
        "coverage_missing_intents": list(coverage.missing_intents),
        "coverage_blocking_reason_count": len(coverage.blocking_reasons),
        "coverage_repair_hints": list(coverage.repair_hints),
        "source_saturation_reached": coverage.passed,
    }


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
    extractions: list[ExtractionResult],
    evidence_items: list[EvidenceItem],
    gaps: list[QualityGap],
    brief: ResearchBrief,
) -> dict[str, Any]:
    ok_pages = [page for page in pages if page.status == "ok"]
    rejected_pages = [page for page in pages if page.status == "rejected"]
    failed_pages = [page for page in pages if page.status == "failed"]
    accepted_items = [
        item
        for item in evidence_items
        if item.status == "accepted"
    ]
    rejected_items = [item for item in evidence_items if item.status == "rejected"]
    expected_fields = _expected_field_count(brief, extractions)
    accepted_fields = {
        item.field
        for item in accepted_items
        if item.competitor == brief.competitor and item.dimension == brief.dimension
    }
    repairable_gap_count = sum(1 for gap in gaps if gap.severity in {"warn", "blocker"})
    blocking_gap_count = sum(1 for gap in gaps if gap.severity == "blocker")
    return {
        "candidate_count": len(candidates),
        "captured_page_count": len(pages),
        "captured_ok_count": len(ok_pages),
        "captured_rejected_count": len(rejected_pages),
        "captured_failed_count": len(failed_pages),
        "extraction_count": len(extractions),
        "evidence_item_count": len(evidence_items),
        "accepted_evidence_item_count": len(accepted_items),
        "rejected_evidence_item_count": len(rejected_items),
        "gap_count": len(gaps),
        "repairable_gap_count": repairable_gap_count,
        "blocking_gap_count": blocking_gap_count,
        "verified_capture_rate": len(ok_pages) / max(1, len(pages)),
        "accepted_evidence_rate": len(accepted_items) / max(1, len(evidence_items)),
        "field_support_rate": len(accepted_fields) / max(1, expected_fields),
        "source_saturation_reached": (
            len(ok_pages) >= brief.target_source_count and len(gaps) == 0
        ),
    }


def _expected_field_count(brief: ResearchBrief, extractions: list[ExtractionResult]) -> int:
    fields = set(brief.required_fields)
    for extraction in extractions:
        if extraction.competitor != brief.competitor or extraction.dimension != brief.dimension:
            continue
        for field, value in extraction.fields.items():
            if field == "confidence_reason":
                continue
            if _empty_metric_value(value):
                continue
            if isinstance(value, dict) and value.get("status") == "not_found_in_source":
                continue
            fields.add(field)
    return len(fields)


def _empty_metric_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return False
