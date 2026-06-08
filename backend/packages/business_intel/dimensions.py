from __future__ import annotations

from packages.schema.enterprise import BusinessIntelPlan


def effective_analysis_dimensions(plan: BusinessIntelPlan) -> list[str]:
    """Return required scenario dimensions plus project-specific accepted dimensions."""

    return _unique_dimensions(
        [*plan.scenario_pack.required_dimensions, *plan.requested_dimensions]
    )


def _unique_dimensions(dimensions: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for dimension in dimensions:
        key = dimension.casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(dimension)
    return result
