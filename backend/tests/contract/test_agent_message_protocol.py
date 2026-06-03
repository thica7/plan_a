import pytest

from packages.agents import SubagentContext
from packages.config import Settings
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.schema.models import AgentMessage
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
        payload={"plan": detail.plan.model_dump(mode="json")},
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


@pytest.mark.asyncio
async def test_agent_message_payload_schema_is_enforced_on_append() -> None:
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=_settings())
    detail = await service.create_run(
        RunCreateRequest(
            topic="Message schema append",
            competitors=["A"],
            dimensions=["feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]  # noqa: SLF001 - protocol-level test.

    with pytest.raises(ValueError, match="agent_message.payload_schema.invalid"):
        service._append_agent_message(  # noqa: SLF001
            record,
            from_agent="planner",
            to_agent="collector_dispatch",
            message_type="analysis_plan_ready",
            payload_schema="AnalysisPlan",
            payload={"dimension": "feature", "competitor": "A"},
        )


@pytest.mark.asyncio
async def test_agent_message_payload_schema_is_enforced_on_consume() -> None:
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=_settings())
    detail = await service.create_run(
        RunCreateRequest(
            topic="Message schema consume",
            competitors=["A"],
            dimensions=["feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]  # noqa: SLF001 - protocol-level test.
    record.detail.agent_messages.append(
        AgentMessage(
            id="msg-invalid-history",
            run_id=detail.id,
            from_agent="reflector",
            to_agent="writer",
            message_type="reflection_ready",
            payload_schema="ReflectionRecord",
            payload={"coverage_gaps": ["missing wrapper key"]},
        )
    )

    with pytest.raises(ValueError, match="agent_message.payload_schema.invalid"):
        service._consume_queued_agent_messages(  # noqa: SLF001
            record,
            to_agent="writer",
            consumer_agent="writer",
            message_types={"reflection_ready"},
        )


@pytest.mark.asyncio
async def test_agent_message_consumption_populates_subagent_context() -> None:
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=_settings())
    detail = await service.create_run(
        RunCreateRequest(
            topic="Message context",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]  # noqa: SLF001 - protocol-level test.
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="pricing::A")
    message = service._append_agent_message(  # noqa: SLF001
        record,
        from_agent="collector_dispatch",
        to_agent="collector",
        message_type="collect_task",
        payload_schema="CollectTaskPayload",
        payload={
            "topic": "Message context",
            "dimension": "pricing",
            "competitor": "A",
            "homepage_hint": "x" * 500,
        },
    )

    service._consume_agent_message(  # noqa: SLF001
        record,
        message,
        consumer_agent="collector",
        context=context,
    )

    assert context.messages[-1]["role"] == "agent_message"
    assert '"message_type": "collect_task"' in context.messages[-1]["content"]
    assert "homepage_hint" not in context.messages[-1]["content"]
    consume_span = next(
        span
        for span in record.detail.trace_spans
        if span.name == "agent_message_consumed:collect_task"
    )
    assert consume_span.metadata["context_id"] == context.context_id
    assert consume_span.metadata["message_count"] == 1
