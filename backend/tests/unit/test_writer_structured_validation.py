from __future__ import annotations

import pytest

from packages.agents.writer.structured_renderer import render_structured_report
from packages.agents.writer.structured_validation import validate_structured_report
from test_writer_structured_renderer import _report


DEFAULT_SOURCE_IDS = {"raw-source-a", "raw-source-b"}


def _clean_report():
    report = _report()

    report.core.user_review_themes.competitor_themes.append(
        report.core.user_review_themes.competitor_themes[0].model_copy(
            deep=True,
            update={"competitor": "Windsurf"},
        )
    )
    report.core.competitor_deep_dives.append(
        report.core.competitor_deep_dives[0].model_copy(
            deep=True,
            update={"competitor": "Windsurf"},
        )
    )
    report.core.swot.competitors.append(
        report.core.swot.competitors[0].model_copy(
            deep=True,
            update={"competitor": "Windsurf"},
        )
    )
    report.core.battlecard.plays.insert(
        0,
        report.core.battlecard.plays[0].model_copy(
            deep=True,
            update={"competitor": "Cursor"},
        ),
    )

    return report


def _validate(report, *, allowed_source_ids=None, strong_source_ids=None):
    return validate_structured_report(
        report,
        allowed_source_ids=(
            DEFAULT_SOURCE_IDS if allowed_source_ids is None else allowed_source_ids
        ),
        strong_source_ids=(
            DEFAULT_SOURCE_IDS if strong_source_ids is None else strong_source_ids
        ),
    )


def test_unknown_cited_text_source_ids_are_rejected_with_recommendation_path() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation.source_ids = ["missing-source"]

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "invalid_source_id"
        and "core.executive_summary.recommendation" in issue.path
        for issue in validation.issues
    )


def test_unknown_matrix_cell_source_ids_are_rejected() -> None:
    report = _clean_report()
    report.core.decision_matrix.dimensions[0].cells[0].source_ids = [
        "missing-source"
    ]

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "invalid_source_id"
        and issue.path == "core.decision_matrix.dimensions[0].cells[0].source_ids[0]"
        for issue in validation.issues
    )


def test_unknown_source_appendix_source_id_is_rejected() -> None:
    report = _clean_report()
    report.support.evidence_appendix[0].source_id = "missing-source"

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "invalid_source_id"
        and issue.path == "support.evidence_appendix[0].source_id"
        for issue in validation.issues
    )


def test_invalid_source_id_grammar_is_rejected_before_publication() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation.source_ids = ["bad source id"]

    validation = _validate(
        report,
        allowed_source_ids={*DEFAULT_SOURCE_IDS, "bad source id"},
    )

    assert not validation.passed
    assert any(
        issue.code == "invalid_source_id"
        and issue.path == "core.executive_summary.recommendation.source_ids[0]"
        for issue in validation.issues
    )


def test_explicit_empty_allowed_source_ids_are_not_replaced_by_defaults() -> None:
    validation = _validate(_clean_report(), allowed_source_ids=set())

    assert not validation.passed
    assert any(
        issue.code == "invalid_source_id"
        and issue.path == "core.executive_summary.recommendation.source_ids[0]"
        for issue in validation.issues
    )


def test_weak_recommendation_evidence_rejects_gap_roles_and_missing_strong_sources() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation.evidence_role = "simulated_research"

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "weak_recommendation_evidence"
        and issue.repair_target == "core.executive_summary"
        for issue in validation.issues
    )

    report = _clean_report()
    validation = _validate(report, strong_source_ids={"raw-source-b"})

    assert not validation.passed
    assert any(issue.code == "weak_recommendation_evidence" for issue in validation.issues)


@pytest.mark.parametrize("evidence_role", ["simulated_research", "evidence_gap"])
def test_risk_adjusted_rationale_weak_evidence_roles_are_rejected(
    evidence_role: str,
) -> None:
    report = _clean_report()
    report.core.executive_summary.risk_adjusted_rationale.evidence_role = (
        evidence_role
    )

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "weak_recommendation_evidence"
        and issue.path == "core.executive_summary.risk_adjusted_rationale"
        and issue.repair_target == "core.executive_summary"
        for issue in validation.issues
    )


def test_risk_adjusted_rationale_missing_strong_source_is_rejected() -> None:
    report = _clean_report()

    validation = _validate(report, strong_source_ids={"raw-source-a"})

    assert not validation.passed
    assert any(
        issue.code == "weak_recommendation_evidence"
        and issue.path == "core.executive_summary.risk_adjusted_rationale"
        and issue.repair_target == "core.executive_summary"
        for issue in validation.issues
    )


def test_template_only_battlecard_is_rejected() -> None:
    report = _clean_report()
    play = report.core.battlecard.plays[0]
    play.use_when.text = "direct battlecard positioning"
    play.attack_points[0].text = "objection handling"
    play.defense_points[0].text = "deployment check"

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "battlecard_template_only"
        and issue.repair_target == "core.battlecard"
        for issue in validation.issues
    )


def test_template_like_executive_summary_is_rejected() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation.text = (
        "This report is structured as decision analysis first with core conclusion "
        "and decision posture."
    )
    report.core.executive_summary.risk_adjusted_rationale.text = "risk boundary"

    validation = _validate(report)

    assert not validation.passed
    assert "executive_summary_template_only" in validation.issue_codes()
    assert "executive_summary_missing_risk_adjusted_rationale" in validation.issue_codes()


def test_structured_validation_rejects_template_only_executive_summary() -> None:
    report = _report()
    report.core.executive_summary.recommendation.text = "core conclusion"

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-a"},
        strong_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "executive_summary_template_only" in result.issue_codes()


def test_internal_terms_are_rejected_in_cited_text_before_rendering() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation.text = (
        "The source_registry entry must never reach published output."
    )

    assert "source_registry" in render_structured_report(report)

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "internal_term_leak"
        and issue.path == "core.executive_summary.recommendation.text"
        for issue in validation.issues
    )


def test_internal_terms_are_rejected_in_matrix_summary_and_appendix_title() -> None:
    report = _clean_report()
    report.core.decision_matrix.dimensions[0].cells[0].summary = (
        "This represented_by marker is internal."
    )
    report.support.evidence_appendix[0].title = "Segment Evidence Pack JSON export"

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "internal_term_leak"
        and issue.path == "core.decision_matrix.dimensions[0].cells[0].summary"
        for issue in validation.issues
    )
    assert any(
        issue.code == "internal_term_leak"
        and issue.path == "support.evidence_appendix[0].title"
        for issue in validation.issues
    )


def test_markdown_source_token_leakage_is_rejected_in_cited_text_and_matrix_summary() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation = (
        report.core.executive_summary.recommendation.model_copy(
            update={"text": "Leaked raw citation [source:raw-source-a]"}
        )
    )
    report.core.decision_matrix.dimensions[0].cells[0] = (
        report.core.decision_matrix.dimensions[0].cells[0].model_copy(
            update={"summary": "Leaked matrix citation [Source:raw-source-a]"}
        )
    )

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "markdown_source_token_in_text"
        and issue.path == "core.executive_summary.recommendation.text"
        for issue in validation.issues
    )
    assert any(
        issue.code == "markdown_source_token_in_text"
        and issue.path == "core.decision_matrix.dimensions[0].cells[0].summary"
        for issue in validation.issues
    )


@pytest.mark.parametrize(
    ("field_label", "expected_path"),
    [
        ("appendix_title", "support.evidence_appendix[0].title"),
        ("battlecard_target_buyer", "core.battlecard.plays[0].target_buyer"),
        ("topic", "topic"),
        ("competitor_heading", "competitors[0]"),
        ("matrix_dimension", "core.decision_matrix.dimensions[0].dimension"),
    ],
)
def test_markdown_source_token_leakage_is_rejected_in_renderer_visible_strings(
    field_label: str,
    expected_path: str,
) -> None:
    report = _clean_report()
    raw_text = "leaked renderer-visible value [source:raw-source-a]"
    if field_label == "appendix_title":
        report.support.evidence_appendix[0].title = raw_text
    elif field_label == "battlecard_target_buyer":
        report.core.battlecard.plays[0].target_buyer = raw_text
    elif field_label == "topic":
        report.topic = raw_text
    elif field_label == "competitor_heading":
        report.competitors[0] = raw_text
    elif field_label == "matrix_dimension":
        report.core.decision_matrix.dimensions[0].dimension = raw_text
    else:
        raise AssertionError(f"Unhandled field label: {field_label}")

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "markdown_source_token_in_text"
        and issue.path == expected_path
        for issue in validation.issues
    )


def test_internal_terms_are_rejected_in_battlecard_target_buyer() -> None:
    report = _clean_report()
    report.core.battlecard.plays[0].target_buyer = (
        "Engineering lead using source_registry notes"
    )

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "internal_term_leak"
        and issue.path == "core.battlecard.plays[0].target_buyer"
        for issue in validation.issues
    )


def test_missing_competitor_coverage_is_rejected() -> None:
    validation = _validate(_report())

    assert not validation.passed
    assert any(
        issue.code == "competitor_coverage_missing"
        and "Windsurf" in issue.message
        and "user_review_themes" in issue.message
        for issue in validation.issues
    )
    assert any(
        issue.code == "competitor_coverage_missing"
        and "Windsurf" in issue.message
        and "swot" in issue.message
        for issue in validation.issues
    )
    assert any(
        issue.code == "competitor_coverage_missing"
        and "Windsurf" in issue.message
        and "competitor_deep_dives" in issue.message
        for issue in validation.issues
    )
    assert any(
        issue.code == "competitor_coverage_missing"
        and "Cursor" in issue.message
        and "battlecard" in issue.message
        for issue in validation.issues
    )


def test_missing_user_theme_competitor_coverage_is_rejected() -> None:
    report = _clean_report()
    report.core.user_review_themes.competitor_themes = [
        theme
        for theme in report.core.user_review_themes.competitor_themes
        if theme.competitor != "Windsurf"
    ]

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "competitor_coverage_missing"
        and issue.path == "core.user_review_themes.competitor_themes"
        and "Windsurf" in issue.message
        and "user_review_themes" in issue.message
        for issue in validation.issues
    )


def test_missing_swot_competitor_coverage_is_rejected() -> None:
    report = _clean_report()
    report.core.swot.competitors = [
        swot
        for swot in report.core.swot.competitors
        if swot.competitor != "Windsurf"
    ]

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "competitor_coverage_missing"
        and issue.path == "core.swot.competitors"
        and "Windsurf" in issue.message
        and "swot" in issue.message
        for issue in validation.issues
    )


def test_empty_swot_quadrant_is_rejected() -> None:
    report = _clean_report()
    report.core.swot.competitors[0].strengths = []

    validation = _validate(report)

    assert not validation.passed
    assert any(
        issue.code == "swot_quadrant_missing"
        and issue.path == "core.swot.competitors[0].strengths"
        for issue in validation.issues
    )


def test_clean_fixture_with_all_requested_competitors_covered_passes() -> None:
    validation = _validate(_clean_report())

    assert validation.passed
    assert validation.issues == []
    assert validation.issue_codes() == []


def test_validation_passing_report_renders_without_hygiene_errors() -> None:
    report = _clean_report()
    validation = _validate(report)

    assert validation.passed
    render_structured_report(report)


def test_telemetry_payload_includes_status_counts_codes_and_repair_targets() -> None:
    report = _clean_report()
    report.core.executive_summary.recommendation.source_ids = ["missing-source"]
    report.core.battlecard.plays[0].use_when.text = "direct battlecard positioning"

    validation = _validate(report)
    payload = validation.telemetry_payload()

    assert payload["passed"] is False
    assert payload["issue_count"] == len(validation.issues)
    assert "invalid_source_id" in payload["issue_codes"]
    assert "battlecard_template_only" in payload["issue_codes"]
    assert "core.battlecard" in payload["repair_targets"]
