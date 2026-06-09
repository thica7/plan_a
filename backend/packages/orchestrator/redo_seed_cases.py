from __future__ import annotations

from pathlib import Path

from packages.orchestrator.scoping import assign_redo_scope
from packages.schema.models import QCIssue, RedoScope, RedoScopeSeedCase

EXPECTED_REDO_SCOPE_KINDS = {"writer_only", "comparator", "analyst", "collector", "full"}
DEFAULT_REDO_SCOPE_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "redo_scope_seed_cases.expected.json"
)


def build_redo_scope_seed_cases() -> list[RedoScopeSeedCase]:
    cases = [
        _case(
            case_id="writer_phantom_citation",
            description="Report contains a citation token that does not resolve.",
            issue=QCIssue(
                id="seed-writer-phantom-citation",
                severity="blocker",
                detected_by="citation",
                target_agent="writer",
                field_path="report_md",
                problem="Report cites [source:missing] but no matching RawSource exists.",
                redo_scope=RedoScope(kind="full", rationale="placeholder"),
            ),
            expected=RedoScope(kind="writer_only", rationale="phantom citation only"),
        ),
        _case(
            case_id="comparator_matrix_mismatch",
            description="Comparison matrix cell conflicts with structured analyst output.",
            issue=QCIssue(
                id="seed-comparator-matrix-mismatch",
                severity="blocker",
                detected_by="consistency",
                target_agent="comparator",
                target_subagent="pricing",
                field_path="comparison_matrix.cells[pricing][Cursor]",
                problem="Matrix says pricing is unknown while analyst pricing slice has a claim.",
                redo_scope=RedoScope(kind="full", rationale="placeholder"),
            ),
            expected=RedoScope(
                kind="comparator",
                target_subagent="pricing",
                rationale="comparison matrix mismatch",
            ),
        ),
        _case(
            case_id="analyst_empty_slice",
            description="Analyst branch returned no structured findings for a collected slice.",
            issue=QCIssue(
                id="seed-analyst-empty-slice",
                severity="blocker",
                detected_by="schema",
                target_agent="analyst",
                target_subagent="security",
                target_competitor="Glean",
                field_path="competitor_kbs[Glean].slices[security]",
                problem="Security analyst did not produce structured findings for Glean.",
                redo_scope=RedoScope(kind="full", rationale="placeholder"),
            ),
            expected=RedoScope(
                kind="analyst",
                target_subagent="security",
                target_competitor="Glean",
                rationale="Security analyst did not produce structured findings for Glean.",
            ),
        ),
        _case(
            case_id="collector_missing_verified_source",
            description="Collector branch failed to gather verified evidence for a dimension.",
            issue=QCIssue(
                id="seed-collector-missing-verified-source",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                target_competitor="Cursor",
                field_path="raw_sources[Cursor][pricing]",
                problem="No verified pricing source was collected for Cursor.",
                redo_scope=RedoScope(kind="full", rationale="placeholder"),
            ),
            expected=RedoScope(
                kind="collector",
                target_subagent="pricing",
                target_competitor="Cursor",
                rationale="No verified pricing source was collected for Cursor.",
            ),
        ),
        _case(
            case_id="full_unscoped_schema_break",
            description="Planner-level schema break cannot be safely localized.",
            issue=QCIssue(
                id="seed-full-unscoped-schema-break",
                severity="blocker",
                detected_by="schema",
                target_agent="planner",
                field_path="analysis_plan.competitors",
                problem="Planner returned an empty competitor set for a non-empty task.",
                redo_scope=RedoScope(kind="full", rationale="placeholder"),
            ),
            expected=RedoScope(kind="full", rationale="unscoped blocker"),
        ),
    ]
    kinds = {case.assigned_scope.kind for case in cases}
    if kinds != EXPECTED_REDO_SCOPE_KINDS:
        missing = sorted(EXPECTED_REDO_SCOPE_KINDS - kinds)
        extra = sorted(kinds - EXPECTED_REDO_SCOPE_KINDS)
        raise ValueError(f"RedoScope seed coverage mismatch: missing={missing}, extra={extra}")
    return cases


def redo_scope_seed_snapshot(cases: list[RedoScopeSeedCase] | None = None) -> list[dict]:
    return [
        {
            "id": case.id,
            "issue_id": case.issue.id,
            "detected_by": case.issue.detected_by,
            "target_agent": case.issue.target_agent,
            "field_path": case.issue.field_path,
            "expected_kind": case.expected_scope.kind,
            "assigned_kind": case.assigned_scope.kind,
            "target_subagent": case.assigned_scope.target_subagent,
            "target_competitor": case.assigned_scope.target_competitor,
            "rationale": case.assigned_scope.rationale,
        }
        for case in (cases or build_redo_scope_seed_cases())
    ]


def _case(
    *,
    case_id: str,
    description: str,
    issue: QCIssue,
    expected: RedoScope,
) -> RedoScopeSeedCase:
    assigned = assign_redo_scope(issue)
    if assigned != expected:
        raise ValueError(
            f"RedoScope seed case {case_id} expected {expected.kind}, got {assigned.kind}"
        )
    return RedoScopeSeedCase(
        id=case_id,
        description=description,
        issue=issue,
        expected_scope=expected,
        assigned_scope=assigned,
    )
