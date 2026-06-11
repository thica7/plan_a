from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.hitl import HitlLifecycleEvent
from packages.schema.models import (
    AgentMessage,
    AnalysisPlan,
    ComparisonMatrix,
    CompetitorKnowledge,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    ToolCallMessage,
)
from packages.schema.survey import SurveyEvidenceBundle


class _MessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisPlanMessagePayload(_MessagePayload):
    plan: AnalysisPlan
    planner: dict[str, Any] = Field(default_factory=dict)
    mode: str | None = None


class DispatchPlanMessagePayload(_MessagePayload):
    topic: str
    dimensions: list[str]
    competitors: list[str]
    branch_count: int = Field(ge=0)
    fanout: str
    source_ids: list[str] = Field(default_factory=list)


class CollectTaskMessagePayload(_MessagePayload):
    dimension: str
    topic: str | None = None
    competitor: str | None = None
    competitors: list[str] = Field(default_factory=list)
    homepage_hint: str | None = None
    homepage_hints: dict[str, str] = Field(default_factory=dict)
    required_output_schema: str | None = None
    qa_feedback: list[dict[str, Any]] = Field(default_factory=list)
    mode: str | None = None
    task_id: str | None = None
    task_priority: Literal["low", "medium", "high"] | None = None
    task_max_turns: int | None = Field(default=None, ge=1, le=6)
    task_reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class RawSourceCollectionMessagePayload(_MessagePayload):
    dimension: str
    competitor: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    sources: list[RawSource] = Field(default_factory=list)
    covered_competitors: list[str] = Field(default_factory=list)
    count: int | None = Field(default=None, ge=0)
    source_count: int | None = Field(default=None, ge=0)
    retrieval_stage: str | None = None
    message_id: str | None = None


class RawSourceDigestMessagePayload(_MessagePayload):
    dimensions: list[str]
    source_ids: list[str] = Field(default_factory=list)
    before_count: int | None = Field(default=None, ge=0)
    after_count: int | None = Field(default=None, ge=0)


class QCIssueCollectionMessagePayload(_MessagePayload):
    qa_findings: list[QCIssue] = Field(default_factory=list)
    phase: str | None = None
    mode: str | None = None


class AnalysisTaskMessagePayload(_MessagePayload):
    competitor: str
    dimension: str
    source_ids: list[str] = Field(default_factory=list)
    qa_feedback: list[dict[str, Any]] = Field(default_factory=list)
    task_id: str | None = None
    task_priority: Literal["low", "medium", "high"] | None = None
    task_max_turns: int | None = Field(default=None, ge=1, le=6)
    task_reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class KBCacheEntryMessagePayload(_MessagePayload):
    competitor: str
    dimension: str
    content_hash: str
    source_ids: list[str] = Field(default_factory=list)


class CompetitorKnowledgeMessagePayload(_MessagePayload):
    competitor: str
    dimension: str | None = None
    knowledge: CompetitorKnowledge | dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    mode: str | None = None


class CompetitorKBDigestMessagePayload(_MessagePayload):
    dimensions: list[str]
    competitors: list[str]
    kb_summary: dict[str, Any] = Field(default_factory=dict)
    competitor_knowledge_count: int = Field(ge=0)


class ComparisonMatrixMessagePayload(_MessagePayload):
    comparison_matrix: ComparisonMatrix


class ReflectionRecordMessagePayload(_MessagePayload):
    reflection: ReflectionRecord


class MarkdownReportMessagePayload(_MessagePayload):
    report_md: str
    writer_mode: str = ""
    writer_repair_mode: Literal["none", "line", "section", "full"] = "none"
    writer_repair_sections: list[str] = Field(default_factory=list)
    writer_repair_decision: str = ""
    anti_regression_reason: str | None = None
    previous_report_protected: bool = False
    error: str | None = None


class RedoRequestMessagePayload(_MessagePayload):
    redo_scope: RedoScope
    issues: list[QCIssue] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)
    routing: str | None = None


class ToolErrorMessagePayload(_MessagePayload):
    error: str
    dimension: str | None = None
    query: str | None = None
    degraded: bool = False


class HitlMemoryFeedbackMessagePayload(_MessagePayload):
    feedback_id: str
    feedback_type: str
    target_type: str
    target_id: str
    decision: str
    has_note: bool
    dimensions: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    candidate_count: int = Field(ge=0)


class HitlLifecycleMessagePayload(_MessagePayload):
    hitl_lifecycle: HitlLifecycleEvent


class SurveyEvidenceBundleCollectionMessagePayload(_MessagePayload):
    bundles: list[SurveyEvidenceBundle] = Field(default_factory=list)
    reason: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


AGENT_MESSAGE_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "AnalysisPlan": AnalysisPlanMessagePayload,
    "AnalystDispatchPlan": DispatchPlanMessagePayload,
    "AnalysisTaskPayload": AnalysisTaskMessagePayload,
    "CollectTaskPayload": CollectTaskMessagePayload,
    "CollectorDispatchPlan": DispatchPlanMessagePayload,
    "CompetitorKBDigest": CompetitorKBDigestMessagePayload,
    "CompetitorKnowledge": CompetitorKnowledgeMessagePayload,
    "ComparisonMatrix": ComparisonMatrixMessagePayload,
    "HitlLifecyclePayload": HitlLifecycleMessagePayload,
    "HitlMemoryFeedbackPayload": HitlMemoryFeedbackMessagePayload,
    "KBCacheEntry": KBCacheEntryMessagePayload,
    "MarkdownReport": MarkdownReportMessagePayload,
    "QCIssue[]": QCIssueCollectionMessagePayload,
    "RawSource[]": RawSourceCollectionMessagePayload,
    "RawSourceDigest": RawSourceDigestMessagePayload,
    "RedoRequestPayload": RedoRequestMessagePayload,
    "ReflectionRecord": ReflectionRecordMessagePayload,
    "SurveyEvidenceBundle[]": SurveyEvidenceBundleCollectionMessagePayload,
    "ToolError": ToolErrorMessagePayload,
}


def validate_agent_message_payload(
    payload_schema: str,
    payload: Mapping[str, Any] | None,
) -> None:
    schema_model = AGENT_MESSAGE_PAYLOAD_SCHEMAS.get(payload_schema)
    if schema_model is None:
        raise ValueError(f"agent_message.payload_schema.unregistered: {payload_schema}")
    try:
        schema_model.model_validate(dict(payload or {}))
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first_error.get("loc", ())) or "<root>"
        message = first_error.get("msg", "payload validation failed")
        raise ValueError(
            f"agent_message.payload_schema.invalid: {payload_schema}.{location}: {message}"
        ) from exc


__all__ = [
    "AGENT_MESSAGE_PAYLOAD_SCHEMAS",
    "AgentMessage",
    "ToolCallMessage",
    "validate_agent_message_payload",
]
