from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RetrievalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    score: float = Field(ge=-1.0, le=1.0)
    title: str
    source_type: str
    dimension: str
    snippet: str = ""


class GapRetrievalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str
    query: str
    candidate_ids: list[str] = Field(default_factory=list)
    records: list[RetrievalRecord] = Field(default_factory=list)
    grounded_context: str = ""
