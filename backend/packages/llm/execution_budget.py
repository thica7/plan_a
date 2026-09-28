from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from packages.llm.errors import LLMExecutionLimitError


@dataclass
class RunLLMBudget:
    max_calls: int
    max_repairs: int
    calls: int = 0
    repairs: int = 0

    def reserve(self, *, is_repair: bool) -> None:
        if self.calls >= self.max_calls:
            raise LLMExecutionLimitError("run_llm_call_budget_exhausted")
        if is_repair and self.repairs >= self.max_repairs:
            raise LLMExecutionLimitError("run_llm_repair_budget_exhausted")
        self.calls += 1
        self.repairs += int(is_repair)


@dataclass
class LLMCallExecution:
    budget: RunLLMBudget
    is_repair: bool
    attempts: int = 0
    transport_attempts: int = 0

    def reserve(self) -> None:
        self.budget.reserve(is_repair=self.is_repair)
        self.attempts += 1

    def reserve_transport(self) -> None:
        # The outer call reserves its first attempt, including offline adapters.
        if self.transport_attempts:
            self.reserve()
        self.transport_attempts += 1

    def metadata(self) -> dict[str, int | bool]:
        return {
            "llm_request_attempts": self.attempts,
            "llm_retry_count": max(0, self.attempts - 1),
            "llm_repair_attempts": self.attempts if self.is_repair else 0,
            "is_repair": self.is_repair,
            "run_llm_calls_used": self.budget.calls,
            "run_llm_calls_limit": self.budget.max_calls,
            "run_llm_repairs_used": self.budget.repairs,
            "run_llm_repairs_limit": self.budget.max_repairs,
        }


current_llm_execution: ContextVar[LLMCallExecution | None] = ContextVar(
    "current_llm_execution",
    default=None,
)
