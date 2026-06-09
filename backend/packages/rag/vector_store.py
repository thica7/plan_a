from __future__ import annotations

from typing import Protocol

from packages.schema.enterprise import EvidenceRecord, EvidenceSearchHit


class EvidenceVectorStore(Protocol):
    def list_evidence(self, project_id: str | None = None) -> list[EvidenceRecord]: ...

    def search_evidence(
        self,
        *,
        workspace_id: str,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[EvidenceSearchHit]: ...


def recall_evidence(
    *,
    store: EvidenceVectorStore,
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


def recall_evidence_scores(
    *,
    store: EvidenceVectorStore,
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
