from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


def _dict_metadata(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
