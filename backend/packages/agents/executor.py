from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    agent_name: str
    subagent_name: str | None = None
    input_schema: str = "dict"
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    trace_span_ids: list[str] = Field(default_factory=list)


class AgentExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    agent_name: str
    subagent_name: str | None = None
    status: Literal["ok", "error"] = "ok"
    output_schema: str = "dict"
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    trace_span_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentExecutor(Protocol):
    name: str

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult: ...


LegacyAgentHandler = Callable[
    [AgentExecutionRequest],
    AgentExecutionResult
    | BaseModel
    | Mapping[str, Any]
    | Awaitable[AgentExecutionResult | BaseModel | Mapping[str, Any]],
]


class LegacyAgentExecutor:
    """Adapter boundary for current hand-written agents before Pydantic-AI migration."""

    def __init__(
        self,
        *,
        name: str,
        output_schema: str,
        handler: LegacyAgentHandler,
        raise_errors: bool = False,
    ) -> None:
        self.name = name
        self.output_schema = output_schema
        self._handler = handler
        self._raise_errors = raise_errors

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        start = time.perf_counter()
        try:
            raw_result = self._handler(request)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            return self._normalize_result(request, raw_result, start)
        except Exception as exc:
            if self._raise_errors:
                raise
            return AgentExecutionResult(
                run_id=request.run_id,
                agent_name=self.name,
                subagent_name=request.subagent_name,
                status="error",
                output_schema=self.output_schema,
                error=str(exc),
                duration_ms=_elapsed_ms(start),
                trace_span_ids=list(request.trace_span_ids),
            )

    def _normalize_result(
        self,
        request: AgentExecutionRequest,
        raw_result: AgentExecutionResult | BaseModel | Mapping[str, Any],
        start: float,
    ) -> AgentExecutionResult:
        if isinstance(raw_result, AgentExecutionResult):
            return raw_result.model_copy(
                update={
                    "duration_ms": raw_result.duration_ms or _elapsed_ms(start),
                    "trace_span_ids": raw_result.trace_span_ids or request.trace_span_ids,
                }
            )
        if isinstance(raw_result, BaseModel):
            payload = raw_result.model_dump(mode="json")
        else:
            payload = dict(raw_result)
        return AgentExecutionResult(
            run_id=request.run_id,
            agent_name=self.name,
            subagent_name=request.subagent_name,
            status="ok",
            output_schema=self.output_schema,
            payload=payload,
            duration_ms=_elapsed_ms(start),
            trace_span_ids=list(request.trace_span_ids),
        )


class AgentExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, AgentExecutor] = {}

    def register(self, executor: AgentExecutor) -> None:
        if executor.name in self._executors:
            raise ValueError(f"Agent executor already registered: {executor.name}")
        self._executors[executor.name] = executor

    def get(self, name: str) -> AgentExecutor:
        try:
            return self._executors[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent executor: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._executors)

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        return await self.get(request.agent_name).execute(request)


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))
