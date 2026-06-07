from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from packages.knowledge.eval import RetrievalLabel, evaluate_retrieval
from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import QueryRewriter, RetrievalService, get_retrieval_presets


class EmptyRewriter(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        return []


class EvalVectorStore:
    async def search(self, query_vector, **kwargs):
        preset_index = int(query_vector[0])
        preset_name = ["general", "pricing", "comparison"][preset_index]
        return [
            RetrievalHit(
                chunk_id=f"chunk-{preset_name}",
                document_id=f"doc-{preset_name}",
                text=f"{preset_name} evidence",
                score=1.0,
            )
        ]


class EmptyRepo:
    async def search_documents(self, query: str, limit: int = 20):
        return []

    async def get_chunks_for_documents(self, doc_ids: list[str]):
        return {}


def test_competitor_analysis_eval_set_has_required_categories() -> None:
    eval_path = Path(__file__).resolve().parents[3] / "eval" / "competitor-analysis-eval.jsonl"
    entries = [json.loads(line) for line in eval_path.read_text().splitlines()]
    counts = Counter(entry["description"].split(":", 1)[0] for entry in entries)

    assert len(entries) == 30
    assert counts == {
        "pricing": 8,
        "feature": 8,
        "user_review": 7,
        "comparison": 7,
    }
    assert all(entry["query"] and entry["relevant_doc_ids"] for entry in entries)


@pytest.mark.asyncio
async def test_eval_runs_with_all_retrieval_presets() -> None:
    preset_names = [preset.name for preset in get_retrieval_presets()]

    def embed(texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            matched = next((name for name in preset_names if name in text), preset_names[0])
            vectors.append([float(preset_names.index(matched))])
        return vectors

    service = RetrievalService(
        repo=EmptyRepo(),
        vector_store=EvalVectorStore(),
        embed_fn=embed,
        query_rewriter=EmptyRewriter(),
    )

    responses = [
        await service.retrieve(RetrievalRequest(query=preset, preset=preset, mode="dense"))
        for preset in preset_names
    ]
    labels = [
        RetrievalLabel(
            query=preset,
            relevant_doc_ids=[f"doc-{preset}"],
            relevant_chunk_ids=[],
        )
        for preset in preset_names
    ]
    metrics = evaluate_retrieval(labels, [response.hits for response in responses], top_k=1)

    assert metrics["query_count"] == 3
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 1.0
