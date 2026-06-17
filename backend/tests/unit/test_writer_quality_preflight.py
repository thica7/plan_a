from __future__ import annotations

from datetime import datetime

from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


def _detail() -> RunDetail:
    return RunDetail(
        id="run-quality-preflight",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
    )


def test_quality_preflight_fails_duplicate_sections() -> None:
    result = run_writer_quality_preflight(
        _detail(),
        "\n\n".join(
            [
                "## Decision Summary\nFirst.",
                "## Decision Summary\nSecond.",
                "## Competitive Findings\nFindings.",
                "## User Review Themes\nThemes.",
                "## Competitor Deep Dives\nDeep dives.",
                "## Side-by-Side Decision Matrix\nMatrix.",
                "## SWOT Analysis\nSWOT.",
            ]
        ),
    )

    assert result.passed is False
    assert result.duplicate_section_count == 1
    assert result.failure_reasons == ["duplicate_sections"]
    assert result.h2_keys.count("decision_summary") == 2


def test_quality_preflight_fails_core_after_support() -> None:
    result = run_writer_quality_preflight(
        _detail(),
        "\n\n".join(
            [
                "## Decision Summary\nDecision.",
                "## Competitive Findings\nFindings.",
                "## User Review Themes\nThemes.",
                "## Evidence & QA Support\nSupport.",
                "## Competitor Deep Dives\nDeep dives.",
                "## Side-by-Side Decision Matrix\nMatrix.",
                "## SWOT Analysis\nSWOT.",
            ]
        ),
    )

    assert result.passed is False
    assert result.first_support_key == "evidence_support"
    assert result.core_sections_after_support == [
        "competitor_deep_dives",
        "side_by_side_matrix",
        "swot_analysis",
    ]
    assert "core_sections_after_support" in result.failure_reasons
    assert "missing_core_sections" in result.failure_reasons


def test_quality_preflight_passes_ordered_core_report() -> None:
    result = run_writer_quality_preflight(
        _detail(),
        "\n\n".join(
            [
                "## Decision Summary\nDecision.",
                "## Competitive Findings\nFindings.",
                "## User Review Themes\nThemes.",
                "## Competitor Deep Dives\nDeep dives.",
                "## Side-by-Side Decision Matrix\nMatrix.",
                "## SWOT Analysis\nSWOT.",
                "## Evidence & QA Support\nSupport.",
            ]
        ),
    )

    assert result.passed is True
    assert result.failure_reasons == []
    assert result.duplicate_section_count == 0
    assert result.missing_core_sections == []
    assert result.core_sections_after_support == []
    assert result.telemetry_payload() == {
        "passed": True,
        "failure_reasons": [],
        "duplicate_section_count": 0,
        "missing_core_sections": [],
        "core_sections_after_support": [],
        "first_support_key": "evidence_support",
        "h2_keys": [
            "decision_summary",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        ],
    }


def test_quality_preflight_passes_user_research_gap_section() -> None:
    result = run_writer_quality_preflight(
        _detail(),
        "\n\n".join(
            [
                "## Decision Summary\nDecision.",
                "## Competitive Findings\nFindings.",
                (
                    "## User Review Themes\nNo user research evidence was available; "
                    "treat persona conclusions as an evidence gap."
                ),
                "## Competitor Deep Dives\nDeep dives.",
                "## Side-by-Side Decision Matrix\nMatrix.",
                "## SWOT Analysis\nSWOT.",
                "## Evidence & QA Support\nSupport.",
            ]
        ),
    )

    assert result.passed is True
    assert result.missing_core_sections == []
    assert "review_theme_summary" in result.h2_keys
