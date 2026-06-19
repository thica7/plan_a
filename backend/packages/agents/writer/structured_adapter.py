from __future__ import annotations

import re
from dataclasses import dataclass

from packages.agents.writer.structured_hygiene import has_source_token


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_heading(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


_EXECUTIVE_SUMMARY_TEMPLATE_PHRASES = (
    "this report is structured as decision analysis first",
)
_EXECUTIVE_SUMMARY_TEMPLATE_LABELS = (
    "核心结论",
    "决策姿态",
    "风险边界",
    "立即行动",
)
_ENGLISH_STRUCTURAL_HEADINGS = frozenset(
    _normalize_heading(heading)
    for heading in (
        "Direct User / Community Signals",
        "Simulated Survey and Interview Signals",
        "Pricing and Packaging",
        "Feature and Workflow Capability",
        "Positioning and Core Value",
    )
)
_BATTLECARD_TEMPLATE_TERMS = (
    "直接战报定位",
    "反对意见处理",
    "行动偏向",
    "落地检查",
)
_INTERNAL_TERM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"Segment Evidence Pack JSON",
        r"source_registry",
        r"Writer Evidence Pack",
    )
)


@dataclass(frozen=True)
class MarkdownFailureShape:
    code: str
    section: str
    line_number: int


@dataclass(frozen=True)
class MarkdownFailureShapeResult:
    passed: bool
    issues: list[MarkdownFailureShape]

    def issue_codes(self) -> list[str]:
        codes: list[str] = []
        seen: set[str] = set()
        for issue in self.issues:
            if issue.code in seen:
                continue
            codes.append(issue.code)
            seen.add(issue.code)
        return codes


@dataclass(frozen=True)
class _LineContext:
    line_number: int
    text: str
    section: str


def detect_markdown_failure_shapes(
    markdown: str,
    *,
    output_language: str,
) -> MarkdownFailureShapeResult:
    lines = _line_contexts(markdown)
    issues: list[MarkdownFailureShape] = []

    _detect_executive_summary_template(lines, issues)
    _detect_english_structural_heading_in_zh(lines, output_language, issues)
    _detect_battlecard_template(lines, issues)
    _detect_citation_in_table_header(lines, issues)
    _detect_internal_term_leak(lines, issues)

    return MarkdownFailureShapeResult(passed=not issues, issues=issues)


def _detect_executive_summary_template(
    lines: list[_LineContext],
    issues: list[MarkdownFailureShape],
) -> None:
    section_lines = _section_lines(lines, "执行摘要")
    if not section_lines:
        return

    first_label_line: _LineContext | None = None
    matched_labels: set[str] = set()
    for line in section_lines:
        lowered = line.text.casefold()
        if any(
            phrase in lowered for phrase in _EXECUTIVE_SUMMARY_TEMPLATE_PHRASES
        ):
            issues.append(
                MarkdownFailureShape(
                    code="executive_summary_template_only",
                    section=line.section,
                    line_number=line.line_number,
                )
            )
            return

        for label in _EXECUTIVE_SUMMARY_TEMPLATE_LABELS:
            if label in line.text:
                matched_labels.add(label)
                if first_label_line is None:
                    first_label_line = line

    if len(matched_labels) >= 3 and first_label_line is not None:
        issues.append(
            MarkdownFailureShape(
                code="executive_summary_template_only",
                section=first_label_line.section,
                line_number=first_label_line.line_number,
            )
        )


def _detect_english_structural_heading_in_zh(
    lines: list[_LineContext],
    output_language: str,
    issues: list[MarkdownFailureShape],
) -> None:
    if not output_language.lower().startswith("zh"):
        return

    for line in lines:
        heading = _parse_heading(line.text)
        if heading is None:
            continue

        level, text = heading
        if level not in {3, 4}:
            continue

        if _normalize_heading(text) in _ENGLISH_STRUCTURAL_HEADINGS:
            issues.append(
                MarkdownFailureShape(
                    code="english_structural_heading_in_zh",
                    section=line.section,
                    line_number=line.line_number,
                )
            )
            return


def _detect_battlecard_template(
    lines: list[_LineContext],
    issues: list[MarkdownFailureShape],
) -> None:
    section_lines = _section_lines(lines, "战报")
    matched_terms: set[str] = set()
    first_term_line: _LineContext | None = None

    for line in section_lines:
        for term in _BATTLECARD_TEMPLATE_TERMS:
            if term in line.text:
                matched_terms.add(term)
                if first_term_line is None:
                    first_term_line = line

    if len(matched_terms) >= 3 and first_term_line is not None:
        issues.append(
            MarkdownFailureShape(
                code="battlecard_template_only",
                section=first_term_line.section,
                line_number=first_term_line.line_number,
            )
        )


def _detect_citation_in_table_header(
    lines: list[_LineContext],
    issues: list[MarkdownFailureShape],
) -> None:
    for index, line in enumerate(lines):
        if not _is_table_header(lines, index):
            continue
        if has_source_token(line.text):
            issues.append(
                MarkdownFailureShape(
                    code="citation_in_table_header",
                    section=line.section,
                    line_number=line.line_number,
                )
            )
            return


def _detect_internal_term_leak(
    lines: list[_LineContext],
    issues: list[MarkdownFailureShape],
) -> None:
    for line in lines:
        if any(pattern.search(line.text) for pattern in _INTERNAL_TERM_PATTERNS):
            issues.append(
                MarkdownFailureShape(
                    code="internal_term_leak",
                    section=line.section,
                    line_number=line.line_number,
                )
            )
            return


def _line_contexts(markdown: str) -> list[_LineContext]:
    contexts: list[_LineContext] = []
    current_section = ""
    for line_number, text in enumerate(markdown.splitlines(), start=1):
        heading = _parse_heading(text)
        if heading is not None:
            level, heading_text = heading
            if level == 2:
                current_section = heading_text
        contexts.append(
            _LineContext(
                line_number=line_number,
                text=text,
                section=current_section,
            )
        )
    return contexts


def _section_lines(
    lines: list[_LineContext],
    section: str,
) -> list[_LineContext]:
    return [line for line in lines if line.section == section]


def _parse_heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    return len(match.group(1)), match.group(2).strip()


def _is_table_header(lines: list[_LineContext], index: int) -> bool:
    if index + 1 >= len(lines) or not _is_table_row(lines[index].text):
        return False
    return _is_separator_row(lines[index + 1].text)


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_separator_row(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(_is_separator_cell(cell) for cell in cells)


def _table_cells(line: str) -> list[str]:
    if not _is_table_row(line):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_cell(cell: str) -> bool:
    normalized = cell.replace(" ", "").strip(":")
    return len(normalized) >= 3 and set(normalized) == {"-"}
