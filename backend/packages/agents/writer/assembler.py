from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Sequence

from packages.agents.writer.segment_contract import (
    CORE_HEADING_KEYS,
    SUPPORT_HEADING_KEYS,
    heading_key_for,
)
from packages.agents.writer.structured_report import StructuredReport
from packages.business_intel.report_sections import SectionLayer, report_section_marker
from packages.i18n.language import report_label

CANONICAL_REPORT_ORDER: tuple[str, ...] = CORE_HEADING_KEYS + SUPPORT_HEADING_KEYS

_H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
_UNKNOWN_SUPPORT_TERMS = (
    "evidence",
    "source",
    "qa",
    "appendix",
    "risk",
    "collection",
    "rag",
    "memory",
    "\u8bc1\u636e",
    "\u6765\u6e90",
    "\u9644\u5f55",
    "\u98ce\u9669",
    "\u91c7\u96c6",
    "\u6536\u96c6",
    "\u8bb0\u5fc6",
)


@dataclass(frozen=True)
class AssembledReport:
    markdown: str
    telemetry: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportSectionFragment:
    markdown: str
    section_key: str
    layer: str
    segment_name: str
    competitor: str | None = None


@dataclass(frozen=True)
class StructuredReportAssemblyResult:
    report: StructuredReport
    telemetry: dict[str, object]


class StructuredReportAssembler:
    def assemble(
        self,
        *,
        report: StructuredReport,
        expected_competitors: list[str],
    ) -> StructuredReportAssemblyResult:
        expected = list(dict.fromkeys(expected_competitors))
        deep_dive_names = [item.competitor for item in report.core.competitor_deep_dives]
        user_theme_names = [
            item.competitor
            for item in report.core.user_review_themes.competitor_themes
        ]
        swot_names = [item.competitor for item in report.core.swot.competitors]
        battlecard_names = [item.competitor for item in report.core.battlecard.plays]
        telemetry = {
            "expected_competitors": expected,
            "missing_deep_dive_competitors": _missing(expected, deep_dive_names),
            "duplicate_deep_dive_competitors": _duplicates(deep_dive_names),
            "missing_user_theme_competitors": _missing(expected, user_theme_names),
            "duplicate_user_theme_competitors": _duplicates(user_theme_names),
            "missing_swot_competitors": _missing(expected, swot_names),
            "duplicate_swot_competitors": _duplicates(swot_names),
            "missing_battlecard_competitors": _missing(expected, battlecard_names),
            "duplicate_battlecard_competitors": _duplicates(battlecard_names),
        }
        return StructuredReportAssemblyResult(report=report, telemetry=telemetry)


@dataclass(frozen=True)
class _SectionBlock:
    heading: str
    body: str
    key: str | None


def assemble_report_fragments(
    fragments: Sequence[ReportSectionFragment],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    assembled = _assemble_report_blocks(
        [
            (fragment.markdown, fragment.section_key, fragment.layer)
            for fragment in fragments
        ],
        output_language=output_language,
        competitors=competitors,
    )
    layer_counts: dict[str, int] = {}
    for fragment in fragments:
        layer_counts[fragment.layer] = layer_counts.get(fragment.layer, 0) + 1
    telemetry = {
        **assembled.telemetry,
        "input_fragment_count": len(fragments),
        "fragment_layer_counts": layer_counts,
        "fragment_section_keys": [fragment.section_key for fragment in fragments],
        "fragment_segment_names": [fragment.segment_name for fragment in fragments],
    }
    return AssembledReport(markdown=assembled.markdown, telemetry=telemetry)


def assemble_report_sections(
    markdown_sections: Sequence[str],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    return _assemble_report_blocks(
        [(markdown, "", "") for markdown in markdown_sections],
        output_language=output_language,
        competitors=competitors,
    )


def _assemble_report_blocks(
    fragment_inputs: Sequence[tuple[str, str, str]],
    *,
    output_language: object,
    competitors: Sequence[str],
) -> AssembledReport:
    intro_blocks: list[str] = []
    known_sections: dict[str, list[str]] = {}
    known_counts: dict[str, int] = {}
    unknown_core_sections: list[_SectionBlock] = []
    unknown_support_sections: list[_SectionBlock] = []

    output_language_text = str(output_language)
    for markdown, _fragment_section_key, fragment_layer in fragment_inputs:
        intro, sections = _parse_fragment(markdown, output_language_text)
        if intro:
            intro_blocks.append(intro)
        for section in sections:
            if section.key is not None:
                known_sections.setdefault(section.key, []).append(section.body)
                known_counts[section.key] = known_counts.get(section.key, 0) + 1
            elif fragment_layer == "support":
                unknown_support_sections.append(section)
            elif fragment_layer == "core":
                unknown_core_sections.append(section)
            elif _looks_like_support_heading(section.heading):
                unknown_support_sections.append(section)
            else:
                unknown_core_sections.append(section)

    merged_section_keys = [
        key for key in CANONICAL_REPORT_ORDER if known_counts.get(key, 0) > 1
    ]
    duplicate_section_count_before = sum(
        count - 1 for count in known_counts.values() if count > 1
    )

    output_blocks: list[str] = []
    output_blocks.extend(intro_blocks)
    output_blocks.extend(
        _render_known_section(output_language, key, known_sections[key])
        for key in CANONICAL_REPORT_ORDER
        if key in known_sections and key not in SUPPORT_HEADING_KEYS
    )
    output_blocks.extend(
        _render_unknown_section(section) for section in unknown_core_sections
    )
    output_blocks.extend(
        _render_known_section(output_language, key, known_sections[key])
        for key in CANONICAL_REPORT_ORDER
        if key in known_sections and key in SUPPORT_HEADING_KEYS
    )
    output_blocks.extend(
        _render_unknown_section(section) for section in unknown_support_sections
    )

    output_section_keys = [
        key for key in CANONICAL_REPORT_ORDER if key in known_sections
    ]
    first_support_key = next(
        (key for key in output_section_keys if key in SUPPORT_HEADING_KEYS),
        None,
    )
    markdown = "\n\n".join(block for block in output_blocks if block).strip()
    telemetry: dict[str, object] = {
        "input_fragment_count": len(fragment_inputs),
        "output_section_count": len(output_section_keys)
        + len(unknown_core_sections)
        + len(unknown_support_sections),
        "duplicate_section_count_before": duplicate_section_count_before,
        "duplicate_section_count_after": _duplicate_h2_count(
            markdown,
            output_language_text,
        ),
        "merged_section_keys": merged_section_keys,
        "unknown_core_section_count": len(unknown_core_sections),
        "unknown_support_section_count": len(unknown_support_sections),
        "competitors": list(competitors),
        "first_support_key": first_support_key,
    }
    return AssembledReport(markdown=markdown, telemetry=telemetry)


def _parse_fragment(
    markdown: str,
    output_language: str,
) -> tuple[str | None, list[_SectionBlock]]:
    matches = list(_H2_RE.finditer(markdown))
    if not matches:
        stripped = markdown.strip()
        return (stripped or None), []

    intro = markdown[: matches[0].start()].strip()
    sections: list[_SectionBlock] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        )
        heading = match.group(1).strip()
        sections.append(
            _SectionBlock(
                heading=heading,
                body=markdown[body_start:body_end].strip(),
                key=heading_key_for(heading, output_language),
            )
        )
    return (intro or None), sections


def _render_known_section(
    output_language: object,
    key: str,
    bodies: Sequence[str],
) -> str:
    body = "\n\n".join(body for body in bodies if body)
    marker = report_section_marker(key, _section_layer_for_key(key))
    heading = f"## {report_label(output_language, key)}"
    if not body:
        return f"{marker}\n{heading}"
    return f"{marker}\n{heading}\n{body}"


def _section_layer_for_key(key: str) -> SectionLayer:
    if key in SUPPORT_HEADING_KEYS:
        return "support"
    return "core"


def _render_unknown_section(section: _SectionBlock) -> str:
    if not section.body:
        return f"## {section.heading}"
    return f"## {section.heading}\n{section.body}"


def _duplicate_h2_count(markdown: str, output_language: str) -> int:
    counts: dict[str, int] = {}
    for heading in _h2_headings(markdown):
        identity = _heading_identity(heading, output_language)
        counts[identity] = counts.get(identity, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _heading_identity(heading: str, output_language: str) -> str:
    key = heading_key_for(heading, output_language)
    if key is not None:
        return f"known:{key}"
    return f"unknown:{_normalize_unknown_heading(heading)}"


def _h2_headings(markdown: str) -> list[str]:
    return [match.group(1).strip() for match in _H2_RE.finditer(markdown)]


def _normalize_unknown_heading(heading: str) -> str:
    return " ".join(heading.strip().casefold().split())


def _looks_like_support_heading(heading: str) -> bool:
    normalized = heading.casefold()
    return any(term in normalized for term in _UNKNOWN_SUPPORT_TERMS)


def _missing(expected: list[str], actual: list[str]) -> list[str]:
    actual_set = set(actual)
    return [item for item in expected if item not in actual_set]


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates
