from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RunEventType = Literal[
    "run_created",
    "node_started",
    "node_completed",
    "interrupt",
    "qa_issue",
    "report_updated",
    "revision_recorded",
    "run_completed",
    "run_failed",
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "self_consistency.sampled",
    "memory.recalled",
    "memory.feedback_captured",
    "hitl.reviewed",
    "claim.validated",
    "qa.blocked",
    "redo.routed",
    "benchmark.scored",
    "report.ready",
    "runtime.command",
    "writer_preflight",
    "writer_segment_preflight",
    "writer_segment_validated",
    "writer_assembly_completed",
    "writer_assemble_repair_completed",
    "writer_quality_preflight",
    "writer_quality_preflight_repair",
    "writer_structured_repair_selected",
    "writer_structured_section_started",
    "writer_structured_section_completed",
    "writer_structured_section_failed",
    "writer_structured_report_validated",
    "writer_publication_contract_validated",
    "writer_publication_contract_repair_selected",
    "writer_publication_contract_repaired",
    "writer_recommendation_delta_checked",
    "writer_structured_repair_failed_preserved_previous",
    "writer_schema_first_failed_closed",
    "writer_markdown_fallback_used",
    "writer_unified_quality_result_recorded",
]


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    run_id: str
    trace_id: str = ""
    type: RunEventType
    agent: str | None = None
    subagent: str | None = None
    swimlane: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_sse(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "event": self.type,
            "data": self.model_dump_json(),
        }
