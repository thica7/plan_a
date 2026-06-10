"""Pydantic models for the Knowledge Base subsystem."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    last_seen_at: datetime | None = None
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
    crawl_run_id: str | None = None
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
    query: str = Field(min_length=1, max_length=2_000)
    preset: str | None = None
    competitors: list[str] = Field(default_factory=list, max_length=50)
    dimensions: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=20, ge=1, le=100)
    rerank_top_k: int = Field(default=8, ge=0, le=100)
    final_top_k: int = Field(default=8, ge=1, le=100)
    dense_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    sparse_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default=0.0, ge=0.0, le=1.0)
    enable_query_rewrite: bool = True
    num_rewrites: int = Field(default=3, ge=0, le=5)
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
