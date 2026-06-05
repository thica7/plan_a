from __future__ import annotations

import re

from packages.research.models import (
    CapturedPage,
    EvidenceQuote,
    ExtractionResult,
    ResearchBrief,
)

PERSONA_FIELDS = (
    "target_segment",
    "buyer_or_user_role",
    "primary_use_case",
    "switching_trigger",
    "deployment_context",
    "company_size",
    "confidence_reason",
)

_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "target_segment": ("customer", "customers", "teams", "developers", "enterprise", "startup"),
    "buyer_or_user_role": (
        "developer",
        "engineer",
        "product manager",
        "security team",
        "data scientist",
        "admin",
    ),
    "primary_use_case": (
        "use case",
        "build",
        "automate",
        "analyze",
        "support",
        "coding",
        "research",
    ),
    "switching_trigger": (
        "faster",
        "reduce",
        "save time",
        "migrate",
        "replace",
        "improve productivity",
    ),
    "deployment_context": (
        "cloud",
        "api",
        "workspace",
        "enterprise",
        "self-host",
        "browser",
        "ide",
    ),
    "company_size": ("startup", "small business", "team", "enterprise", "organization"),
}


def extract_persona_schema(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    text = _text(page)
    normalized = text.casefold()
    fields: dict[str, object] = {}
    quotes: list[EvidenceQuote] = []

    for field, terms in _FIELD_TERMS.items():
        matches = _matched_terms(normalized, terms)
        fields[field] = _field_value(field, matches)
        quote = _quote_for_terms(page, field, matches)
        if quote is not None:
            quotes.append(quote)

    populated_fields = [field for field in _FIELD_TERMS if fields.get(field)]
    fields["confidence_reason"] = (
        f"Matched {len(populated_fields)} persona fields from public page text."
        if populated_fields
        else ""
    )
    missing_fields = [field for field in PERSONA_FIELDS if not fields.get(field)]
    status = "extracted" if len(missing_fields) <= 2 else "partial"
    return ExtractionResult(
        competitor=brief.competitor,
        dimension=brief.dimension,
        source_candidate_id=page.candidate_id,
        captured_page_id=page.id,
        fields=fields,
        quotes=quotes[:8],
        confidence=_confidence(populated_fields, page.quality_score),
        extractor_name="persona_schema",
        status=status,
        missing_fields=missing_fields,
    )


def _field_value(field: str, matches: list[str]) -> str:
    if not matches:
        return ""
    if field == "buyer_or_user_role":
        return ", ".join(_title_case(match) for match in matches[:3])
    if field == "company_size":
        return ", ".join(_title_case(match) for match in matches[:3])
    return "; ".join(matches[:3])


def _matched_terms(normalized_text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.casefold() in normalized_text]


def _quote_for_terms(
    page: CapturedPage,
    field: str,
    terms: list[str],
) -> EvidenceQuote | None:
    text = _text(page)
    lowered = text.casefold()
    for term in terms:
        match = re.search(re.escape(term), lowered)
        if match:
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 260)
            return EvidenceQuote(
                text=text[start:end].strip(),
                source_url=page.final_url,
                field=field,
                start_offset=start,
                end_offset=end,
            )
    return None


def _confidence(populated_fields: list[str], quality_score: float) -> float:
    coverage = len(populated_fields) / max(1, len(_FIELD_TERMS))
    return max(0.2, min(0.96, quality_score * 0.4 + coverage * 0.6))


def _text(page: CapturedPage) -> str:
    return page.text or page.markdown or page.snippet


def _title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())
