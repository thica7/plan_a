from __future__ import annotations

from packages.research.models import EvidenceItem


def citation_refs_from_evidence_items(items: list[EvidenceItem]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    sorted_items = sorted(items, key=lambda value: value.confidence, reverse=True)
    for index, item in enumerate(sorted_items, 1):
        refs.append(
            {
                "ref": f"S{index}",
                "evidence_item_id": item.id,
                "source_url": item.source_url,
                "field": item.field,
                "confidence": item.confidence,
                "quote": item.quote,
            }
        )
    return refs


def snippet_from_evidence_items(
    items: list[EvidenceItem],
    *,
    fallback: str = "",
    limit: int = 900,
) -> str:
    quotes = [
        " ".join(item.quote.split())
        for item in sorted(items, key=lambda value: value.confidence, reverse=True)
        if item.quote
    ]
    if quotes:
        return " ".join(quotes)[:limit]
    return fallback[:limit]
