from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from packages.business_intel.report_quality import compare_run_quality
from packages.i18n.language import report_label
from packages.research.evidence import publishable_text_noise_problem
from packages.schema.api_dto import RunDetail
from packages.schema.models import QCIssue

WriterRepairMode = Literal["line", "section", "full"]

LINE_REPAIR_MAX_ISSUES = 5
PROTECTABLE_MINIMUMS = {
    "report_structure_score": 0.7,
    "decision_summary_section_score": 1.0,
    "competitive_findings_section_score": 1.0,
    "competitor_deep_dive_section_score": 1.0,
    "layer_analysis_section_score": 1.0,
    "core_analysis_depth_score": 0.6,
    "citation_validity_rate": 0.6,
}
SECTION_REPAIR_HINTS: dict[str, tuple[str, ...]] = {
    "decision_summary": (
        "decision summary",
        "recommended action",
        "decision posture",
        "immediate next move",
    ),
    "competitive_findings": (
        "competitive findings",
        "dimension findings",
        "highest-impact finding",
        "findings section",
    ),
    "review_theme_summary": (
        "review",
        "user review",
        "review_theme",
        "user_research",
        "adoption blocker",
        "switching trigger",
    ),
    "swot_analysis": ("swot", "strength", "weakness", "opportunit", "threat"),
    "competitor_deep_dives": ("competitor deep", "deep_dive", "wins", "watchouts"),
    "battlecard": ("battlecard", "response guidance", "sales response", "objection"),
    "workflow_enterprise_risk": ("workflow", "enterprise risk", "switching cost"),
    "market_landscape": ("market landscape", "category strategy", "competitor clusters"),
    "claim_risk": ("claim risk", "claim_validation", "evidence risk"),
    "rag_gap_fill": ("rag", "gap fill", "retrieval"),
}


@dataclass(frozen=True)
class WriterRepairPlan:
    mode: WriterRepairMode
    reason: str
    previous_report_protectable: bool
    line_numbers: list[int] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    anti_regression_required: bool = False


@dataclass(frozen=True)
class MarkdownSection:
    heading: str
    body: str
    start: int
    end: int


def build_writer_repair_plan(
    detail: RunDetail,
    issues: list[QCIssue],
    upstream_data_changed: bool = False,
) -> WriterRepairPlan:
    protectable = _previous_report_is_protectable(detail)
    if upstream_data_changed:
        return WriterRepairPlan(
            mode="full",
            reason="upstream data changed; full rewrite allowed",
            previous_report_protectable=protectable,
            anti_regression_required=False,
        )
    if not protectable:
        return WriterRepairPlan(
            mode="full",
            reason="report is not protectable; full rewrite required",
            previous_report_protectable=False,
        )

    line_numbers = _report_line_numbers(issues)
    if (
        line_numbers
        and len(line_numbers) <= LINE_REPAIR_MAX_ISSUES
        and len(line_numbers) == len(issues)
    ):
        return WriterRepairPlan(
            mode="line",
            reason="small set of report line findings on protectable report",
            previous_report_protectable=True,
            line_numbers=line_numbers,
        )

    sections = _target_sections(issues)
    if sections and len(sections) <= 2:
        return WriterRepairPlan(
            mode="section",
            reason="small set of section findings on protectable report",
            previous_report_protectable=True,
            sections=sections,
            anti_regression_required=True,
        )

    return WriterRepairPlan(
        mode="full",
        reason="writer findings are broad or unmapped; full rewrite required",
        previous_report_protectable=True,
        anti_regression_required=True,
    )


def apply_line_repair(markdown: str, issues: list[QCIssue]) -> str:
    target_lines = set(_report_line_numbers(issues))
    if not target_lines:
        return markdown

    repaired_lines: list[str] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if line_number in target_lines and publishable_text_noise_problem(line):
            continue
        repaired_lines.append(line)
    return "\n".join(repaired_lines).strip()


def replace_markdown_section(
    markdown: str,
    target_section: str,
    output_language: str,
    replacement_markdown: str,
) -> str:
    replacement = _normalize_section_replacement(replacement_markdown)
    target = _find_section(markdown, target_section, output_language)
    if target is None:
        return f"{markdown.rstrip()}\n\n{replacement}".strip()
    before = markdown[: target.start].rstrip()
    after = markdown[target.end :].lstrip()
    return f"{before}\n\n{replacement}\n\n{after}".strip()


def report_regression_problem(
    previous: RunDetail,
    candidate: RunDetail,
    protected_sections: list[str],
) -> str | None:
    for section_key in protected_sections:
        previous_chars = _section_content_chars(
            previous.report_md,
            section_key,
            previous.output_language,
        )
        candidate_chars = _section_content_chars(
            candidate.report_md,
            section_key,
            candidate.output_language,
        )
        if previous_chars >= 180 and candidate_chars < max(120, previous_chars * 0.55):
            return (
                f"{section_key} section regressed from {previous_chars} to "
                f"{candidate_chars} substantive characters"
            )

    comparison = compare_run_quality(candidate, baseline=previous)
    if comparison.regression_gate_status == "fail":
        return "; ".join(comparison.regression_gate_reasons)
    return None


def _previous_report_is_protectable(detail: RunDetail) -> bool:
    if not detail.report_md.strip():
        return False

    comparison = compare_run_quality(detail)
    if comparison.report_quality_signal:
        return True

    metric_by_name = {metric.name: metric.target_value for metric in comparison.metrics}
    return all(
        metric_by_name.get(name, 0.0) >= minimum
        for name, minimum in PROTECTABLE_MINIMUMS.items()
    )


def _report_line_numbers(issues: list[QCIssue]) -> list[int]:
    numbers: list[int] = []
    for issue in issues:
        match = re.fullmatch(r"report_md\.line\[(\d+)\]", issue.field_path)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(set(numbers))


def _target_sections(issues: list[QCIssue]) -> list[str]:
    sections: list[str] = []
    for issue in issues:
        haystack = " ".join(
            value
            for value in [
                issue.field_path,
                issue.problem,
                issue.target_subagent or "",
                issue.redo_scope.target_subagent or "",
            ]
            if value
        ).casefold()
        for section_key, hints in SECTION_REPAIR_HINTS.items():
            if section_key not in sections and any(hint.casefold() in haystack for hint in hints):
                sections.append(section_key)
    return sections


def _find_section(
    markdown: str,
    section_key: str,
    output_language: str,
) -> MarkdownSection | None:
    aliases = _section_aliases(section_key, output_language)
    return next(
        (section for section in _sections(markdown) if _heading_matches(section.heading, aliases)),
        None,
    )


def _sections(markdown: str) -> list[MarkdownSection]:
    matches = list(re.finditer(r"^\s*##(?!#)\s+(.+?)\s*#*\s*$", markdown, flags=re.MULTILINE))
    sections: list[MarkdownSection] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(
            MarkdownSection(
                heading=match.group(1).strip(),
                body=markdown[match.end() : end].strip(),
                start=match.start(),
                end=end,
            )
        )
    return sections


def _section_aliases(section_key: str, output_language: str) -> tuple[str, ...]:
    aliases = [section_key.replace("_", " ")]
    for language in (output_language, "en-US", "zh-CN"):
        try:
            aliases.append(report_label(language, section_key))
        except KeyError:
            continue
    if section_key == "swot_analysis":
        aliases.append("SWOT")
    return tuple(dict.fromkeys(aliases))


def _heading_matches(heading: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize_heading(heading)
    compact = _compact_heading(heading)
    for alias in aliases:
        normalized_alias = _normalize_heading(alias)
        compact_alias = _compact_heading(alias)
        if not normalized_alias:
            continue
        if normalized_alias in normalized or (compact_alias and compact_alias in compact):
            return True
    return False


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _compact_heading(value: str) -> str:
    return re.sub(r"\s+", "", _normalize_heading(value))


def _normalize_section_replacement(replacement_markdown: str) -> str:
    return replacement_markdown.strip()


def _section_content_chars(
    markdown: str,
    section_key: str,
    output_language: str,
) -> int:
    section = _find_section(markdown, section_key, output_language)
    if section is None:
        return 0
    body = re.sub(r"\[source:[^\]]+\]", "", section.body)
    body = re.sub(r"\s+", " ", body).strip()
    return len(body)
