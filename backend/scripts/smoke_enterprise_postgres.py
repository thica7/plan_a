from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings
from packages.enterprise import EnterprisePostgresStore
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry

DEFAULT_DATABASE_URL = (
    "postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5"
)


async def main() -> None:
    database_url = os.getenv("ENTERPRISE_DATABASE_URL") or DEFAULT_DATABASE_URL
    store = EnterprisePostgresStore(database_url)
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
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant enterprise smoke",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    await service.run_pipeline(detail.id)
    completed = service.get_run(detail.id)
    if completed is None or completed.status != "completed":
        raise SystemExit("Postgres enterprise demo run did not complete.")

    loaded = store.get_run_projection(detail.id)
    if loaded is None:
        raise SystemExit("Postgres enterprise projection was not persisted.")
    if not loaded.evidence_records or not loaded.claim_records:
        raise SystemExit("Postgres enterprise projection is missing evidence or claims.")

    print(
        json.dumps(
            {
                "component": "enterprise_postgres",
                "ok": True,
                "run_id": completed.id,
                "status": completed.status,
                "project_id": loaded.project_id,
                "evidence_count": len(loaded.evidence_records),
                "claim_count": len(loaded.claim_records),
                "report_version_id": loaded.report_version.id,
                "report_chars": len(completed.report_md),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
