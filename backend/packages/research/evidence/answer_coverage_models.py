"""Request coverage records; questions are never treated as source facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class AnswerEvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=600)


class ReportAnswerCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    status: Literal["answered", "partial", "unanswered", "unverified"]
    claim_ids: tuple[str, ...] = Field(default=(), max_length=8)
    reason: str = Field(min_length=1, max_length=800)
    answer: str = Field(default="", max_length=1200)
    resolution: Literal["direct", "conditional", "clarification", "insufficient", "unresolved"] = "unresolved"
    conclusion: Literal["yes", "no", "depends", "unknown", "not_applicable"] = "unknown"
    evidence_spans: tuple[AnswerEvidenceSpan, ...] = Field(default=(), max_length=8)
    missing_fields: tuple[str, ...] = Field(default=(), max_length=16)
    basis_snapshot_id: str | None = Field(default=None, max_length=120)
    binding_version: Literal[2] | None = None

    @model_serializer(mode="wrap")
    def serialize_legacy_defaults(self, handler):
        result = handler(self)
        for key, default in (("answer", ""), ("resolution", "unresolved"), ("conclusion", "unknown"),
                             ("evidence_spans", ()), ("missing_fields", ()), ("basis_snapshot_id", None),
                             ("binding_version", None)):
            if getattr(self, key) == default:
                result.pop(key, None)
        return result
