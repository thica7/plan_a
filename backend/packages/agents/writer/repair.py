from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from packages.business_intel.report_quality import compare_run_quality
from packages.i18n.language import report_label
from packages.identity.source_resolver import normalize_source_token, source_tokens
from packages.research.evidence import publishable_text_noise_problem
from packages.schema.api_dto import RunDetail
from packages.schema.models import QCIssue

WriterRepairMode = Literal["line", "section", "full"]

LINE_REPAIR_MAX_ISSUES = 5
UPSTREAM_SECTION_REPAIR_MAX_SECTIONS = 2
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
        "user review",
        "review themes",
        "customer review",
        "buyer feedback",
        "review_theme",
        "user_research",
        "adoption blocker",
        "switching trigger",
    ),
    "swot_analysis": ("swot", "strength", "weakness", "opportunit", "threat"),
    "competitor_deep_dives": (
        "competitor deep",
        "competitor deep dive",
        "deep_dive",
        "deep dive watchouts",
        "per-competitor wins/watchouts",
    ),
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
        return _upstream_data_changed_repair_plan(detail, issues, protectable)
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


def _upstream_data_changed_repair_plan(
    detail: RunDetail,
    issues: list[QCIssue],
    protectable: bool,
) -> WriterRepairPlan:
    if not protectable:
        return WriterRepairPlan(
            mode="full",
            reason="upstream data changed; previous report is not protectable",
            previous_report_protectable=False,
            anti_regression_required=False,
        )
    sections = _clean_upstream_target_sections(issues)
    if sections and len(sections) <= UPSTREAM_SECTION_REPAIR_MAX_SECTIONS:
        return WriterRepairPlan(
            mode="section",
            reason="upstream data changed; scoped section repair selected",
            previous_report_protectable=True,
            sections=sections,
            anti_regression_required=True,
        )
    return WriterRepairPlan(
        mode="full",
        reason="upstream data changed; broad rewrite required with anti-regression",
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
    section_problem = _protected_section_regression_problem(
        previous, candidate, protected_sections
    )
    if section_problem:
        return section_problem
    user_research_problem = _user_research_source_regression_problem(
        previous, candidate, protected_sections
    )
    if user_research_problem:
        return user_research_problem

    comparison = compare_run_quality(candidate, baseline=previous)
    if comparison.regression_gate_status == "fail":
        return "; ".join(comparison.regression_gate_reasons)
    return None


def section_regression_problem(
    previous: RunDetail,
    candidate: RunDetail,
    protected_sections: list[str],
) -> str | None:
    section_problem = _protected_section_regression_problem(
        previous, candidate, protected_sections
    )
    if section_problem:
        return section_problem
    return _user_research_source_regression_problem(
        previous, candidate, protected_sections
    )


def _protected_section_regression_problem(
    previous: RunDetail,
    candidate: RunDetail,
    protected_sections: list[str],
) -> str | None:
    for section_key in protected_sections:
        previous_section = _find_section(
            previous.report_md,
            section_key,
            previous.output_language,
        )
        candidate_section = _find_section(
            candidate.report_md,
            section_key,
            candidate.output_language,
        )
        previous_chars = _section_content_chars(previous_section)
        candidate_chars = _section_content_chars(candidate_section)
        if (
            previous_section is not None
            and candidate_section is not None
            and _sections_use_different_scripts(previous_section, candidate_section)
        ):
            continue
        if previous_chars >= 180 and candidate_chars < max(120, previous_chars * 0.55):
            return (
                f"{section_key} section regressed from {previous_chars} to "
                f"{candidate_chars} substantive characters"
            )

    return None


def _user_research_source_regression_problem(
    previous: RunDetail,
    candidate: RunDetail,
    protected_sections: list[str],
) -> str | None:
    if "review_theme_summary" in protected_sections:
        user_research_ids = _user_research_source_ids(candidate)
        previous_review_ids = _section_cited_source_ids(
            previous.report_md,
            "review_theme_summary",
            previous.output_language,
        )
        candidate_review_ids = _section_cited_source_ids(
            candidate.report_md,
            "review_theme_summary",
            candidate.output_language,
        )
        if (
            user_research_ids
            and (
                previous_review_ids & user_research_ids
                or _previous_review_section_has_user_research_semantics(previous)
            )
            and not candidate_review_ids & user_research_ids
        ):
            return "review_theme_summary lost user research source citations"

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
        for section_key in _issue_target_sections(issue):
            if section_key not in sections:
                sections.append(section_key)
    return sections


def _clean_upstream_target_sections(issues: list[QCIssue]) -> list[str]:
    if not issues:
        return []

    sections: list[str] = []
    for issue in issues:
        issue_sections = _issue_target_sections(issue)
        if not issue_sections:
            return []
        for section_key in issue_sections:
            if section_key not in sections:
                sections.append(section_key)
    return sections


def _issue_target_sections(issue: QCIssue) -> list[str]:
    haystack = " ".join(
        value
        for value in [
            issue.field_path,
            issue.problem,
            issue.target_subagent or "",
            issue.redo_scope.target_subagent or "",
            issue.redo_scope.rationale,
        ]
        if value
    ).casefold()
    return [
        section_key
        for section_key, hints in SECTION_REPAIR_HINTS.items()
        if any(_section_hint_matches(haystack, hint) for hint in hints)
    ]


def _section_hint_matches(haystack: str, hint: str) -> bool:
    normalized_hint = hint.casefold()
    if re.fullmatch(r"[a-z0-9]{1,3}", normalized_hint):
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_hint)}(?![a-z0-9])",
                haystack,
            )
            is not None
        )
    return normalized_hint in haystack


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


USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_user_note",
    "manual_note",
    "manual",
}

USER_RESEARCH_REVIEW_SEMANTIC_TOKENS = (
    "survey",
    "interview",
    "user research",
    "user review",
    "review theme",
    "adoption blocker",
    "switching trigger",
    "buyer feedback",
    "customer feedback",
    "persona",
    "调查",
    "访谈",
    "用户研究",
    "用户评价",
    "评价",
    "评论",
    "采用",
    "采纳",
    "切换",
    "痛点",
    "阻力",
)


def _section_cited_source_ids(
    markdown: str,
    section_key: str,
    output_language: str,
) -> set[str]:
    section = _find_section(markdown, section_key, output_language)
    if section is None:
        return set()
    return {normalize_source_token(token) for token in source_tokens(section.body)}


def _user_research_source_ids(detail: RunDetail) -> set[str]:
    return {
        source.id
        for source in detail.raw_sources
        if source.source_type in USER_RESEARCH_SOURCE_TYPES
    }


def _previous_review_section_has_user_research_semantics(detail: RunDetail) -> bool:
    section = _find_section(
        detail.report_md,
        "review_theme_summary",
        detail.output_language,
    )
    if section is None:
        return False
    body = re.sub(r"\[source:[^\]]+\]", "", section.body).casefold()
    return any(token in body for token in USER_RESEARCH_REVIEW_SEMANTIC_TOKENS)


def _section_content_chars(
    section: MarkdownSection | None,
) -> int:
    if section is None:
        return 0
    body = re.sub(r"\[source:[^\]]+\]", "", section.body)
    body = re.sub(r"\s+", " ", body).strip()
    return len(body)


def _sections_use_different_scripts(
    previous: MarkdownSection,
    candidate: MarkdownSection,
) -> bool:
    return _contains_cjk(previous.heading + "\n" + previous.body) != _contains_cjk(
        candidate.heading + "\n" + candidate.body
    )


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))
