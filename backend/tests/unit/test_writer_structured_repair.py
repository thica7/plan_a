from __future__ import annotations

from packages.agents.writer.repair import structured_repair_target_for_issue
from packages.schema.models import QCIssue, RedoScope


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
