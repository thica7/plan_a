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
        "price_rows": _price_rows(text),
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
    for token in ("Free", "Go", "Pro", "Team", "Business", "Enterprise", "Max", "Plus", "Edu"):
        if re.search(rf"\b{re.escape(token)}\b", text, flags=re.IGNORECASE):
            names.append(token)
    return names


def _price_points(text: str) -> list[str]:
    matches: list[str] = []
    for clause in _pricing_clauses(text):
        for match in _price_match_regex().finditer(clause):
            if _price_match_is_noise(clause, match):
                continue
            if not _price_match_has_pricing_context(clause, match):
                continue
            matches.append(" ".join(match.group(0).split()))
    return _dedupe(matches)


def _price_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for clause in _pricing_clauses(text):
        for match in _price_match_regex().finditer(clause):
            if _price_match_is_noise(clause, match):
                continue
            tier_name = _tier_name_near_price(clause, match)
            if not tier_name and not _price_match_has_metered_unit(match.group(0)):
                continue
            price = " ".join(match.group(0).split())
            key = (tier_name.casefold(), price.casefold())
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "tier_name": tier_name,
                    "price": price,
                    "billing_cycle": _billing_cycle_for_clause(clause),
                    "usage_limit": _first_usage_limit(clause),
                }
            )
    return rows


def _price_match_regex() -> re.Pattern[str]:
    return re.compile(
        r"(?:\$|USD\s*)\s?\d+(?:\.\d+)?"
        r"(?:\s*(?:/|per)\s*(?:month|mo|year|yr|user|seat|developer|"
        r"active\s+day|day|1M tokens|MTok|million tokens|tokens?))?",
        flags=re.IGNORECASE,
    )


def _pricing_clauses(text: str) -> list[str]:
    clauses = re.split(r"(?<=[.!?。；;])\s+|\n+|\s+\|\s+", text)
    return [clause.strip() for clause in clauses if clause.strip()]


def _price_match_is_noise(clause: str, match: re.Match[str]) -> bool:
    unit = match.group(0).casefold()
    if re.search(r"\b(per|/)\s*(?:month|mo|year|yr|user|seat|developer|1m|million|mtok|tokens?)\b", unit):
        return False
    window = clause[max(0, match.start() - 48) : min(len(clause), match.end() + 72)]
    return bool(
        re.search(
            r"\b(?:promo|promotional|coupon|trial\s+balance|credit\s+balance)\b|"
            r"\b(?:in|as|worth)\s+credits?\b|"
            r"\bcredits?\s+(?:balance|included)\b|"
            r"\bnot\s+(?:a\s+)?(?:plan\s+)?price\b",
            window,
            flags=re.IGNORECASE,
        )
    )


def _price_match_has_pricing_context(clause: str, match: re.Match[str]) -> bool:
    lowered = clause.casefold()
    if _tier_name_near_price(clause, match):
        return True
    if _price_match_has_metered_unit(match.group(0)):
        return True
    return bool(
        re.search(
            r"\b(price|pricing|costs?|plans?|billing|per\s+user|per\s+seat|"
            r"monthly|annually|enterprise|contact sales)\b",
            lowered,
        )
    )


def _price_match_has_metered_unit(price: str) -> bool:
    return bool(
        re.search(
            r"(?:/|per)\s*(?:1m|million|mtok|tokens?|active\s+day|day|request)",
            price,
            flags=re.IGNORECASE,
        )
    )


def _tier_name_near_price(clause: str, match: re.Match[str]) -> str:
    before = clause[max(0, match.start() - 80) : match.start()]
    after = clause[match.end() : min(len(clause), match.end() + 60)]
    for text in (before, after):
        name = _last_tier_name(text)
        if name:
            return name
    return ""


def _last_tier_name(text: str) -> str:
    candidates: list[tuple[int, str]] = []
    for token in (
        "Free",
        "Go",
        "Pro",
        "Team",
        "Teams",
        "Business",
        "Enterprise",
        "Max",
        "Plus",
        "Edu",
    ):
        for match in re.finditer(rf"\b{re.escape(token)}\b", text, flags=re.IGNORECASE):
            label = "Team" if token == "Teams" else token
            candidates.append((match.start(), label))
    if not candidates:
        return ""
    return max(candidates, key=lambda item: item[0])[1]


def _billing_cycle_for_clause(clause: str) -> str:
    lowered = clause.casefold()
    if re.search(r"\b(per month|/month|monthly|/mo|per mo)\b", lowered):
        return "monthly"
    if re.search(r"\b(per year|/year|annual|annually|yearly|/yr|per yr)\b", lowered):
        return "annual"
    if re.search(r"\b(per token|per 1m|/1m|mtok|million tokens|active day|per day)\b", lowered):
        return "usage"
    return ""


def _first_usage_limit(clause: str) -> str:
    matches = re.findall(
        r"\b\d(?:[\d,]*)(?:\.\d+)?\s*(?:k|m|million|billion)?\s+"
        r"(?:tokens?|requests?|credits?|seats?|users?|context|messages)\b",
        clause,
        flags=re.IGNORECASE,
    )
    return " ".join(matches[0].split()) if matches else ""


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
    if field == "price_rows" and isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            price = str(item.get("price") or "")
            if price:
                return _window_for_value(text, price)
        return _window_for_terms(text, ("pricing", "plans", "billing", "enterprise"))
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
