from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

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
    reservation_settled: asyncio.Event = field(default_factory=asyncio.Event, repr=False, compare=False)

    stage_headroom: int = 0
    delivery_reserves: dict[str, int] = field(default_factory=dict)
    delivery_charged: dict[str, int] = field(default_factory=dict)
    delivery_calls: dict[str, int] = field(default_factory=dict)
    delivery_call_reserves: dict[str, int] = field(default_factory=dict)
    delivery_finished: set[str] = field(default_factory=set)

    def protected_tokens(self, phase: str | None) -> int:
        protected = sum(max(0, amount - self.delivery_charged.get(key, 0))
                   for key, amount in self.delivery_reserves.items()
                   if key != phase and key not in self.delivery_finished)
        core = ('analyst:', 'comparator:', 'reflector:', 'writer:', 'qa:', 'answer:', 'final_qa:')
        if not (phase or '').startswith(core) and any(
            key.startswith(core) and key not in self.delivery_finished for key in self.delivery_reserves
        ):
            protected += self.stage_headroom
        return protected

    def protected_calls(self, phase: str | None) -> int:
        return sum(max(0, self.delivery_call_reserves.get(key, 1) - self.delivery_calls.get(key, 0))
                   for key in self.delivery_reserves
                   if key != phase and key not in self.delivery_finished)

    def finish_delivery(self, phase: str) -> None:
        self.delivery_finished.add(phase)
        self.reservation_settled.set()

    def cost(self, prompt: int, output: int, cached: int = 0) -> float:
        cached = max(0, min(prompt, cached))
        return ((prompt - cached) * self.input_usd_per_million
                + cached * self.cache_usd_per_million
                + output * self.output_usd_per_million) / 1_000_000

    def reserve(
        self, *, is_repair: bool, input_tokens: int = 0, max_output_tokens: int = 0, phase: str | None = None,
    ) -> None:
        if self.calls >= self.max_calls:
            raise LLMExecutionLimitError("run_llm_call_budget_exhausted")
        required_calls = self.calls + self.protected_calls(None)
        if required_calls > self.max_calls:
            raise LLMExecutionLimitError(
                f'run_llm_scope_budget_insufficient:required_calls={required_calls},limit={self.max_calls}')
        if is_repair and self.repairs >= self.max_repairs:
            raise LLMExecutionLimitError("run_llm_repair_budget_exhausted")
        tokens = input_tokens + max_output_tokens
        cost = self.cost(input_tokens, max_output_tokens)
        if self.max_tokens and self.tokens_used + self.tokens_reserved + tokens > self.max_tokens:
            raise LLMExecutionLimitError("run_llm_token_budget_exhausted")
        total_cost = self.cost_used_usd + self.cost_reserved_usd + cost
        if self.max_cost_usd and total_cost > self.max_cost_usd:
            raise LLMExecutionLimitError("run_llm_cost_budget_exhausted")
        # Other unfinished segments keep their allowance. The current segment
        # can use its own allowance plus unprotected headroom, never another's.
        protected = self.protected_tokens(phase)
        if ((self.max_tokens and self.tokens_used + self.tokens_reserved + tokens + protected > self.max_tokens)
                or self.calls + 1 + self.protected_calls(phase) > self.max_calls
                or (self.max_cost_usd and total_cost + protected * max(
                    self.input_usd_per_million, self.output_usd_per_million) / 1_000_000 > self.max_cost_usd)):
            raise LLMExecutionLimitError("run_llm_budget_reserved_for_delivery")
        if phase in self.delivery_reserves:
            self.delivery_charged[phase] = self.delivery_charged.get(phase, 0) + tokens
            self.delivery_calls[phase] = self.delivery_calls.get(phase, 0) + 1
        self.calls += 1
        self.repairs += int(is_repair)
        self.tokens_reserved += tokens
        self.cost_reserved_usd += cost


@dataclass
class LLMCallExecution:
    budget: RunLLMBudget
    is_repair: bool
    phase: str | None = None
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
                            max_output_tokens=self.max_output_tokens, phase=self.phase)
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
        if self.phase in self.budget.delivery_reserves:
            self.budget.delivery_charged[self.phase] += tokens - self.input_tokens - self.max_output_tokens
        self.budget.tokens_used += tokens
        self.budget.cost_used_usd += cost
        self.tokens_charged += tokens
        self.cost_charged_usd += cost
        self.budget.reservation_settled.set()
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

    def metadata(self) -> dict[str, int | float | bool | str]:
        return {
            "delivery_tokens_protected": self.budget.protected_tokens(self.phase),
            "delivery_calls_protected": self.budget.protected_calls(self.phase),
            "llm_request_attempts": self.attempts,
            "llm_transport_attempts": self.transport_attempts,
            "llm_admission_status": "admitted" if self.attempts else "rejected",
            "llm_phase": self.phase or "unallocated",
            "stage_headroom_tokens": self.budget.stage_headroom,
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
