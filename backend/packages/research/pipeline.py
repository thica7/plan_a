from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from packages.research.assembly import assemble_research_summary
from packages.research.capture import CaptureCache, capture_candidate
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
    RepairTask,
    ResearchBrief,
    ResearchResult,
    SourceCandidate,
)
from packages.research.repair import repair_tasks_from_gaps
from packages.search import SearchResult

FetchCallable = Callable[[str], Awaitable[Any]]
SearchCallable = Callable[[str, int], Awaitable[list[SearchResult]]]


async def run_research_pipeline(
    brief: ResearchBrief,
    *,
    fetch: FetchCallable,
    search: SearchCallable | None = None,
    seed_candidates: list[SourceCandidate] | None = None,
    repair_tasks: list[RepairTask] | None = None,
    capture_cache: CaptureCache | None = None,
) -> ResearchResult:
    candidates = await _discover_candidates(
        brief,
        search=search,
        seed_candidates=seed_candidates or [],
        repair_tasks=repair_tasks or [],
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
    planned_repairs = repair_tasks_from_gaps(gaps)
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
        },
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
    stats = {"capture_cache_hits": 0, "capture_fetch_count": 0}
    for candidate in candidates[: brief.max_fetches]:
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
