from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError

from packages.config import Settings
from packages.schema.api_dto import (
    ReportApprovalSignalRequest,
    ReportApprovalSignalResponse,
    ReportApprovalStartRequest,
    ReportApprovalStartResponse,
    RunCreateRequest,
    WorkflowStartResponse,
)
from packages.workflows.client import workflow_id_for_request
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.models import (
    CompetitiveIntelWorkflowInput,
    ReportApprovalSignalDecision,
    ReportApprovalWorkflowInput,
)
from packages.workflows.report_approval import ReportApprovalWorkflow


class TemporalClient(Protocol):
    async def start_workflow(
        self,
        workflow: object,
        arg: object,
        *,
        id: str,
        task_queue: str,
    ) -> WorkflowHandle: ...

    def get_workflow_handle(self, workflow_id: str) -> WorkflowHandle: ...


TemporalClientFactory = Callable[[Settings], Awaitable[TemporalClient]]


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


def workflow_idempotency_key(request: RunCreateRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"workflow:{digest}"


def run_id_for_idempotency_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"run-{digest}"


def report_approval_workflow_id(report_version_id: str) -> str:
    digest = hashlib.sha256(report_version_id.encode("utf-8")).hexdigest()[:32]
    return f"report-approval-{digest}"


async def _connect_temporal_client(settings: Settings) -> TemporalClient:
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
