from __future__ import annotations

import re
from typing import Literal

OutputLanguage = Literal["zh-CN", "en-US"]

DEFAULT_OUTPUT_LANGUAGE: OutputLanguage = "zh-CN"
SUPPORTED_OUTPUT_LANGUAGES: set[str] = {"zh-CN", "en-US"}

REPORT_LABELS: dict[OutputLanguage, dict[str, str]] = {
    "zh-CN": {
        "executive_summary": "\u6267\u884c\u6458\u8981",
        "executive_takeaway": "\u6267\u884c\u6458\u8981",
        "decision_summary": "\u51b3\u7b56\u6458\u8981",
        "competitive_findings": "\u7ade\u4e89\u53d1\u73b0",
        "review_theme_summary": "用户评价整理",
        "competitor_deep_dives": "\u7ade\u54c1\u6df1\u6316",
        "swot_analysis": "SWOT 分析",
        "evidence_support": "\u8bc1\u636e\u4e0e QA \u652f\u6491",
        "executive_overview": "\u6267\u884c\u6982\u89c8",
        "source_quality": "\u6765\u6e90\u8d28\u91cf\u4e0e\u8986\u76d6",
        "side_by_side_matrix": "\u6a2a\u5411\u51b3\u7b56\u77e9\u9635",
        "scenario_checklist": "\u573a\u666f QA \u6e05\u5355",
        "battlecard": "\u6218\u62a5",
        "dimension_winners": "\u7ef4\u5ea6\u7ed3\u8bba",
        "comparison_matrix": "\u5bf9\u6bd4\u77e9\u9635",
        "knowledge_coverage": "\u77e5\u8bc6\u8986\u76d6",
        "confidence_notes": "\u7f6e\u4fe1\u5ea6\u8bf4\u660e",
        "claim_risk": "\u58f0\u660e\u6821\u9a8c\u4e0e\u8bc1\u636e\u98ce\u9669",
        "next_collection": "\u4e0b\u4e00\u6b65\u91c7\u96c6\u4e0e\u9a8c\u8bc1\u8ba1\u5212",
        "evidence_appendix": "\u8bc1\u636e\u9644\u5f55",
        "generation_notes": "\u751f\u6210\u8bf4\u660e",
        "memory_context": "\u8bb0\u5fc6\u4e0a\u4e0b\u6587",
        "user_research_evidence": "\u7528\u6237\u7814\u7a76\u8bc1\u636e",
        "rag_gap_fill": "RAG \u7f3a\u53e3\u8865\u5168",
        "workflow_enterprise_risk": "\u5de5\u4f5c\u6d41\u4e0e\u4f01\u4e1a\u98ce\u9669",
        "business_implications": "\u4e1a\u52a1\u5f71\u54cd",
        "market_landscape": "\u5e02\u573a\u683c\u5c40",
    },
    "en-US": {
        "executive_summary": "Executive Summary",
        "executive_takeaway": "Executive Takeaway",
        "decision_summary": "Decision Summary",
        "competitive_findings": "Competitive Findings",
        "review_theme_summary": "User Review Themes",
        "competitor_deep_dives": "Competitor Deep Dives",
        "swot_analysis": "SWOT Analysis",
        "evidence_support": "Evidence & QA Support",
        "executive_overview": "Executive Overview",
        "source_quality": "Source Quality & Coverage",
        "side_by_side_matrix": "Side-by-Side Decision Matrix",
        "scenario_checklist": "Scenario QA Checklist",
        "battlecard": "Battlecard",
        "dimension_winners": "Dimension Winners",
        "comparison_matrix": "Comparison Matrix",
        "knowledge_coverage": "Knowledge Coverage",
        "confidence_notes": "Confidence Notes",
        "claim_risk": "Claim Validation & Evidence Risk",
        "next_collection": "Next Collection / Verification Plan",
        "evidence_appendix": "Evidence Appendix",
        "generation_notes": "Generation Notes",
        "memory_context": "Memory Context",
        "user_research_evidence": "User Research Evidence",
        "rag_gap_fill": "RAG Gap Fill",
        "workflow_enterprise_risk": "Workflow & Enterprise Risk",
        "business_implications": "Business Implications",
        "market_landscape": "Market Landscape",
    },
}

MOJIBAKE_MARKER_RE = re.compile(r"[\u0080-\u009f]|[脙脗]|忙|莽|猫|茅|氓|盲|茂|冒")
MOJIBAKE_SEGMENT_RE = re.compile(
    r"[\u0080-\u00ff\u20ac\u2018-\u201d\u2022\u2026\u2122]{2,}"
)


def normalize_output_language(value: object) -> OutputLanguage:
    if value == "en-US":
        return "en-US"
    return DEFAULT_OUTPUT_LANGUAGE


def language_instruction(output_language: object) -> str:
    language = normalize_output_language(output_language)
    if language == "en-US":
        return (
            "Use English for all user-facing generated analysis, report headings, "
            "recommendations, QA explanations, and caveats. Preserve source citation "
            "syntax exactly."
        )
    return (
        "Use Simplified Chinese for all user-facing generated analysis, report headings, "
        "recommendations, QA explanations, and caveats. Preserve product names, company "
        "names, URLs, source IDs, citation tokens like [source:ID], model names, "
        "framework names, and formal standards in their original form when appropriate. "
        "Do not translate source IDs or citation syntax."
    )


def report_label(output_language: object, key: str) -> str:
    language = normalize_output_language(output_language)
    return REPORT_LABELS[language][key]


def repair_mojibake_text(text: str) -> str:
    """Repair common UTF-8 text that was decoded as Latin-1 or Windows-1252."""

    if not text or not _looks_like_mojibake(text):
        return text
    full_repair = _best_full_repair(text)
    if full_repair is not None:
        return full_repair
    return MOJIBAKE_SEGMENT_RE.sub(_repair_segment_match, text)


def _looks_like_mojibake(text: str) -> bool:
    return _mojibake_score(text) >= 2


def _mojibake_score(text: str) -> int:
    control_count = len(re.findall(r"[\u0080-\u009f]", text))
    marker_count = len(MOJIBAKE_MARKER_RE.findall(text))
    replacement_count = text.count("\ufffd")
    return control_count * 3 + marker_count + replacement_count * 2


def _best_full_repair(text: str) -> str | None:
    original_score = _mojibake_score(text)
    candidates = [_decode_mojibake(text, encoding) for encoding in ("latin-1", "cp1252")]
    valid = [candidate for candidate in candidates if candidate is not None]
    if not valid:
        return None
    best = min(valid, key=_mojibake_score)
    if _mojibake_score(best) < original_score:
        return best
    return None


def _repair_segment_match(match: re.Match[str]) -> str:
    segment = match.group(0)
    repaired = _best_full_repair(segment)
    return repaired if repaired is not None else segment


def _decode_mojibake(text: str, encoding: str) -> str | None:
    try:
        return text.encode(encoding).decode("utf-8")
    except UnicodeError:
        return None
