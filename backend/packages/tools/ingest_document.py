"""LangGraph tool for ingesting one knowledge document."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import tool

from ..knowledge.embeddings import get_embedding_provider_from_env
from ..knowledge.ingestion import IngestionPipeline
from ..knowledge.models import DocumentCreate, KnowledgeScope, SourceRole
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


async def ingest_document_reference(
    url: str,
    title: str,
    text: str,
    competitor: str,
    dimension: str,
    source_type: str,
    metadata: dict[str, Any] | None = None,
    crawl_run_id: str | None = None,
    index_vectors: bool = True,
    workspace_id: str | None = None,
    project_id: str | None = None,
    market: str | None = None,
    source_role: SourceRole = "source",
    fetched_at: datetime | None = None,
    source_published_at: datetime | None = None,
    source_updated_at: datetime | None = None,
    last_verified_at: datetime | None = None,
    markdown: str = "",
) -> dict[str, object]:
    """Internal trusted-caller ingestion returning provenance without the body."""
    if workspace_id is None:
        raise ValueError("Trusted workspace_id is required for knowledge ingestion")
    scope = KnowledgeScope(workspace_id=workspace_id, project_id=project_id)
    repo = KnowledgeRepository()
    await repo.initialise()
    try:
        embedding_provider = get_embedding_provider_from_env() if index_vectors else None
        pipeline = IngestionPipeline(
            repo=repo,
            vector_store=_vector_store_for_ingest(embedding_provider is not None),
        )
        document_id = await pipeline.ingest(
            DocumentCreate(
                url=url,
                title=title,
                text=text,
                competitor=competitor,
                dimension=dimension,
                source_type=source_type,
                metadata=metadata or {},
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                market=market,
                source_role=source_role,
                fetched_at=fetched_at,
                source_published_at=source_published_at,
                source_updated_at=source_updated_at,
                last_verified_at=last_verified_at,
                markdown=markdown,
            ),
            embedding_provider=embedding_provider,
            crawl_run_id=crawl_run_id,
        )
        stored = await repo.get_document(document_id, scope=scope)
        if stored is None:
            raise RuntimeError("Ingested document is missing from its trusted scope")
        return {
            "document_id": stored.id,
            "workspace_id": stored.workspace_id,
            "project_id": stored.project_id,
            "document_version": stored.version,
            "content_hash": stored.content_hash,
            "fetched_at": stored.fetched_at.isoformat(),
            "source_published_at": (
                stored.source_published_at.isoformat() if stored.source_published_at else None
            ),
            "source_updated_at": (
                stored.source_updated_at.isoformat() if stored.source_updated_at else None
            ),
            "last_verified_at": (
                stored.last_verified_at.isoformat() if stored.last_verified_at else None
            ),
        }
    finally:
        await repo.close()


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
    workspace_id: str | None = None,
    project_id: str | None = None,
    market: str | None = None,
    source_role: SourceRole = "source",
    fetched_at: datetime | None = None,
    source_published_at: datetime | None = None,
    source_updated_at: datetime | None = None,
    last_verified_at: datetime | None = None,
    markdown: str = "",
) -> str:
    """Ingest a document in a server-supplied scope and return its document ID."""
    reference = await ingest_document_reference(
        url=url,
        title=title,
        text=text,
        competitor=competitor,
        dimension=dimension,
        source_type=source_type,
        metadata=metadata,
        crawl_run_id=crawl_run_id,
        index_vectors=index_vectors,
        workspace_id=workspace_id,
        project_id=project_id,
        market=market,
        source_role=source_role,
        fetched_at=fetched_at,
        source_published_at=source_published_at,
        source_updated_at=source_updated_at,
        last_verified_at=last_verified_at,
        markdown=markdown,
    )
    return str(reference["document_id"])
