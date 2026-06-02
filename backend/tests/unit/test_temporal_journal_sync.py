from pathlib import Path
from uuid import uuid4

import pytest

from packages.config import Settings
from packages.memory import RunJournal
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key="key",
        ark_model="model",
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )


@pytest.mark.asyncio
async def test_run_service_refreshes_runs_created_by_another_process() -> None:
    db_path = Path("logs") / f"test_temporal_journal_sync_{uuid4().hex}.db"
    api_journal = RunJournal(db_path)
    worker_journal = RunJournal(db_path)
    api_service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        journal=api_journal,
    )
    worker_service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        journal=worker_journal,
    )

    try:
        created = await worker_service.create_run(
            RunCreateRequest(
                topic="Temporal journal sync",
                competitors=["Cursor"],
                dimensions=["pricing"],
                execution_mode="demo",
                idempotency_key="workflow:test-temporal-journal-sync",
            )
        )
        await worker_service.emit(
            created.id,
            "node_started",
            "planner",
            None,
            "Worker-side event.",
        )

        loaded = api_service.get_run(created.id)
        trace = api_service.get_trace(created.id)

        assert loaded is not None
        assert loaded.id == created.id
        assert api_service.list_runs()[0].id == created.id
        assert trace is not None
        assert [event.type for event in trace] == ["run_created", "node_started"]
    finally:
        db_path.unlink(missing_ok=True)
