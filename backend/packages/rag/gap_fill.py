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
from packages.schema.enterprise import (
    EvidenceGapFillDecisionEvent,
    EvidenceGapFillResult,
    EvidenceGapItem,
    EvidenceGapReport,
    EvidenceRecord,
    ReportVersionRecord,
)
from packages.schema.rag import RetrievalRecord
from packages.search import SearchResult
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
            if _robots_blocked_fetch(fetched):
                online_failures.append(
                    {
                        "gap_id": gap.id,
                        "stage": "robots",
                        "url": fetched.url or result.url,
                        "error": fetched.error or "Blocked by robots/source policy.",
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
    before_gap_count = len(updated_gaps)
    after_gap_count = len(remaining_gap_ids)
    online_collected_ids = online_collected_evidence_ids or []
    online_failure_items = online_failures or []
    decision_events = _gap_fill_decision_events(
        updated_report,
        candidate_ids=candidate_ids,
        filled_gap_ids=filled_gap_ids,
        remaining_gap_ids=remaining_gap_ids,
        before_gap_count=before_gap_count,
        after_gap_count=after_gap_count,
        online_collected_evidence_ids=online_collected_ids,
        online_failures=online_failure_items,
        source_report_version=source_report_version,
    )
    updated_version = (
        _write_gap_fill_report_version(
            source=source_report_version,
            store=store,
            report=updated_report,
            candidate_ids=candidate_ids,
            filled_gap_ids=filled_gap_ids,
            remaining_gap_ids=remaining_gap_ids,
            online_collected_evidence_ids=online_collected_ids,
            online_failures=online_failure_items,
            decision_events=decision_events,
        )
        if source_report_version is not None
        else None
    )
    gap_closure_rate = len(filled_gap_ids) / before_gap_count if before_gap_count else 0.0
    gap_fill_chain_closed = bool(filled_gap_ids and candidate_ids and updated_version is not None)
    return EvidenceGapFillResult(
        project_id=project_id,
        workspace_id=workspace_id,
        source_report_version_id=source_report_version.id if source_report_version else None,
        updated_report_version_id=updated_version.id if updated_version else None,
        gap_count=len(updated_gaps),
        before_gap_count=before_gap_count,
        after_gap_count=after_gap_count,
        gap_closure_rate=round(gap_closure_rate, 3),
        filled_gap_count=len(filled_gap_ids),
        added_evidence_count=len(candidate_ids),
        online_collected_evidence_count=len(online_collected_ids),
        online_failure_count=len(online_failure_items),
        gap_fill_chain_closed=gap_fill_chain_closed,
        candidate_evidence_ids=candidate_ids,
        filled_gap_ids=filled_gap_ids,
        remaining_gap_ids=remaining_gap_ids,
        decision_events=decision_events,
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


def _robots_blocked_fetch(fetched: FetchPageResult) -> bool:
    error = (fetched.error or "").casefold()
    return not fetched.ok and "robots" in error and "blocked" in error


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
            gap.model_copy(
                update={
                    "evidence_ids": _unique_ids(gap.evidence_ids + new_candidate_ids)
                }
            )
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
    decision_events: list[EvidenceGapFillDecisionEvent],
) -> ReportVersionRecord:
    metadata = dict(source.quality_metadata)
    metadata["rag_gap_fill"] = {
        "source_report_version_id": source.id,
        "before_gap_count": len(filled_gap_ids) + len(remaining_gap_ids),
        "after_gap_count": len(remaining_gap_ids),
        "gap_closure_rate": (
            round(len(filled_gap_ids) / (len(filled_gap_ids) + len(remaining_gap_ids)), 3)
            if filled_gap_ids or remaining_gap_ids
            else 0.0
        ),
        "filled_gap_ids": filled_gap_ids,
        "remaining_gap_ids": remaining_gap_ids,
        "candidate_evidence_ids": candidate_ids,
        "gap_fill_chain_closed": bool(filled_gap_ids and candidate_ids),
        "online_collected_evidence_ids": online_collected_evidence_ids,
        "online_failures": online_failures,
        "retrieval_records": [
            record.model_dump(mode="json")
            for gap in report.gaps
            for record in gap.retrieval_records
        ],
        "decision_events": [event.model_dump(mode="json") for event in decision_events],
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


def _gap_fill_decision_events(
    report: EvidenceGapReport,
    *,
    candidate_ids: list[str],
    filled_gap_ids: list[str],
    remaining_gap_ids: list[str],
    before_gap_count: int,
    after_gap_count: int,
    online_collected_evidence_ids: list[str],
    online_failures: list[dict[str, str]],
    source_report_version: ReportVersionRecord | None,
) -> list[EvidenceGapFillDecisionEvent]:
    gap_ids = [gap.id for gap in report.gaps]
    retrieval_contexts = _gap_retrieval_contexts(report)
    retrieval_records = [
        record.model_dump(mode="json") for gap in report.gaps for record in gap.retrieval_records
    ]
    chunk_ids = _unique_ids(
        [
            record.chunk_id
            for gap in report.gaps
            for record in gap.retrieval_records
            if record.chunk_id
        ]
    )
    rerank_scores = {
        _retrieval_record_key(record): record.rerank_score
        for gap in report.gaps
        for record in gap.retrieval_records
    }
    closure_rate = round(len(filled_gap_ids) / before_gap_count, 3) if before_gap_count else 0.0
    events = [
        EvidenceGapFillDecisionEvent(
            event_type="rag.retrieved",
            message=(
                f"Retrieved {len(candidate_ids)} candidate evidence item(s) for "
                f"{len(filled_gap_ids)}/{before_gap_count} evidence gap(s)."
            ),
            gap_ids=gap_ids,
            evidence_ids=candidate_ids,
            payload={
                "gap_count": len(gap_ids),
                "before_gap_count": before_gap_count,
                "after_gap_count": after_gap_count,
                "gap_closure_rate": closure_rate,
                "filled_gap_ids": filled_gap_ids,
                "remaining_gap_ids": remaining_gap_ids,
                "candidate_ids": candidate_ids,
                "retrieval_queries": [
                    context["query"] for context in retrieval_contexts if context["query"]
                ],
                "retrieval_contexts": retrieval_contexts,
                "chunk_ids": chunk_ids,
                "rerank_scores": rerank_scores,
                "retrieval_records": retrieval_records,
                "retrieval_record_count": len(retrieval_records),
            },
        )
    ]
    if online_collected_evidence_ids or online_failures:
        events.append(
            EvidenceGapFillDecisionEvent(
                event_type="tool.called",
                message=(
                    "Online gap fill fetched "
                    f"{len(online_collected_evidence_ids)} evidence item(s) with "
                    f"{len(online_failures)} failure(s)."
                ),
                gap_ids=gap_ids,
                evidence_ids=online_collected_evidence_ids,
                payload={
                    "tool": "online_gap_fill",
                    "online_collected_evidence_ids": online_collected_evidence_ids,
                    "online_failure_count": len(online_failures),
                    "online_failures": online_failures,
                },
            )
        )
    if source_report_version is not None:
        events.append(
            EvidenceGapFillDecisionEvent(
                event_type="report.ready",
                message="Created a draft ReportVersion with RAG gap fill evidence links.",
                gap_ids=filled_gap_ids,
                evidence_ids=candidate_ids,
                payload={
                    "source_report_version_id": source_report_version.id,
                    "parent_report_version_id": source_report_version.id,
                    "updated_report_version_id": _gap_fill_report_version_id(
                        source_report_version,
                        filled_gap_ids,
                        candidate_ids,
                    ),
                    "gap_fill_chain_closed": bool(filled_gap_ids and candidate_ids),
                    "candidate_ids": candidate_ids,
                },
            )
        )
    return events


def _gap_retrieval_contexts(report: EvidenceGapReport) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    for gap in report.gaps:
        records = gap.retrieval_records
        if not (
            gap.retrieval_query
            or gap.retrieval_candidate_ids
            or records
            or gap.retrieval_candidate_chunk_count
        ):
            continue
        contexts.append(
            {
                "gap_id": gap.id,
                "query": gap.retrieval_query,
                "candidate_ids": gap.retrieval_candidate_ids,
                "chunk_ids": _unique_ids(
                    [record.chunk_id for record in records if record.chunk_id]
                ),
                "candidate_chunk_count": gap.retrieval_candidate_chunk_count,
                "unique_evidence_candidate_count": gap.retrieval_unique_evidence_count,
                "dedupe_drop_count": gap.retrieval_dedupe_drop_count,
                "rerank_scores": {
                    _retrieval_record_key(record): record.rerank_score for record in records
                },
            }
        )
    return contexts


def _retrieval_record_key(record: RetrievalRecord) -> str:
    return record.chunk_id or f"{record.evidence_id}#chunk:{record.chunk_index}"


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
        added = _format_gap_fill_source_tokens(gap.evidence_ids)
        lines.append(f"- {gap.id}: linked evidence candidates {added}.")
        if gap.retrieval_grounded_context:
            lines.append(f"  - Grounded context: {gap.retrieval_grounded_context[:600]}")
    return "\n".join(lines).strip() + "\n"


def _format_gap_fill_source_tokens(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return "none"
    return ", ".join(f"[source:{evidence_id}]" for evidence_id in evidence_ids)


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
