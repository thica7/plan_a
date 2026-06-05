from __future__ import annotations

from packages.research.models import EvidenceItem, ExtractionResult


def evidence_items_from_extractions(
    extractions: list[ExtractionResult],
    *,
    min_accept_confidence: float = 0.35,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for extraction in extractions:
        quote_by_field = {
            quote.field: quote.text for quote in extraction.quotes if quote.field and quote.text
        }
        for field, value in extraction.fields.items():
            if _empty(value):
                continue
            quote = quote_by_field.get(field, "")
            status = "accepted" if extraction.confidence >= min_accept_confidence else "rejected"
            items.append(
                EvidenceItem(
                    competitor=extraction.competitor,
                    dimension=extraction.dimension,
                    field=field,
                    value=value,
                    source_candidate_id=extraction.source_candidate_id,
                    captured_page_id=extraction.captured_page_id,
                    source_url=_source_url_for_field(extraction, field),
                    quote=quote,
                    confidence=extraction.confidence,
                    status=status,
                    rejection_reason=(
                        None
                        if status == "accepted"
                        else (
                            "Extraction confidence is below field-level admission threshold "
                            f"{min_accept_confidence:.2f}."
                        )
                    ),
                    metadata={"extraction_id": extraction.id},
                )
            )
    return items


def _source_url_for_field(extraction: ExtractionResult, field: str) -> str | None:
    for quote in extraction.quotes:
        if quote.field == field and quote.source_url:
            return quote.source_url
    return None


def _empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return False
