"""LangGraph tool for ingesting one knowledge document."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..knowledge.embeddings import get_embedding_provider_from_env
from ..knowledge.ingestion import IngestionPipeline
from ..knowledge.models import DocumentCreate
from ..knowledge.repository import KnowledgeRepository


class _NoopVectorStore:
    async def upsert(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        return None


def _vector_store_for_ingest(index_vectors: bool):
    if not index_vectors:
        return _NoopVectorStore()
    from ..knowledge.vector_store import VectorStore

    return VectorStore()


@tool
async def ingest_document_tool(
    url: str,
    title: str,
    text: str,
    competitor: str,
    dimension: str,
    source_type: str,
    metadata: dict[str, Any] | None = None,
    crawl_run_id: str | None = None,
    index_vectors: bool = True,
) -> str:
    """Ingest a document into the knowledge base and return its document ID."""
    repo = KnowledgeRepository()
    await repo.initialise()
    try:
        embedding_provider = get_embedding_provider_from_env() if index_vectors else None
        pipeline = IngestionPipeline(
            repo=repo,
            vector_store=_vector_store_for_ingest(embedding_provider is not None),
        )
        return await pipeline.ingest(
            DocumentCreate(
                url=url,
                title=title,
                text=text,
                competitor=competitor,
                dimension=dimension,
                source_type=source_type,
                metadata=metadata or {},
            ),
            embedding_provider=embedding_provider,
            crawl_run_id=crawl_run_id,
        )
    finally:
        await repo.close()
