from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import RetrievalService


class FixedVectorStore:
    async def search(self, query_vector, **kwargs):
        return [
            RetrievalHit(
                chunk_id="dense",
                document_id="dense-doc",
                text="dense text",
                score=1.0,
            )
        ]


class SparseRepo:
    async def search_documents(self, query: str, limit: int = 20):
        return [
            SimpleNamespace(
                id="sparse-doc",
                url=None,
                title="Sparse",
                competitor=None,
                dimension=None,
                source_type="manual",
                content_hash="hash",
            )
        ]

    async def get_chunks_for_documents(self, doc_ids: list[str]):
        return {
            "sparse-doc": [
                SimpleNamespace(
                    id="sparse",
                    document_id="sparse-doc",
                    text="sparse text",
                )
            ]
        }


def embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        if "dense text" in text:
            vectors.append([1.0, 0.0])
        elif "sparse text" in text:
            vectors.append([0.0, 1.0])
        else:
            vectors.append([1.0, 0.0])
    return vectors


@pytest.mark.asyncio
async def test_retrieval_weights_and_final_top_k_are_request_scoped() -> None:
    service = RetrievalService(
        repo=SparseRepo(),
        vector_store=FixedVectorStore(),
        embed_fn=embed,
    )

    dense_only = await service.retrieve(
        RetrievalRequest(
            query="pricing",
            enable_query_rewrite=False,
            dense_weight=1.0,
            sparse_weight=0.0,
            final_top_k=1,
        )
    )
    sparse_only = await service.retrieve(
        RetrievalRequest(
            query="pricing",
            enable_query_rewrite=False,
            dense_weight=0.0,
            sparse_weight=1.0,
            final_top_k=1,
        )
    )

    assert dense_only.hits[0].chunk_id == "dense"
    assert sparse_only.hits[0].chunk_id == "sparse"
    assert len(dense_only.hits) == 1


@pytest.mark.asyncio
async def test_mmr_diversifies_when_enabled() -> None:
    service = RetrievalService(
        repo=SparseRepo(),
        vector_store=FixedVectorStore(),
        embed_fn=embed,
    )

    response = await service.retrieve(
        RetrievalRequest(
            query="pricing",
            enable_query_rewrite=False,
            dense_weight=1.0,
            sparse_weight=1.0,
            rerank_top_k=2,
            final_top_k=2,
            mmr_lambda=0.1,
        )
    )

    assert [hit.chunk_id for hit in response.hits] == ["dense", "sparse"]
