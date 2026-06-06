"""Pydantic models for the Knowledge Base subsystem."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class KnowledgeDocument(BaseModel):
    """A crawled or ingested document stored in the knowledge base."""

    id: str
    url: str | None = None
    canonical_url: str | None = None
    title: str
    source_type: str  # webpage_verified | webpage_search | report | manual
    competitor: str | None = None
    dimension: str | None = None
    content_hash: str
    text: str
    markdown: str = ""
    metadata: dict[str, Any] = {}
    fetched_at: datetime
    indexed_at: datetime | None = None
    status: str = "active"  # active | archived | deleted
    is_active: bool = True
    version: int = 1
    parent_document_id: str | None = None


class DocumentCreate(BaseModel):
    """Payload to ingest a new document."""

    url: str | None = None
    canonical_url: str | None = None
    title: str
    source_type: str
    competitor: str | None = None
    dimension: str | None = None
    text: str
    markdown: str = ""
    metadata: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------

class KnowledgeChunk(BaseModel):
    """A text chunk vectorised and stored in Qdrant."""

    id: str
    document_id: str
    chunk_index: int
    text: str
    token_count: int
    embedding_model: str
    content_hash: str
    metadata: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class RetrievalHit(BaseModel):
    """A single result from hybrid retrieval."""

    chunk_id: str
    document_id: str
    text: str
    score: float
    rerank_score: float | None = None
    rerank_model: str | None = None
    url: str | None = None
    title: str | None = None
    competitor: str | None = None
    dimension: str | None = None
    source_type: str = ""
    content_hash: str = ""


class RetrievalRequest(BaseModel):
    query: str
    competitors: list[str] = []
    dimensions: list[str] = []
    top_k: int = 20
    rerank_top_k: int = 8
    final_top_k: int = 8
    dense_weight: float = 1.0
    sparse_weight: float = 1.0
    mmr_lambda: float = 0.0
    enable_query_rewrite: bool = True
    num_rewrites: int = 3
    mode: Literal["dense", "hybrid"] = "hybrid"


class RetrievalResponse(BaseModel):
    hits: list[RetrievalHit]
    query: str
    total: int


# ---------------------------------------------------------------------------
# Citation (for analyst sub-agents)
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    """A citation attached to an analyst output."""

    chunk_id: str
    document_id: str
    url: str | None = None
    title: str
    text_snippet: str
    score: float
