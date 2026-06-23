from __future__ import annotations

from packages.agents.writer.repair import structured_repair_target_for_issue
from packages.agents.writer.structured_repair import (
    merge_scoped_structured_report,
    previous_recommendation_posture,
    recommendation_delta_problem,
    scoped_structured_section_keys,
    structured_scoped_regression_problem,
)
from packages.schema.models import QCIssue, RedoScope


def _scope(kind: str, subagent: str, competitor: str) -> RedoScope:
    return RedoScope(
        kind=kind,
        target_subagent=subagent,
        target_competitor=competitor,
        rationale=f"{competitor} {subagent} redo",
    )


def _issue(
    code: str,
    field_path: str = "report_md",
    *,
    target_subagent: str | None = None,
) -> QCIssue:
    return QCIssue(
        id=f"issue-{code}",
        severity="warn",
        detected_by="schema",
        target_agent="writer",
        target_subagent=target_subagent,
        field_path=field_path,
        problem=code,
        redo_scope=RedoScope(kind="writer_only", rationale="repair"),
    )


def test_structured_repair_maps_localized_issue_codes_to_schema_paths() -> None:
    assert (
        structured_repair_target_for_issue(_issue("battlecard_template_only"))
        == "core.battlecard"
    )
    assert (
        structured_repair_target_for_issue(_issue("executive_summary_template_only"))
        == "core.executive_summary"
    )
    assert (
        structured_repair_target_for_issue(_issue("citation_in_table_header"))
        == "renderer"
    )
    assert (
        structured_repair_target_for_issue(_issue("english_structural_heading_in_zh"))
        == "renderer"
    )
    assert (
        structured_repair_target_for_issue(
            _issue("internal_term_leak", "core.competitive_findings[0]")
        )
        == "core.competitive_findings"
    )


def test_structured_repair_maps_persona_claim_warns_to_user_review_themes() -> None:
    issue = _issue(
        "release_gate.claim_self_consistency_required",
        "report_md.section[user_review_themes]",
    )
    assert structured_repair_target_for_issue(issue) == "core.user_review_themes"


def test_structured_repair_maps_release_gate_claim_subagent_to_schema_paths() -> None:
    issue = _issue(
        "release_gate.claim_self_consistency_required",
        "release_gate.claim_self_consistency_required",
        target_subagent="pricing",
    )
    assert structured_repair_target_for_issue(issue) == "core.decision_matrix"


def test_scoped_structured_section_keys_for_persona_redo() -> None:
    keys = scoped_structured_section_keys([_scope("collector", "persona", "Claude Code")])

    assert keys == {
        "user_review_themes",
        "competitor_deep_dive::Claude Code",
        "support",
    }


def test_scoped_structured_section_keys_for_pricing_redo() -> None:
    keys = scoped_structured_section_keys([_scope("collector", "pricing", "Windsurf")])

    assert keys == {
        "decision_matrix",
        "competitor_deep_dive::Windsurf",
        "support",
    }


def test_scoped_structured_section_keys_for_feature_redo() -> None:
    keys = scoped_structured_section_keys([_scope("collector", "feature", "Cursor")])

    assert keys == {
        "competitor_deep_dive::Cursor",
        "support",
    }


def test_merge_scoped_structured_report_replaces_only_affected_sections() -> None:
    from test_writer_structured_renderer import _report

    previous = _report("en-US")
    candidate = previous.model_copy(deep=True)
    previous.core.executive_summary.recommendation.text = "Keep Cursor as baseline."
    candidate.core.executive_summary.recommendation.text = "Windsurf is the new default."
    previous.core.user_review_themes.cross_competitor_patterns[0].text = (
        "Previous persona pattern."
    )
    candidate.core.user_review_themes.cross_competitor_patterns[0].text = (
        "Updated persona pattern."
    )
    previous.core.competitor_deep_dives[0].persona_adoption[0].text = (
        "Previous Cursor persona adoption."
    )
    candidate.core.competitor_deep_dives[0].persona_adoption[0].text = (
        "Updated Cursor persona adoption."
    )
    previous.core.decision_matrix.interpretation[0].text = "Previous pricing matrix."
    candidate.core.decision_matrix.interpretation[0].text = "Updated pricing matrix."
    previous.support.source_quality[0].text = "Previous support."
    candidate.support.source_quality[0].text = "Updated support."

    merged = merge_scoped_structured_report(
        previous=previous,
        candidate=candidate,
        scopes=[_scope("collector", "persona", "Cursor")],
    )

    assert merged.core.executive_summary.recommendation.text == "Keep Cursor as baseline."
    assert (
        merged.core.user_review_themes.cross_competitor_patterns[0].text
        == "Updated persona pattern."
    )
    assert (
        merged.core.competitor_deep_dives[0].persona_adoption[0].text
        == "Updated Cursor persona adoption."
    )
    assert merged.core.decision_matrix.interpretation[0].text == "Previous pricing matrix."
    assert merged.support.source_quality[0].text == "Updated support."


def test_structured_scoped_regression_problem_detects_thinned_scoped_section() -> None:
    from test_writer_structured_renderer import _report

    previous = _report("en-US")
    candidate = previous.model_copy(deep=True)
    previous.core.user_review_themes.cross_competitor_patterns[0].text = (
        "Previous persona pattern includes adoption blocker, buyer context, "
        "switching trigger, and evidence caveat with enough detail."
    )
    candidate.core.user_review_themes.cross_competitor_patterns[0].text = "Thin."
    candidate.core.user_review_themes.competitor_themes[0].direct_user_signals = []
    merged = merge_scoped_structured_report(
        previous=previous,
        candidate=candidate,
        scopes=[_scope("collector", "persona", "Cursor")],
    )

    problem = structured_scoped_regression_problem(
        previous=previous,
        merged=merged,
        affected_keys=scoped_structured_section_keys(
            [_scope("collector", "persona", "Cursor")]
        ),
    )

    assert problem is not None
    assert "user_review_themes" in problem


def test_structured_scoped_regression_allows_minor_source_count_variation() -> None:
    from test_writer_structured_renderer import _report

    previous = _report("en-US")
    merged = previous.model_copy(deep=True)
    previous_source_ids = [f"raw-source-{index}" for index in range(62)]
    previous.core.competitor_deep_dives[0].positioning[0].source_ids = previous_source_ids
    merged.core.competitor_deep_dives[0].positioning[0].source_ids = previous_source_ids[:-1]

    problem = structured_scoped_regression_problem(
        previous=previous,
        merged=merged,
        affected_keys={"competitor_deep_dives"},
    )

    assert problem is None


def test_structured_scoped_regression_detects_material_source_count_loss() -> None:
    from test_writer_structured_renderer import _report

    previous = _report("en-US")
    merged = previous.model_copy(deep=True)
    previous_source_ids = [f"raw-source-{index}" for index in range(10)]
    previous.core.competitor_deep_dives[0].positioning[0].source_ids = previous_source_ids
    merged.core.competitor_deep_dives[0].positioning[0].source_ids = previous_source_ids[:4]

    problem = structured_scoped_regression_problem(
        previous=previous,
        merged=merged,
        affected_keys={"competitor_deep_dives"},
    )

    assert problem is not None
    assert "source_id_count" in problem


def test_previous_recommendation_posture_uses_structured_report_first() -> None:
    from test_writer_structured_renderer import _report

    report = _report("en-US")
    report.core.executive_summary.recommendation.text = "Choose Cursor."

    assert (
        previous_recommendation_posture(
            previous_structured_report=report,
            previous_report="Recommendation: Choose Windsurf.",
        )
        == "Choose Cursor."
    )


def test_previous_recommendation_posture_extracts_markdown_when_snapshot_missing() -> None:
    markdown = """## Executive Summary
- Recommendation: GitHub Copilot and Cursor are the risk-adjusted primary choices. [source:raw-source-a]
- Risk boundary: validate pricing.
"""

    assert previous_recommendation_posture(
        previous_structured_report=None,
        previous_report=markdown,
    ) == "GitHub Copilot and Cursor are the risk-adjusted primary choices"


def test_previous_recommendation_posture_extracts_localized_summary_markdown() -> None:
    markdown = """<!-- report-section:key=executive_summary layer=core -->
## 执行摘要
- 建议: 优先采用 Cursor 作为团队采购基线。 [source:raw-source-a]
"""

    assert previous_recommendation_posture(
        previous_structured_report=None,
        previous_report=markdown,
    ) == "优先采用 Cursor 作为团队采购基线"


def test_previous_recommendation_posture_extracts_simplified_decision_summary() -> None:
    markdown = """## 决策摘要
- 建议: 采用 Cursor 作为采购基线。 [source:raw-source-a]
"""

    assert previous_recommendation_posture(
        previous_structured_report=None,
        previous_report=markdown,
    ) == "采用 Cursor 作为采购基线"


def test_previous_recommendation_posture_ignores_support_material_suggestions() -> None:
    markdown = """## 支撑材料
#### 后续采集
- 建议: 补充 Windsurf 企业采购案例和安全材料。 [source:raw-source-b]
"""

    assert (
        previous_recommendation_posture(
            previous_structured_report=None,
            previous_report=markdown,
        )
        == ""
    )


def test_recommendation_delta_problem_detects_unjustified_top_choice_change() -> None:
    problem = recommendation_delta_problem(
        previous_recommendation="GitHub Copilot and Cursor are the risk-adjusted primary choices.",
        candidate_recommendation="Windsurf is the primary recommendation.",
        scoped_competitors={"Claude Code"},
        scoped_dimensions={"persona"},
        candidate_rationale="Windsurf has broad feature coverage.",
    )

    assert problem is not None
    assert "recommendation changed" in problem


def test_recommendation_delta_problem_allows_scoped_justification() -> None:
    problem = recommendation_delta_problem(
        previous_recommendation="GitHub Copilot is the baseline.",
        candidate_recommendation="Claude Code is now the primary recommendation.",
        scoped_competitors={"Claude Code"},
        scoped_dimensions={"persona"},
        candidate_rationale=(
            "New Claude Code persona evidence from the scoped redo shows stronger "
            "adoption fit for terminal-heavy teams."
        ),
    )

    assert problem is None
