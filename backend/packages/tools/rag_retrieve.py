"""LangGraph tool for knowledge base retrieval."""

from __future__ import annotations

from functools import lru_cache

from langchain_core.tools import tool

from ..knowledge.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    get_embedding_provider_from_env,
)
from ..knowledge.models import RetrievalRequest
from ..knowledge.repository import KnowledgeRepository
from ..knowledge.retrieval import RetrievalService


@lru_cache(maxsize=1)
def _get_embedding_provider() -> EmbeddingProvider:
    return get_embedding_provider_from_env() or HashEmbeddingProvider()


def _empty_embeddings(texts: list[str]) -> list[list[float]]:
    return []


@tool
async def rag_retrieve_tool(
    query: str,
    competitors: list[str],
    dimensions: list[str],
    top_k: int,
    mode: str = "hybrid",
    preset: str | None = None,
) -> list[dict[str, object]]:
    """Retrieve relevant knowledge chunks for a competitive analysis query."""
    repo = KnowledgeRepository()
    await repo.initialise()
    try:
        retrieval_mode = mode if mode in {"dense", "hybrid", "sparse"} else "hybrid"
        if retrieval_mode == "sparse":
            vector_store = object()
            embed_fn = _empty_embeddings
        else:
            from ..knowledge.vector_store import VectorStore

            embedding_provider = _get_embedding_provider()
            vector_store = VectorStore()
            embed_fn = embedding_provider.embed_documents
        service = RetrievalService(
            repo=repo,
            vector_store=vector_store,
            embed_fn=embed_fn,
        )
        response = await service.retrieve(
            RetrievalRequest(
                query=query,
                preset=preset,
                competitors=competitors,
                dimensions=dimensions,
                top_k=top_k,
                final_top_k=top_k,
                enable_query_rewrite=retrieval_mode != "sparse",
                num_rewrites=0 if retrieval_mode == "sparse" else 3,
                mode=retrieval_mode,
            )
        )
        return [hit.model_dump(mode="json") for hit in response.hits]
    finally:
        await repo.close()
