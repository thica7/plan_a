from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
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
    ReportApprovalWorkflowInput,
    ReportApprovalWorkflowResult,
)
from packages.workflows.replay import replay_temporal_history  # noqa: E402
from packages.workflows.report_approval import ReportApprovalWorkflow  # noqa: E402
from packages.workflows.service import report_approval_workflow_id  # noqa: E402
from packages.workflows.worker import build_competitive_intel_worker_components  # noqa: E402


async def main() -> None:
    args = _parse_args()
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
    components = build_competitive_intel_worker_components(service, enterprise_store=store)
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
            handle = await client.start_workflow(
                CompetitiveIntelWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
                result_type=CompetitiveIntelWorkflowResult,
                run_timeout=timedelta(seconds=60),
            )
            result = await asyncio.wait_for(handle.result(), timeout=75)
            projection = store.get_run_projection(result.run_id)
            if result.status != "completed":
                raise SystemExit(f"Temporal workflow did not complete: {result.status}")
            if projection is None:
                raise SystemExit("Temporal workflow completed without enterprise projection.")
            if projection.report_version.id != result.report_version_id:
                raise SystemExit(
                    "Temporal workflow result does not match stored report version."
                )

            approval_workflow_id = report_approval_workflow_id(result.report_version_id)
            approval_input = ReportApprovalWorkflowInput(
                report_version_id=result.report_version_id,
                requested_by="temporal-smoke",
                approver_ids=["temporal-smoke-approver"],
                timeout_seconds=30,
            )
            approval_handle = await client.start_workflow(
                ReportApprovalWorkflow.run,
                approval_input,
                id=approval_workflow_id,
                task_queue=task_queue,
                result_type=ReportApprovalWorkflowResult,
                run_timeout=timedelta(seconds=45),
            )
            await approval_handle.signal(
                ReportApprovalWorkflow.approve,
                args=["temporal-smoke-approver", "server smoke approval"],
            )
            approval_result = await asyncio.wait_for(approval_handle.result(), timeout=45)
            workflow_replay = await replay_temporal_history(await handle.fetch_history())
            approval_replay = await replay_temporal_history(
                await approval_handle.fetch_history()
            )
    except RPCError as exc:
        raise SystemExit(f"Temporal workflow execution failed: {exc}") from exc
    except TimeoutError as exc:
        raise SystemExit(
            "Temporal workflow smoke timed out after 75 seconds. "
            f"workflow_id={workflow_id} task_queue={task_queue}"
        ) from exc

    approved_version = store.get_report_version(result.report_version_id)
    if approval_result.decision != "approved" or approval_result.final_status != "approved":
        raise SystemExit("Temporal approval workflow did not approve the report version.")
    if approved_version is None or approved_version.status != "approved":
        raise SystemExit("Temporal approval workflow did not persist approved status.")
    if not workflow_replay.ok:
        raise SystemExit(f"CompetitiveIntelWorkflow replay failed: {workflow_replay.failure}")
    if not approval_replay.ok:
        raise SystemExit(f"ReportApprovalWorkflow replay failed: {approval_replay.failure}")

    summary = {
        "component": "temporal_server",
        "ok": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "workflow_id": workflow_id,
        "run_id": result.run_id,
        "status": result.status,
        "task_queue": task_queue,
        "report_version_id": result.report_version_id,
        "approval_workflow_id": approval_workflow_id,
        "approval_status": approval_result.final_status,
        "workflow_replay_ok": workflow_replay.ok,
        "workflow_replay_event_count": workflow_replay.event_count,
        "approval_replay_ok": approval_replay.ok,
        "approval_replay_event_count": approval_replay.event_count,
        "evidence_count": result.evidence_count,
        "claim_count": result.claim_count,
        "event_count": len(service.get_trace(result.run_id) or []),
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def _render_report(summary: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Temporal Replay Report",
            "",
            f"- Generated at: {summary['generated_at']}",
            f"- Workflow id: {summary['workflow_id']}",
            f"- Run id: {summary['run_id']}",
            f"- Task queue: {summary['task_queue']}",
            f"- CompetitiveIntel status: {summary['status']}",
            f"- Approval status: {summary['approval_status']}",
            f"- CompetitiveIntel replay: {summary['workflow_replay_ok']}",
            f"- CompetitiveIntel history events: {summary['workflow_replay_event_count']}",
            f"- Approval replay: {summary['approval_replay_ok']}",
            f"- Approval history events: {summary['approval_replay_event_count']}",
            "",
            "## Interpretation",
            "",
            "This report fetches real Temporal workflow histories after execution and replays "
            "them with the Temporal Python SDK Replayer. A pass means the current workflow "
            "definitions can deterministically replay the stored histories.",
            "",
        ]
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real Temporal server smoke and replay its histories."
    )
    parser.add_argument("--report", default=None, help="Optional markdown report path.")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
