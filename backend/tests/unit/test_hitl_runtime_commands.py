import pytest

from packages.auth import EnterpriseUserContext
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.runtime import ResumeReviewCommand, RuntimeCommandError, RuntimeCommandService
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_resume_review_requires_pending_hitl_interrupt() -> None:
    store = EnterpriseMemoryStore()
    run_service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    runtime = RuntimeCommandService(
        settings=_settings(),
        run_service=run_service,
        workflow_service=object(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )

    try:
        detail = await run_service.create_run(
            RunCreateRequest(
                topic="HITL runtime stale accept",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )
        run_service._runs[detail.id].detail.status = "completed"

        with pytest.raises(RuntimeCommandError) as blocked:
            await runtime.resume_review(
                ResumeReviewCommand(
                    run_id=detail.id,
                    request=HitlResumeRequest(decision="accept"),
                ),
                actor=_actor(),
            )

        assert blocked.value.status_code == 409
        assert "no pending HITL interrupt" in str(blocked.value.detail)
        assert run_service._runs[detail.id].detail.status == "completed"
    finally:
        await run_service._graph_checkpointer.aclose()


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key="key",
        ark_model="model",
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
        enterprise_store_backend="memory",
        enterprise_database_url=None,
        hitl_enabled=True,
    )


def _actor() -> EnterpriseUserContext:
    return EnterpriseUserContext(
        user_id="system-user",
        role="owner",
        workspace_id="default-workspace",
    )
