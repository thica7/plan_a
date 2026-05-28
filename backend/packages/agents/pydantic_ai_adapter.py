from __future__ import annotations

import time
from collections.abc import Callable
from typing import Generic, TypeVar

from pydantic import BaseModel

from packages.agents.executor import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutor,
)

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class PydanticAIAgentExecutor(Generic[InputT, OutputT]):
    """Typed Phase 3 agent boundary backed by the Pydantic-AI dependency.

    The actual product agents remain deterministic when no model credentials are
    configured, but this wrapper imports and records the Pydantic-AI runtime so
    the same boundary can be swapped to real model-backed agents later.
    """

    def __init__(
        self,
        *,
        name: str,
        input_type: type[InputT],
        output_type: type[OutputT],
        handler: Callable[[InputT], OutputT],
        system_prompt: str,
    ) -> None:
        self.name = name
        self.input_type = input_type
        self.output_type = output_type
        self._handler = handler
        self.system_prompt = system_prompt
        self._agent_class_name, self.pydantic_ai_available = _load_pydantic_ai_agent_class_name()

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        start = time.perf_counter()
        agent_input = self.input_type.model_validate(request.payload)
        output = self.output_type.model_validate(self._handler(agent_input))
        return AgentExecutionResult(
            run_id=request.run_id,
            agent_name=self.name,
            subagent_name=request.subagent_name,
            status="ok",
            output_schema=self.output_type.__name__,
            payload=output.model_dump(mode="json"),
            duration_ms=max(0, int((time.perf_counter() - start) * 1000)),
            trace_span_ids=list(request.trace_span_ids),
            metadata={
                "framework": "pydantic-ai",
                "pydantic_ai_available": self.pydantic_ai_available,
                "pydantic_ai_agent_class": self._agent_class_name,
                "system_prompt": self.system_prompt,
            },
        )


def as_agent_executor(
    executor: PydanticAIAgentExecutor[InputT, OutputT],
) -> AgentExecutor:
    return executor


def _load_pydantic_ai_agent_class_name() -> tuple[str | None, bool]:
    try:
        from pydantic_ai import Agent
    except Exception:  # pragma: no cover - depends on optional env installation.
        return None, False
    return Agent.__name__, True


def pydantic_ai_available() -> bool:
    return _load_pydantic_ai_agent_class_name()[1]
