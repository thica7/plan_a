from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RetrievalChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    evidence_id: str
    chunk_index: int = Field(ge=0)
    title: str
    source_type: str
    dimension: str
    text: str
    source_url: str = ""


class RetrievalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    chunk_id: str = ""
    chunk_index: int = Field(default=0, ge=0)
    score: float = Field(ge=-1.0, le=1.0)
    vector_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    bm25_score: float = Field(default=0.0, ge=0.0)
    rerank_score: float = Field(default=0.0, ge=0.0, le=1.0)
    title: str
    source_type: str
    dimension: str
    snippet: str = ""
    source_url: str = ""
    retrieval_stage: str = "hybrid_rerank"


class GapRetrievalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str
    query: str
    rewritten_queries: list[str] = Field(default_factory=list)
    candidate_chunk_count: int = Field(default=0, ge=0)
    unique_evidence_candidate_count: int = Field(default=0, ge=0)
    dedupe_drop_count: int = Field(default=0, ge=0)
    candidate_ids: list[str] = Field(default_factory=list)
    records: list[RetrievalRecord] = Field(default_factory=list)
    grounded_context: str = ""
