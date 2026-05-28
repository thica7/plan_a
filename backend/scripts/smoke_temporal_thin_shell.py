from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.orchestrator.service import RunService
from packages.skills.registry import SkillRegistry
from packages.workflows.activities import CompetitiveIntelActivities
from packages.workflows.models import CompetitiveIntelWorkflowInput


async def main() -> None:
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
        ),
        enterprise_store=store,
    )
    activities = CompetitiveIntelActivities(service)
    request = CompetitiveIntelWorkflowInput(
        topic="AI coding assistant temporal smoke",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key="temporal-thin-shell-smoke",
    )

    created = await activities.create_run(request)
    duplicate = await activities.create_run(request)
    completed = await activities.run_langgraph_pipeline(created.run_id)
    completed_again = await activities.run_langgraph_pipeline(created.run_id)
    projection = await activities.load_projection(created.run_id)

    if created.run_id != duplicate.run_id:
        raise SystemExit("Temporal create activity was not idempotent.")
    if completed.status != "completed" or completed_again.status != "completed":
        raise SystemExit("Temporal LangGraph activity did not complete idempotently.")
    if not projection.report_version_id or projection.evidence_count < 1:
        raise SystemExit("Temporal projection activity did not load enterprise projection.")

    print(
        json.dumps(
            {
                "component": "temporal_thin_shell",
                "ok": True,
                "run_id": created.run_id,
                "idempotency_key": created.idempotency_key,
                "status": completed.status,
                "report_version_id": projection.report_version_id,
                "evidence_count": projection.evidence_count,
                "claim_count": projection.claim_count,
                "event_count": len(service.get_trace(created.run_id) or []),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
