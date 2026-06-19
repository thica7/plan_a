from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from packages.agents.writer.structured_report import (
    BattlecardPlay,
    CitedText,
    StructuredReport,
)


_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:#-]+$")
_SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]", re.IGNORECASE)
_INTERNAL_TERM_RES = [
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
]
_WEAK_RECOMMENDATION_ROLES = {"simulated_research", "evidence_gap"}
_BATTLECARD_TEMPLATE_TERMS = (
    "直接战报定位",
    "反对意见处理",
    "行动偏向",
    "落地检查",
    "direct battlecard positioning",
    "objection handling",
    "deployment check",
)
_EXECUTIVE_TEMPLATE_TERMS = (
    "This report is structured as decision analysis first",
    "core conclusion",
    "decision posture",
    "risk boundary",
    "immediate action",
    "核心结论",
    "决策姿态",
    "风险边界",
    "立即行动",
)
_SWOT_QUADRANTS = ("strengths", "weaknesses", "opportunities", "threats")
_MIN_RISK_RATIONALE_CHARS = 20
_MIN_SUBSTANTIVE_BATTLECARD_FIELDS = 4


@dataclass(frozen=True)
class StructuredValidationIssue:
    code: str
    path: str
    message: str
    repair_target: str


@dataclass(frozen=True)
class StructuredReportValidation:
    passed: bool
    issues: list[StructuredValidationIssue]

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


def validate_structured_report(
    report: StructuredReport,
    *,
    allowed_source_ids: set[str],
    strong_source_ids: set[str],
) -> StructuredReportValidation:
    issues: list[StructuredValidationIssue] = []

    _validate_source_ids(report, allowed_source_ids, issues)
    _validate_recommendation_evidence(report, strong_source_ids, issues)
    _validate_competitor_coverage(report, issues)
    _validate_swot_quadrants(report, issues)
    _validate_text_leakage(report, issues)
    _validate_battlecards(report, issues)
    _validate_executive_summary(report, issues)

    return StructuredReportValidation(passed=not issues, issues=issues)


def _validate_source_ids(
    report: StructuredReport,
    allowed_source_ids: set[str],
    issues: list[StructuredValidationIssue],
) -> None:
    for path, cited_text in report.iter_cited_text():
        for index, source_id in enumerate(cited_text.source_ids):
            _validate_source_id(
                source_id,
                path=f"{path}.source_ids[{index}]",
                allowed_source_ids=allowed_source_ids,
                repair_target=path,
                issues=issues,
            )

    for path, cell in report.iter_matrix_cells():
        for index, source_id in enumerate(cell.source_ids):
            _validate_source_id(
                source_id,
                path=f"{path}.source_ids[{index}]",
                allowed_source_ids=allowed_source_ids,
                repair_target=path,
                issues=issues,
            )

    for path, row in report.iter_source_appendix_rows():
        _validate_source_id(
            row.source_id,
            path=f"{path}.source_id",
            allowed_source_ids=allowed_source_ids,
            repair_target=path,
            issues=issues,
        )


def _validate_source_id(
    source_id: str,
    *,
    path: str,
    allowed_source_ids: set[str],
    repair_target: str,
    issues: list[StructuredValidationIssue],
) -> None:
    if not _SOURCE_ID_RE.fullmatch(source_id):
        issues.append(
            StructuredValidationIssue(
                code="invalid_source_id",
                path=path,
                message=f"Source ID {source_id!r} contains invalid characters.",
                repair_target=repair_target,
            )
        )
        return

    if source_id not in allowed_source_ids:
        issues.append(
            StructuredValidationIssue(
                code="invalid_source_id",
                path=path,
                message=f"Source ID {source_id!r} is not in allowed_source_ids.",
                repair_target=repair_target,
            )
        )


def _validate_recommendation_evidence(
    report: StructuredReport,
    strong_source_ids: set[str],
    issues: list[StructuredValidationIssue],
) -> None:
    summary = report.core.executive_summary
    fields = (
        ("core.executive_summary.recommendation", summary.recommendation),
        (
            "core.executive_summary.risk_adjusted_rationale",
            summary.risk_adjusted_rationale,
        ),
    )
    for path, claim in fields:
        uses_weak_role = claim.evidence_role in _WEAK_RECOMMENDATION_ROLES
        has_strong_source = any(
            source_id in strong_source_ids for source_id in claim.source_ids
        )
        if uses_weak_role or not has_strong_source:
            issues.append(
                StructuredValidationIssue(
                    code="weak_recommendation_evidence",
                    path=path,
                    message=(
                        "Recommendation and risk-adjusted rationale require at "
                        "least one strong source and cannot rely on simulated "
                        "research or evidence gaps."
                    ),
                    repair_target="core.executive_summary",
                )
            )


def _validate_competitor_coverage(
    report: StructuredReport,
    issues: list[StructuredValidationIssue],
) -> None:
    requested = [(competitor, _competitor_key(competitor)) for competitor in report.competitors]
    section_sets = {
        "competitor_deep_dives": {
            _competitor_key(deep_dive.competitor)
            for deep_dive in report.core.competitor_deep_dives
        },
        "user_review_themes": {
            _competitor_key(theme.competitor)
            for theme in report.core.user_review_themes.competitor_themes
        },
        "swot": {
            _competitor_key(swot.competitor)
            for swot in report.core.swot.competitors
        },
        "battlecard": {
            _competitor_key(play.competitor) for play in report.core.battlecard.plays
        },
    }
    section_paths = {
        "competitor_deep_dives": "core.competitor_deep_dives",
        "user_review_themes": "core.user_review_themes.competitor_themes",
        "swot": "core.swot.competitors",
        "battlecard": "core.battlecard.plays",
    }

    for section_name, covered_competitors in section_sets.items():
        for competitor, key in requested:
            if key not in covered_competitors:
                path = section_paths[section_name]
                issues.append(
                    StructuredValidationIssue(
                        code="competitor_coverage_missing",
                        path=path,
                        message=(
                            f"Missing requested competitor {competitor!r} in "
                            f"{section_name}."
                        ),
                        repair_target=path,
                    )
                )


def _competitor_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_swot_quadrants(
    report: StructuredReport,
    issues: list[StructuredValidationIssue],
) -> None:
    for competitor_index, swot in enumerate(report.core.swot.competitors):
        for quadrant in _SWOT_QUADRANTS:
            if not getattr(swot, quadrant):
                path = f"core.swot.competitors[{competitor_index}].{quadrant}"
                issues.append(
                    StructuredValidationIssue(
                        code="swot_quadrant_missing",
                        path=path,
                        message=(
                            f"SWOT quadrant {quadrant!r} is empty for "
                            f"{swot.competitor!r}."
                        ),
                        repair_target="core.swot",
                    )
                )


def _validate_text_leakage(
    report: StructuredReport,
    issues: list[StructuredValidationIssue],
) -> None:
    for path, cited_text in report.iter_cited_text():
        _validate_text_field(
            cited_text.text,
            path=f"{path}.text",
            repair_target=path,
            check_source_tokens=True,
            issues=issues,
        )

    for path, cell in report.iter_matrix_cells():
        _validate_text_field(
            cell.summary,
            path=f"{path}.summary",
            repair_target=path,
            check_source_tokens=True,
            issues=issues,
        )

    for path, row in report.iter_source_appendix_rows():
        for field_name in ("title", "url", "competitor", "dimension"):
            _validate_text_field(
                getattr(row, field_name),
                path=f"{path}.{field_name}",
                repair_target=path,
                check_source_tokens=False,
                issues=issues,
            )


def _validate_text_field(
    text: str,
    *,
    path: str,
    repair_target: str,
    check_source_tokens: bool,
    issues: list[StructuredValidationIssue],
) -> None:
    if check_source_tokens and _SOURCE_TOKEN_RE.search(text):
        issues.append(
            StructuredValidationIssue(
                code="markdown_source_token_in_text",
                path=path,
                message="Text contains a raw Markdown source token.",
                repair_target=repair_target,
            )
        )

    if any(pattern.search(text) for pattern in _INTERNAL_TERM_RES):
        issues.append(
            StructuredValidationIssue(
                code="internal_term_leak",
                path=path,
                message="Text contains internal writer or evidence-pack terminology.",
                repair_target=repair_target,
            )
        )


def _validate_battlecards(
    report: StructuredReport,
    issues: list[StructuredValidationIssue],
) -> None:
    for play_index, play in enumerate(report.core.battlecard.plays):
        path = f"core.battlecard.plays[{play_index}]"
        text_values = [text for _path, text in _battlecard_text_fields(path, play)]
        joined = "\n".join(text_values)
        has_template_terms = _contains_any_term(joined, _BATTLECARD_TEMPLATE_TERMS)
        substantive_count = sum(
            1 for text in text_values if _is_substantive_battlecard_text(text)
        )

        if (
            has_template_terms
            or substantive_count < _MIN_SUBSTANTIVE_BATTLECARD_FIELDS
        ):
            issues.append(
                StructuredValidationIssue(
                    code="battlecard_template_only",
                    path=path,
                    message=(
                        "Battlecard play looks generic or lacks enough "
                        "substantive play-specific fields."
                    ),
                    repair_target="core.battlecard",
                )
            )


def _battlecard_text_fields(
    path: str,
    play: BattlecardPlay,
) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = [(f"{path}.target_buyer", play.target_buyer)]
    fields.append((f"{path}.use_when.text", play.use_when.text))
    for field_name in (
        "attack_points",
        "defense_points",
        "likely_objections",
        "rebuttal_talk_tracks",
        "proof_needed_before_external_use",
    ):
        for item_index, claim in enumerate(getattr(play, field_name)):
            fields.append((f"{path}.{field_name}[{item_index}].text", claim.text))
    return fields


def _is_substantive_battlecard_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 18:
        return False
    return not _contains_any_term(stripped, _BATTLECARD_TEMPLATE_TERMS)


def _validate_executive_summary(
    report: StructuredReport,
    issues: list[StructuredValidationIssue],
) -> None:
    summary = report.core.executive_summary
    fields: tuple[tuple[str, CitedText], ...] = (
        ("core.executive_summary.recommendation", summary.recommendation),
        (
            "core.executive_summary.risk_adjusted_rationale",
            summary.risk_adjusted_rationale,
        ),
    )

    if any(
        _contains_any_term(claim.text, _EXECUTIVE_TEMPLATE_TERMS)
        for _path, claim in fields
    ):
        issues.append(
            StructuredValidationIssue(
                code="executive_summary_template_only",
                path="core.executive_summary",
                message="Executive summary contains template or system-style wording.",
                repair_target="core.executive_summary",
            )
        )

    rationale = summary.risk_adjusted_rationale.text.strip()
    if len(rationale) < _MIN_RISK_RATIONALE_CHARS:
        issues.append(
            StructuredValidationIssue(
                code="executive_summary_missing_risk_adjusted_rationale",
                path="core.executive_summary.risk_adjusted_rationale",
                message="Risk-adjusted rationale is too short to support the decision.",
                repair_target="core.executive_summary",
            )
        )


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)
