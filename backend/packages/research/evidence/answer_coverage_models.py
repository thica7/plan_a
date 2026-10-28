"""Request coverage records; questions are never treated as source facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer


class DecisionCredential(BaseModel):
    """Transport receipt only; consumers reconstruct its current authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_ref: str
    question_id: str
    task_id: str
    claim_id: str
    witness_kind: Literal["quantity_excess", "resource_non_entailment"]
    conclusion: Literal["no"]
    evidence_refs: tuple[str, ...]
    scenario_refs: tuple[str, ...]
    binding_sha256: str
    answer_span_id: str
    answer_input_sha256: str
    answer_output_sha256: str


class AnswerEvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=600)


class AnswerSubquestionBinding(BaseModel):
    """A reviewed decision tied to an exact request part and whole published premises."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    question_quote: str = Field(min_length=1, max_length=1000)
    claim_ids: tuple[str, ...] = Field(default=(), max_length=8)
    conclusion: Literal["yes", "no", "depends", "unknown", "not_applicable"]
    relation: Literal["direct", "explicit_negative", "upper_bound", "resource_scope",
                      "permission_entailment", "destructive_effect", "unresolved"]
    support_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


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
    binding_version: Literal[2, 3] | None = None
    subquestion_bindings: tuple[AnswerSubquestionBinding, ...] = Field(default=(), max_length=8)
    decision_credentials: tuple[DecisionCredential, ...] | None = Field(default=None, max_length=8)

    @field_validator('binding_version', mode='before')
    @classmethod
    def exact_binding_version(cls, value):
        if value is not None and (type(value) is not int or value not in (2, 3)):
            raise ValueError('unsupported exact integer answer binding version')
        return value

    @model_serializer(mode="wrap")
    def serialize_legacy_defaults(self, handler):
        result = handler(self)
        for key, default in (("answer", ""), ("resolution", "unresolved"), ("conclusion", "unknown"),
                             ("evidence_spans", ()), ("missing_fields", ()), ("basis_snapshot_id", None),
                             ("binding_version", None), ("subquestion_bindings", ())):
            if getattr(self, key) == default:
                result.pop(key, None)
        if self.decision_credentials is None:
            result.pop('decision_credentials', None)
        return result
