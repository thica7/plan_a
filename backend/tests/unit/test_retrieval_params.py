from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import (
    RetrievalPreset,
    RetrievalService,
    get_retrieval_preset,
    get_retrieval_presets,
)


class FixedVectorStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def search(self, query_vector, **kwargs):
        self.calls.append(kwargs)
        return [
            RetrievalHit(
                chunk_id="dense",
                document_id="dense-doc",
                text="dense text",
                score=1.0,
            )
        ]


class SparseRepo:
    def __init__(self) -> None:
        self.limits: list[int] = []
        self.filters: list[dict[str, list[str] | None]] = []

    async def search_documents(
        self,
        query: str,
        limit: int = 20,
        *,
        competitors: list[str] | None = None,
        dimensions: list[str] | None = None,
    ):
        self.limits.append(limit)
        self.filters.append({"competitors": competitors, "dimensions": dimensions})
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

    def get_document_weight(self, document) -> float:
        return 1.0


class DuplicateDocumentVectorStore:
    async def search(self, query_vector, **kwargs):
        return [
            RetrievalHit(
                chunk_id="chunk-a1",
                document_id="doc-a",
                text="first A",
                score=1.0,
            ),
            RetrievalHit(
                chunk_id="chunk-a2",
                document_id="doc-a",
                text="second A",
                score=0.9,
            ),
            RetrievalHit(
                chunk_id="chunk-b1",
                document_id="doc-b",
                text="first B",
                score=0.8,
            ),
        ]


class LeakyVectorStore:
    async def search(self, query_vector, **kwargs):
        return [
            RetrievalHit(
                chunk_id="allowed",
                document_id="allowed-doc",
                text="allowed text",
                score=1.0,
                competitor="OpenAI Codex",
                dimension="docs",
            ),
            RetrievalHit(
                chunk_id="wrong-competitor",
                document_id="wrong-competitor-doc",
                text="wrong competitor text",
                score=0.95,
                competitor="GitHub Copilot",
                dimension="docs",
            ),
            RetrievalHit(
                chunk_id="wrong-dimension",
                document_id="wrong-dimension-doc",
                text="wrong dimension text",
                score=0.9,
                competitor="OpenAI Codex",
                dimension="pricing",
            ),
        ]


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


def test_retrieval_presets_validate_builtin_parameters() -> None:
    presets = {preset.name: preset for preset in get_retrieval_presets()}

    assert set(presets) == {"general", "pricing", "comparison"}
    assert presets["pricing"].dense_weight == 0.3
    assert presets["pricing"].sparse_weight == 0.7
    assert presets["pricing"].query_rewrite_enabled is False


def test_retrieval_preset_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        get_retrieval_preset("missing")
    with pytest.raises(ValueError):
        RetrievalPreset(
            name="bad",
            description="bad",
            dense_weight=1.5,
            sparse_weight=0.0,
            top_k=1,
            rerank_top_k=0,
            mmr_lambda=0.0,
            query_rewrite_enabled=False,
        )


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


@pytest.mark.asyncio
async def test_preset_parameters_flow_into_retrieval() -> None:
    repo = SparseRepo()
    vector_store = FixedVectorStore()
    service = RetrievalService(
        repo=repo,
        vector_store=vector_store,
        embed_fn=embed,
    )

    response = await service.retrieve(
        RetrievalRequest(
            query="pricing",
            preset="pricing",
            final_top_k=20,
        )
    )

    assert vector_store.calls[0]["top_k"] == 5
    assert repo.limits == [5]
    assert len(response.hits) <= 5


@pytest.mark.asyncio
async def test_retrieval_filters_flow_into_dense_and_sparse_search() -> None:
    repo = SparseRepo()
    vector_store = FixedVectorStore()
    service = RetrievalService(
        repo=repo,
        vector_store=vector_store,
        embed_fn=embed,
    )

    await service.retrieve(
        RetrievalRequest(
            query="security",
            competitors=["Netlify"],
            dimensions=["security"],
            enable_query_rewrite=False,
        )
    )

    assert vector_store.calls[0]["competitors"] == ["Netlify"]
    assert vector_store.calls[0]["dimensions"] == ["security"]
    assert repo.filters == [{"competitors": ["Netlify"], "dimensions": ["security"]}]


@pytest.mark.asyncio
async def test_retrieval_prefers_document_diversity_in_final_hits() -> None:
    service = RetrievalService(
        repo=SparseRepo(),
        vector_store=DuplicateDocumentVectorStore(),
        embed_fn=embed,
    )

    response = await service.retrieve(
        RetrievalRequest(
            query="pricing",
            mode="dense",
            enable_query_rewrite=False,
            final_top_k=3,
        )
    )

    assert [hit.chunk_id for hit in response.hits] == ["chunk-a1", "chunk-b1", "chunk-a2"]


@pytest.mark.asyncio
async def test_retrieval_filters_final_hits_as_a_safety_net() -> None:
    service = RetrievalService(
        repo=SparseRepo(),
        vector_store=LeakyVectorStore(),
        embed_fn=embed,
    )

    response = await service.retrieve(
        RetrievalRequest(
            query="codex docs",
            mode="dense",
            competitors=["OpenAI Codex"],
            dimensions=["docs"],
            enable_query_rewrite=False,
            final_top_k=5,
        )
    )

    assert [hit.chunk_id for hit in response.hits] == ["allowed"]
    assert response.total == 1
