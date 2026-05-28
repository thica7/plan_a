from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError

from packages.config import Settings
from packages.schema.api_dto import RunCreateRequest, WorkflowStartResponse
from packages.workflows.client import workflow_id_for_request
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.models import CompetitiveIntelWorkflowInput


class TemporalClient(Protocol):
    async def start_workflow(
        self,
        workflow: object,
        arg: object,
        *,
        id: str,
        task_queue: str,
    ) -> WorkflowHandle: ...


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


async def _connect_temporal_client(settings: Settings) -> TemporalClient:
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
