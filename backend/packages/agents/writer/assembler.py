from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from packages.agents.writer.segment_contract import (
    CORE_HEADING_KEYS,
    SECTION_ALLOWED_KEYS,
    SUPPORT_HEADING_KEYS,
    heading_key_for,
)
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
class _SectionBlock:
    heading: str
    body: str
    key: str | None


def assemble_report_sections(
    markdown_sections: Sequence[str],
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
    for markdown in markdown_sections:
        intro, sections = _parse_fragment(markdown, output_language_text)
        if intro:
            intro_blocks.append(intro)
        for section in sections:
            if section.key is not None:
                known_sections.setdefault(section.key, []).append(section.body)
                known_counts[section.key] = known_counts.get(section.key, 0) + 1
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
        "input_fragment_count": len(markdown_sections),
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


def join_section_repair_parts(
    parts: Sequence[str],
    section_headings: str,
) -> str:
    requested_headings, requested_keys = _requested_repair_targets(section_headings)
    has_requested_targets = bool(requested_headings or requested_keys)
    seen_headings: set[str] = set()
    cleaned_parts: list[str] = []
    for part in parts:
        include_current_block = not has_requested_targets
        cleaned_lines: list[str] = []
        for line in part.strip().splitlines():
            heading = line.strip()
            is_top_level_heading = heading.startswith("## ") and not heading.startswith(
                "### "
            )
            if is_top_level_heading:
                include_current_block = not has_requested_targets or _repair_heading_allowed(
                    heading,
                    requested_headings=requested_headings,
                    requested_keys=requested_keys,
                )
                if not include_current_block:
                    continue
                if heading in seen_headings:
                    continue
                seen_headings.add(heading)
            if include_current_block:
                cleaned_lines.append(line)
        cleaned_part = "\n".join(cleaned_lines).strip()
        if cleaned_part:
            cleaned_parts.append(cleaned_part)
    return "\n\n".join(cleaned_parts)


def _requested_repair_targets(section_headings: str) -> tuple[set[str], set[str]]:
    requested_headings: set[str] = set()
    requested_keys: set[str] = set()
    for raw_line in section_headings.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "->" in line:
            section_key, heading = (part.strip() for part in line.split("->", 1))
            requested_keys.update(SECTION_ALLOWED_KEYS.get(section_key, (section_key,)))
        else:
            heading = line
        if heading.startswith("## ") and not heading.startswith("### "):
            requested_headings.add(heading)
            heading_key = heading_key_for(heading[3:].strip(), "zh-CN")
            if heading_key is not None:
                requested_keys.update(SECTION_ALLOWED_KEYS.get(heading_key, (heading_key,)))
    return requested_headings, requested_keys


def _repair_heading_allowed(
    heading: str,
    *,
    requested_headings: set[str],
    requested_keys: set[str],
) -> bool:
    if heading in requested_headings:
        return True
    heading_key = heading_key_for(heading[3:].strip(), "zh-CN")
    return heading_key in requested_keys


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
    heading = f"## {report_label(output_language, key)}"
    if not body:
        return heading
    return f"{heading}\n{body}"


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
