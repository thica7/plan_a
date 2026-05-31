from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy

from packages.workflows.models import (
    CREATE_RUN_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    CompetitiveIntelWorkflowInput,
    CompetitiveIntelWorkflowResult,
    RunStatus,
    WorkflowProjectionState,
    WorkflowRunState,
    WorkflowStatus,
)


@workflow.defn
class CompetitiveIntelWorkflow:
    """Temporal outer shell for one existing LangGraph competitive-intel run."""

    def __init__(self) -> None:
        self._status = "initialized"
        self._run_id: str | None = None
        self._report_version_id: str | None = None
        self._evidence_count = 0
        self._claim_count = 0

    @workflow.run
    async def run(
        self,
        request: CompetitiveIntelWorkflowInput,
    ) -> CompetitiveIntelWorkflowResult:
        self._status = "creating_run"
        created = await workflow.execute_activity(
            CREATE_RUN_ACTIVITY,
            request,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        created_state = _coerce_run_state(created)
        self._run_id = created_state.run_id
        self._status = "running_langgraph"
        executed = await workflow.execute_activity(
            RUN_LANGGRAPH_ACTIVITY,
            created_state.run_id,
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        executed_state = _coerce_run_state(executed)
        self._run_id = executed_state.run_id
        self._status = "loading_projection"
        projection = await workflow.execute_activity(
            LOAD_PROJECTION_ACTIVITY,
            executed_state.run_id,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        projection_state = _coerce_projection_state(projection)
        self._report_version_id = projection_state.report_version_id
        self._evidence_count = projection_state.evidence_count
        self._claim_count = projection_state.claim_count
        self._status = _workflow_status(executed_state.status)
        return _workflow_result(executed_state, projection_state)

    @workflow.query
    def state(self) -> dict[str, object]:
        return {
            "workflow_type": "CompetitiveIntelWorkflow",
            "status": self._status,
            "run_id": self._run_id,
            "report_version_id": self._report_version_id,
            "evidence_count": self._evidence_count,
            "claim_count": self._claim_count,
        }


def _workflow_result(
    run_state: WorkflowRunState,
    projection: WorkflowProjectionState,
) -> CompetitiveIntelWorkflowResult:
    return CompetitiveIntelWorkflowResult(
        run_id=run_state.run_id,
        idempotency_key=run_state.idempotency_key,
        status=_workflow_status(run_state.status),
        workspace_id=run_state.workspace_id,
        project_id=projection.project_id or run_state.project_id,
        report_version_id=projection.report_version_id,
        evidence_count=projection.evidence_count,
        claim_count=projection.claim_count,
        report_chars=run_state.report_chars,
        qa_finding_count=run_state.qa_finding_count,
    )


def _workflow_status(status: str) -> WorkflowStatus:
    if status == "interrupted":
        return "interrupted"
    if status == "failed":
        return "failed"
    return "completed"


def _coerce_run_state(value: WorkflowRunState | Mapping[str, object]) -> WorkflowRunState:
    if isinstance(value, WorkflowRunState):
        return value
    return WorkflowRunState(
        run_id=_text(value, "run_id"),
        idempotency_key=_text(value, "idempotency_key"),
        status=_run_status(value.get("status")),
        workspace_id=_text(value, "workspace_id"),
        project_id=_optional_text(value.get("project_id")),
        current_node=_optional_text(value.get("current_node")),
        report_chars=_int(value.get("report_chars")),
        qa_finding_count=_int(value.get("qa_finding_count")),
    )


def _coerce_projection_state(
    value: WorkflowProjectionState | Mapping[str, object],
) -> WorkflowProjectionState:
    if isinstance(value, WorkflowProjectionState):
        return value
    return WorkflowProjectionState(
        run_id=_text(value, "run_id"),
        workspace_id=_text(value, "workspace_id"),
        project_id=_optional_text(value.get("project_id")),
        report_version_id=_optional_text(value.get("report_version_id")),
        evidence_count=_int(value.get("evidence_count")),
        claim_count=_int(value.get("claim_count")),
    )


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise ValueError(f"Temporal activity payload field {key!r} must be a string.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError("Temporal activity payload optional text field must be a string or null.")


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("Temporal activity payload integer field must not be boolean.")
    if isinstance(value, int):
        return value
    raise ValueError("Temporal activity payload integer field must be an integer.")


def _run_status(value: object) -> RunStatus:
    if value in {"queued", "running", "interrupted", "completed", "failed"}:
        return cast(RunStatus, value)
    raise ValueError("Temporal activity payload status field is invalid.")
