from __future__ import annotations

import pytest

from packages.knowledge.eval import RetrievalLabel, evaluate_retrieval
from packages.knowledge.models import RetrievalHit


def test_eval_metrics_compute_recall_mrr_and_ndcg_at_k() -> None:
    labels = [
        RetrievalLabel(
            query="pricing",
            relevant_doc_ids=["doc-a"],
            relevant_chunk_ids=["chunk-b"],
        ),
        RetrievalLabel(
            query="security",
            relevant_doc_ids=[],
            relevant_chunk_ids=["chunk-d"],
        ),
    ]
    results = [
        [
            RetrievalHit(chunk_id="chunk-x", document_id="doc-x", text="", score=1.0),
            RetrievalHit(chunk_id="chunk-b", document_id="doc-b", text="", score=0.9),
            RetrievalHit(chunk_id="chunk-c", document_id="doc-a", text="", score=0.8),
        ],
        [
            RetrievalHit(chunk_id="chunk-d", document_id="doc-d", text="", score=1.0),
        ],
    ]

    metrics = evaluate_retrieval(labels, results, top_k=2)

    assert metrics["query_count"] == 2
    assert metrics["recall_at_k"] == pytest.approx(0.75)
    assert metrics["mrr"] == pytest.approx(0.75)
    assert metrics["ndcg_at_k"] == pytest.approx((0.6309297535714575 / 1.6309297535714575 + 1) / 2)
    assert metrics["per_query"][0]["matched_count"] == 1
