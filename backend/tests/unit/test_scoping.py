from packages.orchestrator.scoping import assign_redo_scope, build_redo_scope
from packages.schema.models import QCIssue, RedoScope


def test_assign_redo_scope_for_citation() -> None:
    issue = QCIssue(
        id="citation-1",
        severity="blocker",
        detected_by="citation",
        target_agent="writer",
        field_path="report_md",
        problem="Phantom citation",
        redo_scope=RedoScope(kind="full", rationale="placeholder"),
    )

    scope = assign_redo_scope(issue)

    assert scope.kind == "writer_only"


def test_assign_redo_scope_for_missing_pricing_evidence() -> None:
    issue = QCIssue(
        id="missing-pricing",
        severity="blocker",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="pricing",
        field_path="raw_sources[pricing]",
        problem="No evidence sources were collected for pricing.",
        redo_scope=RedoScope(kind="full", rationale="placeholder"),
    )

    scope = assign_redo_scope(issue)

    assert scope.kind == "collector"
    assert scope.target_subagent == "pricing"


def test_assign_redo_scope_for_empty_analyst_output() -> None:
    issue = QCIssue(
        id="empty-analyst-pricing-alpha",
        severity="warn",
        detected_by="schema",
        target_agent="analyst",
        target_subagent="pricing",
        field_path="competitor_kbs[Alpha].slices[pricing]",
        problem="Pricing analyst did not produce structured findings for Alpha.",
        redo_scope=RedoScope(kind="full", rationale="placeholder"),
    )

    scope = assign_redo_scope(issue)

    assert scope.kind == "analyst"
    assert scope.target_subagent == "pricing"


def test_build_redo_scope_matches_issue_assignment() -> None:
    issue = QCIssue(
        id="collector-low-quality",
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="feature",
        target_competitor="Alpha",
        field_path="raw_sources[feature-1]",
        problem="Feature source is too thin to support the claim.",
        redo_scope=RedoScope(kind="full", rationale="placeholder"),
    )

    scope = build_redo_scope(
        detected_by=issue.detected_by,
        target_agent=issue.target_agent,
        target_subagent=issue.target_subagent,
        target_competitor=issue.target_competitor,
        field_path=issue.field_path,
        problem=issue.problem,
    )

    assert scope == assign_redo_scope(issue)
    assert scope.kind == "collector"
    assert scope.target_subagent == "feature"
    assert scope.target_competitor == "Alpha"
    assert scope.rationale != "placeholder"
