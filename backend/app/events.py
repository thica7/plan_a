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
