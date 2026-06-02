from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from packages.identity import (
    compute_content_hash,
    compute_evidence_id,
    normalize_dimension_key,
    normalize_url,
)
from packages.rag.gap_retrieval import (
    EvidenceRetriever,
    build_gap_retrieval_query,
    decorate_evidence_gap_report_with_retrieval,
)
from packages.search import SearchResult
from packages.schema.enterprise import (
    EvidenceGapFillResult,
    EvidenceGapItem,
    EvidenceGapReport,
    EvidenceRecord,
    ReportVersionRecord,
)
from packages.tools import FetchPageResult


class GapFillStore(EvidenceRetriever, Protocol):
    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]: ...

    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord: ...

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord: ...


OnlineSearch = Callable[[str, int], Awaitable[list[SearchResult]]]
OnlineFetch = Callable[[str], Awaitable[FetchPageResult]]


def fill_evidence_gaps(
    report: EvidenceGapReport,
    *,
    store: GapFillStore,
    workspace_id: str,
    project_id: str | None = None,
    source_report_version: ReportVersionRecord | None = None,
    limit: int = 3,
) -> EvidenceGapFillResult:
    project_id = project_id or report.project_id
    decorated = decorate_evidence_gap_report_with_retrieval(
        report,
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=limit,
    )
    return _finalize_gap_fill(
        decorated,
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        source_report_version=source_report_version,
    )


async def fill_evidence_gaps_online(
    report: EvidenceGapReport,
    *,
    store: GapFillStore,
    workspace_id: str,
    project_id: str | None = None,
    source_report_version: ReportVersionRecord | None = None,
    search: OnlineSearch,
    fetch: OnlineFetch,
    limit: int = 3,
    max_search_results: int = 3,
    max_fetches_per_gap: int = 2,
) -> EvidenceGapFillResult:
    project_id = project_id or report.project_id
    decorated = decorate_evidence_gap_report_with_retrieval(
        report,
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=limit,
    )
    online_collected_ids: list[str] = []
    online_failures: list[dict[str, str]] = []
    for gap in decorated.gaps:
        if gap.retrieval_candidate_ids:
            continue
        query = gap.retrieval_query or build_gap_retrieval_query(gap)
        if not query:
            continue
        try:
            results = await search(query, max_search_results)
        except Exception as exc:  # noqa: BLE001 - online fill should degrade to local RAG.
            online_failures.append({"gap_id": gap.id, "stage": "search", "error": str(exc)})
            continue
        for result in _unique_search_results(results)[:max_fetches_per_gap]:
            try:
                fetched = await fetch(result.url)
            except Exception as exc:  # noqa: BLE001 - keep remaining search results usable.
                online_failures.append(
                    {
                        "gap_id": gap.id,
                        "stage": "fetch",
                        "url": result.url,
                        "error": str(exc),
                    }
                )
                continue
            evidence = _online_evidence_from_gap(
                gap=gap,
                result=result,
                fetched=fetched,
                workspace_id=workspace_id,
                project_id=project_id,
                query=query,
            )
            if evidence is None:
                continue
            stored = store.upsert_evidence(evidence)
            online_collected_ids.append(stored.id)
    if online_collected_ids:
        decorated = decorate_evidence_gap_report_with_retrieval(
            decorated,
            store=store,
            workspace_id=workspace_id,
            project_id=project_id,
            limit=limit,
        )
    return _finalize_gap_fill(
        decorated,
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        source_report_version=source_report_version,
        online_collected_evidence_ids=_unique_ids(online_collected_ids),
        online_failures=online_failures,
    )


def _finalize_gap_fill(
    decorated: EvidenceGapReport,
    *,
    store: GapFillStore,
    workspace_id: str,
    project_id: str,
    source_report_version: ReportVersionRecord | None,
    online_collected_evidence_ids: list[str] | None = None,
    online_failures: list[dict[str, str]] | None = None,
) -> EvidenceGapFillResult:
    updated_gaps, filled_gap_ids, candidate_ids = _filled_gaps(decorated.gaps)
    updated_report = decorated.model_copy(update={"gaps": updated_gaps})
    remaining_gap_ids = [gap.id for gap in updated_gaps if not gap.evidence_ids]
    updated_version = (
        _write_gap_fill_report_version(
            source=source_report_version,
            store=store,
            report=updated_report,
            candidate_ids=candidate_ids,
            filled_gap_ids=filled_gap_ids,
            remaining_gap_ids=remaining_gap_ids,
            online_collected_evidence_ids=online_collected_evidence_ids or [],
            online_failures=online_failures or [],
        )
        if source_report_version is not None
        else None
    )
    return EvidenceGapFillResult(
        project_id=project_id,
        workspace_id=workspace_id,
        source_report_version_id=source_report_version.id if source_report_version else None,
        updated_report_version_id=updated_version.id if updated_version else None,
        gap_count=len(updated_gaps),
        filled_gap_count=len(filled_gap_ids),
        added_evidence_count=len(candidate_ids),
        candidate_evidence_ids=candidate_ids,
        filled_gap_ids=filled_gap_ids,
        remaining_gap_ids=remaining_gap_ids,
        report=updated_report,
        updated_report_version=updated_version,
    )


def _unique_search_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for result in results:
        url_key = normalize_url(result.url)
        if not url_key or url_key in seen:
            continue
        seen.add(url_key)
        unique.append(result)
    return unique


def _online_evidence_from_gap(
    *,
    gap: EvidenceGapItem,
    result: SearchResult,
    fetched: FetchPageResult,
    workspace_id: str,
    project_id: str,
    query: str,
) -> EvidenceRecord | None:
    source_type = "webpage_verified" if fetched.ok else "web_search_result"
    if gap.source_type_required and not _source_type_matches(gap.source_type_required, source_type):
        return None
    source_url = normalize_url(fetched.url if fetched.ok else result.url)
    if not source_url:
        return None
    title = (fetched.title if fetched.ok and fetched.title else result.title).strip() or source_url
    full_text = fetched.text.strip() if fetched.ok else ""
    snippet = _best_snippet(full_text, result.snippet)
    content_basis = full_text or result.snippet or title or source_url
    content_hash = fetched.content_hash if fetched.ok else compute_content_hash(content_basis)[:16]
    competitor_id = (gap.competitor_id or gap.competitor_name or "unknown").strip()
    dimension = normalize_dimension_key(gap.dimension or "general")
    evidence_id = compute_evidence_id(source_url, content_hash, competitor_id, dimension)
    return EvidenceRecord(
        id=evidence_id,
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=None,
        raw_source_id=f"online-gap-{hashlib.sha256(f'{gap.id}|{source_url}'.encode()).hexdigest()[:16]}",
        competitor_id=competitor_id,
        dimension=dimension,
        source_type=source_type,
        title=title[:240],
        url=source_url,
        canonical_url=source_url,
        snippet=snippet,
        content_hash=content_hash,
        reliability_score=0.82 if fetched.ok else 0.64,
        freshness_score=0.75,
        quality_label="unreviewed",
        metadata={
            "online_gap_fill": True,
            "gap_id": gap.id,
            "query": query,
            "recommended_query": gap.recommended_query,
            "search_title": result.title,
            "search_snippet": result.snippet,
            "search_date": result.date,
            "search_last_updated": result.last_updated,
            "fetch_ok": fetched.ok,
            "fetch_status_code": fetched.status_code,
            "fetch_error": fetched.error,
            "full_text": full_text[:12000],
        },
    )


def _best_snippet(full_text: str, fallback: str) -> str:
    text = full_text or fallback
    return " ".join(text.split())[:700]


def _source_type_matches(required: str, actual: str) -> bool:
    required_value = required.casefold().strip()
    if not required_value or required_value in {"any", "any usable source"}:
        return True
    return required_value == actual.casefold().strip()


def _filled_gaps(
    gaps: list[EvidenceGapItem],
) -> tuple[list[EvidenceGapItem], list[str], list[str]]:
    updated_gaps: list[EvidenceGapItem] = []
    filled_gap_ids: list[str] = []
    all_candidate_ids: list[str] = []
    for gap in gaps:
        candidate_ids = _unique_ids(
            [record.evidence_id for record in gap.retrieval_records]
            + list(gap.retrieval_candidate_ids)
        )
        new_candidate_ids = [item for item in candidate_ids if item not in gap.evidence_ids]
        if new_candidate_ids:
            filled_gap_ids.append(gap.id)
            all_candidate_ids.extend(new_candidate_ids)
        updated_gaps.append(
            gap.model_copy(update={"evidence_ids": _unique_ids(gap.evidence_ids + new_candidate_ids)})
        )
    return updated_gaps, _unique_ids(filled_gap_ids), _unique_ids(all_candidate_ids)


def _write_gap_fill_report_version(
    *,
    source: ReportVersionRecord,
    store: GapFillStore,
    report: EvidenceGapReport,
    candidate_ids: list[str],
    filled_gap_ids: list[str],
    remaining_gap_ids: list[str],
    online_collected_evidence_ids: list[str],
    online_failures: list[dict[str, str]],
) -> ReportVersionRecord:
    metadata = dict(source.quality_metadata)
    metadata["rag_gap_fill"] = {
        "source_report_version_id": source.id,
        "filled_gap_ids": filled_gap_ids,
        "remaining_gap_ids": remaining_gap_ids,
        "candidate_evidence_ids": candidate_ids,
        "online_collected_evidence_ids": online_collected_evidence_ids,
        "online_failures": online_failures,
        "retrieval_records": [
            record.model_dump(mode="json")
            for gap in report.gaps
            for record in gap.retrieval_records
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }
    version = source.model_copy(
        update={
            "id": _gap_fill_report_version_id(source, filled_gap_ids, candidate_ids),
            "parent_version_id": source.id,
            "version_number": _next_version_number(store, source.project_id),
            "status": "draft",
            "report_md": _append_gap_fill_section(
                source.report_md,
                report.gaps,
                filled_gap_ids=filled_gap_ids,
            ),
            "evidence_ids": _unique_ids(source.evidence_ids + candidate_ids),
            "quality_metadata": metadata,
            "created_at": datetime.utcnow(),
            "published_at": None,
        }
    )
    return store.upsert_report_version(version)


def _append_gap_fill_section(
    report_md: str,
    gaps: list[EvidenceGapItem],
    *,
    filled_gap_ids: list[str],
) -> str:
    lines = [report_md.rstrip(), "", "## RAG Gap Fill", ""]
    if not filled_gap_ids:
        lines.append("- No retrieval candidates were strong enough to fill open evidence gaps.")
        return "\n".join(lines).strip() + "\n"
    for gap in gaps:
        if gap.id not in filled_gap_ids:
            continue
        added = ", ".join(gap.evidence_ids)
        lines.append(f"- {gap.id}: linked evidence candidates {added}.")
        if gap.retrieval_grounded_context:
            lines.append(f"  - Grounded context: {gap.retrieval_grounded_context[:600]}")
    return "\n".join(lines).strip() + "\n"


def _gap_fill_report_version_id(
    source: ReportVersionRecord,
    filled_gap_ids: list[str],
    candidate_ids: list[str],
) -> str:
    digest = hashlib.sha256(
        "|".join([source.id, *filled_gap_ids, *candidate_ids]).encode("utf-8")
    ).hexdigest()[:16]
    return f"report-version-gap-fill-{digest}"


def _next_version_number(store: GapFillStore, project_id: str) -> int:
    versions = store.list_report_versions(project_id=project_id)
    if not versions:
        return 1
    return max(version.version_number for version in versions) + 1


def _unique_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
