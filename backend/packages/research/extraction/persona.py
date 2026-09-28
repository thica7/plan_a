from __future__ import annotations

import re

from packages.research.extraction.quality import quote_quality_problem, quote_window_from_match
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


def extract_generic_persona(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    """Extract only audience and tasks confirmed in the captured page."""
    text = _text(page)
    fields: dict[str, object] = {}
    quotes: list[EvidenceQuote] = []
    for sentence in re.finditer(r"[^。！？.!?;\n]+[。！？.!?;]?", text):
        clause = sentence.group()
        names = [brief.competitor]
        if brief.product_name and brief.product_name.casefold() != brief.competitor.casefold():
            names.append(brief.product_name)
        mentions = sorted(
            (match.start(), name)
            for name in names
            for match in re.finditer(re.escape(name), clause, flags=re.IGNORECASE)
        )
        for index, (start, name) in enumerate(mentions):
            if name != brief.competitor:
                continue
            end = mentions[index + 1][0] if index + 1 < len(mentions) else len(clause)
            segment = clause[start:end].strip()
            separator = re.search(r"[，,]", segment)
            first_part = segment[:separator.start()] if separator else segment
            if re.search(r"[和与及、]|\band\b", first_part, re.I):
                continue
            supported_segment = first_part
            if separator:
                next_part = re.split(r"[，,]", segment[separator.end():], maxsplit=1)[0]
                if next_part.strip().startswith(("适合", "用于")):
                    supported_segment = segment[:separator.end() + len(next_part)]
            if quote_quality_problem(supported_segment, dimension="persona"):
                continue
            for field, pattern in (
                ("target_segment", r"面向([^，。；;]{2,30})"),
                ("primary_use_case", r"(?:适合|用于)([^，。；;]{2,40})"),
            ):
                match = re.search(pattern, supported_segment)
                if match is None or field in fields:
                    continue
                fields[field] = match.group(1).strip()
                quotes.append(EvidenceQuote(
                    text=supported_segment, source_url=page.final_url, field=field,
                    start_offset=sentence.start() + start + match.start(),
                    end_offset=sentence.start() + start + match.end(),
                ))
    return ExtractionResult(
        competitor=brief.competitor, dimension=brief.dimension,
        source_candidate_id=page.candidate_id, captured_page_id=page.id,
        fields=fields, quotes=quotes,
        confidence=min(.85, page.quality_score * .8) if fields else .2,
        extractor_name="generic_product_persona",
        status="extracted" if fields else "partial",
        missing_fields=[] if fields else ["target_segment", "primary_use_case"],
        metadata={"category": brief.product_category},
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
    for term in terms:
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if match:
            quote_text = quote_window_from_match(
                text,
                match_start=match.start(),
                match_end=match.end(),
                dimension="persona",
            )
            if not quote_text:
                continue
            return EvidenceQuote(
                text=quote_text,
                source_url=page.final_url,
                field=field,
                start_offset=match.start(),
                end_offset=match.end(),
            )
    return None


def _confidence(populated_fields: list[str], quality_score: float) -> float:
    coverage = len(populated_fields) / max(1, len(_FIELD_TERMS))
    return max(0.2, min(0.96, quality_score * 0.4 + coverage * 0.6))


def _text(page: CapturedPage) -> str:
    return page.text or page.markdown or page.snippet


def _title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())
