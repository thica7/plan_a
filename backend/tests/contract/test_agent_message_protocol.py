import pytest

from packages.config import Settings
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry


def _settings() -> Settings:
    return Settings(
        demo_mode=False,
        ark_api_key="key",
        ark_model="model",
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )


@pytest.mark.asyncio
async def test_agent_message_is_consumed_as_structured_runtime_envelope() -> None:
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=_settings())
    detail = await service.create_run(
        RunCreateRequest(
            topic="Message protocol",
            competitors=["A"],
            dimensions=["feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]  # noqa: SLF001 - protocol-level test.
    message = service._append_agent_message(  # noqa: SLF001
        record,
        from_agent="planner",
        to_agent="collector_dispatch",
        message_type="analysis_plan_ready",
        payload_schema="AnalysisPlan",
        payload={"dimension": "feature", "competitor": "A"},
    )

    consumed = service._consume_queued_agent_messages(  # noqa: SLF001
        record,
        to_agent="collector_dispatch",
        consumer_agent="collector_dispatch",
        message_types={"analysis_plan_ready"},
    )

    assert consumed == [message]
    assert message.status == "consumed"
    assert message.consumed_by == "collector_dispatch"
    assert message.consumed_at is not None
    assert any(call.source_message_id == message.id for call in record.detail.tool_call_messages)
