from __future__ import annotations

from dataclasses import dataclass

from packages.schema.enterprise import EvidenceRecord
from packages.schema.rag import RetrievalChunk, RetrievalRecord


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk: RetrievalChunk
    evidence: EvidenceRecord
    vector_score: float
    bm25_score: float
    recall_score: float


def rerank_candidates(
    candidates: list[RetrievalCandidate],
    *,
    limit: int,
) -> list[RetrievalRecord]:
    if not candidates:
        return []
    max_bm25 = max(candidate.bm25_score for candidate in candidates) or 1.0
    ranked = sorted(
        (
            (
                _hybrid_score(candidate, max_bm25=max_bm25),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: (
            item[0],
            item[1].evidence.reliability_score,
            item[1].chunk.title.casefold(),
        ),
        reverse=True,
    )
    records: list[RetrievalRecord] = []
    seen_evidence_ids: set[str] = set()
    for score, candidate in ranked:
        if candidate.evidence.id in seen_evidence_ids:
            continue
        seen_evidence_ids.add(candidate.evidence.id)
        records.append(
            RetrievalRecord(
                evidence_id=candidate.evidence.id,
                chunk_id=candidate.chunk.id,
                chunk_index=candidate.chunk.chunk_index,
                score=round(score, 4),
                vector_score=round(candidate.vector_score, 4),
                bm25_score=round(candidate.bm25_score, 4),
                rerank_score=round(score, 4),
                title=candidate.evidence.title,
                source_type=candidate.evidence.source_type,
                dimension=candidate.evidence.dimension,
                snippet=candidate.chunk.text[:420],
                source_url=candidate.chunk.source_url,
            )
        )
        if len(records) >= limit:
            break
    return records


def _hybrid_score(candidate: RetrievalCandidate, *, max_bm25: float) -> float:
    vector_component = _normalize_vector(candidate.vector_score)
    bm25_component = min(1.0, candidate.bm25_score / max_bm25) if max_bm25 > 0 else 0.0
    recall_component = _normalize_vector(candidate.recall_score)
    quality_component = _quality_score(candidate.evidence)
    score = (
        vector_component * 0.35
        + bm25_component * 0.35
        + recall_component * 0.15
        + quality_component * 0.15
    )
    return max(0.0, min(1.0, score))


def _normalize_vector(score: float) -> float:
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def _quality_score(evidence: EvidenceRecord) -> float:
    label_bonus = {
        "accepted": 1.0,
        "unreviewed": 0.75,
        "stale": 0.35,
        "rejected": 0.0,
    }.get(evidence.quality_label, 0.5)
    reliability = max(0.0, min(1.0, evidence.reliability_score))
    freshness = max(0.0, min(1.0, evidence.freshness_score))
    return reliability * 0.65 + label_bonus * 0.25 + freshness * 0.10
