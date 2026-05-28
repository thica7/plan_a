from __future__ import annotations

import hashlib

from temporalio.client import Client

from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.models import (
    DEFAULT_TEMPORAL_TASK_QUEUE,
    CompetitiveIntelWorkflowInput,
    CompetitiveIntelWorkflowResult,
)


async def start_competitive_intel_workflow(
    client: Client,
    request: CompetitiveIntelWorkflowInput,
    *,
    task_queue: str = DEFAULT_TEMPORAL_TASK_QUEUE,
    workflow_id: str | None = None,
) -> CompetitiveIntelWorkflowResult:
    handle = await client.start_workflow(
        CompetitiveIntelWorkflow.run,
        request,
        id=workflow_id or workflow_id_for_request(request),
        task_queue=task_queue,
    )
    return await handle.result()


def workflow_id_for_request(request: CompetitiveIntelWorkflowInput) -> str:
    source = request.idempotency_key or "|".join(
        [
            request.workspace_id,
            request.project_id or "",
            request.topic,
            ",".join(request.competitors),
            ",".join(request.dimensions),
        ]
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    return f"competitive-intel-{digest}"
