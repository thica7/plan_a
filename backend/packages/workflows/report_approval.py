from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy

from packages.workflows.models import (
    APPROVE_REPORT_VERSION_ACTIVITY,
    REJECT_REPORT_VERSION_ACTIVITY,
    REQUEST_REPORT_APPROVAL_ACTIVITY,
    ReportApprovalDecision,
    ReportApprovalDecisionInput,
    ReportApprovalSignalDecision,
    ReportApprovalState,
    ReportApprovalWorkflowInput,
    ReportApprovalWorkflowResult,
    ReportVersionWorkflowStatus,
)


@dataclass
class _ApprovalSignal:
    decision: ReportApprovalSignalDecision
    approver_id: str
    note: str = ""


@workflow.defn
class ReportApprovalWorkflow:
    """Temporal approval prototype for one report version."""

    def __init__(self) -> None:
        self._decision: _ApprovalSignal | None = None

    @workflow.run
    async def run(
        self,
        request: ReportApprovalWorkflowInput,
    ) -> ReportApprovalWorkflowResult:
        requested = _coerce_approval_state(
            await workflow.execute_activity(
                REQUEST_REPORT_APPROVAL_ACTIVITY,
                request,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(seconds=request.timeout_seconds),
                timeout_summary=f"report-approval-{request.report_version_id}",
            )
        except TimeoutError:
            return _approval_result(requested, decision="timed_out")

        decision = self._decision
        if decision is None:
            return _approval_result(requested, decision="timed_out")
        activity_input = ReportApprovalDecisionInput(
            report_version_id=request.report_version_id,
            approver_id=decision.approver_id,
            note=decision.note,
        )
        if decision.decision == "approved":
            final_state = _coerce_approval_state(
                await workflow.execute_activity(
                    APPROVE_REPORT_VERSION_ACTIVITY,
                    activity_input,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )
            return _approval_result(
                final_state,
                decision="approved",
                approver_id=decision.approver_id,
                note=decision.note,
            )
        final_state = _coerce_approval_state(
            await workflow.execute_activity(
                REJECT_REPORT_VERSION_ACTIVITY,
                activity_input,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
        return _approval_result(
            final_state,
            decision="rejected",
            approver_id=decision.approver_id,
            note=decision.note,
        )

    @workflow.signal
    async def approve(self, approver_id: str, note: str = "") -> None:
        self._decision = _ApprovalSignal(
            decision="approved",
            approver_id=approver_id,
            note=note,
        )

    @workflow.signal
    async def reject(self, approver_id: str, note: str = "") -> None:
        self._decision = _ApprovalSignal(
            decision="rejected",
            approver_id=approver_id,
            note=note,
        )


def _approval_result(
    state: ReportApprovalState,
    *,
    decision: ReportApprovalDecision,
    approver_id: str | None = None,
    note: str = "",
) -> ReportApprovalWorkflowResult:
    return ReportApprovalWorkflowResult(
        report_version_id=state.report_version_id,
        workspace_id=state.workspace_id,
        project_id=state.project_id,
        decision=decision,
        final_status=state.status,
        approver_id=approver_id,
        note=note,
    )


def _coerce_approval_state(
    value: ReportApprovalState | Mapping[str, object],
) -> ReportApprovalState:
    if isinstance(value, ReportApprovalState):
        return value
    return ReportApprovalState(
        report_version_id=_text(value, "report_version_id"),
        workspace_id=_text(value, "workspace_id"),
        project_id=_text(value, "project_id"),
        status=_report_status(value.get("status")),
        approver_id=_optional_text(value.get("approver_id")),
        note=_optional_text(value.get("note")) or "",
    )


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise ValueError(f"Temporal approval payload field {key!r} must be a string.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError("Temporal approval payload optional text field must be a string or null.")


def _report_status(value: object) -> ReportVersionWorkflowStatus:
    if value in {"draft", "in_review", "approved", "published", "archived"}:
        return cast(ReportVersionWorkflowStatus, value)
    raise ValueError("Temporal approval payload status field is invalid.")
