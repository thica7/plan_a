"""Deterministic, read-only checks of what a selected evidence view can answer.

This checks structured evidence completeness. It neither calculates prices/costs
nor certifies that arbitrary prose follows from the allowed facts.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, time

from packages.research.evidence.answer_models import (
    AnswerBoundary,
    AnswerRequirement,
    FactDecision,
)
from packages.research.evidence.snapshot_models import (
    EvidenceFact,
    EvidenceSource,
    StageEvidenceView,
    canonical_json,
)

_SIGNAL_TYPES = {"report", "webpage_search", "web_search_result", "llm_public_knowledge"}
_SOURCE_DATES = (
    "source_published_at",
    "source_updated_at",
    "source_fetched_at",
    "last_verified_at",
)
_FACT_DATES = (
    "verified_at",
    "last_verified_at",
    "published_at",
    "updated_at",
    "observed_at",
    "effective_at",
    "effective_date",
    "charge_date",
    "source_published_at",
    "source_updated_at",
    "source_fetched_at",
)
_COMPLIANCE_FIELDS = ("industry", "jurisdiction", "compliance_standard", "intended_use")


def _present(value: object) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    return not isinstance(value, str) or value.strip().casefold() not in {
        "",
        "unknown",
        "n/a",
        "unspecified",
        "not known",
    }


def _text(value: object) -> bool:
    return isinstance(value, str) and _present(value)


def _capacity(value: object) -> bool:
    return _text(value) or (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and value > 0
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _same(left: object, right: object) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.strip().casefold() == right.strip().casefold()
    return canonical_json(left) == canonical_json(right)


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo is not None else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return _day(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            pass
    return None


def _timestamp(value: object, *, end_of_day: bool = False) -> datetime | None:
    """Date-only boundaries cover the UTC day; time boundaries require an offset."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return datetime.combine(
                date.fromisoformat(value), time.max if end_of_day else time.min, tzinfo=UTC
            )
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        return ()
    if any(not isinstance(item, str) or not _present(item) for item in value):
        return ()
    return tuple(sorted(set(item.strip() for item in value)))


def _currency(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value) is not None


def _amount(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
        and value >= 0
    )


def _money_fields(fact: EvidenceFact) -> dict[str, object]:
    """Only recorded structured fields supply amounts and price qualifiers."""
    value = fact.value
    fields = {
        key: value[key]
        for key in ("amount", "currency", "unit", "tier_name", "billing_cycle")
        if isinstance(value, dict) and key in value
    }
    fields.update(fact.qualifiers)
    if not _present(fields.get("currency")):
        unit = fields.get("unit") or fact.unit
        if _currency(unit):
            fields["currency"] = unit
    if not _present(fields.get("plan")):
        fields["plan"] = fields.get("tier_name")
    if not _present(fields.get("billing_interval")):
        fields["billing_interval"] = fields.get("billing_cycle")
    return fields


def _is_money(fact: EvidenceFact) -> bool:
    value = fact.value
    return (
        fact.field in {"price", "amount", "charge", "cost_component"}
        or isinstance(value, dict)
        and ("amount" in value or "currency" in value)
        or "amount" in fact.qualifiers
    )


def _clarifications(requirement: AnswerRequirement, context: dict[str, object]) -> set[str]:
    missing: set[str] = set()
    if requirement.intent in {"current_price", "price_comparison"} and not _present(
        requirement.market
    ):
        missing.add("market")
    if requirement.intent == "price_comparison":
        if not _strings(context.get("channels")):
            missing.add("channels")
        if not _currency(context.get("currency")):
            missing.add("currency")
        start = _timestamp(context.get("window_start"))
        end = _timestamp(context.get("window_end"), end_of_day=True)
        if start is None:
            missing.add("window_start")
        if end is None or end.date() > requirement.as_of:
            missing.add("window_end")
        if start is not None and end is not None and start > end:
            missing.update(("window_start", "window_end"))
        if not _capacity(context.get("capacity")):
            missing.add("capacity")
        if not _text(context.get("condition")):
            missing.add("condition")
        if "discount_eligibility" in context and not _present(context["discount_eligibility"]):
            missing.add("discount_eligibility")
    elif requirement.intent == "total_cost":
        if not _present(context.get("reporting_period")):
            missing.add("reporting_period")
        if not _currency(context.get("currency")):
            missing.add("currency")
        if not _strings(context.get("required_components")):
            missing.add("required_components")
    elif requirement.intent == "compliance":
        missing.update(key for key in _COMPLIANCE_FIELDS if not _text(context.get(key)))
    return missing


def _source_checks(
    source: EvidenceSource | None,
    requirement: AnswerRequirement,
) -> tuple[set[str], set[str]]:
    reasons: set[str] = set()
    missing: set[str] = set()
    if source is None:
        return {"source_missing"}, {"source"}
    if not any(
        _same(name, requirement.competitor)
        for name in (source.competitor, *source.covered_competitors)
    ):
        reasons.add("competitor_mismatch")
    if not _same(source.dimension, requirement.dimension):
        reasons.add("dimension_mismatch")
    if source.status != "active":
        reasons.add("source_inactive")
    if (
        source.role != "source"
        or source.material_level not in {"full_source", "kb_document"}
        or source.source_type in _SIGNAL_TYPES
    ):
        reasons.add("non_original_source")
    if any(
        observed is not None and _day(observed) > requirement.as_of
        for observed in (getattr(source, key) for key in _SOURCE_DATES)
    ):
        reasons.add("future_source_date")
    if _present(requirement.market):
        if not _present(source.market):
            reasons.add("market_missing")
            missing.add("market")
        elif not _same(source.market, requirement.market):
            reasons.add("market_mismatch")
    return reasons, missing


def _base_checks(
    fact: EvidenceFact,
    source: EvidenceSource | None,
    requirement: AnswerRequirement,
    conflicts: set[str],
) -> tuple[set[str], set[str]]:
    reasons: set[str] = set()
    missing: set[str] = set()
    if not _same(fact.competitor, requirement.competitor):
        reasons.add("competitor_mismatch")
    if not _same(fact.dimension, requirement.dimension):
        reasons.add("dimension_mismatch")
    if fact.status != "supported":
        reasons.add("unsupported_status")
    if not fact.quote.strip():
        reasons.add("evidence_quote_missing")
        missing.add("quote")
    if not fact.evidence_item_ids or any(not item.strip() for item in fact.evidence_item_ids):
        reasons.add("evidence_item_ids_missing")
        missing.add("evidence_item_ids")
    if fact.id in conflicts:
        reasons.add("unresolved_conflict")
    source_reasons, source_missing = _source_checks(source, requirement)
    reasons.update(source_reasons)
    missing.update(source_missing)
    if _present(requirement.market):
        if not _present(fact.market):
            reasons.add("market_missing")
            missing.add("market")
        elif not _same(fact.market, requirement.market):
            reasons.add("market_mismatch")
    value = fact.value
    date_records = (fact.qualifiers, value if isinstance(value, dict) else {})
    for record in date_records:
        for key in _FACT_DATES:
            raw_date = record.get(key)
            if _present(raw_date) and (observed := _day(raw_date)) is not None:
                if observed > requirement.as_of:
                    reasons.add("future_fact_date")
    return reasons, missing


def _money_checks(fields: dict[str, object]) -> tuple[set[str], set[str]]:
    reasons: set[str] = set()
    missing: set[str] = set()
    if not _amount(fields.get("amount")):
        reasons.add("missing_entity_price")
        missing.add("amount")
    if not _currency(fields.get("currency")):
        reasons.add("currency_invalid")
        missing.add("currency")
    return reasons, missing


def _verified_day(fact: EvidenceFact, source: EvidenceSource | None) -> date | None:
    if "verified_at" in fact.qualifiers:
        return _day(fact.qualifiers["verified_at"])
    return _day(source.last_verified_at) if source is not None else None


def _price_checks(
    fact: EvidenceFact,
    source: EvidenceSource | None,
    requirement: AnswerRequirement,
    fields: dict[str, object],
    context: dict[str, object],
    clarifications: set[str],
) -> tuple[set[str], set[str]]:
    reasons, missing = _money_checks(fields)
    required = {"price_type", "price_basis", "billing_interval", "tax_scope"}
    basis = fields.get("price_basis")
    if basis == "device":
        required.update(("model", "capacity", "condition"))
    elif basis == "subscription":
        required.update(("plan", "seat_type"))
    else:
        missing.add("price_basis")
    missing.update(
        key
        for key in required
        if not (_capacity(fields.get(key)) if key == "capacity" else _text(fields.get(key)))
    )
    listed_without_tax = (
        fields.get("price_type") == "official_current"
        and fields.get("price_scope") == "listed_unit"
        and fields.get("tax_scope") == "unknown"
    )
    if fields.get("price_type") not in ("official_current", "channel_offer"):
        reasons.add("current_price_type_required")
        missing.add("price_type")
    if fields.get("price_type") == "channel_offer":
        missing.update(key for key in ("channel", "offer_conditions") if not _text(fields.get(key)))
        if not _text(fields.get("shipping_scope")):
            missing.add("shipping_scope")
    verified = _verified_day(fact, source)
    if verified is None:
        reasons.add("unverified_price")
        missing.add("verified_at")
    elif verified > requirement.as_of:
        reasons.add("future_fact_date")
        missing.add("verified_at")
    elif (requirement.as_of - verified).days > 7:
        reasons.add("stale_price")
        missing.add("verified_at")
    if not _present(requirement.market):
        reasons.add("market_missing")
        missing.add("market")
    for key in ("model", "capacity", "condition", "plan", "seat_type", "currency"):
        if _present(context.get(key)) and not _same(fields.get(key), context[key]):
            reasons.add("price_scope_mismatch")
            missing.add(key)
    if requirement.intent == "price_comparison":
        if not _text(fields.get("offer_conditions")):
            missing.add("offer_conditions")
        if not _text(fields.get("shipping_scope")):
            missing.add("shipping_scope")
        if "discount_eligibility" in context and not _same(
            fields.get("discount_eligibility"), context["discount_eligibility"]
        ):
            reasons.add("comparison_scope_mismatch")
            missing.add("discount_eligibility")
        if clarifications:
            reasons.add("comparison_conditions_missing")
        else:
            if not any(
                _same(fields.get("channel"), channel)
                for channel in _strings(context.get("channels"))
            ):
                reasons.add("comparison_scope_mismatch")
                missing.add("channel")
            start = _timestamp(context["window_start"])
            end = _timestamp(context["window_end"], end_of_day=True)
            observed_value = fact.qualifiers.get("observed_at")
            observed = _timestamp(observed_value)
            date_only_observation = isinstance(observed_value, str) and bool(
                re.fullmatch(r"\d{4}-\d{2}-\d{2}", observed_value.strip())
            )
            window_has_time = any(
                re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(context[key]).strip()) is None
                for key in ("window_start", "window_end")
            )
            if observed is None or (date_only_observation and window_has_time):
                reasons.add("observation_time_missing")
                missing.add("observed_at")
            elif not (start <= observed <= end):
                reasons.add("outside_comparison_window")
                missing.add("window")
    blocked_fields = missing - ({"tax_scope"} if listed_without_tax else set())
    if blocked_fields:
        reasons.add("missing_price_fields")
    return reasons, missing


def _cost_checks(
    fact: EvidenceFact,
    source: EvidenceSource | None,
    requirement: AnswerRequirement,
    fields: dict[str, object],
    context: dict[str, object],
    clarifications: set[str],
) -> tuple[set[str], set[str]]:
    reasons, missing = _money_checks(fields)
    # Expense records have their own schema; device/subscription quote conditions do not apply.
    records = fact.qualifiers | (fact.value if isinstance(fact.value, dict) else {})
    for key in ("cost_component", "charge_id", "reporting_period"):
        valid = _present(records.get(key)) if key == "reporting_period" else _text(records.get(key))
        if not valid:
            missing.add(key)
    verified = _verified_day(fact, source)
    if verified is None:
        missing.add("verified_at")
    elif verified > requirement.as_of:
        reasons.add("future_fact_date")
        missing.add("verified_at")
    if clarifications:
        reasons.add("cost_conditions_missing")
    else:
        if not _same(records.get("reporting_period"), context["reporting_period"]):
            missing.add("reporting_period")
        if not _same(fields.get("currency"), context["currency"]):
            missing.add("currency")
        if not any(
            _same(records.get("cost_component"), component)
            for component in _strings(context["required_components"])
        ):
            missing.add("cost_component")
    if missing:
        reasons.add("cost_scope_mismatch")
    return reasons, missing


def evaluate_answer_boundary(
    view: StageEvidenceView, requirement: AnswerRequirement
) -> AnswerBoundary:
    """Preserve usable facts while reporting incomplete or unspecified answer conditions."""
    context = requirement.context
    clarifications = _clarifications(requirement, context)
    sources = {source.id: source for source in view.sources}
    conflicts = {fact_id for conflict in view.conflicts for fact_id in conflict.fact_ids}
    decisions: list[FactDecision] = []
    missing: set[str] = set()
    prices: list[EvidenceFact] = []
    costs: list[EvidenceFact] = []
    compliance: list[EvidenceFact] = []
    for fact in sorted(view.facts, key=lambda item: item.id):
        source = sources.get(fact.source_id)
        reasons, fact_missing = _base_checks(fact, source, requirement, conflicts)
        if fact.id not in view.fact_ids:
            reasons.add("fact_not_in_view")
        if fact.source_id not in view.source_ids:
            reasons.add("source_not_in_view")
        value = fact.value
        if isinstance(value, dict):
            common_fields = value.keys() & fact.qualifiers.keys()
            if any(not _same(value[key], fact.qualifiers[key]) for key in common_fields):
                reasons.add("structured_field_conflict")
        if _is_money(fact):
            fields = _money_fields(fact)
            cost_record = fact.field in {"cost_component", "charge"} or (
                fact.field in {"price", "amount"}
                and "cost_component"
                in (fact.qualifiers | (value if isinstance(value, dict) else {}))
            )
            if requirement.intent == "total_cost" and cost_record:
                extra_reasons, extra_missing = _cost_checks(
                    fact, source, requirement, fields, context, clarifications
                )
                if not reasons and not extra_reasons:
                    costs.append(fact)
            else:
                extra_reasons, extra_missing = _price_checks(
                    fact, source, requirement, fields, context, clarifications
                )
                if not reasons and not extra_reasons:
                    prices.append(fact)
            reasons.update(extra_reasons)
            fact_missing.update(extra_missing)
        compliance_claim = fact.field in {"compliance", "compliance_standard", "certification"} or (
            fact.field == "support_level" and fact.qualifiers.get("claim_kind") == "compliance"
        )
        if requirement.intent == "compliance" and compliance_claim:
            if clarifications:
                reasons.add("compliance_conditions_missing")
            else:
                scope = fact.qualifiers
                if any(not _same(scope.get(key), context[key]) for key in _COMPLIANCE_FIELDS):
                    reasons.add("compliance_evidence_missing")
                    fact_missing.add("compliance_evidence")
                elif not reasons:
                    compliance.append(fact)
        decisions.append(
            FactDecision(
                fact_id=fact.id,
                source_id=fact.source_id,
                allowed=not reasons,
                reasons=tuple(sorted(reasons)),
                missing_fields=tuple(sorted(fact_missing)),
            )
        )
        missing.update(fact_missing)
    if requirement.intent == "current_price" and not prices:
        missing.update(("amount", "currency", "current_price"))
    elif requirement.intent == "price_comparison":
        for channel in _strings(context.get("channels")):
            if not any(_same(fact.qualifiers.get("channel"), channel) for fact in prices):
                missing.add(f"observations.{channel}")
    elif requirement.intent == "total_cost":
        for component in _strings(context.get("required_components")):
            if not any(
                _same(
                    (fact.qualifiers | (fact.value if isinstance(fact.value, dict) else {})).get(
                        "cost_component"
                    ),
                    component,
                )
                for fact in costs
            ):
                missing.add(f"cost_component.{component}")
    elif requirement.intent == "compliance" and not compliance:
        missing.add("compliance_evidence")
    allowed = tuple(item.fact_id for item in decisions if item.allowed)
    withheld = tuple(item.fact_id for item in decisions if not item.allowed)
    has_guidance = requirement.intent == "source_guidance" and any(
        source.id in view.source_ids and not _source_checks(source, requirement)[0]
        for source in view.sources
    )
    if clarifications:
        status = "clarify"
    elif not allowed and has_guidance:
        status = "partial"
        missing.add("structured_facts")
    elif not allowed:
        status = "insufficient"
        if not missing:
            missing.add("supporting_facts")
    elif missing or withheld:
        status = "partial"
    else:
        status = "answer"
    return AnswerBoundary(
        snapshot_id=view.snapshot_id,
        requirement=requirement,
        status=status,
        allowed_fact_ids=allowed,
        withheld_fact_ids=withheld,
        missing_fields=tuple(sorted(missing)),
        clarification_fields=tuple(sorted(clarifications)),
        fact_decisions=tuple(decisions),
        view_source_ids=tuple(sorted(set(view.source_ids))),
        view_fact_ids=tuple(sorted(set(view.fact_ids))),
    )
