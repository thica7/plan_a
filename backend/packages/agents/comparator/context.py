"""Replace exact repeated evidence values with references to the current view."""

from __future__ import annotations

from packages.research.evidence.snapshot_models import canonical_json


def compact_analysis_context(payload: object, facts) -> object:
    references = {}
    ambiguous = set()
    protected = {
        "qualifiers",
        "source_ids",
        "source_id",
        "competitor",
        "dimension",
        "market",
        "unit",
        "status",
    }
    for fact in facts:
        for field in ("value", "quote"):
            value = getattr(fact, field)
            if not isinstance(value, (str, dict, list)) or not value:
                continue
            key = canonical_json(value)
            reference = references.setdefault(key, {"evidence_fact_refs": [], "field": field})
            if reference["field"] != field:
                ambiguous.add(key)
            if reference["field"] == field and fact.id not in reference["evidence_fact_refs"]:
                reference["evidence_fact_refs"].append(fact.id)

    def contains_conditions(value):
        if isinstance(value, dict):
            return bool(protected.intersection(value)) or any(
                contains_conditions(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(contains_conditions(item) for item in value)
        return False

    def walk(value):
        key = canonical_json(value)
        reference = references.get(key)
        if (
            reference is not None
            and key not in ambiguous
            and not contains_conditions(value)
            and len(canonical_json(reference)) < len(key)
        ):
            return {
                "evidence_fact_refs": list(reference["evidence_fact_refs"]),
                "field": reference["field"],
            }
        if isinstance(value, dict):
            # Keep the comparison basis and citation scope directly readable.
            return {name: item if name in protected else walk(item) for name, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(payload)
