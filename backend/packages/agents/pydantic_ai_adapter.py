from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any, Generic, TypeVar

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
        model: object | str | None = None,
    ) -> None:
        self.name = name
        self.input_type = input_type
        self.output_type = output_type
        self._handler = handler
        self.system_prompt = system_prompt
        self._model = model
        self._agent_class_name, self.pydantic_ai_available = _load_pydantic_ai_agent_class_name()
        self._runtime_agent = _create_pydantic_ai_agent(
            name=name,
            output_type=output_type,
            system_prompt=system_prompt,
            model=model,
        )
        self._input_schema_hash = _model_schema_hash(self.input_type)
        self._output_schema_hash = _model_schema_hash(self.output_type)
        self._system_prompt_hash = _text_hash(system_prompt)

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        start = time.perf_counter()
        agent_input = self.input_type.model_validate(request.payload)
        output, execution_mode, runtime_result_type = await self._execute_typed(
            agent_input,
            request.context,
        )
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
                "pydantic_ai_runtime_agent_created": self._runtime_agent is not None,
                "pydantic_ai_runtime_agent_class": type(self._runtime_agent).__name__
                if self._runtime_agent is not None
                else None,
                "pydantic_ai_model_backed_capable": self.pydantic_ai_available,
                "pydantic_ai_model_backed_requested": _model_backed_requested(
                    request.context
                ),
                "pydantic_ai_runtime_result_type": runtime_result_type,
                "system_prompt": self.system_prompt,
                "system_prompt_hash": self._system_prompt_hash,
                "input_schema": self.input_type.__name__,
                "output_schema": self.output_type.__name__,
                "input_schema_hash": self._input_schema_hash,
                "output_schema_hash": self._output_schema_hash,
                "execution_mode": execution_mode,
                "typed_contract_enforced": True,
            },
        )

    async def _execute_typed(
        self,
        agent_input: InputT,
        context: dict[str, Any],
    ) -> tuple[OutputT, str, str | None]:
        mode = str(context.get("pydantic_ai_execution_mode") or "").strip().lower()
        if mode == "test_model":
            deterministic_output = self.output_type.model_validate(self._handler(agent_input))
            model = _create_test_model(deterministic_output)
            runtime_agent = _create_pydantic_ai_agent(
                name=self.name,
                output_type=self.output_type,
                system_prompt=self.system_prompt,
                model=model,
            )
            if runtime_agent is not None:
                result = await runtime_agent.run(_runtime_prompt(agent_input))
                return (
                    self.output_type.model_validate(result.output),
                    "pydantic_ai_test_model_backed",
                    type(result).__name__,
                )
        if mode == "model_backed":
            model = context.get("pydantic_ai_model") or self._model
            if model and self.pydantic_ai_available:
                runtime_agent = _create_pydantic_ai_agent(
                    name=self.name,
                    output_type=self.output_type,
                    system_prompt=self.system_prompt,
                    model=model,
                )
                if runtime_agent is not None:
                    result = await runtime_agent.run(_runtime_prompt(agent_input))
                    return (
                        self.output_type.model_validate(result.output),
                        "pydantic_ai_model_backed",
                        type(result).__name__,
                    )
        return (
            self.output_type.model_validate(self._handler(agent_input)),
            "deterministic_handler",
            None,
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


def _create_pydantic_ai_agent(
    *,
    name: str,
    output_type: type[OutputT],
    system_prompt: str,
    model: object | str | None = None,
) -> object | None:
    try:
        from pydantic_ai import Agent
    except Exception:  # pragma: no cover - depends on optional env installation.
        return None
    return Agent(
        model,
        output_type=output_type,
        instructions=system_prompt,
        name=name,
        defer_model_check=True,
    )


def _create_test_model(output: BaseModel) -> object | None:
    try:
        from pydantic_ai.models.test import TestModel
    except Exception:  # pragma: no cover - depends on optional env installation.
        return None
    return TestModel(custom_output_args=output.model_dump(mode="json"))


def _runtime_prompt(agent_input: BaseModel) -> str:
    return (
        "Validate and return the structured output for this typed agent input:\n"
        + agent_input.model_dump_json()
    )


def _model_backed_requested(context: dict[str, Any]) -> bool:
    mode = str(context.get("pydantic_ai_execution_mode") or "").strip().lower()
    return mode in {"model_backed", "test_model"}


def _model_schema_hash(model_type: type[BaseModel]) -> str:
    schema_json = json.dumps(
        model_type.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return _text_hash(schema_json)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
