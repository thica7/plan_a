from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry


async def main() -> None:
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
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistants",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    await service.run_pipeline(detail.id)
    completed = service.get_run(detail.id)
    if completed is None or completed.status != "completed":
        raise SystemExit("Minimal run did not complete.")

    print(
        json.dumps(
            {
                "component": "minimal_run",
                "ok": True,
                "run_id": completed.id,
                "status": completed.status,
                "event_count": len(service.get_trace(completed.id) or []),
                "report_chars": len(completed.report_md),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
