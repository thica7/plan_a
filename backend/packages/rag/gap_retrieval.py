from __future__ import annotations

from typing import Protocol

from packages.rag.retriever import retrieve_grounded_context
from packages.schema.enterprise import (
    EvidenceGapItem,
    EvidenceGapReport,
    EvidenceRecord,
    EvidenceSearchHit,
)
from packages.schema.rag import GapRetrievalContext


class EvidenceRetriever(Protocol):
    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]: ...

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
                        "retrieval_candidate_chunk_count": contexts[gap.id].candidate_chunk_count,
                        "retrieval_unique_evidence_count": (
                            contexts[gap.id].unique_evidence_candidate_count
                        ),
                        "retrieval_dedupe_drop_count": contexts[gap.id].dedupe_drop_count,
                        "retrieval_candidate_ids": contexts[gap.id].candidate_ids,
                        "retrieval_records": contexts[gap.id].records,
                        "retrieval_grounded_context": contexts[gap.id].grounded_context,
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
    return retrieve_grounded_context(
        store=store,
        workspace_id=workspace_id,
        gap_id=gap.id,
        query=query,
        rewritten_queries=_gap_query_variants(gap, query),
        project_id=project_id,
        exclude_evidence_ids=set(gap.evidence_ids),
        source_type_required=gap.source_type_required,
        limit=limit,
    )


def build_gap_retrieval_query(gap: EvidenceGapItem) -> str:
    parts = [
        gap.recommended_query,
        gap.competitor_name or gap.competitor_id or "",
        gap.dimension or "",
        gap.source_type_required or "",
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _gap_query_variants(gap: EvidenceGapItem, primary_query: str) -> list[str]:
    variants = [primary_query]
    competitor = gap.competitor_name or gap.competitor_id or ""
    if competitor and gap.dimension:
        variants.append(f"{competitor} {gap.dimension}")
    if gap.recommended_query:
        variants.append(gap.recommended_query)
    if competitor and gap.source_type_required:
        variants.append(f"{competitor} {gap.source_type_required}")
    return variants
