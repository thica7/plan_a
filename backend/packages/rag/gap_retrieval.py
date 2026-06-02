from __future__ import annotations

from typing import Protocol

from packages.schema.enterprise import EvidenceGapItem, EvidenceGapReport, EvidenceSearchHit
from packages.schema.rag import GapRetrievalContext, RetrievalRecord


class EvidenceRetriever(Protocol):
    def search_evidence(
        self,
        *,
        workspace_id: str,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[EvidenceSearchHit]: ...


def decorate_evidence_gap_report_with_retrieval(
    report: EvidenceGapReport,
    *,
    store: EvidenceRetriever,
    workspace_id: str,
    project_id: str | None = None,
    limit: int = 3,
) -> EvidenceGapReport:
    contexts = {
        gap.id: retrieve_gap_candidates(
            store=store,
            workspace_id=workspace_id,
            project_id=project_id,
            gap=gap,
            limit=limit,
        )
        for gap in report.gaps
    }
    return report.model_copy(
        update={
            "gaps": [
                gap.model_copy(
                    update={
                        "retrieval_query": contexts[gap.id].query,
                        "retrieval_candidate_ids": contexts[gap.id].candidate_ids,
                    }
                )
                for gap in report.gaps
            ]
        }
    )


def retrieve_gap_candidates(
    *,
    store: EvidenceRetriever,
    workspace_id: str,
    gap: EvidenceGapItem,
    project_id: str | None = None,
    limit: int = 3,
) -> GapRetrievalContext:
    query = build_gap_retrieval_query(gap)
    if not query:
        return GapRetrievalContext(gap_id=gap.id, query="")
    hits = store.search_evidence(
        workspace_id=workspace_id,
        project_id=project_id,
        query=query,
        limit=max(limit * 3, limit),
    )
    records: list[RetrievalRecord] = []
    seen: set[str] = set()
    for hit in hits:
        evidence = hit.evidence
        if evidence.id in seen or evidence.id in gap.evidence_ids:
            continue
        if not _source_type_matches_gap(gap, evidence.source_type):
            continue
        seen.add(evidence.id)
        records.append(
            RetrievalRecord(
                evidence_id=evidence.id,
                score=round(hit.score, 4),
                title=evidence.title,
                source_type=evidence.source_type,
                dimension=evidence.dimension,
                snippet=evidence.snippet[:360],
            )
        )
        if len(records) >= limit:
            break
    return GapRetrievalContext(
        gap_id=gap.id,
        query=query,
        candidate_ids=[record.evidence_id for record in records],
        records=records,
        grounded_context=_grounded_context(records),
    )


def build_gap_retrieval_query(gap: EvidenceGapItem) -> str:
    parts = [
        gap.recommended_query,
        gap.competitor_name or gap.competitor_id or "",
        gap.dimension or "",
        gap.source_type_required or "",
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _source_type_matches_gap(gap: EvidenceGapItem, source_type: str) -> bool:
    required = (gap.source_type_required or "").casefold().strip()
    if not required or required in {"any usable source", "any"}:
        return True
    return required == source_type.casefold().strip()


def _grounded_context(records: list[RetrievalRecord]) -> str:
    lines = []
    for record in records:
        lines.append(
            f"[source:{record.evidence_id}] {record.title} "
            f"({record.source_type}, score={record.score}): {record.snippet}"
        )
    return "\n".join(lines)
