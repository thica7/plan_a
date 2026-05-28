import pytest
from pydantic import BaseModel

from packages.agents import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutorRegistry,
    LegacyAgentExecutor,
)


class TypedOutput(BaseModel):
    answer: str
    score: float


@pytest.mark.asyncio
async def test_legacy_agent_executor_wraps_async_mapping_result() -> None:
    async def handler(request: AgentExecutionRequest) -> dict[str, object]:
        return {"echo": request.payload["question"]}

    executor = LegacyAgentExecutor(
        name="analyst",
        output_schema="EchoPayload",
        handler=handler,
    )

    result = await executor.execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="analyst",
            subagent_name="pricing",
            payload={"question": "price?"},
            trace_span_ids=["span-1"],
        )
    )

    assert result.status == "ok"
    assert result.payload == {"echo": "price?"}
    assert result.output_schema == "EchoPayload"
    assert result.trace_span_ids == ["span-1"]


@pytest.mark.asyncio
async def test_legacy_agent_executor_wraps_pydantic_output() -> None:
    def handler(request: AgentExecutionRequest) -> TypedOutput:
        return TypedOutput(answer=str(request.payload["answer"]), score=0.8)

    executor = LegacyAgentExecutor(
        name="writer",
        output_schema="TypedOutput",
        handler=handler,
    )

    result = await executor.execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="writer",
            payload={"answer": "done"},
        )
    )

    assert result.payload == {"answer": "done", "score": 0.8}


@pytest.mark.asyncio
async def test_legacy_agent_executor_returns_typed_error() -> None:
    def handler(request: AgentExecutionRequest) -> dict[str, object]:
        raise RuntimeError(f"failed {request.run_id}")

    executor = LegacyAgentExecutor(
        name="collector",
        output_schema="CollectorOutput",
        handler=handler,
    )

    result = await executor.execute(
        AgentExecutionRequest(run_id="run-1", agent_name="collector")
    )

    assert result.status == "error"
    assert result.error == "failed run-1"
    assert result.payload == {}


@pytest.mark.asyncio
async def test_agent_executor_registry_routes_by_name() -> None:
    executor = LegacyAgentExecutor(
        name="qa",
        output_schema="QAOutput",
        handler=lambda request: AgentExecutionResult(
            run_id=request.run_id,
            agent_name=request.agent_name,
            output_schema="QAOutput",
            payload={"passed": True},
        ),
    )
    registry = AgentExecutorRegistry()
    registry.register(executor)

    result = await registry.execute(AgentExecutionRequest(run_id="run-1", agent_name="qa"))

    assert registry.names() == ["qa"]
    assert result.payload == {"passed": True}
    with pytest.raises(ValueError, match="already registered"):
        registry.register(executor)
