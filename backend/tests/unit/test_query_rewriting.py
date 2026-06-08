from __future__ import annotations

import pytest

from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import QueryRewriter, RetrievalService


class FakeRewriter(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        return [f"{query} rewrite {index}" for index in range(num_rewrites)]


class FakeVectorStore:
    def __init__(self) -> None:
        self.searches: list[list[float]] = []

    async def search(self, query_vector, **kwargs):
        self.searches.append(query_vector)
        return [
            RetrievalHit(
                chunk_id=f"chunk-{int(query_vector[0])}",
                document_id=f"doc-{int(query_vector[0])}",
                text=f"text {int(query_vector[0])}",
                score=1.0,
            )
        ]


class EmptyRepo:
    async def search_documents(self, query: str, limit: int = 20, **kwargs):
        return []

    async def get_chunks_for_documents(self, doc_ids: list[str]):
        return {}


@pytest.mark.asyncio
async def test_query_rewriting_runs_each_query_and_fuses_results() -> None:
    embedded: list[str] = []

    def embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            embedded.append(text)
            vectors.append([float(len(embedded)), 0.0])
        return vectors

    vector_store = FakeVectorStore()
    service = RetrievalService(
        repo=EmptyRepo(),
        vector_store=vector_store,
        embed_fn=embed,
        query_rewriter=FakeRewriter(),
    )

    response = await service.retrieve(
        RetrievalRequest(
            query="pricing controls",
            top_k=5,
            final_top_k=5,
            num_rewrites=2,
            mode="hybrid",
        )
    )

    assert embedded == [
        "pricing controls",
        "pricing controls rewrite 0",
        "pricing controls rewrite 1",
    ]
    assert len(vector_store.searches) == 3
    assert {hit.chunk_id for hit in response.hits} == {"chunk-1", "chunk-2", "chunk-3"}
    assert response.query == "pricing controls"
