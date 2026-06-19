from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from packages.agents.writer.structured_hygiene import (
    SOURCE_TOKEN_RE,
    has_source_token,
    is_valid_source_id,
)
from packages.agents.writer.structured_renderer import _EN_LABELS
from packages.agents.writer.structured_report import StructuredReport


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WHITESPACE_RE = re.compile(r"\s+")
_SOURCE_MARKER = "[source:"


def _normalize_heading(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


_ENGLISH_STRUCTURAL_HEADINGS = frozenset(
    _normalize_heading(heading)
    for heading in (
        *_EN_LABELS.values(),
        "Feature and Workflow Capability",
        "Direct User / Community Signals",
        "Simulated Survey and Interview Signals",
        "Battlecard",
    )
)
_INTERNAL_TERM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"source_registry",
        r"allowed_source_ids",
        r"represented_by",
        r"Segment Evidence Pack JSON",
        r"Writer Evidence Pack",
        r"\bfact:",
        r"\bsignal:",
    )
)


@dataclass(frozen=True)
class PublicationContractIssue:
    code: str
    line_number: int
    message: str
    repair_target: str


@dataclass(frozen=True)
class PublicationContractResult:
    passed: bool
    issues: list[PublicationContractIssue]

    def issue_codes(self) -> list[str]:
        return sorted({issue.code for issue in self.issues})

    def telemetry_payload(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issue_count": len(self.issues),
            "issue_codes": self.issue_codes(),
            "repair_targets": sorted(
                {issue.repair_target for issue in self.issues if issue.repair_target}
            ),
        }


def validate_publication_contract(
    markdown: str,
    *,
    structured_report: StructuredReport | None,
    allowed_source_ids: set[str],
) -> PublicationContractResult:
    lines = markdown.splitlines()
    issues: list[PublicationContractIssue] = []
    is_zh = _is_zh_report(structured_report)

    _validate_headings(lines, is_zh=is_zh, issues=issues)
    _validate_table_headers(lines, issues=issues)
    _validate_internal_terms(lines, issues=issues)
    _validate_source_citations(
        lines,
        allowed_source_ids=allowed_source_ids,
        issues=issues,
    )
    _validate_core_support_order(lines, is_zh=is_zh, issues=issues)

    return PublicationContractResult(passed=not issues, issues=issues)


def _is_zh_report(report: StructuredReport | None) -> bool:
    if report is None:
        return False
    return report.output_language.lower().startswith("zh")


def _validate_headings(
    lines: list[str],
    *,
    is_zh: bool,
    issues: list[PublicationContractIssue],
) -> None:
    for line_number, line in enumerate(lines, start=1):
        heading = _parse_heading(line)
        if heading is None:
            continue

        level, text = heading
        if has_source_token(text):
            issues.append(
                PublicationContractIssue(
                    code="citation_in_heading",
                    line_number=line_number,
                    message="Markdown heading contains a source citation.",
                    repair_target="renderer",
                )
            )

        if is_zh and level in {2, 3, 4}:
            clean_text = SOURCE_TOKEN_RE.sub("", text)
            if _normalize_heading(clean_text) in _ENGLISH_STRUCTURAL_HEADINGS:
                issues.append(
                    PublicationContractIssue(
                        code="english_structural_heading_in_zh",
                        line_number=line_number,
                        message=(
                            "zh-CN report contains an English structural heading."
                        ),
                        repair_target="renderer",
                    )
                )


def _validate_table_headers(
    lines: list[str],
    *,
    issues: list[PublicationContractIssue],
) -> None:
    for index, line in enumerate(lines):
        if not _is_table_header(lines, index):
            continue
        if has_source_token(line):
            issues.append(
                PublicationContractIssue(
                    code="citation_in_table_header",
                    line_number=index + 1,
                    message="Markdown table header contains a source citation.",
                    repair_target="renderer",
                )
            )


def _validate_internal_terms(
    lines: list[str],
    *,
    issues: list[PublicationContractIssue],
) -> None:
    for line_number, line in enumerate(lines, start=1):
        if any(pattern.search(line) for pattern in _INTERNAL_TERM_PATTERNS):
            issues.append(
                PublicationContractIssue(
                    code="internal_term_leak",
                    line_number=line_number,
                    message=(
                        "Markdown contains internal writer or evidence-pack "
                        "terminology."
                    ),
                    repair_target="structured_section",
                )
            )


def _validate_source_citations(
    lines: list[str],
    *,
    allowed_source_ids: set[str],
    issues: list[PublicationContractIssue],
) -> None:
    for line_number, line in enumerate(lines, start=1):
        matches = list(SOURCE_TOKEN_RE.finditer(line))
        matched_starts = {match.start() for match in matches}
        search_from = 0
        lowered = line.casefold()
        while True:
            marker_start = lowered.find(_SOURCE_MARKER, search_from)
            if marker_start == -1:
                break
            if marker_start not in matched_starts:
                issues.append(
                    PublicationContractIssue(
                        code="invalid_source_id",
                        line_number=line_number,
                        message="Malformed Markdown source citation token.",
                        repair_target="structured_section",
                    )
                )
            search_from = marker_start + len(_SOURCE_MARKER)

        for match in matches:
            token = match.group(0)
            source_id = token[token.find(":") + 1 : -1]
            if not source_id or not is_valid_source_id(source_id):
                issues.append(
                    PublicationContractIssue(
                        code="invalid_source_id",
                        line_number=line_number,
                        message="Source citation contains a malformed source ID.",
                        repair_target="structured_section",
                    )
                )
                continue
            if source_id not in allowed_source_ids:
                issues.append(
                    PublicationContractIssue(
                        code="invalid_source_id",
                        line_number=line_number,
                        message="Source citation is not in allowed_source_ids.",
                        repair_target="structured_section",
                    )
                )


def _validate_core_support_order(
    lines: list[str],
    *,
    is_zh: bool,
    issues: list[PublicationContractIssue],
) -> None:
    if is_zh:
        core_line = _find_h2(lines, {"战报"})
        support_line = _find_h2(lines, {"支撑材料"})
    else:
        core_line = _find_h2(lines, {"battlecard", "battlecards"})
        support_line = _find_h2(lines, {"support materials"})

    if core_line is None or support_line is None or support_line > core_line:
        return

    issues.append(
        PublicationContractIssue(
            code="support_before_core",
            line_number=support_line,
            message="Support materials appear before the core battlecard section.",
            repair_target="renderer",
        )
    )


def _parse_heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    return len(match.group(1)), match.group(2).strip()


def _find_h2(lines: list[str], headings: set[str]) -> int | None:
    for line_number, line in enumerate(lines, start=1):
        heading = _parse_heading(line)
        if heading is None:
            continue
        level, text = heading
        if level == 2 and _normalize_heading(text) in headings:
            return line_number
    return None


def _is_table_header(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines) or not _is_table_row(lines[index]):
        return False
    return _is_separator_row(lines[index + 1])


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
