from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from packages.hitl import (
    HitlLifecycleStage,
    HitlReviewKind,
    append_hitl_lifecycle,
    build_hitl_lifecycle_event,
    hitl_lifecycle_history,
)
from packages.schema.enterprise import ReportReleaseGate, ReportVersionRecord

ApprovalDecision = Literal["approved", "rejected"]


def mark_report_approval_requested(
    version: ReportVersionRecord,
    *,
    requested_by: str,
    approver_ids: list[str],
    requested_at: datetime | None = None,
) -> ReportVersionRecord:
    requested_at = requested_at or datetime.utcnow()
    metadata = _metadata_with_lifecycle_event(
        version,
        {
            "event": "approval_requested",
            "actor_id": requested_by,
            "created_at": requested_at.isoformat(),
            "approver_ids": approver_ids,
        },
    )
    metadata = _metadata_with_hitl_lifecycle_event(
        metadata,
        version,
        lifecycle_stage="requested",
        review_kind="report_approval",
        stage="report_approval",
        decision="pending",
        actor_id=requested_by,
        target_type="report_version",
        target_id=version.id,
        result_action="await_approval_decision",
        created_at=requested_at,
        event_metadata={"approver_ids": approver_ids},
    )
    metadata["approval_workflow"] = {
        **_dict_metadata(metadata.get("approval_workflow")),
        "status": "in_review",
        "requested_by": requested_by,
        "requested_at": requested_at.isoformat(),
        "approver_ids": approver_ids,
        "decision": "pending",
    }
    return version.model_copy(update={"status": "in_review", "quality_metadata": metadata})


def mark_report_approval_decision(
    version: ReportVersionRecord,
    *,
    decision: ApprovalDecision,
    approver_id: str,
    note: str,
    gate: ReportReleaseGate | None = None,
    decided_at: datetime | None = None,
) -> ReportVersionRecord:
    decided_at = decided_at or datetime.utcnow()
    gate_snapshot = report_release_gate_snapshot(gate)
    metadata = _metadata_with_lifecycle_event(
        version,
        {
            "event": f"approval_{decision}",
            "actor_id": approver_id,
            "created_at": decided_at.isoformat(),
            "note": note,
            "release_gate": gate_snapshot,
        },
    )
    metadata = _metadata_with_hitl_lifecycle_event(
        metadata,
        version,
        lifecycle_stage="approved" if decision == "approved" else "rejected",
        review_kind="report_approval",
        stage="report_approval",
        decision=decision,
        actor_id=approver_id,
        target_type="report_version",
        target_id=version.id,
        result_action="approval_decision_recorded",
        note=note,
        created_at=decided_at,
        event_metadata={"release_gate": gate_snapshot},
    )
    metadata["approval_workflow"] = {
        **_dict_metadata(metadata.get("approval_workflow")),
        "status": decision,
        "decision": decision,
        "decided_by": approver_id,
        "decided_at": decided_at.isoformat(),
        "note": note,
        "release_gate": gate_snapshot,
    }
    return version.model_copy(update={"status": decision, "quality_metadata": metadata})


def mark_report_published(
    version: ReportVersionRecord,
    *,
    actor_id: str,
    gate: ReportReleaseGate,
    published_at: datetime | None = None,
) -> ReportVersionRecord:
    published_at = published_at or datetime.utcnow()
    gate_snapshot = report_release_gate_snapshot(gate)
    metadata = _metadata_with_lifecycle_event(
        version,
        {
            "event": "published",
            "actor_id": actor_id,
            "created_at": published_at.isoformat(),
            "release_gate": gate_snapshot,
        },
    )
    metadata = _metadata_with_hitl_lifecycle_event(
        metadata,
        version,
        lifecycle_stage="published",
        review_kind="report_publication",
        stage="report_publication",
        decision="published",
        actor_id=actor_id,
        target_type="report_version",
        target_id=version.id,
        result_action="report_published",
        created_at=published_at,
        event_metadata={"release_gate": gate_snapshot},
    )
    metadata["publication"] = {
        "status": "published",
        "published_by": actor_id,
        "published_at": published_at.isoformat(),
        "release_gate": gate_snapshot,
    }
    return version.model_copy(
        update={
            "status": "published",
            "published_at": published_at,
            "quality_metadata": metadata,
        }
    )


def report_transition_audit_after(
    version: ReportVersionRecord,
    *,
    transition: str,
    actor_id: str | None,
    note: str = "",
    gate: ReportReleaseGate | None = None,
) -> dict[str, Any]:
    return {
        "transition": transition,
        "actor_id": actor_id,
        "note": note,
        "report_version_id": version.id,
        "project_id": version.project_id,
        "run_id": version.run_id,
        "version_number": version.version_number,
        "status": version.status,
        "release_gate": report_release_gate_snapshot(gate),
    }


def report_release_gate_snapshot(gate: ReportReleaseGate | None) -> dict[str, Any]:
    if gate is None:
        return {}
    return {
        "allowed": gate.allowed,
        "status": gate.status,
        "readiness_score": gate.readiness.score,
        "readiness_risk_level": gate.readiness.risk_level,
        "issue_count": gate.issue_count,
        "blocker_count": gate.blocker_count,
        "warn_count": gate.warn_count,
        "issue_ids": [issue.id for issue in gate.issues],
    }


def _metadata_with_lifecycle_event(
    version: ReportVersionRecord,
    event: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(version.quality_metadata)
    history = metadata.get("report_lifecycle")
    metadata["report_lifecycle"] = [
        *(history if isinstance(history, list) else []),
        event,
    ]
    return metadata


def _metadata_with_hitl_lifecycle_event(
    report_metadata: dict[str, Any],
    version: ReportVersionRecord,
    *,
    lifecycle_stage: HitlLifecycleStage,
    review_kind: HitlReviewKind,
    stage: str,
    decision: str,
    actor_id: str | None,
    target_type: str,
    target_id: str,
    result_action: str,
    note: str = "",
    created_at: datetime,
    event_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_hitl_lifecycle_event(
        lifecycle_stage=lifecycle_stage,
        review_kind=review_kind,
        stage=stage,
        decision=decision,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        run_id=version.run_id,
        report_version_id=version.id,
        result_action=result_action,
        note=note,
        metadata=event_metadata,
        created_at=created_at,
        sequence=len(hitl_lifecycle_history(report_metadata)) + 1,
    )
    return append_hitl_lifecycle(report_metadata, event)


def _dict_metadata(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
