from __future__ import annotations

from typing import Any

from packages.research.models import QualityGap, RepairTask, ResearchBrief


def assemble_research_report(
    brief: ResearchBrief,
    *,
    fields: list[dict[str, Any]],
    gaps: list[QualityGap],
    repair_tasks: list[RepairTask],
) -> dict[str, Any]:
    return {
        "title": f"{brief.competitor} {brief.dimension} research brief",
        "status": "needs_repair" if gaps else "ready",
        "summary": _summary(brief, fields, gaps),
        "field_count": len(fields),
        "gap_count": len(gaps),
        "repair_task_count": len(repair_tasks),
    }


def _summary(
    brief: ResearchBrief,
    fields: list[dict[str, Any]],
    gaps: list[QualityGap],
) -> str:
    if gaps:
        return (
            f"{brief.competitor} / {brief.dimension} has {len(fields)} accepted "
            f"field(s) and {len(gaps)} remaining quality gap(s)."
        )
    return (
        f"{brief.competitor} / {brief.dimension} has {len(fields)} accepted "
        "field(s) and no remaining quality gaps."
    )
