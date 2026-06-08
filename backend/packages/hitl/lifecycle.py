from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.identity import stable_prefixed_id

HitlLifecycleStage = Literal[
    "requested",
    "accepted",
    "modified",
    "rejected",
    "timed_out",
    "resumed",
    "redo_requested",
    "revision_created",
    "approved",
    "published",
]

HitlReviewKind = Literal[
    "planner_review",
    "qa_review",
    "manual_redo",
    "manual_report_revision",
    "report_approval",
    "report_publication",
]


class HitlLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    lifecycle_stage: HitlLifecycleStage
    review_kind: HitlReviewKind
    stage: str | None = None
    decision: str = ""
    actor_id: str | None = None
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=240)
    run_id: str | None = None
    report_version_id: str | None = None
    redo_scope: dict[str, Any] | None = None
    audit_log_id: str | None = None
    decision_replay_event_id: str | None = None
    result_action: str = ""
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


def build_hitl_lifecycle_event(
    *,
    lifecycle_stage: HitlLifecycleStage,
    review_kind: HitlReviewKind,
    target_type: str,
    target_id: str,
    stage: str | None = None,
    decision: str = "",
    actor_id: str | None = None,
    run_id: str | None = None,
    report_version_id: str | None = None,
    redo_scope: dict[str, Any] | None = None,
    audit_log_id: str | None = None,
    decision_replay_event_id: str | None = None,
    result_action: str = "",
    note: str = "",
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    sequence: int | str | None = None,
) -> HitlLifecycleEvent:
    created_at = created_at or datetime.utcnow()
    anchor_id = run_id or report_version_id or target_id
    event_sequence = sequence if sequence is not None else created_at.isoformat()
    event_id = stable_prefixed_id(
        "hitl-life",
        anchor_id,
        review_kind,
        lifecycle_stage,
        decision,
        target_type,
        target_id,
        event_sequence,
        length=16,
    )
    return HitlLifecycleEvent(
        id=event_id,
        lifecycle_stage=lifecycle_stage,
        review_kind=review_kind,
        stage=stage,
        decision=decision,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        run_id=run_id,
        report_version_id=report_version_id,
        redo_scope=redo_scope,
        audit_log_id=audit_log_id,
        decision_replay_event_id=decision_replay_event_id,
        result_action=result_action,
        note=note,
        metadata=metadata or {},
        created_at=created_at,
    )


def append_hitl_lifecycle(
    metadata: dict[str, Any],
    event: HitlLifecycleEvent,
) -> dict[str, Any]:
    updated = dict(metadata)
    updated["hitl_lifecycle"] = [
        *hitl_lifecycle_history(updated),
        event.model_dump(mode="json"),
    ]
    return updated


def hitl_lifecycle_history(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []
    history = metadata.get("hitl_lifecycle")
    if not isinstance(history, list):
        return []
    return [dict(item) for item in history if isinstance(item, dict)]


def review_kind_for_stage(stage: str) -> HitlReviewKind:
    key = stage.casefold()
    if key == "planner":
        return "planner_review"
    if key == "qa":
        return "qa_review"
    return "manual_redo"


def lifecycle_stage_for_resume_decision(
    decision: str,
    *,
    note: str | None = None,
) -> HitlLifecycleStage:
    if (note or "").startswith("Auto-accepted after HITL timeout"):
        return "timed_out"
    if decision == "modify_plan":
        return "modified"
    if decision == "redo":
        return "redo_requested"
    return "accepted"
