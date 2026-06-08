from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from packages.research.models import (
    EvidenceItem,
    NormalizedEvidenceField,
    NormalizedFeatureField,
    NormalizedPersonaField,
    NormalizedPricingField,
)


def normalized_fields_from_evidence_items(
    evidence_items: Iterable[EvidenceItem],
) -> list[NormalizedEvidenceField]:
    accepted = [item for item in evidence_items if item.status == "accepted"]
    return [
        *normalized_pricing_fields_from_evidence_items(accepted),
        *normalized_feature_fields_from_evidence_items(accepted),
        *normalized_persona_fields_from_evidence_items(accepted),
    ]


def normalized_pricing_fields_from_evidence_items(
    evidence_items: Iterable[EvidenceItem],
) -> list[NormalizedPricingField]:
    pricing_items = [
        item
        for item in evidence_items
        if item.status == "accepted" and "pricing" in item.dimension.casefold()
    ]
    if not pricing_items:
        return []

    model_type = _first_text(pricing_items, "pricing_model_type")
    tier_names = _list_texts(pricing_items, "tier_names")
    prices = _list_texts(pricing_items, "price_points")
    billing_cycles = _list_texts(pricing_items, "billing_cycle")
    usage_limits = _list_texts(pricing_items, "usage_limits")
    enterprise_condition = _first_text(pricing_items, "enterprise_condition")
    rows = max(1, len(tier_names), len(prices), len(billing_cycles), len(usage_limits))
    best_quote = _best_quote(pricing_items, preferred_fields=("price_points", "pricing_model_type"))
    evidence_ids = [item.id for item in pricing_items]
    competitor = _first_attr(pricing_items, "competitor")
    confidence = max((item.confidence for item in pricing_items), default=0.0)
    source_url = _first_attr(pricing_items, "source_url") or None

    return [
        NormalizedPricingField(
            competitor=competitor,
            model_type=model_type,
            tier_name=_nth_or_empty(tier_names, index),
            price=_nth_or_empty(prices, index),
            billing_cycle=_nth_or_empty(billing_cycles, index),
            usage_limit=_nth_or_empty(usage_limits, index),
            enterprise_condition=enterprise_condition,
            source_quote=best_quote,
            evidence_item_ids=evidence_ids,
            source_url=source_url,
            confidence=confidence,
        )
        for index in range(rows)
    ]


def normalized_feature_fields_from_evidence_items(
    evidence_items: Iterable[EvidenceItem],
) -> list[NormalizedFeatureField]:
    fields: list[NormalizedFeatureField] = []
    for item in evidence_items:
        if item.status != "accepted" or "feature" not in item.dimension.casefold():
            continue
        value = item.value
        if not isinstance(value, Mapping):
            continue
        status = str(value.get("status") or "").strip()
        if not status or status in {"not_found_in_source", "not_applicable"}:
            continue
        fields.append(
            NormalizedFeatureField(
                competitor=item.competitor,
                slot=item.field,
                support_level=status,
                evidence_terms=_string_list(value.get("evidence_terms")),
                evidence_quote=item.quote.strip(),
                evidence_item_ids=[item.id],
                source_url=item.source_url,
                confidence=item.confidence,
            )
        )
    return fields


def normalized_persona_fields_from_evidence_items(
    evidence_items: Iterable[EvidenceItem],
) -> list[NormalizedPersonaField]:
    persona_items = [
        item
        for item in evidence_items
        if item.status == "accepted"
        and ("persona" in item.dimension.casefold() or "user" in item.dimension.casefold())
    ]
    if not persona_items:
        return []

    quote = _best_quote(
        persona_items,
        preferred_fields=(
            "primary_use_case",
            "buyer_or_user_role",
            "target_segment",
            "switching_trigger",
        ),
    )
    if not any(item.value for item in persona_items) and not quote:
        return []
    return [
        NormalizedPersonaField(
            competitor=_first_attr(persona_items, "competitor"),
            segment=_first_text(persona_items, "target_segment"),
            role=_first_text(persona_items, "buyer_or_user_role"),
            company_size=_first_text(persona_items, "company_size"),
            use_case=_first_text(persona_items, "primary_use_case"),
            pain_point=_first_text(persona_items, "switching_trigger"),
            confidence_reason=_first_text(persona_items, "confidence_reason"),
            evidence_quote=quote,
            evidence_item_ids=[item.id for item in persona_items],
            source_url=_first_attr(persona_items, "source_url") or None,
            confidence=max((item.confidence for item in persona_items), default=0.0),
        )
    ]


def normalized_fields_as_dicts(
    fields: Iterable[NormalizedEvidenceField],
) -> list[dict[str, Any]]:
    return [field.model_dump(mode="json") for field in fields]


def normalized_fields_from_source(source: object) -> list[dict[str, Any]]:
    metadata = _source_metadata(source)
    raw_fields = metadata.get("normalized_fields")
    if not isinstance(raw_fields, list):
        return []
    fields: list[dict[str, Any]] = []
    for raw_field in raw_fields:
        if isinstance(raw_field, Mapping):
            fields.append({str(key): value for key, value in raw_field.items()})
    return fields


def normalized_summary_from_source(
    source: object,
    *,
    dimension: str = "",
    limit: int = 260,
) -> str:
    source_dimension = dimension or str(_source_value(source, "dimension") or "")
    summaries = [
        summary
        for field in normalized_fields_from_source(source)
        if _field_matches_dimension(field, source_dimension)
        for summary in [_summary_for_field(field)]
        if summary
    ]
    return " ".join(summaries)[:limit].strip()


def _field_matches_dimension(field: Mapping[str, Any], dimension: str) -> bool:
    if not dimension:
        return True
    kind = str(field.get("kind") or field.get("dimension") or "").casefold()
    dimension_key = dimension.casefold()
    return kind in dimension_key or dimension_key in kind


def _summary_for_field(field: Mapping[str, Any]) -> str:
    kind = str(field.get("kind") or "").casefold()
    if kind == "pricing":
        parts = [
            _labeled("pricing model", field.get("model_type")),
            _labeled("tier", field.get("tier_name")),
            _labeled("price", field.get("price")),
            _labeled("billing", field.get("billing_cycle")),
            _labeled("limit", field.get("usage_limit")),
            _labeled("enterprise", field.get("enterprise_condition")),
            _labeled("evidence quote", field.get("source_quote")),
        ]
        return "; ".join(part for part in parts if part)
    if kind == "feature":
        terms = _string_list(field.get("evidence_terms"))
        parts = [
            _labeled("feature slot", field.get("slot")),
            _labeled("support", field.get("support_level")),
            _labeled("terms", ", ".join(terms)),
            _labeled("evidence quote", field.get("evidence_quote")),
        ]
        return "; ".join(part for part in parts if part)
    if kind == "persona":
        parts = [
            _labeled("segment", field.get("segment")),
            _labeled("role", field.get("role")),
            _labeled("company size", field.get("company_size")),
            _labeled("use case", field.get("use_case")),
            _labeled("pain point", field.get("pain_point")),
            _labeled("confidence reason", field.get("confidence_reason")),
            _labeled("evidence quote", field.get("evidence_quote")),
        ]
        return "; ".join(part for part in parts if part)
    return ""


def _labeled(label: str, value: object) -> str:
    text = str(value or "").strip()
    return f"{label}: {text}" if text else ""


def _first_text(items: list[EvidenceItem], field: str) -> str:
    for item in items:
        if item.field == field:
            value = _first_value(item.value)
            if value:
                return value
    return ""


def _list_texts(items: list[EvidenceItem], field: str) -> list[str]:
    values: list[str] = []
    for item in items:
        if item.field == field:
            values.extend(_string_list(item.value))
    return _dedupe_keep_order(values)


def _first_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        for key in ("name", "value", "label", "status"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    values = _string_list(value)
    return values[0] if values else ""


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        values: list[str] = []
        for item in value.values():
            values.extend(_string_list(item))
        return values
    if isinstance(value, Iterable):
        values: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
            elif not isinstance(item, str):
                text = str(item).strip()
                if text:
                    values.append(text)
        return values
    text = str(value).strip()
    return [text] if text else []


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _nth_or_empty(values: list[str], index: int) -> str:
    if not values:
        return ""
    if index < len(values):
        return values[index]
    return values[-1]


def _best_quote(items: list[EvidenceItem], *, preferred_fields: tuple[str, ...]) -> str:
    ordered = [
        *[item for field in preferred_fields for item in items if item.field == field],
        *items,
    ]
    for item in ordered:
        quote = item.quote.strip()
        if quote:
            return quote
    return ""


def _first_attr(items: list[EvidenceItem], field: str) -> str:
    for item in items:
        value = getattr(item, field, None)
        if value:
            return str(value)
    return ""


def _source_metadata(source: object) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        metadata = source.get("metadata")
    else:
        metadata = getattr(source, "metadata", None)
    return metadata if isinstance(metadata, Mapping) else {}


def _source_value(source: object, field: str) -> object:
    if isinstance(source, Mapping):
        return source.get(field)
    return getattr(source, field, None)
