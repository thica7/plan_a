"""LangGraph tool for knowledge base retrieval."""

from __future__ import annotations

from functools import lru_cache

from langchain_core.tools import tool

from ..knowledge.embeddings import (
    EmbeddingProvider,
    get_embedding_provider_from_env,
)
from ..knowledge.models import KnowledgeScope, RetrievalRequest, SourceRole
from ..knowledge.repository import KnowledgeRepository
from ..knowledge.retrieval import RetrievalService


@lru_cache(maxsize=1)
def _get_embedding_provider() -> EmbeddingProvider | None:
    return get_embedding_provider_from_env()


def _empty_embeddings(texts: list[str]) -> list[list[float]]:
    raise RuntimeError("Embedding provider is disabled")


@tool
async def rag_retrieve_tool(
    query: str,
    competitors: list[str],
    dimensions: list[str],
    top_k: int,
    mode: str = "hybrid",
    preset: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
    market: str | None = None,
    source_roles: list[SourceRole] | None = None,
    max_age_days: int | None = None,
) -> list[dict[str, object]]:
    """Retrieve relevant knowledge chunks for a competitive analysis query."""
    # The server caller supplies this boundary; this tool is not an authentication layer.
    if workspace_id is None:
        return []
    scope = KnowledgeScope(workspace_id=workspace_id, project_id=project_id)
    repo = KnowledgeRepository()
    await repo.initialise()
    try:
        embedding_provider = None
        retrieval_mode = mode if mode in {"dense", "hybrid", "sparse"} else "hybrid"
        if retrieval_mode == "sparse":
            vector_store = object()
            embed_fn = _empty_embeddings
        else:
            from ..knowledge.vector_store import VectorStore

            embedding_provider = _get_embedding_provider()
            vector_store = VectorStore()
            embed_fn = (
                embedding_provider.embed_documents if embedding_provider else _empty_embeddings
            )
        service = RetrievalService(
            repo=repo,
            vector_store=vector_store,
            embed_fn=embed_fn,
            embedding_provider=embedding_provider,
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
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                include_workspace_library=include_workspace_library,
                market=market,
                source_roles=source_roles or [],
                max_age_days=max_age_days,
            )
        )
        return [hit.model_dump(mode="json") for hit in response.hits]
    finally:
        await repo.close()
