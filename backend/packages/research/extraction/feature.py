from __future__ import annotations

import re
from collections.abc import Iterable

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
