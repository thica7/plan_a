from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Mapping

from packages.i18n.language import report_label

SegmentKind = Literal[
    "evidence_shard",
    "section_fragment",
    "support_fragment",
    "final_report",
]
SegmentValidationStatus = Literal["pass", "retry", "fail"]

CORE_HEADING_KEYS: tuple[str, ...] = (
    "executive_summary",
    "executive_takeaway",
    "decision_summary",
    "competitive_findings",
    "review_theme_summary",
    "community_evidence_triangulation",
    "competitor_deep_dives",
    "swot_analysis",
)
SUPPORT_HEADING_KEYS: tuple[str, ...] = (
    "evidence_support",
    "source_quality",
    "knowledge_coverage",
    "confidence_notes",
    "claim_risk",
    "next_collection",
    "evidence_appendix",
    "generation_notes",
    "memory_context",
    "user_research_evidence",
    "rag_gap_fill",
)
SECTION_ALLOWED_KEYS: dict[str, tuple[str, ...]] = {
    "decision_summary": (
        "executive_summary",
        "executive_takeaway",
        "decision_summary",
        "competitive_findings",
    ),
    "competitive_findings": ("competitive_findings",),
    "review_theme_summary": (
        "review_theme_summary",
        "community_evidence_triangulation",
    ),
    "competitor_deep_dives": ("competitor_deep_dives",),
    "evidence_support": SUPPORT_HEADING_KEYS,
    "final_report": CORE_HEADING_KEYS + SUPPORT_HEADING_KEYS,
}
HEADING_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "executive_summary": ("Executive Summary",),
    "executive_takeaway": ("Executive Takeaway",),
    "decision_summary": ("Decision Summary",),
    "competitive_findings": ("Competitive Findings",),
    "review_theme_summary": (
        "User Research",
        "User Research Summary",
        "User Review Themes",
        "Review Theme Summary",
    ),
    "community_evidence_triangulation": ("Community Evidence Triangulation",),
    "competitor_deep_dives": (
        "Competitor Deep Dive",
        "Competitor Deep Dives",
    ),
    "evidence_support": (
        "Evidence Support",
        "Evidence and QA Support",
        "Evidence QA Support",
    ),
}

_H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)
_SUPPORTED_OUTPUT_LANGUAGES = ("zh-CN", "en-US")


@dataclass(frozen=True)
class SegmentContract:
    segment_kind: SegmentKind
    section_id: str
    output_language: str = "zh-CN"
    allow_h2: bool = True
    allowed_heading_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class SegmentValidationResult:
    status: SegmentValidationStatus
    h2_headings: list[str]
    forbidden_headings: list[str]
    forbidden_heading_keys: list[str]
    errors: list[str]


def segment_contract_for(segment: Mapping[str, object]) -> SegmentContract:
    output_language = _string_value(segment.get("output_language")) or "zh-CN"
    segment_kind = _segment_kind(segment.get("segment_kind"))
    section_id = _section_id_for(segment)

    if section_id == "evidence_support":
        segment_kind = "support_fragment"
    if segment_kind == "evidence_shard":
        return SegmentContract(
            segment_kind=segment_kind,
            section_id=section_id,
            output_language=output_language,
            allow_h2=False,
            allowed_heading_keys=(),
        )

    allowed_heading_keys = SECTION_ALLOWED_KEYS.get(section_id, (section_id,))
    if segment_kind == "final_report":
        section_id = "final_report"
        allowed_heading_keys = SECTION_ALLOWED_KEYS["final_report"]

    return SegmentContract(
        segment_kind=segment_kind,
        section_id=section_id,
        output_language=output_language,
        allow_h2=True,
        allowed_heading_keys=allowed_heading_keys,
    )


def validate_segment_contract(
    markdown: str, contract: SegmentContract
) -> SegmentValidationResult:
    if not markdown.strip():
        return SegmentValidationResult(
            status="fail",
            h2_headings=[],
            forbidden_headings=[],
            forbidden_heading_keys=[],
            errors=["segment output is empty"],
        )

    h2_headings = _h2_headings(markdown)
    if not contract.allow_h2 and h2_headings:
        return SegmentValidationResult(
            status="retry",
            h2_headings=h2_headings,
            forbidden_headings=[],
            forbidden_heading_keys=[],
            errors=["evidence_shard must not contain H2 headings"],
        )

    allowed_heading_keys = set(contract.allowed_heading_keys)
    forbidden_headings: list[str] = []
    forbidden_heading_keys: list[str] = []
    for heading in h2_headings:
        heading_key = heading_key_for(heading, contract.output_language)
        if heading_key is not None and heading_key not in allowed_heading_keys:
            forbidden_headings.append(heading)
            forbidden_heading_keys.append(heading_key)

    if forbidden_headings:
        return SegmentValidationResult(
            status="retry",
            h2_headings=h2_headings,
            forbidden_headings=forbidden_headings,
            forbidden_heading_keys=forbidden_heading_keys,
            errors=["segment contains forbidden H2 headings"],
        )

    return SegmentValidationResult(
        status="pass",
        h2_headings=h2_headings,
        forbidden_headings=[],
        forbidden_heading_keys=[],
        errors=[],
    )


def heading_key_for(heading: str, output_language: str) -> str | None:
    normalized_heading = _normalize_heading(heading)
    for key, aliases in _heading_aliases(output_language).items():
        if normalized_heading in {_normalize_heading(alias) for alias in aliases}:
            return key
    return None


def _heading_aliases(output_language: str) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {}
    keys = set(CORE_HEADING_KEYS) | set(SUPPORT_HEADING_KEYS) | set(HEADING_KEY_ALIASES)
    languages = tuple(
        dict.fromkeys((output_language, *_SUPPORTED_OUTPUT_LANGUAGES))
    )
    for key in keys:
        label_aliases: list[str] = []
        for language in languages:
            try:
                label_aliases.append(report_label(language, key))
            except KeyError:
                continue
        label_aliases.extend(HEADING_KEY_ALIASES.get(key, ()))
        aliases[key] = tuple(label_aliases)
    return aliases


def _normalize_heading(heading: str) -> str:
    return " ".join(heading.strip().translate(_DASH_TRANSLATION).lower().split())


def _h2_headings(markdown: str) -> list[str]:
    return [match.group(1).strip() for match in _H2_RE.finditer(markdown)]


def _section_id_for(segment: Mapping[str, object]) -> str:
    segment_name = _string_value(segment.get("segment_name"))
    if segment_name == "user_research":
        return "review_theme_summary"
    if segment_name == "support_appendix":
        return "evidence_support"
    if segment_name:
        return segment_name
    section_id = _string_value(segment.get("section_id"))
    return section_id or "decision_summary"


def _segment_kind(value: object) -> SegmentKind:
    if value in {
        "evidence_shard",
        "section_fragment",
        "support_fragment",
        "final_report",
    }:
        return value  # type: ignore[return-value]
    return "section_fragment"


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
