from packages.orchestrator.scoping import assign_redo_scope
from packages.schema.models import QCIssue, RedoScope


def test_collect_qa_issue_routes_back_to_specific_collector_branch() -> None:
    issue = QCIssue(
        id="missing-pricing-a",
        severity="blocker",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="pricing",
        target_competitor="A",
        field_path="raw_sources",
        problem="A has no pricing evidence.",
        redo_scope=RedoScope(kind="full", rationale="placeholder"),
    )

    scope = assign_redo_scope(issue)

    assert scope.kind == "collector"
    assert scope.target_subagent == "pricing"
    assert scope.target_competitor == "A"
