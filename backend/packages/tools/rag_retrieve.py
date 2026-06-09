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
from ..knowledge.vector_store import VectorStore


@lru_cache(maxsize=1)
def _get_embedding_provider() -> EmbeddingProvider:
    return get_embedding_provider_from_env() or HashEmbeddingProvider()


@tool
async def rag_retrieve_tool(
    query: str,
    competitors: list[str],
    dimensions: list[str],
    top_k: int,
) -> list[dict[str, object]]:
    """Retrieve relevant knowledge chunks for a competitive analysis query."""
    repo = KnowledgeRepository()
    await repo.initialise()
    try:
        embedding_provider = _get_embedding_provider()
        service = RetrievalService(
            repo=repo,
            vector_store=VectorStore(),
            embed_fn=embedding_provider.embed_documents,
        )
        response = await service.retrieve(
            RetrievalRequest(
                query=query,
                competitors=competitors,
                dimensions=dimensions,
                top_k=top_k,
            )
        )
        return [hit.model_dump(mode="json") for hit in response.hits]
    finally:
        await repo.close()
