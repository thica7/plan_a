from __future__ import annotations

from temporalio import activity

from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.workflows.models import (
    CREATE_RUN_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    CompetitiveIntelWorkflowInput,
    WorkflowProjectionState,
    WorkflowRunState,
)


class CompetitiveIntelActivities:
    def __init__(self, service: RunService) -> None:
        self._service = service

    @activity.defn(name=CREATE_RUN_ACTIVITY)
    async def create_run(self, request: CompetitiveIntelWorkflowInput) -> WorkflowRunState:
        detail = await self._service.create_run(
            RunCreateRequest(
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                idempotency_key=request.idempotency_key or None,
                topic=request.topic,
                competitors=request.competitors,
                dimensions=request.dimensions,
                competitor_layer=request.competitor_layer,
                scenario_id=request.scenario_id,
                execution_mode=request.execution_mode,
                auto_redo_warn_enabled=request.auto_redo_warn_enabled,
            )
        )
        return _run_state(detail)

    @activity.defn(name=RUN_LANGGRAPH_ACTIVITY)
    async def run_langgraph_pipeline(self, run_id: str) -> WorkflowRunState:
        detail = self._service.get_run(run_id)
        if detail is None:
            raise RuntimeError(f"Run not found: {run_id}")
        if detail.status not in {"completed", "interrupted", "failed"}:
            detail = await self._service.run_pipeline(run_id)
        if detail is None:
            raise RuntimeError(f"Run disappeared during pipeline execution: {run_id}")
        if detail.status == "failed":
            raise RuntimeError(f"Run failed during LangGraph activity: {run_id}")
        return _run_state(detail)

    @activity.defn(name=LOAD_PROJECTION_ACTIVITY)
    async def load_projection(self, run_id: str) -> WorkflowProjectionState:
        detail = self._service.get_run(run_id)
        if detail is None:
            raise RuntimeError(f"Run not found: {run_id}")
        projection = self._service.get_enterprise_projection(run_id)
        if projection is None:
            return WorkflowProjectionState(
                run_id=run_id,
                workspace_id=detail.workspace_id,
                project_id=detail.project_id,
            )
        return WorkflowProjectionState(
            run_id=run_id,
            workspace_id=projection.workspace_id,
            project_id=projection.project_id,
            report_version_id=projection.report_version.id,
            evidence_count=len(projection.evidence_records),
            claim_count=len(projection.claim_records),
        )


def _run_state(detail: RunDetail) -> WorkflowRunState:
    return WorkflowRunState(
        run_id=detail.id,
        idempotency_key=detail.idempotency_key,
        status=detail.status,
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        current_node=detail.current_node,
        report_chars=len(detail.report_md),
        qa_finding_count=len(detail.qa_findings),
    )
