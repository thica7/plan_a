from __future__ import annotations

from typing import Any

from packages.research.models import EvidenceItem, QualityGap, RepairTask, ResearchBrief


def assemble_research_summary(
    brief: ResearchBrief,
    *,
    evidence_items: list[EvidenceItem],
    gaps: list[QualityGap],
    repair_tasks: list[RepairTask],
) -> dict[str, Any]:
    accepted = [item for item in evidence_items if item.status == "accepted"]
    rejected = [item for item in evidence_items if item.status == "rejected"]
    fields = _field_summaries(accepted, rejected)
    return {
        "branch_key": brief.branch_key,
        "competitor": brief.competitor,
        "dimension": brief.dimension,
        "accepted_field_count": len(fields),
        "accepted_evidence_item_count": len(accepted),
        "rejected_evidence_item_count": len(rejected),
        "gap_count": len(gaps),
        "repair_task_count": len(repair_tasks),
        "fields": fields,
        "gap_ids": [gap.id for gap in gaps],
        "repair_task_ids": [task.id for task in repair_tasks],
    }


def _field_summaries(
    accepted: list[EvidenceItem],
    rejected: list[EvidenceItem],
) -> list[dict[str, Any]]:
    rejected_by_field: dict[str, int] = {}
    for item in rejected:
        rejected_by_field[item.field] = rejected_by_field.get(item.field, 0) + 1

    accepted_by_field: dict[str, list[EvidenceItem]] = {}
    for item in accepted:
        accepted_by_field.setdefault(item.field, []).append(item)

    fields: list[dict[str, Any]] = []
    for field, items in sorted(accepted_by_field.items()):
        top = sorted(items, key=lambda item: item.confidence, reverse=True)[0]
        fields.append(
            {
                "field": field,
                "value": top.value,
                "confidence": top.confidence,
                "source_url": top.source_url,
                "quote": top.quote,
                "accepted_count": len(items),
                "rejected_count": rejected_by_field.get(field, 0),
                "evidence_item_ids": [item.id for item in items],
            }
        )
    return fields
