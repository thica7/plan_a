from __future__ import annotations

from packages.research.models import QualityGap, RepairTask
from packages.research.repair.strategies import repair_task_from_gap


def repair_tasks_from_gaps(gaps: list[QualityGap]) -> list[RepairTask]:
    return [repair_task_from_gap(gap) for gap in gaps if gap.severity in {"warn", "blocker"}]
