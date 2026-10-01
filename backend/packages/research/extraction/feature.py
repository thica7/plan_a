from __future__ import annotations

import re
from collections.abc import Iterable

from packages.research.extraction.quality import (
    HARDWARE_SPEC_RE,
    quote_quality_problem,
    quote_window_from_match,
)
from packages.research.models import (
    CapturedPage,
    EvidenceQuote,
    ExtractionResult,
    ResearchBrief,
)

FEATURE_SLOTS = (
    "core_capability",
    "context_window",
    "multimodal",
    "tool_use",
    "agentic_workflow",
    "repository_context",
    "enterprise_controls",
    "deployment_api",
    "customization",
)

_GENERIC_CAPABILITY_VERBS = re.compile(
    r"具备|支持|提供|可以|可更换|包含|采用|includes?|supports?|offers?|features?|provides?|has\b",
    flags=re.IGNORECASE,
)
_GENERIC_NEGATION = re.compile(
    r"不支持|无法|不提供|不具备|不能|没有|does not support|doesn't support|"
    r"does not have|doesn't have|has no|without|not available|\bnot supported\b|\bunsupported\b",
    flags=re.IGNORECASE,
)


def extract_generic_capabilities(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    """Keep product capabilities as source-backed phrases across categories."""
    text = _text(page)
    fields: dict[str, object] = {}
    quotes: list[EvidenceQuote] = []
    for clause_match in re.finditer(r"(?:[^。！？.!?;\n]|(?<=\d)\.(?=\d))+", text):
        clause = clause_match.group().strip()
        clause_start = clause_match.start() + len(clause_match.group()) - len(
            clause_match.group().lstrip()
        )
        navigation_labels = (
            "skip to main content", "privacy policy", "order details", "shipping info",
            "refunds and returns", "community guidelines", "search loading", "how to buy",
        )
        navigation_matches = list(re.finditer(
            "|".join(re.escape(label) for label in navigation_labels), clause, re.I,
        ))
        if len(navigation_matches) >= 3:
            segment_start = 0
            fact_segment = None
            for segment_end, next_start in [
                *((match.start(), match.end()) for match in navigation_matches),
                (len(clause), len(clause)),
            ]:
                segment = clause[segment_start:segment_end]
                segment_verb = _GENERIC_CAPABILITY_VERBS.search(segment)
                if (
                    segment_verb is not None
                    and brief.competitor.casefold() in segment[:segment_verb.start()].casefold()
                    and segment[segment_verb.end():].strip()
                ):
                    fact_segment = segment.strip()
                    clause_start += segment_start + len(segment) - len(segment.lstrip())
                    break
                segment_start = next_start
            if fact_segment is None:
                continue
            clause = fact_segment
        verb = _GENERIC_CAPABILITY_VERBS.search(clause)
        if not clause or verb is None or not clause[verb.end():].strip():
            continue
        if brief.competitor.casefold() not in clause[:verb.start()].casefold():
            continue
        if brief.product_name and brief.product_name != brief.competitor and brief.product_name.casefold() in clause.casefold():
            continue
        if re.search(r"[和与及、]|\band\b", clause[:verb.start()], re.I):
            continue
        if _GENERIC_NEGATION.search(clause):
            continue
        index = len(fields) + 1
        key = f"capability_{index}"
        fields[key] = {"status": "supported", "evidence_terms": [clause[:180]]}
        quotes.append(EvidenceQuote(
            text=clause, source_url=page.final_url, field=key,
            start_offset=clause_start, end_offset=clause_start + len(clause),
        ))
        if index >= 6:
            break
    if (
        brief.competitor.casefold() in page.title.casefold()
        and re.search(r"\b(?:specs|specifications)\b|技术参数|规格", page.title, re.I)
        and not re.search(r"\b(?:versus|vs|comparison)\b|对比|比较", page.title, re.I)
    ):
        for label in re.finditer(
            r"\b(?:screen|display|storage|ram|battery)\b|屏幕|存储|内存|电池", text, re.I,
        ):
            if len(fields) >= 6:
                break
            line_end = text.find("\n", label.start())
            end = min(len(text), label.start() + 180)
            if line_end >= 0:
                end = min(end, line_end)
            quote = text[label.start():end].rstrip()
            if (
                not HARDWARE_SPEC_RE.search(quote)
                or quote_quality_problem(quote, dimension=brief.dimension)
                or _GENERIC_NEGATION.search(quote)
                or re.search(r"\b(?:promotion|giveaway|win|prize)\b|促销|抽奖|赠品", quote, re.I)
                or any(quote in existing.text for existing in quotes)
            ):
                continue
            key = f"capability_{len(fields) + 1}"
            fields[key] = {"status": "supported", "evidence_terms": [quote]}
            quotes.append(EvidenceQuote(
                text=quote, source_url=page.final_url, field=key,
                start_offset=label.start(), end_offset=label.start() + len(quote),
            ))
    return ExtractionResult(
        competitor=brief.competitor, dimension=brief.dimension,
        source_candidate_id=page.candidate_id, captured_page_id=page.id,
        fields=fields, quotes=quotes,
        confidence=min(0.85, page.quality_score * 0.8) if quotes else 0.2,
        extractor_name="generic_product_capabilities",
        status="extracted" if quotes else "partial",
        missing_fields=[] if quotes else ["product_capabilities"],
        metadata={"category": brief.product_category, "capability_count": len(quotes)},
    )

_SLOT_TERMS: dict[str, tuple[str, ...]] = {
    "core_capability": (
        "model",
        "assistant",
        "coding",
        "chat",
        "reasoning",
        "generate",
        "analyze",
    ),
    "context_window": ("context window", "context length", "token context", "long context"),
    "multimodal": ("image", "vision", "audio", "multimodal", "file upload", "pdf"),
    "tool_use": ("tool use", "function calling", "tools", "api", "actions"),
    "agentic_workflow": (
        "agent",
        "autonomous",
        "workflow",
        "tasks",
        "plan",
        "execute",
        "computer use",
    ),
    "repository_context": (
        "repository",
        "codebase",
        "github",
        "pull request",
        "workspace",
        "ide",
    ),
    "enterprise_controls": (
        "enterprise",
        "sso",
        "scim",
        "admin",
        "audit",
        "security",
        "privacy",
    ),
    "deployment_api": ("api", "sdk", "endpoint", "deploy", "cloud", "self-host", "server"),
    "customization": (
        "custom",
        "fine-tune",
        "instructions",
        "memory",
        "adapter",
        "workspace rules",
    ),
}


def extract_feature_slots(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    text = _text(page)
    normalized = text.casefold()
    fields: dict[str, object] = {}
    quotes: list[EvidenceQuote] = []

    for slot in FEATURE_SLOTS:
        status, terms = _slot_status(normalized, _SLOT_TERMS[slot])
        fields[slot] = {
            "status": status,
            "evidence_terms": terms,
        }
        quote = _quote_for_terms(page, slot, terms)
        if quote is not None:
            quotes.append(quote)

    missing_fields = [
        slot
        for slot in FEATURE_SLOTS
        if isinstance(fields[slot], dict)
        and fields[slot].get("status") == "not_found_in_source"
    ]
    status = "extracted" if len(missing_fields) <= 2 else "partial"
    return ExtractionResult(
        competitor=brief.competitor,
        dimension=brief.dimension,
        source_candidate_id=page.candidate_id,
        captured_page_id=page.id,
        fields=fields,
        quotes=quotes[:8],
        confidence=_confidence(fields.values(), page.quality_score),
        extractor_name="feature_slots",
        status=status,
        missing_fields=missing_fields,
        metadata={"slot_count": len(FEATURE_SLOTS)},
    )


def _slot_status(normalized_text: str, terms: Iterable[str]) -> tuple[str, list[str]]:
    matched = [term for term in terms if term.casefold() in normalized_text]
    if not matched:
        return "not_found_in_source", []
    if len(matched) == 1:
        return "partial", matched
    return "supported", matched


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
                dimension="feature",
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


def _confidence(values: Iterable[object], quality_score: float) -> float:
    statuses = [
        value.get("status")
        for value in values
        if isinstance(value, dict) and isinstance(value.get("status"), str)
    ]
    if not statuses:
        return 0.2
    supported = sum(1 for status in statuses if status == "supported")
    partial = sum(1 for status in statuses if status == "partial")
    coverage = (supported + partial * 0.55) / len(statuses)
    return max(0.2, min(0.98, quality_score * 0.4 + coverage * 0.6))


def _text(page: CapturedPage) -> str:
    return page.text or page.markdown or page.snippet
