from __future__ import annotations

import pytest

from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import QueryRewriter, RetrievalService


class FakeRewriter(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        return [f"{query} expanded"]


class CountingVectorStore:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query_vector, **kwargs):
        self.calls += 1
        return [
            RetrievalHit(
                chunk_id=f"chunk-{self.calls}",
                document_id="doc",
                text="cached text",
                score=1.0,
            )
        ]


class EmptyRepo:
    async def search_documents(self, query: str, limit: int = 20):
        return []

    async def get_chunks_for_documents(self, doc_ids: list[str]):
        return {}


def embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(text)), 0.0] for text in texts]


@pytest.mark.asyncio
async def test_retrieval_cache_reuses_identical_request_and_keys_parameters() -> None:
    vector_store = CountingVectorStore()
    service = RetrievalService(
        repo=EmptyRepo(),
        vector_store=vector_store,
        embed_fn=embed,
    )
    request = RetrievalRequest(
        query="security",
        mode="dense",
        enable_query_rewrite=False,
        final_top_k=1,
    )

    first = await service.retrieve(request)
    second = await service.retrieve(request)
    third = await service.retrieve(request.model_copy(update={"final_top_k": 2}))

    assert vector_store.calls == 2
    assert first.hits[0].chunk_id == second.hits[0].chunk_id
    assert third.hits[0].chunk_id == "chunk-2"


@pytest.mark.asyncio
async def test_retrieval_cache_is_bypassed_for_query_rewrite_requests() -> None:
    vector_store = CountingVectorStore()
    service = RetrievalService(
        repo=EmptyRepo(),
        vector_store=vector_store,
        embed_fn=embed,
        query_rewriter=FakeRewriter(),
    )
    request = RetrievalRequest(
        query="pricing",
        mode="dense",
        enable_query_rewrite=True,
        num_rewrites=1,
        final_top_k=2,
    )

    await service.retrieve(request)
    await service.retrieve(request)

    assert vector_store.calls == 4
