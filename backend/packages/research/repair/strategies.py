from __future__ import annotations

from packages.research.models import QualityGap, RepairTask


def repair_task_from_gap(gap: QualityGap) -> RepairTask:
    target_fields = target_fields_from_gap(gap)
    return RepairTask(
        gap_id=gap.id,
        strategy=gap.suggested_action,
        competitor=gap.competitor,
        dimension=gap.dimension,
        target_fields=target_fields,
        query_hints=query_hints_for_gap(gap, target_fields),
        acceptance_rule=gap.acceptance_rule,
        metadata={"gap_reason": gap.reason, "severity": gap.severity},
    )


def query_hints_for_gap(gap: QualityGap, fields: list[str]) -> list[str]:
    competitor = gap.competitor or ""
    field_phrase = " ".join(fields).replace("_", " ").strip()
    dimension_phrase = gap.dimension.replace("_", " ")
    if gap.suggested_action == "pricing_model_repair":
        intents = [
            "official pricing plans billing",
            "API pricing token usage limits",
            "enterprise pricing official",
        ]
    elif gap.suggested_action == "feature_slot_repair":
        intents = [
            f"official docs {field_phrase}",
            "product features developer documentation",
            "enterprise features official docs",
        ]
    elif gap.suggested_action == "persona_schema_repair":
        intents = [
            "customer story use case official",
            "case study enterprise customers",
            "solutions teams developers use cases",
        ]
    elif gap.suggested_action == "mark_not_applicable":
        intents = [
            "license terms model card official",
            "self hosted open weight license official",
        ]
    else:
        intents = [f"official {dimension_phrase} {field_phrase}".strip()]
    return _dedupe(
        [
            " ".join(part for part in (competitor, intent, field_phrase) if part).strip()
            for intent in intents
        ]
    )


def target_fields_from_gap(gap: QualityGap) -> list[str]:
    if not gap.field:
        return []
    return [part.strip() for part in gap.field.split(",") if part.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped
