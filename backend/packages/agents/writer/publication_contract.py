from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from packages.agents.writer.heading_hygiene import (
    ENGLISH_STRUCTURAL_HEADINGS,
    normalize_heading_text,
)
from packages.agents.writer.structured_hygiene import (
    SOURCE_TOKEN_RE,
    find_malformed_source_token_attempts,
    has_source_token,
    is_valid_source_id,
)
from packages.agents.writer.structured_renderer import (
    STRUCTURED_REPORT_EN_LABELS,
    STRUCTURED_REPORT_ZH_LABELS,
)
from packages.agents.writer.structured_report import StructuredReport


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SECTION_MARKER_RE = re.compile(r"^<!--\s*report-section:[^>]*-->\s*$")
_SECTION_MARKER_PREFIX_RE = re.compile(r"^<!--\s*report-section:[^>]*-->")


def _normalize_heading(text: str) -> str:
    return normalize_heading_text(text)


_CORE_SECTION_KEYS = (
    "executive_summary",
    "decision_summary",
    "competitive_findings",
    "user_review_themes",
    "competitor_deep_dives",
    "decision_matrix",
    "swot",
    "battlecard",
    "community_triangulation",
)
_SUPPORT_SECTION_KEYS = (
    "support_materials",
    "source_quality",
    "user_research_evidence",
    "rag_gap_fill",
    "scenario_qa",
    "claim_risk",
    "next_collection",
    "evidence_appendix",
)
_EN_CORE_SECTION_HEADINGS = frozenset(
    _normalize_heading(heading)
    for heading in (
        *(STRUCTURED_REPORT_EN_LABELS[key] for key in _CORE_SECTION_KEYS),
        "Battlecard",
    )
)
_ZH_CORE_SECTION_HEADINGS = frozenset(
    _normalize_heading(STRUCTURED_REPORT_ZH_LABELS[key]) for key in _CORE_SECTION_KEYS
)
_EN_SUPPORT_SECTION_HEADINGS = frozenset(
    _normalize_heading(heading)
    for heading in (
        *(STRUCTURED_REPORT_EN_LABELS[key] for key in _SUPPORT_SECTION_KEYS),
        "Source Appendix",
        "Claim Support Audit",
    )
)
_ZH_SUPPORT_SECTION_HEADINGS = frozenset(
    _normalize_heading(STRUCTURED_REPORT_ZH_LABELS[key]) for key in _SUPPORT_SECTION_KEYS
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
        r"\bkb:[A-Za-z0-9_.:#-]+",
    )
)


@dataclass(frozen=True)
class PublicationContractIssue:
    code: str
    line_number: int
    message: str
    repair_target: str
    excerpt: str = ""


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
            "issues": [
                {
                    "code": issue.code,
                    "line_number": issue.line_number,
                    "message": issue.message,
                    "repair_target": issue.repair_target,
                    "excerpt": issue.excerpt,
                }
                for issue in self.issues
            ],
        }


def validate_publication_contract(
    markdown: str,
    *,
    structured_report: StructuredReport | None,
    allowed_source_ids: set[str],
    output_language: str | None = None,
) -> PublicationContractResult:
    lines = markdown.splitlines()
    issues: list[PublicationContractIssue] = []
    is_zh = _is_zh_report(structured_report, output_language=output_language)

    _validate_section_marker_lines(lines, issues=issues)
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


def _is_zh_report(
    report: StructuredReport | None,
    *,
    output_language: str | None = None,
) -> bool:
    if report is None:
        return bool(output_language) and output_language.lower().startswith("zh")
    return report.output_language.lower().startswith("zh")


def _validate_section_marker_lines(
    lines: list[str],
    *,
    issues: list[PublicationContractIssue],
) -> None:
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not _SECTION_MARKER_PREFIX_RE.match(stripped):
            continue
        if not _SECTION_MARKER_RE.fullmatch(stripped):
            issues.append(
                PublicationContractIssue(
                    code="citation_on_section_marker"
                    if has_source_token(stripped)
                    else "invalid_section_marker_line",
                    line_number=line_number,
                    message="Section marker line must contain only the marker comment.",
                    repair_target="renderer",
                )
            )


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
            if _normalize_heading(clean_text) in ENGLISH_STRUCTURAL_HEADINGS:
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
                    excerpt=_line_excerpt(line),
                )
            )


def _validate_source_citations(
    lines: list[str],
    *,
    allowed_source_ids: set[str],
    issues: list[PublicationContractIssue],
) -> None:
    for line_number, line in enumerate(lines, start=1):
        for _token in find_malformed_source_token_attempts(line):
            issues.append(
                PublicationContractIssue(
                    code="invalid_source_id",
                    line_number=line_number,
                    message="Malformed Markdown source citation token.",
                    repair_target="structured_section",
                )
            )

        matches = list(SOURCE_TOKEN_RE.finditer(line))
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
        core_headings = _ZH_CORE_SECTION_HEADINGS
        support_headings = _ZH_SUPPORT_SECTION_HEADINGS
    else:
        core_headings = _EN_CORE_SECTION_HEADINGS
        support_headings = _EN_SUPPORT_SECTION_HEADINGS

    first_support_line: int | None = None
    for line_number, line in enumerate(lines, start=1):
        heading = _parse_heading(line)
        if heading is None:
            continue

        level, text = heading
        if level != 2:
            continue

        normalized = _normalize_heading(SOURCE_TOKEN_RE.sub("", text))
        if normalized in support_headings and first_support_line is None:
            first_support_line = line_number
        if normalized in core_headings and first_support_line is not None:
            issues.append(
                PublicationContractIssue(
                    code="support_before_core",
                    line_number=first_support_line,
                    message=(
                        "Support, audit, appendix, or QA sections appear before "
                        "all core business report sections are complete."
                    ),
                    repair_target="renderer",
                )
            )
            return


def _parse_heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    return len(match.group(1)), match.group(2).strip()


def _line_excerpt(line: str, limit: int = 220) -> str:
    excerpt = re.sub(r"\s+", " ", line).strip()
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: max(0, limit - 3)].rstrip() + "..."


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
