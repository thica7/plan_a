from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

from packages.llm.errors import LLMExecutionLimitError


@dataclass
class RunLLMBudget:
    max_calls: int
    max_repairs: int
    calls: int = 0
    repairs: int = 0
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    tokens_used: int = 0
    tokens_reserved: int = 0
    cost_used_usd: float = 0.0
    cost_reserved_usd: float = 0.0
    input_usd_per_million: float = 0.3
    cache_usd_per_million: float = 0.006
    output_usd_per_million: float = 1.2

    def cost(self, prompt: int, output: int, cached: int = 0) -> float:
        cached = max(0, min(prompt, cached))
        return ((prompt - cached) * self.input_usd_per_million
                + cached * self.cache_usd_per_million
                + output * self.output_usd_per_million) / 1_000_000

    def reserve(
        self, *, is_repair: bool, input_tokens: int = 0, max_output_tokens: int = 0,
    ) -> None:
        if self.calls >= self.max_calls:
            raise LLMExecutionLimitError("run_llm_call_budget_exhausted")
        if is_repair and self.repairs >= self.max_repairs:
            raise LLMExecutionLimitError("run_llm_repair_budget_exhausted")
        tokens = input_tokens + max_output_tokens
        cost = self.cost(input_tokens, max_output_tokens)
        if self.max_tokens and self.tokens_used + self.tokens_reserved + tokens > self.max_tokens:
            raise LLMExecutionLimitError("run_llm_token_budget_exhausted")
        total_cost = self.cost_used_usd + self.cost_reserved_usd + cost
        if self.max_cost_usd and total_cost > self.max_cost_usd:
            raise LLMExecutionLimitError("run_llm_cost_budget_exhausted")
        self.calls += 1
        self.repairs += int(is_repair)
        self.tokens_reserved += tokens
        self.cost_reserved_usd += cost


@dataclass
class LLMCallExecution:
    budget: RunLLMBudget
    is_repair: bool
    attempts: int = 0
    transport_attempts: int = 0
    input_tokens: int = 0
    max_output_tokens: int = 0
    pending_attempts: int = 0
    tokens_charged: int = 0
    cost_charged_usd: float = 0.0
    provider_accounted: bool = False
    checkpoint: Callable[[], None] | None = None

    def reserve(self) -> None:
        self.budget.reserve(is_repair=self.is_repair, input_tokens=self.input_tokens,
                            max_output_tokens=self.max_output_tokens)
        self.attempts += 1
        self.pending_attempts += 1
        if self.checkpoint is not None:
            self.checkpoint()

    def reserve_transport(self) -> None:
        # The outer call reserves its first attempt, including offline adapters.
        if self.transport_attempts:
            self.reserve()
        self.transport_attempts += 1

    def settle_attempt(
        self, *, prompt_tokens: int, completion_tokens: int, cache_hit_tokens: int = 0,
    ) -> None:
        if not self.pending_attempts:
            return
        self.pending_attempts -= 1
        self.budget.tokens_reserved -= self.input_tokens + self.max_output_tokens
        reserved_cost = self.budget.cost(self.input_tokens, self.max_output_tokens)
        self.budget.cost_reserved_usd = max(0.0, self.budget.cost_reserved_usd - reserved_cost)
        tokens = max(0, prompt_tokens) + max(0, completion_tokens)
        cost = self.budget.cost(max(0, prompt_tokens), max(0, completion_tokens), cache_hit_tokens)
        self.budget.tokens_used += tokens
        self.budget.cost_used_usd += cost
        self.tokens_charged += tokens
        self.cost_charged_usd += cost
        if self.checkpoint is not None:
            self.checkpoint()

    def settle(self, *, prompt_tokens: int | None = None, completion_tokens: int | None = None,
               cache_hit_tokens: int = 0) -> None:
        # Missing usage (timeout, cancellation or transport error) retains its
        # conservative charge. Every attempt remains visible after recovery.
        has_usage = prompt_tokens is not None and completion_tokens is not None
        if not self.provider_accounted and has_usage:
            self.settle_attempt(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                                cache_hit_tokens=cache_hit_tokens)
        while self.pending_attempts:
            self.settle_attempt(
                prompt_tokens=self.input_tokens, completion_tokens=self.max_output_tokens)

    def metadata(self) -> dict[str, int | float | bool]:
        return {
            "llm_request_attempts": self.attempts,
            "llm_retry_count": max(0, self.attempts - 1),
            "llm_repair_attempts": self.attempts if self.is_repair else 0,
            "is_repair": self.is_repair,
            "run_llm_calls_used": self.budget.calls,
            "run_llm_calls_limit": self.budget.max_calls,
            "run_llm_repairs_used": self.budget.repairs,
            "run_llm_repairs_limit": self.budget.max_repairs,
            "llm_tokens_charged": self.tokens_charged,
            "llm_cost_charged_usd": self.cost_charged_usd,
            "run_llm_tokens_used": self.budget.tokens_used,
            "run_llm_tokens_limit": self.budget.max_tokens,
            "run_llm_cost_used_usd": self.budget.cost_used_usd,
            "run_llm_cost_limit_usd": self.budget.max_cost_usd,
            "llm_reserved_input_tokens": self.input_tokens,
            "llm_max_output_tokens": self.max_output_tokens,
        }


current_llm_execution: ContextVar[LLMCallExecution | None] = ContextVar(
    "current_llm_execution",
    default=None,
)
