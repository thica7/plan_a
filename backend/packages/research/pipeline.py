from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from packages.research.capture import capture_candidate
from packages.research.discovery import (
    build_search_queries,
    homepage_candidates,
    rank_and_dedupe_candidates,
    search_result_candidates,
    trusted_registry_candidates,
)
from packages.research.evaluation import quality_gaps_from_extractions
from packages.research.extraction import extract_page
from packages.research.models import (
    CapturedPage,
    EvidenceItem,
    ExtractionResult,
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
) -> ResearchResult:
    candidates = await _discover_candidates(
        brief,
        search=search,
        seed_candidates=seed_candidates or [],
        repair_tasks=repair_tasks or [],
    )
    captured_pages = await _capture_candidates(brief, candidates, fetch)
    extractions = [
        extract_page(brief, page)
        for page in captured_pages
        if page.status == "ok" and (page.text or page.markdown or page.snippet)
    ]
    evidence_items = _evidence_items_from_extractions(extractions)
    gaps = quality_gaps_from_extractions(brief, extractions)
    planned_repairs = repair_tasks_from_gaps(gaps)
    return ResearchResult(
        brief=brief,
        candidates=candidates,
        captured_pages=captured_pages,
        extractions=extractions,
        evidence_items=evidence_items,
        gaps=gaps,
        repair_tasks=planned_repairs,
        metrics=_metrics(candidates, captured_pages, extractions, evidence_items, gaps),
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
) -> list[CapturedPage]:
    pages: list[CapturedPage] = []
    for candidate in candidates[: brief.max_fetches]:
        pages.append(await capture_candidate(candidate, fetch))
    return pages


def _evidence_items_from_extractions(
    extractions: list[ExtractionResult],
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for extraction in extractions:
        quote_by_field = {
            quote.field: quote.text for quote in extraction.quotes if quote.field and quote.text
        }
        for field, value in extraction.fields.items():
            if _empty(value):
                continue
            items.append(
                EvidenceItem(
                    competitor=extraction.competitor,
                    dimension=extraction.dimension,
                    field=field,
                    value=value,
                    source_candidate_id=extraction.source_candidate_id,
                    captured_page_id=extraction.captured_page_id,
                    source_url=_source_url_for_field(extraction, field),
                    quote=quote_by_field.get(field, ""),
                    confidence=extraction.confidence,
                    status="accepted" if extraction.confidence >= 0.35 else "unreviewed",
                    metadata={"extraction_id": extraction.id},
                )
            )
    return items


def _source_url_for_field(extraction: ExtractionResult, field: str) -> str | None:
    for quote in extraction.quotes:
        if quote.field == field and quote.source_url:
            return quote.source_url
    return None


def _metrics(
    candidates: list[SourceCandidate],
    pages: list[CapturedPage],
    extractions: list[ExtractionResult],
    evidence_items: list[EvidenceItem],
    gaps: list[object],
) -> dict[str, Any]:
    ok_pages = [page for page in pages if page.status == "ok"]
    return {
        "candidate_count": len(candidates),
        "captured_page_count": len(pages),
        "captured_ok_count": len(ok_pages),
        "extraction_count": len(extractions),
        "evidence_item_count": len(evidence_items),
        "gap_count": len(gaps),
        "verified_capture_rate": len(ok_pages) / max(1, len(pages)),
    }


def _empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return False
