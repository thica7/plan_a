"""Request coverage records; questions are never treated as source facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportAnswerCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    status: Literal["answered", "partial", "unanswered", "unverified"]
    claim_ids: tuple[str, ...] = Field(default=(), max_length=8)
    reason: str = Field(min_length=1, max_length=800)
