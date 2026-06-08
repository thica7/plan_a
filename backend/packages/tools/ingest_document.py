"""LangGraph tool for ingesting one knowledge document."""

from __future__ import annotations

from langchain_core.tools import tool

from ..knowledge.embeddings import get_embedding_provider_from_env
from ..knowledge.ingestion import IngestionPipeline
from ..knowledge.models import DocumentCreate
from ..knowledge.repository import KnowledgeRepository
from ..knowledge.vector_store import VectorStore


@tool
async def ingest_document_tool(
    url: str,
    title: str,
    text: str,
    competitor: str,
    dimension: str,
    source_type: str,
) -> str:
    """Ingest a document into the knowledge base and return its document ID."""
    repo = KnowledgeRepository()
    await repo.initialise()
    try:
        pipeline = IngestionPipeline(repo=repo, vector_store=VectorStore())
        embedding_provider = get_embedding_provider_from_env()
        return await pipeline.ingest(
            DocumentCreate(
                url=url,
                title=title,
                text=text,
                competitor=competitor,
                dimension=dimension,
                source_type=source_type,
            ),
            embedding_provider=embedding_provider,
        )
    finally:
        await repo.close()
