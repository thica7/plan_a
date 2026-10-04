"""Pydantic models for the Knowledge Base subsystem."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SourceRole = Literal["source", "historical_report"]
KnowledgeNamespace = tuple[str | None, str | None, str | None, str | None, str | None, str | None]


class KnowledgeScope(BaseModel):
    """Trusted workspace and project boundary; None project selects its public library."""

    workspace_id: str = Field(min_length=1)
    project_id: str | None = None
    include_workspace_library: bool = False

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace_id must be nonempty")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("project_id must be nonempty or None for the workspace library")
        return value


class _ScopedContext(BaseModel):
    workspace_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = None

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("workspace_id must be nonempty")
        return value

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("project_id must be nonempty or None for the workspace library")
        return value

    @property
    def scope(self) -> KnowledgeScope | None:
        if self.workspace_id is None:
            return None
        return KnowledgeScope(workspace_id=self.workspace_id, project_id=self.project_id)


class _SourceContext(_ScopedContext):
    market: str | None = None
    source_role: SourceRole = "source"
    source_published_at: datetime | None = None
    source_updated_at: datetime | None = None
    last_verified_at: datetime | None = None

    @model_validator(mode="after")
    def classify_report(self):
        if self.source_type == "report":
            self.source_role = "historical_report"
        return self

    @property
    def namespace(self) -> KnowledgeNamespace:
        if self.workspace_id is None:
            return (None, None, None, None, None, None)
        return (self.workspace_id, self.project_id, self.competitor,
                self.dimension, self.market, self.source_role)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class KnowledgeDocument(_SourceContext):
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
    indexing_status: Literal["pending", "ready", "failed"] = "pending"
    indexing_error: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    index_version: str | None = None


class KnowledgeRollbackResult(BaseModel):
    """Result for rolling back polluted knowledge documents."""

    matched_count: int = 0
    rolled_back_count: int = 0
    restored_count: int = 0
    archived_document_ids: list[str] = Field(default_factory=list)
    restored_document_ids: list[str] = Field(default_factory=list)
    skipped_document_ids: list[str] = Field(default_factory=list)
    vector_cleanup_error: str | None = None


class DocumentCreate(_SourceContext):
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
    fetched_at: datetime | None = None


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


class RetrievalHit(_SourceContext):
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
    document_version: int = 1
    content_hash: str = ""
    fetched_at: datetime | None = None
    last_seen_at: datetime | None = None
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalIntent(BaseModel):
    """Caller-declared facts and presentation preferences, without scope authority."""

    model_config = {"extra": "forbid"}

    fact_queries: list[str] = Field(min_length=1, max_length=5)
    required_terms: list[str] = Field(default_factory=list, max_length=10)
    output_language: str | None = Field(default=None, max_length=40)
    require_citations: bool = False

    @field_validator("fact_queries", "required_terms")
    @classmethod
    def validate_terms(cls, values: list[str], info) -> list[str]:
        limit = 500 if info.field_name == "fact_queries" else 80
        if any(not value.strip() or len(value) > limit for value in values):
            raise ValueError(
                f"{info.field_name} entries must be nonblank and at most {limit} characters"
            )
        return values


class RetrievalRequest(_ScopedContext):
    include_workspace_library: bool = False
    market: str | None = None
    source_roles: list[SourceRole] = Field(default_factory=list, max_length=2)
    max_age_days: int | None = Field(default=None, ge=0)

    @property
    def scope(self) -> KnowledgeScope | None:
        scope = super().scope
        if scope is not None:
            scope.include_workspace_library = self.include_workspace_library
        return scope

    query: str = Field(min_length=1, max_length=2_000)
    intent_policy: Literal["raw", "structured"] = "structured"
    retrieval_intent: RetrievalIntent | None = None
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
    mode: Literal["dense", "hybrid", "sparse"] = "hybrid"

    @model_validator(mode="after")
    def validate_intent_policy(self):
        if self.intent_policy == "raw" and self.retrieval_intent is not None:
            raise ValueError("raw intent_policy cannot include retrieval_intent")
        return self


class RetrievalResponse(BaseModel):
    hits: list[RetrievalHit]
    query: str
    total: int
    diagnostics: dict[str, Any] = Field(default_factory=dict)


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
