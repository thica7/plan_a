from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from packages.workflows.models import (
    CREATE_RUN_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    CompetitiveIntelWorkflowInput,
    CompetitiveIntelWorkflowResult,
    WorkflowProjectionState,
    WorkflowRunState,
    WorkflowStatus,
)


@workflow.defn
class CompetitiveIntelWorkflow:
    """Temporal outer shell for one existing LangGraph competitive-intel run."""

    @workflow.run
    async def run(
        self,
        request: CompetitiveIntelWorkflowInput,
    ) -> CompetitiveIntelWorkflowResult:
        created = await workflow.execute_activity(
            CREATE_RUN_ACTIVITY,
            request,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        executed = await workflow.execute_activity(
            RUN_LANGGRAPH_ACTIVITY,
            created.run_id,
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        projection = await workflow.execute_activity(
            LOAD_PROJECTION_ACTIVITY,
            executed.run_id,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return _workflow_result(executed, projection)


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
