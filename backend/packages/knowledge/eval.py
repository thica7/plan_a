"""Retrieval evaluation metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import RetrievalHit


@dataclass(frozen=True)
class RetrievalLabel:
    query: str
    relevant_doc_ids: list[str]
    relevant_chunk_ids: list[str]


def evaluate_retrieval(
    labels: list[RetrievalLabel],
    results: list[list[RetrievalHit]],
    *,
    top_k: int,
) -> dict[str, object]:
    per_query = [
        evaluate_query(label, hits, top_k=top_k)
        for label, hits in zip(labels, results, strict=False)
    ]
    total = max(1, len(per_query))
    return {
        "top_k": top_k,
        "query_count": len(per_query),
        "recall_at_k": sum(item["recall_at_k"] for item in per_query) / total,
        "mrr": sum(item["mrr"] for item in per_query) / total,
        "ndcg_at_k": sum(item["ndcg_at_k"] for item in per_query) / total,
        "per_query": per_query,
    }


def evaluate_query(
    label: RetrievalLabel,
    hits: list[RetrievalHit],
    *,
    top_k: int,
) -> dict[str, object]:
    relevant = _relevant_units(label)
    top_hits = hits[:top_k]
    matched: set[tuple[str, str]] = set()
    relevance_by_rank: list[int] = []
    first_relevant_rank = 0

    for rank, hit in enumerate(top_hits, 1):
        hit_units = _hit_units(hit)
        hit_matches = relevant & hit_units
        if hit_matches:
            matched.update(hit_matches)
            relevance_by_rank.append(1)
            if first_relevant_rank == 0:
                first_relevant_rank = rank
        else:
            relevance_by_rank.append(0)

    recall = len(matched) / len(relevant) if relevant else 0.0
    mrr = 1.0 / first_relevant_rank if first_relevant_rank else 0.0
    ndcg = _ndcg(relevance_by_rank, ideal_relevant_count=len(relevant), top_k=top_k)
    return {
        "query": label.query,
        "relevant_count": len(relevant),
        "retrieved_count": len(top_hits),
        "matched_count": len(matched),
        "recall_at_k": recall,
        "mrr": mrr,
        "ndcg_at_k": ndcg,
    }


def _relevant_units(label: RetrievalLabel) -> set[tuple[str, str]]:
    units = {("doc", doc_id) for doc_id in label.relevant_doc_ids}
    units.update(("chunk", chunk_id) for chunk_id in label.relevant_chunk_ids)
    return units


def _hit_units(hit: RetrievalHit) -> set[tuple[str, str]]:
    return {("doc", hit.document_id), ("chunk", hit.chunk_id)}


def _ndcg(relevance_by_rank: list[int], *, ideal_relevant_count: int, top_k: int) -> float:
    if ideal_relevant_count <= 0:
        return 0.0
    dcg = sum(
        relevance / math.log2(rank + 1)
        for rank, relevance in enumerate(relevance_by_rank, 1)
    )
    ideal_len = min(ideal_relevant_count, top_k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_len + 1))
    return dcg / idcg if idcg else 0.0
