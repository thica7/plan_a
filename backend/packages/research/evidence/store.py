from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from packages.research.models import EvidenceItem

T = TypeVar("T")


def dedupe_by_id(items: Iterable[T]) -> list[T]:
    seen: set[str] = set()
    deduped: list[T] = []
    for item in items:
        item_id = str(getattr(item, "id", "") or "")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        deduped.append(item)
    return deduped


def accepted_evidence_items(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    return [item for item in items if item.status == "accepted"]


def rejected_evidence_items(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    return [item for item in items if item.status == "rejected"]


def accepted_evidence_by_page(items: Iterable[EvidenceItem]) -> dict[str, list[EvidenceItem]]:
    grouped: dict[str, list[EvidenceItem]] = {}
    for item in accepted_evidence_items(items):
        grouped.setdefault(item.captured_page_id, []).append(item)
    return grouped
