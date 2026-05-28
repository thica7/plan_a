from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from temporalio.client import Client
from temporalio.service import RPCError
from temporalio.worker import Worker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings  # noqa: E402
from packages.enterprise import EnterpriseMemoryStore  # noqa: E402
from packages.orchestrator.service import RunService  # noqa: E402
from packages.skills.registry import SkillRegistry  # noqa: E402
from packages.workflows.client import workflow_id_for_request  # noqa: E402
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow  # noqa: E402
from packages.workflows.models import (  # noqa: E402
    CompetitiveIntelWorkflowInput,
    CompetitiveIntelWorkflowResult,
)
from packages.workflows.worker import build_competitive_intel_worker_components  # noqa: E402


async def main() -> None:
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233")
    temporal_namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    smoke_id = uuid4().hex
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", f"competitive-intel-smoke-{smoke_id[:8]}")
    try:
        client = await Client.connect(
            temporal_address,
            namespace=temporal_namespace,
        )
    except Exception as exc:  # noqa: BLE001 - smoke should explain missing server clearly.
        raise SystemExit(
            "Temporal server is unavailable. Start it with "
            "`docker compose up -d postgres temporal temporal-ui` and retry. "
            f"address={temporal_address} namespace={temporal_namespace}"
        ) from exc

    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=30,
            llm_temperature=0.2,
            enterprise_store_backend="memory",
            enterprise_database_url=None,
            temporal_address=temporal_address,
            temporal_namespace=temporal_namespace,
            temporal_task_queue=task_queue,
        ),
        enterprise_store=store,
    )
    components = build_competitive_intel_worker_components(service)
    request = CompetitiveIntelWorkflowInput(
        topic="AI coding assistant temporal server smoke",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key=f"temporal-server-smoke-{smoke_id}",
    )
    workflow_id = workflow_id_for_request(request)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=components.workflows,
        activities=components.activities,
    )
    try:
        async with worker:
            result = await asyncio.wait_for(
                client.execute_workflow(
                    CompetitiveIntelWorkflow.run,
                    request,
                    id=workflow_id,
                    task_queue=task_queue,
                    result_type=CompetitiveIntelWorkflowResult,
                    run_timeout=timedelta(seconds=60),
                ),
                timeout=75,
            )
    except RPCError as exc:
        raise SystemExit(f"Temporal workflow execution failed: {exc}") from exc
    except TimeoutError as exc:
        raise SystemExit(
            "Temporal workflow smoke timed out after 75 seconds. "
            f"workflow_id={workflow_id} task_queue={task_queue}"
        ) from exc

    projection = store.get_run_projection(result.run_id)
    if result.status != "completed":
        raise SystemExit(f"Temporal workflow did not complete: {result.status}")
    if projection is None:
        raise SystemExit("Temporal workflow completed without enterprise projection.")
    if projection.report_version.id != result.report_version_id:
        raise SystemExit("Temporal workflow result does not match stored report version.")

    print(
        json.dumps(
            {
                "component": "temporal_server",
                "ok": True,
                "workflow_id": workflow_id,
                "run_id": result.run_id,
                "status": result.status,
                "task_queue": task_queue,
                "report_version_id": result.report_version_id,
                "evidence_count": result.evidence_count,
                "claim_count": result.claim_count,
                "event_count": len(service.get_trace(result.run_id) or []),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
