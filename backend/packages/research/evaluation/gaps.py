from __future__ import annotations

from packages.research.extraction.feature import FEATURE_SLOTS
from packages.research.extraction.persona import PERSONA_FIELDS
from packages.research.extraction.pricing import PRICING_FIELDS
from packages.research.models import EvidenceItem, ExtractionResult, QualityGap, ResearchBrief

_OPTIONAL_PRICING_FIELDS_FOR_OPEN_WEIGHT = {
    "tier_names",
    "price_points",
    "billing_cycle",
    "usage_limits",
    "enterprise_condition",
}


def quality_gaps_from_extractions(
    brief: ResearchBrief,
    extractions: list[ExtractionResult],
) -> list[QualityGap]:
    relevant = [
        extraction
        for extraction in extractions
        if extraction.competitor == brief.competitor and extraction.dimension == brief.dimension
    ]
    if not relevant:
        return [
            QualityGap(
                severity="blocker",
                dimension=brief.dimension,
                competitor=brief.competitor,
                reason="No extraction result exists for this competitor and dimension.",
                suggested_action="targeted_discovery",
                acceptance_rule="At least one captured source must produce a non-empty extraction.",
            )
        ]

    merged_fields = _merge_fields(relevant)
    missing_fields = _merged_missing_fields(relevant)
    key = brief.dimension.casefold()
    if "pricing" in key:
        gaps = _pricing_gaps(brief, merged_fields, missing_fields, relevant)
    elif "persona" in key or "user" in key or "buyer" in key:
        gaps = _persona_gaps(brief, merged_fields, missing_fields, relevant)
    else:
        gaps = _feature_gaps(brief, merged_fields, relevant)
    return _dedupe_gaps(gaps)


def quality_gaps_from_admitted_evidence(
    brief: ResearchBrief,
    extractions: list[ExtractionResult],
    evidence_items: list[EvidenceItem],
) -> list[QualityGap]:
    relevant_items = [
        item
        for item in evidence_items
        if item.competitor == brief.competitor and item.dimension == brief.dimension
    ]
    accepted = [item for item in relevant_items if item.status == "accepted"]
    rejected = [item for item in relevant_items if item.status == "rejected"]
    if not relevant_items:
        return []
    if not accepted:
        return [
            QualityGap(
                severity="blocker",
                dimension=brief.dimension,
                competitor=brief.competitor,
                reason=(
                    "Extraction produced fields, but no field-level evidence passed "
                    "admission."
                ),
                suggested_action=_repair_strategy_for_dimension(brief.dimension),
                acceptance_rule=(
                    "At least one extracted field must have accepted evidence from "
                    "an ok captured page and a field-level quote."
                ),
                source_ids=[item.captured_page_id for item in rejected],
                metadata={
                    "source": "evidence_admission",
                    "rejected_evidence_item_ids": [item.id for item in rejected],
                },
            )
        ]

    expected_fields = _evidence_expected_fields(extractions, brief)
    accepted_fields = {item.field for item in accepted}
    missing_accepted_fields = sorted(expected_fields - accepted_fields)
    if not missing_accepted_fields:
        return []
    severity = "blocker" if _dimension_requires_field_support(brief.dimension) else "warn"
    return [
        QualityGap(
            severity=severity,
            dimension=brief.dimension,
            competitor=brief.competitor,
            field=",".join(missing_accepted_fields),
            reason=(
                "Field-level evidence admission rejected or could not bind accepted "
                f"support for: {', '.join(missing_accepted_fields)}."
            ),
            suggested_action=_repair_strategy_for_dimension(brief.dimension),
            acceptance_rule=(
                "Every extracted required field must either have accepted evidence "
                "or be explicitly marked not applicable."
            ),
            source_ids=[item.captured_page_id for item in rejected],
            metadata={
                "source": "evidence_admission",
                "accepted_evidence_item_ids": [item.id for item in accepted],
                "rejected_evidence_item_ids": [item.id for item in rejected],
            },
        )
    ]


def _pricing_gaps(
    brief: ResearchBrief,
    fields: dict[str, object],
    missing_fields: set[str],
    extractions: list[ExtractionResult],
) -> list[QualityGap]:
    model_type = str(fields.get("pricing_model_type") or "")
    if model_type in {"open_weight_self_hosted", "license_based", "not_applicable"}:
        missing_fields -= _OPTIONAL_PRICING_FIELDS_FOR_OPEN_WEIGHT
        if not fields.get("not_applicable_reason") and not any(
            extraction.not_applicable_reason for extraction in extractions
        ):
            return [
                QualityGap(
                    severity="warn",
                    dimension=brief.dimension,
                    competitor=brief.competitor,
                    field="not_applicable_reason",
                    reason=(
                        "Pricing is not directly comparable but no explicit "
                        "not-applicable explanation was produced."
                    ),
                    suggested_action="mark_not_applicable",
                    acceptance_rule="Explain why SaaS/API tier extraction is not applicable.",
                    source_ids=[extraction.captured_page_id for extraction in extractions],
                )
            ]

    actionable = [
        field
        for field in PRICING_FIELDS
        if field in missing_fields and field not in {"billing_cycle"}
    ]
    if not actionable:
        return []
    return [
        QualityGap(
            severity="blocker" if "pricing_model_type" in actionable else "warn",
            dimension=brief.dimension,
            competitor=brief.competitor,
            field=",".join(actionable),
            reason=f"Pricing extraction is missing structured field(s): {', '.join(actionable)}.",
            suggested_action="pricing_model_repair",
            acceptance_rule=(
                "Collect or derive pricing model type, tiers or price evidence "
                "from verified public sources."
            ),
            source_ids=[extraction.captured_page_id for extraction in extractions],
        )
    ]


def _feature_gaps(
    brief: ResearchBrief,
    fields: dict[str, object],
    extractions: list[ExtractionResult],
) -> list[QualityGap]:
    missing_slots = [
        slot
        for slot in FEATURE_SLOTS
        if not isinstance(fields.get(slot), dict)
        or fields[slot].get("status") == "not_found_in_source"
    ]
    if not missing_slots:
        return []
    severity = "blocker" if len(missing_slots) > len(FEATURE_SLOTS) // 2 else "warn"
    return [
        QualityGap(
            severity=severity,
            dimension=brief.dimension,
            competitor=brief.competitor,
            field=",".join(missing_slots),
            reason=(
                "Feature slot matrix is missing public evidence for: "
                f"{', '.join(missing_slots)}."
            ),
            suggested_action="feature_slot_repair",
            acceptance_rule=(
                "Collect verified docs that cover the missing feature slot(s), "
                "or mark unsupported with evidence."
            ),
            source_ids=[extraction.captured_page_id for extraction in extractions],
        )
    ]


def _persona_gaps(
    brief: ResearchBrief,
    fields: dict[str, object],
    missing_fields: set[str],
    extractions: list[ExtractionResult],
) -> list[QualityGap]:
    actionable = [field for field in PERSONA_FIELDS if field in missing_fields]
    if not actionable:
        return []
    return [
        QualityGap(
            severity="warn",
            dimension=brief.dimension,
            competitor=brief.competitor,
            field=",".join(actionable),
            reason=f"Persona schema is missing public evidence for: {', '.join(actionable)}.",
            suggested_action="persona_schema_repair",
            acceptance_rule=(
                "Collect customer story, use-case, solution, or public community "
                "evidence for missing persona fields."
            ),
            source_ids=[extraction.captured_page_id for extraction in extractions],
        )
    ]


def _merge_fields(extractions: list[ExtractionResult]) -> dict[str, object]:
    merged: dict[str, object] = {}
    for extraction in sorted(extractions, key=lambda item: item.confidence, reverse=True):
        for field, value in extraction.fields.items():
            if field not in merged or _empty(merged[field]):
                merged[field] = value
    for extraction in extractions:
        if extraction.not_applicable_reason and not merged.get("not_applicable_reason"):
            merged["not_applicable_reason"] = extraction.not_applicable_reason
    return merged


def _merged_missing_fields(extractions: list[ExtractionResult]) -> set[str]:
    missing = set().union(*(set(extraction.missing_fields) for extraction in extractions))
    for extraction in extractions:
        for field, value in extraction.fields.items():
            if not _empty(value):
                missing.discard(field)
    return missing


def _empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return False


def _dedupe_gaps(gaps: list[QualityGap]) -> list[QualityGap]:
    seen: set[tuple[str, str | None, str | None, str]] = set()
    deduped: list[QualityGap] = []
    for gap in gaps:
        key = (gap.dimension, gap.competitor, gap.field, gap.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return deduped


def _evidence_expected_fields(
    extractions: list[ExtractionResult],
    brief: ResearchBrief,
) -> set[str]:
    expected: set[str] = set(brief.required_fields)
    for extraction in extractions:
        if extraction.competitor != brief.competitor or extraction.dimension != brief.dimension:
            continue
        for field, value in extraction.fields.items():
            if field == "confidence_reason":
                continue
            if _empty(value):
                continue
            if isinstance(value, dict) and value.get("status") in {"not_found_in_source"}:
                continue
            expected.add(field)
    return expected


def _repair_strategy_for_dimension(dimension: str) -> str:
    key = dimension.casefold()
    if "pricing" in key:
        return "pricing_model_repair"
    if "persona" in key or "user" in key or "buyer" in key:
        return "persona_schema_repair"
    return "feature_slot_repair"


def _dimension_requires_field_support(dimension: str) -> bool:
    return "pricing" in dimension.casefold()
