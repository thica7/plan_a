from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ResearchDepth = Literal["quick", "standard", "deep"]


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


RESEARCH_DEPTH_BUDGETS: dict[ResearchDepth, ResearchDepthBudget] = {
    "quick": ResearchDepthBudget(2, 2, 1, 6, 3, 1, 0, 60, "4,000-6,000"),
    "standard": ResearchDepthBudget(5, 3, 2, 10, 5, 2, 1, 120, "8,000-12,000"),
    "deep": ResearchDepthBudget(8, 5, 3, 16, 8, 3, 2, 160, "16,000-20,000"),
}


def research_depth_budget(depth: ResearchDepth | None) -> ResearchDepthBudget | None:
    return RESEARCH_DEPTH_BUDGETS[depth] if depth is not None else None
