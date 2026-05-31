from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError

from packages.config import Settings
from packages.schema.api_dto import (
    MonitorStartRequest,
    MonitorStartResponse,
    ReportApprovalSignalRequest,
    ReportApprovalSignalResponse,
    ReportApprovalStartRequest,
    ReportApprovalStartResponse,
    RunCreateRequest,
    ScheduledScanStartRequest,
    ScheduledScanStartResponse,
    WorkflowStartResponse,
    WorkflowStateResponse,
)
from packages.workflows.client import workflow_id_for_request
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.models import (
    CompetitiveIntelWorkflowInput,
    MonitorWorkflowInput,
    ReportApprovalSignalDecision,
    ReportApprovalWorkflowInput,
    ScheduledScanWorkflowInput,
)
from packages.workflows.monitor import MonitorWorkflow
from packages.workflows.report_approval import ReportApprovalWorkflow
from packages.workflows.scheduled_scan import ScheduledScanWorkflow


class TemporalClient(Protocol):
    async def start_workflow(
        self,
        workflow: object,
        arg: object,
        *,
        id: str,
        task_queue: str,
        cron_schedule: str | None = None,
    ) -> WorkflowHandle: ...

    def get_workflow_handle(self, workflow_id: str) -> WorkflowHandle: ...


TemporalClientFactory = Callable[[Settings], Awaitable[TemporalClient]]


@dataclass(frozen=True)
class TemporalCutoverDecision:
    route: Literal["langgraph", "temporal"]
    target_percent: int
    bucket: int
    reason: str


class TemporalWorkflowService:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: TemporalClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or _connect_temporal_client

    async def start_competitive_intel(
        self,
        request: RunCreateRequest,
    ) -> WorkflowStartResponse:
        workflow_input = competitive_intel_input_from_run_request(request)
        workflow_id = workflow_id_for_request(workflow_input)
        client = await self._client_factory(self._settings)
        try:
            await client.start_workflow(
                CompetitiveIntelWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=self._settings.temporal_task_queue,
            )
            status = "started"
        except WorkflowAlreadyStartedError:
            status = "already_started"
        return WorkflowStartResponse(
            workflow_id=workflow_id,
            run_id=run_id_for_idempotency_key(workflow_input.idempotency_key),
            idempotency_key=workflow_input.idempotency_key,
            task_queue=self._settings.temporal_task_queue,
            status=status,
        )

    async def start_report_approval(
        self,
        request: ReportApprovalStartRequest,
    ) -> ReportApprovalStartResponse:
        workflow_input = ReportApprovalWorkflowInput(
            report_version_id=request.report_version_id,
            requested_by=request.requested_by,
            approver_ids=request.approver_ids,
            timeout_seconds=request.timeout_seconds,
        )
        workflow_id = report_approval_workflow_id(request.report_version_id)
        client = await self._client_factory(self._settings)
        try:
            await client.start_workflow(
                ReportApprovalWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=self._settings.temporal_task_queue,
            )
            status = "started"
        except WorkflowAlreadyStartedError:
            status = "already_started"
        return ReportApprovalStartResponse(
            workflow_id=workflow_id,
            report_version_id=request.report_version_id,
            task_queue=self._settings.temporal_task_queue,
            status=status,
        )

    async def start_scheduled_scan(
        self,
        request: ScheduledScanStartRequest,
    ) -> ScheduledScanStartResponse:
        workflow_input = scheduled_scan_input_from_request(request)
        workflow_id = scheduled_scan_workflow_id(workflow_input)
        client = await self._client_factory(self._settings)
        try:
            await client.start_workflow(
                ScheduledScanWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=self._settings.temporal_task_queue,
                cron_schedule=request.cron_schedule,
            )
            status = "started"
        except WorkflowAlreadyStartedError:
            status = "already_started"
        return ScheduledScanStartResponse(
            workflow_id=workflow_id,
            workspace_id=request.workspace_id,
            schedule_id=request.schedule_id,
            task_queue=self._settings.temporal_task_queue,
            status=status,
        )

    async def start_monitor(
        self,
        request: MonitorStartRequest,
    ) -> MonitorStartResponse:
        workflow_input = monitor_input_from_request(request)
        workflow_id = monitor_workflow_id(workflow_input)
        client = await self._client_factory(self._settings)
        try:
            await client.start_workflow(
                MonitorWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=self._settings.temporal_task_queue,
            )
            status = "started"
        except WorkflowAlreadyStartedError:
            status = "already_started"
        return MonitorStartResponse(
            workflow_id=workflow_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            monitor_id=request.monitor_id,
            task_queue=self._settings.temporal_task_queue,
            status=status,
        )

    async def approve_report(
        self,
        report_version_id: str,
        request: ReportApprovalSignalRequest,
    ) -> ReportApprovalSignalResponse:
        return await self._signal_report_approval(
            report_version_id,
            request,
            decision="approved",
        )

    async def reject_report(
        self,
        report_version_id: str,
        request: ReportApprovalSignalRequest,
    ) -> ReportApprovalSignalResponse:
        return await self._signal_report_approval(
            report_version_id,
            request,
            decision="rejected",
        )

    async def _signal_report_approval(
        self,
        report_version_id: str,
        request: ReportApprovalSignalRequest,
        *,
        decision: ReportApprovalSignalDecision,
    ) -> ReportApprovalSignalResponse:
        workflow_id = report_approval_workflow_id(report_version_id)
        client = await self._client_factory(self._settings)
        handle = client.get_workflow_handle(workflow_id)
        signal = (
            ReportApprovalWorkflow.approve
            if decision == "approved"
            else ReportApprovalWorkflow.reject
        )
        await handle.signal(signal, args=[request.approver_id, request.note])
        return ReportApprovalSignalResponse(
            workflow_id=workflow_id,
            report_version_id=report_version_id,
            decision=decision,
            status="signaled",
        )

    async def get_workflow_state(self, workflow_id: str) -> WorkflowStateResponse:
        client = await self._client_factory(self._settings)
        handle = client.get_workflow_handle(workflow_id)
        state = await handle.query("state")
        normalized_state = dict(state) if isinstance(state, dict) else {"raw": str(state)}
        return WorkflowStateResponse(
            workflow_id=workflow_id,
            task_queue=self._settings.temporal_task_queue,
            status=_workflow_state_status(normalized_state.get("status")),
            state=normalized_state,
        )


def competitive_intel_input_from_run_request(
    request: RunCreateRequest,
) -> CompetitiveIntelWorkflowInput:
    idempotency_key = request.idempotency_key or workflow_idempotency_key(request)
    return CompetitiveIntelWorkflowInput(
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        idempotency_key=idempotency_key,
        topic=request.topic,
        competitors=request.competitors,
        dimensions=request.dimensions,
        competitor_layer=request.competitor_layer,
        scenario_id=request.scenario_id,
        execution_mode=request.execution_mode,
        auto_redo_warn_enabled=request.auto_redo_warn_enabled,
    )


def scheduled_scan_input_from_request(
    request: ScheduledScanStartRequest,
) -> ScheduledScanWorkflowInput:
    return ScheduledScanWorkflowInput(
        workspace_id=request.workspace_id,
        schedule_id=request.schedule_id,
        requested_by=request.requested_by,
        project_ids=request.project_ids,
        dimensions=request.dimensions,
        execution_mode=request.execution_mode,
        max_projects=request.max_projects,
    )


def monitor_input_from_request(request: MonitorStartRequest) -> MonitorWorkflowInput:
    return MonitorWorkflowInput(
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        monitor_id=request.monitor_id,
        requested_by=request.requested_by,
        dimensions=request.dimensions,
        execution_mode=request.execution_mode,
        interval_seconds=request.interval_seconds,
        max_cycles=request.max_cycles,
    )


def decide_temporal_cutover(
    settings: Settings,
    request: RunCreateRequest,
) -> TemporalCutoverDecision:
    target_percent = max(0, min(100, settings.temporal_traffic_percent))
    if settings.run_orchestration_backend != "temporal":
        return TemporalCutoverDecision(
            route="langgraph",
            target_percent=target_percent,
            bucket=0,
            reason="RUN_ORCHESTRATION_BACKEND is langgraph.",
        )
    bucket = _stable_cutover_bucket(request)
    if target_percent >= 100:
        return TemporalCutoverDecision(
            route="temporal",
            target_percent=target_percent,
            bucket=bucket,
            reason="Temporal cutover target is 100%.",
        )
    if target_percent <= 0:
        return TemporalCutoverDecision(
            route="langgraph",
            target_percent=target_percent,
            bucket=bucket,
            reason="Temporal cutover target is 0%.",
        )
    if bucket < target_percent:
        return TemporalCutoverDecision(
            route="temporal",
            target_percent=target_percent,
            bucket=bucket,
            reason="Stable request bucket falls inside Temporal cutover target.",
        )
    return TemporalCutoverDecision(
        route="langgraph",
        target_percent=target_percent,
        bucket=bucket,
        reason="Stable request bucket remains on LangGraph during staged cutover.",
    )


def workflow_idempotency_key(request: RunCreateRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"workflow:{digest}"


def run_id_for_idempotency_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"run-{digest}"


def _stable_cutover_bucket(request: RunCreateRequest) -> int:
    key = request.idempotency_key or workflow_idempotency_key(request)
    digest = hashlib.sha256(f"temporal-cutover:{key}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def report_approval_workflow_id(report_version_id: str) -> str:
    digest = hashlib.sha256(report_version_id.encode("utf-8")).hexdigest()[:32]
    return f"report-approval-{digest}"


def scheduled_scan_workflow_id(request: ScheduledScanWorkflowInput) -> str:
    raw = f"{request.workspace_id}|{request.schedule_id}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"scheduled-scan-{digest}"


def monitor_workflow_id(request: MonitorWorkflowInput) -> str:
    raw = f"{request.workspace_id}|{request.project_id}|{request.monitor_id}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"monitor-{digest}"


def _workflow_state_status(value: object) -> str:
    allowed = {
        "initialized",
        "creating_run",
        "running_langgraph",
        "loading_projection",
        "running",
        "waiting",
        "completed",
        "partial",
        "empty",
        "interrupted",
        "timed_out",
        "failed",
        "unknown",
    }
    if isinstance(value, str) and value in allowed:
        return value
    return "unknown"


async def _connect_temporal_client(settings: Settings) -> TemporalClient:
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
