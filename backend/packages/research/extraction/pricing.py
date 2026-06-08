from __future__ import annotations

import re

from packages.research.extraction.quality import quote_window_from_match
from packages.research.models import (
    CapturedPage,
    EvidenceQuote,
    ExtractionResult,
    ResearchBrief,
)

PRICING_FIELDS = (
    "pricing_model_type",
    "tier_names",
    "price_points",
    "billing_cycle",
    "usage_limits",
    "enterprise_condition",
)


def extract_pricing_model(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    text = _text(page)
    normalized = text.casefold()
    pricing_model_type = _pricing_model_type(brief.competitor, normalized)
    fields = {
        "pricing_model_type": pricing_model_type,
        "tier_names": _tier_names(text),
        "price_points": _price_points(text),
        "billing_cycle": _billing_cycle(normalized),
        "usage_limits": _usage_limits(text),
        "enterprise_condition": _enterprise_condition(normalized),
    }
    missing_fields = [
        field
        for field in PRICING_FIELDS
        if not fields.get(field)
        and not (
            field in {"tier_names", "price_points", "billing_cycle"}
            and pricing_model_type
            in {"open_weight_self_hosted", "license_based", "not_applicable"}
        )
    ]
    status = "extracted" if len(missing_fields) <= 2 else "partial"
    if pricing_model_type in {"open_weight_self_hosted", "license_based"} and not fields[
        "price_points"
    ]:
        status = "not_applicable"
    confidence = _confidence(fields, missing_fields, page.quality_score)
    return ExtractionResult(
        competitor=brief.competitor,
        dimension=brief.dimension,
        source_candidate_id=page.candidate_id,
        captured_page_id=page.id,
        fields=fields,
        quotes=_quotes(page, fields),
        confidence=confidence,
        extractor_name="pricing_model",
        status=status,
        missing_fields=missing_fields,
        not_applicable_reason=(
            "Open-weight or license-based model access is not directly comparable "
            "to SaaS/API tiers."
            if status == "not_applicable"
            else None
        ),
    )


def _pricing_model_type(competitor: str, normalized_text: str) -> str:
    competitor_key = competitor.casefold()
    if "llama" in competitor_key and any(
        term in normalized_text
        for term in ("open source", "open-weight", "open weight", "license", "self-host")
    ):
        return "open_weight_self_hosted"
    if "license" in normalized_text and not re.search(r"\$\s*\d+", normalized_text):
        return "license_based"
    if any(term in normalized_text for term in ("token", "input", "output", "mtok", "api")):
        return "api_usage_based"
    if any(term in normalized_text for term in ("per user", "per seat", "monthly", "annually")):
        return "subscription_saas"
    if "enterprise" in normalized_text and "contact" in normalized_text:
        return "enterprise_contract"
    return "not_disclosed"


def _tier_names(text: str) -> list[str]:
    names = []
    for token in ("Free", "Pro", "Team", "Business", "Enterprise", "Max", "Plus"):
        if re.search(rf"\b{re.escape(token)}\b", text, flags=re.IGNORECASE):
            names.append(token)
    return names


def _price_points(text: str) -> list[str]:
    matches = re.findall(
        r"(?:\$|USD\s*)\s?\d+(?:\.\d+)?(?:\s*/\s?(?:month|year|user|seat|1M tokens|MTok))?",
        text,
        flags=re.IGNORECASE,
    )
    token_matches = re.findall(
        r"\$\s?\d+(?:\.\d+)?\s*(?:input|output)?\s*(?:/|per)\s*(?:1M|million|MTok|tokens?)",
        text,
        flags=re.IGNORECASE,
    )
    return _dedupe([*matches, *token_matches])


def _billing_cycle(normalized_text: str) -> list[str]:
    cycles = []
    for token in ("monthly", "month", "annual", "annually", "yearly", "per token", "per 1m"):
        if token in normalized_text:
            cycles.append(token)
    return _dedupe(cycles)


def _usage_limits(text: str) -> list[str]:
    return _dedupe(
        re.findall(
            r"\b\d+(?:,\d+)?(?:\.\d+)?\s*(?:tokens?|requests?|credits?|seats?|users?|context)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _enterprise_condition(normalized_text: str) -> str:
    if "contact sales" in normalized_text or "contact us" in normalized_text:
        return "contact_sales"
    if "enterprise" in normalized_text:
        return "enterprise_available"
    return ""


def _confidence(
    fields: dict[str, object],
    missing_fields: list[str],
    quality_score: float,
) -> float:
    filled = sum(1 for field in PRICING_FIELDS if fields.get(field))
    base = filled / len(PRICING_FIELDS)
    penalty = min(0.25, len(missing_fields) * 0.04)
    return max(0.2, min(0.98, quality_score * 0.45 + base * 0.55 - penalty))


def _quotes(page: CapturedPage, fields: dict[str, object]) -> list[EvidenceQuote]:
    text = _text(page)
    quotes = []
    for field, value in fields.items():
        if not value:
            continue
        snippet = _window_for_field(text, field, value)
        if snippet:
            quotes.append(EvidenceQuote(text=snippet, source_url=page.final_url, field=field))
    return quotes[:6]


def _window_for_field(text: str, field: str, value: object) -> str:
    if field == "pricing_model_type":
        model_type = str(value)
        if model_type == "api_usage_based":
            return _window_for_terms(text, ("token", "input", "output", "api", "mtok"))
        if model_type == "subscription_saas":
            return _window_for_terms(text, ("per user", "per seat", "monthly", "annually"))
        if model_type == "enterprise_contract":
            return _window_for_terms(text, ("enterprise", "contact sales", "contact us"))
        if model_type in {"open_weight_self_hosted", "license_based"}:
            return _window_for_terms(text, ("open weight", "open-weight", "license", "self-host"))
        if model_type == "not_disclosed":
            return _window_for_terms(text, ("pricing", "plans", "billing", "enterprise"))
    if field == "enterprise_condition":
        return _window_for_terms(text, ("enterprise", "contact sales", "contact us"))
    return _window_for_value(text, value)


def _window_for_terms(text: str, terms: tuple[str, ...]) -> str:
    lowered = text.casefold()
    for term in terms:
        idx = lowered.find(term.casefold())
        if idx >= 0:
            return quote_window_from_match(
                text,
                match_start=idx,
                match_end=idx + len(term),
                dimension="pricing",
            )
    return ""


def _window_for_value(text: str, value: object) -> str:
    values = value if isinstance(value, list) else [str(value)]
    lowered = text.casefold()
    for item in values:
        if not item:
            continue
        idx = lowered.find(str(item).casefold())
        if idx >= 0:
            item_text = str(item)
            return quote_window_from_match(
                text,
                match_start=idx,
                match_end=idx + len(item_text),
                dimension="pricing",
            )
    return ""


def _text(page: CapturedPage) -> str:
    return page.text or page.markdown or page.snippet


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = " ".join(value.split()).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped
