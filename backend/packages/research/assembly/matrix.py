from __future__ import annotations

from typing import Any

from packages.research.evidence import (
    accepted_evidence_items,
    citation_refs_from_evidence_items,
    rejected_evidence_items,
)
from packages.research.models import EvidenceItem


def field_matrix_from_evidence_items(
    evidence_items: list[EvidenceItem],
) -> list[dict[str, Any]]:
    rejected_by_field: dict[str, int] = {}
    for item in rejected_evidence_items(evidence_items):
        rejected_by_field[item.field] = rejected_by_field.get(item.field, 0) + 1

    accepted_by_field: dict[str, list[EvidenceItem]] = {}
    for item in accepted_evidence_items(evidence_items):
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
                "citations": citation_refs_from_evidence_items(items),
            }
        )
    return fields
