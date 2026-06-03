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
        output, execution_mode, runtime_result_type, runtime_metadata = await self._execute_typed(
            agent_input,
            request.context,
        )
        metadata = {
            "framework": "pydantic-ai",
            "pydantic_ai_available": self.pydantic_ai_available,
            "pydantic_ai_agent_class": self._agent_class_name,
            "pydantic_ai_runtime_agent_created": self._runtime_agent is not None,
            "pydantic_ai_runtime_agent_class": type(self._runtime_agent).__name__
            if self._runtime_agent is not None
            else None,
            "pydantic_ai_model_backed_capable": self.pydantic_ai_available,
            "pydantic_ai_model_backed_requested": _model_backed_requested(request.context),
            "pydantic_ai_model_backed_fallback": execution_mode.endswith("_fallback"),
            "pydantic_ai_runtime_result_type": runtime_result_type,
            "pydantic_ai_model_name": _model_name_from_context(request.context, self._model),
            "system_prompt": self.system_prompt,
            "system_prompt_hash": self._system_prompt_hash,
            "input_schema": self.input_type.__name__,
            "output_schema": self.output_type.__name__,
            "input_schema_hash": self._input_schema_hash,
            "output_schema_hash": self._output_schema_hash,
            "execution_mode": execution_mode,
            "typed_contract_enforced": True,
        }
        metadata.update(runtime_metadata)
        return AgentExecutionResult(
            run_id=request.run_id,
            agent_name=self.name,
            subagent_name=request.subagent_name,
            status="ok",
            output_schema=self.output_type.__name__,
            payload=output.model_dump(mode="json"),
            duration_ms=max(0, int((time.perf_counter() - start) * 1000)),
            trace_span_ids=list(request.trace_span_ids),
            metadata=metadata,
        )

    async def _execute_typed(
        self,
        agent_input: InputT,
        context: dict[str, Any],
    ) -> tuple[OutputT, str, str | None, dict[str, Any]]:
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
                try:
                    result = await runtime_agent.run(
                        _runtime_prompt(agent_input, self.output_type)
                    )
                    return (
                        _validate_runtime_output(result, self.output_type),
                        "pydantic_ai_test_model_backed",
                        type(result).__name__,
                        {},
                    )
                except Exception as exc:  # noqa: BLE001 - typed fallback is intentional.
                    return (
                        deterministic_output,
                        "pydantic_ai_test_model_fallback",
                        None,
                        {"pydantic_ai_test_model_error": _safe_error(exc)},
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
                    try:
                        result = await runtime_agent.run(
                            _runtime_prompt(agent_input, self.output_type)
                        )
                        return (
                            _validate_runtime_output(result, self.output_type),
                            "pydantic_ai_model_backed",
                            type(result).__name__,
                            {},
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve product availability.
                        return (
                            self.output_type.model_validate(self._handler(agent_input)),
                            "pydantic_ai_model_backed_fallback",
                            None,
                            {"pydantic_ai_model_backed_error": _safe_error(exc)},
                        )
        return (
            self.output_type.model_validate(self._handler(agent_input)),
            "deterministic_handler",
            None,
            {},
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


def _runtime_prompt(agent_input: BaseModel, output_type: type[BaseModel]) -> str:
    output_schema = json.dumps(
        output_type.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return (
        "Execute this typed business-intelligence agent. Return only structured "
        "output that validates against the JSON schema. Do not include markdown.\n"
        f"Output JSON schema:\n{output_schema}\n"
        f"Typed agent input:\n{agent_input.model_dump_json()}"
    )


def _validate_runtime_output(result: object, output_type: type[OutputT]) -> OutputT:
    output = getattr(result, "output", getattr(result, "data", result))
    if isinstance(output, output_type):
        return output
    if isinstance(output, BaseModel):
        return output_type.model_validate(output.model_dump(mode="json"))
    if isinstance(output, str):
        return output_type.model_validate_json(output)
    return output_type.model_validate(output)


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return message[:240]


def _model_backed_requested(context: dict[str, Any]) -> bool:
    mode = str(context.get("pydantic_ai_execution_mode") or "").strip().lower()
    return mode in {"model_backed", "test_model"}


def _model_name_from_context(context: dict[str, Any], default_model: object | str | None) -> str | None:
    model = context.get("pydantic_ai_model") or default_model
    if model is None:
        return None
    if isinstance(model, str):
        return model
    return type(model).__name__


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
