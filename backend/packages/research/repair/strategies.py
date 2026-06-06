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
        metadata={"gap_reason": gap.reason, "severity": gap.severity, **gap.metadata},
    )


def query_hints_for_gap(gap: QualityGap, fields: list[str]) -> list[str]:
    competitor = gap.competitor or ""
    field_phrase = " ".join(fields).replace("_", " ").strip()
    dimension_phrase = gap.dimension.replace("_", " ")
    required_action = str(gap.metadata.get("required_action") or "")
    claim_ids = [str(item) for item in gap.metadata.get("claim_ids", []) if str(item)]
    if required_action == "delete":
        return _dedupe([f"remove unsupported claim {' '.join(claim_ids)}".strip()])
    if required_action in {"downgrade", "rewrite_report_section"}:
        return _dedupe([f"rewrite caveat claim {' '.join(claim_ids)}".strip()])
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
        issue_metadata = gap.metadata.get("issue_metadata")
        issue_types: list[str] = []
        if isinstance(issue_metadata, dict):
            issue_types = [
                str(item).replace("_", " ")
                for item in issue_metadata.get("claim_validation_issue_types", [])
                if str(item)
            ]
        issue_phrase = " ".join(issue_types)
        intents = [
            f"official {dimension_phrase} {field_phrase} {issue_phrase}".strip(),
            f"verified evidence {dimension_phrase} {field_phrase}".strip(),
        ]
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
