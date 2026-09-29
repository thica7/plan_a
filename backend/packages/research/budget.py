from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ResearchDepth = Literal["quick", "standard", "deep"]
ANALYST_ONE_SHOT_FANOUT_SLICES = 8
PLANNER_LLM_RESERVED_CALLS = 2
OTHER_PRE_WRITER_LLM_RESERVED_CALLS = 4


@dataclass(frozen=True)
class ResearchDepthBudget:
    competitor_limit: int
    target_sources: int
    max_search_queries: int
    max_candidates: int
    max_fetches: int
    max_advanced_fetches: int
    max_repair_rounds: int
    llm_max_calls: int
    report_chars: str
    max_slices: int
    collector_max_turns: int
    analyst_max_turns: int
    writer_reserved_calls: int

    def allowed_slices(self, deployment_llm_max_calls: int) -> int:
        available_calls = (
            min(max(1, deployment_llm_max_calls), self.llm_max_calls)
            - self.writer_reserved_calls
            - PLANNER_LLM_RESERVED_CALLS
            - OTHER_PRE_WRITER_LLM_RESERVED_CALLS
        )
        allowed = 0
        for slices in range(1, self.max_slices + 1):
            analyst_turns = (
                1 if slices > ANALYST_ONE_SHOT_FANOUT_SLICES
                else self.analyst_max_turns + 1
            )
            if slices * (self.collector_max_turns + 1 + analyst_turns) > available_calls:
                break
            allowed = slices
        return allowed


RESEARCH_DEPTH_BUDGETS: dict[ResearchDepth, ResearchDepthBudget] = {
    "quick": ResearchDepthBudget(2, 2, 1, 6, 3, 1, 0, 60, "4,000-6,000", 6, 1, 1, 20),
    "standard": ResearchDepthBudget(5, 3, 2, 10, 5, 2, 1, 120, "8,000-12,000", 12, 2, 2, 24),
    "deep": ResearchDepthBudget(8, 5, 3, 16, 8, 3, 2, 160, "16,000-20,000", 24, 3, 3, 32),
}


def research_depth_budget(depth: ResearchDepth | None) -> ResearchDepthBudget | None:
    return RESEARCH_DEPTH_BUDGETS[depth] if depth is not None else None
