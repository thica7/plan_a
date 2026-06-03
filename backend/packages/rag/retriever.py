from __future__ import annotations

from typing import Protocol

from packages.enterprise.embedding_index import cosine_similarity, deterministic_embedding
from packages.rag.bm25 import BM25Index
from packages.rag.chunker import chunk_corpus
from packages.rag.reranker import RetrievalCandidate, rerank_candidates
from packages.schema.enterprise import EvidenceRecord, EvidenceSearchHit
from packages.schema.rag import GapRetrievalContext, RetrievalRecord


class EvidenceCorpusStore(Protocol):
    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]: ...

    def search_evidence(
        self,
        *,
        workspace_id: str,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[EvidenceSearchHit]: ...


def retrieve_grounded_context(
    *,
    store: EvidenceCorpusStore,
    workspace_id: str,
    gap_id: str,
    query: str,
    rewritten_queries: list[str] | None = None,
    project_id: str | None = None,
    exclude_evidence_ids: set[str] | None = None,
    source_type_required: str | None = None,
    limit: int = 3,
) -> GapRetrievalContext:
    queries = _dedupe_queries([query, *(rewritten_queries or [])])
    if not queries:
        return GapRetrievalContext(gap_id=gap_id, query="")
    evidence = _candidate_evidence(
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        queries=queries,
        recall_limit=max(limit * 8, 20),
    )
    excluded = exclude_evidence_ids or set()
    filtered = [
        item
        for item in evidence
        if item.id not in excluded
        and item.workspace_id == workspace_id
        and (project_id is None or item.project_id == project_id)
        and _source_type_matches(source_type_required, item.source_type)
    ]
    chunks = chunk_corpus(filtered)
    if not chunks:
        return GapRetrievalContext(gap_id=gap_id, query=queries[0], rewritten_queries=queries)
    bm25 = BM25Index(chunks)
    query_vector = deterministic_embedding(" ".join(queries))
    recall_scores = _recall_scores(
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        queries=queries,
        recall_limit=max(limit * 8, 20),
    )
    evidence_by_id = {item.id: item for item in filtered}
    candidates: list[RetrievalCandidate] = []
    for chunk in chunks:
        evidence_item = evidence_by_id.get(chunk.evidence_id)
        if evidence_item is None:
            continue
        candidates.append(
            RetrievalCandidate(
                chunk=chunk,
                evidence=evidence_item,
                vector_score=cosine_similarity(query_vector, deterministic_embedding(chunk.text)),
                bm25_score=max(bm25.score(item, chunk) for item in queries),
                recall_score=recall_scores.get(chunk.evidence_id, 0.0),
            )
        )
    records = rerank_candidates(candidates, limit=limit)
    unique_evidence_count = len({candidate.evidence.id for candidate in candidates})
    return GapRetrievalContext(
        gap_id=gap_id,
        query=queries[0],
        rewritten_queries=queries,
        candidate_chunk_count=len(candidates),
        unique_evidence_candidate_count=unique_evidence_count,
        dedupe_drop_count=max(0, len(candidates) - unique_evidence_count),
        candidate_ids=[record.evidence_id for record in records],
        records=records,
        grounded_context=grounded_context(records),
    )


def grounded_context(records: list[RetrievalRecord]) -> str:
    lines = []
    for record in records:
        lines.append(
            f"[source:{record.evidence_id}#chunk:{record.chunk_index}] {record.title} "
            f"({record.source_type}, hybrid={record.score}, bm25={record.bm25_score}, "
            f"vector={record.vector_score}): {record.snippet}"
        )
    return "\n".join(lines)


def _candidate_evidence(
    *,
    store: EvidenceCorpusStore,
    workspace_id: str,
    project_id: str | None,
    queries: list[str],
    recall_limit: int,
) -> list[EvidenceRecord]:
    evidence_by_id = {
        item.id: item
        for item in store.list_evidence(project_id=project_id)
        if item.workspace_id == workspace_id
    }
    for query in queries:
        for hit in store.search_evidence(
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=recall_limit,
        ):
            evidence_by_id[hit.evidence.id] = hit.evidence
    return list(evidence_by_id.values())


def _recall_scores(
    *,
    store: EvidenceCorpusStore,
    workspace_id: str,
    project_id: str | None,
    queries: list[str],
    recall_limit: int,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for query in queries:
        for hit in store.search_evidence(
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            limit=recall_limit,
        ):
            scores[hit.evidence.id] = max(scores.get(hit.evidence.id, -1.0), hit.score)
    return scores


def _source_type_matches(required: str | None, actual: str) -> bool:
    required_value = (required or "").casefold().strip()
    if not required_value or required_value in {"any usable source", "any"}:
        return True
    return required_value == actual.casefold().strip()


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        normalized = " ".join(query.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
