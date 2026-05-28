from __future__ import annotations

from temporalio import activity

from packages.enterprise import EnterpriseStore
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import ReportVersionRecord
from packages.workflows.models import (
    APPROVE_REPORT_VERSION_ACTIVITY,
    CREATE_RUN_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    REJECT_REPORT_VERSION_ACTIVITY,
    REQUEST_REPORT_APPROVAL_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    CompetitiveIntelWorkflowInput,
    ReportApprovalDecisionInput,
    ReportApprovalState,
    ReportApprovalWorkflowInput,
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


class ReportApprovalActivities:
    def __init__(self, store: EnterpriseStore) -> None:
        self._store = store

    @activity.defn(name=REQUEST_REPORT_APPROVAL_ACTIVITY)
    async def request_report_approval(
        self,
        request: ReportApprovalWorkflowInput,
    ) -> ReportApprovalState:
        version = self._require_report_version(request.report_version_id)
        updated = version.model_copy(update={"status": "in_review"})
        return _approval_state(self._store.upsert_report_version(updated))

    @activity.defn(name=APPROVE_REPORT_VERSION_ACTIVITY)
    async def approve_report_version(
        self,
        decision: ReportApprovalDecisionInput,
    ) -> ReportApprovalState:
        version = self._require_report_version(decision.report_version_id)
        updated = version.model_copy(update={"status": "approved"})
        return _approval_state(
            self._store.upsert_report_version(updated),
            approver_id=decision.approver_id,
            note=decision.note,
        )

    @activity.defn(name=REJECT_REPORT_VERSION_ACTIVITY)
    async def reject_report_version(
        self,
        decision: ReportApprovalDecisionInput,
    ) -> ReportApprovalState:
        version = self._require_report_version(decision.report_version_id)
        updated = version.model_copy(update={"status": "draft"})
        return _approval_state(
            self._store.upsert_report_version(updated),
            approver_id=decision.approver_id,
            note=decision.note,
        )

    def _require_report_version(self, report_version_id: str) -> ReportVersionRecord:
        version = self._store.get_report_version(report_version_id)
        if version is None:
            raise RuntimeError(f"Report version not found: {report_version_id}")
        return version


def _approval_state(
    version: ReportVersionRecord,
    *,
    approver_id: str | None = None,
    note: str = "",
) -> ReportApprovalState:
    return ReportApprovalState(
        report_version_id=version.id,
        workspace_id=version.workspace_id,
        project_id=version.project_id,
        status=version.status,
        approver_id=approver_id,
        note=note,
    )
