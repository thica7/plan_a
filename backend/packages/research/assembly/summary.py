from __future__ import annotations

from typing import Any

from packages.research.assembly.matrix import field_matrix_from_evidence_items
from packages.research.assembly.report import assemble_research_report
from packages.research.evidence import accepted_evidence_items, rejected_evidence_items
from packages.research.models import EvidenceItem, QualityGap, RepairTask, ResearchBrief


def assemble_research_summary(
    brief: ResearchBrief,
    *,
    evidence_items: list[EvidenceItem],
    gaps: list[QualityGap],
    repair_tasks: list[RepairTask],
) -> dict[str, Any]:
    accepted = accepted_evidence_items(evidence_items)
    rejected = rejected_evidence_items(evidence_items)
    fields = field_matrix_from_evidence_items(evidence_items)
    report = assemble_research_report(
        brief,
        fields=fields,
        gaps=gaps,
        repair_tasks=repair_tasks,
    )
    return {
        "branch_key": brief.branch_key,
        "competitor": brief.competitor,
        "dimension": brief.dimension,
        "report": report,
        "accepted_field_count": len(fields),
        "accepted_evidence_item_count": len(accepted),
        "rejected_evidence_item_count": len(rejected),
        "gap_count": len(gaps),
        "repair_task_count": len(repair_tasks),
        "fields": fields,
        "gap_ids": [gap.id for gap in gaps],
        "repair_task_ids": [task.id for task in repair_tasks],
    }
