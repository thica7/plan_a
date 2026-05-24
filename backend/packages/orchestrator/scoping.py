from packages.schema.models import QCIssue, RedoScope


def assign_redo_scope(issue: QCIssue) -> RedoScope:
    if issue.detected_by == "citation" and issue.target_agent == "writer":
        return RedoScope(kind="writer_only", rationale="phantom citation only")
    if issue.detected_by == "consistency" and "matrix" in issue.field_path:
        return RedoScope(
            kind="comparator",
            target_subagent=issue.target_subagent,
            rationale="comparison matrix mismatch",
        )
    if issue.target_agent == "comparator":
        return RedoScope(kind="comparator", target_subagent=issue.target_subagent, rationale=issue.problem)
    if issue.target_agent == "analyst":
        return RedoScope(
            kind="analyst",
            target_subagent=issue.target_subagent,
            target_competitor=issue.target_competitor,
            rationale=issue.problem,
        )
    if issue.target_agent == "collector":
        return RedoScope(
            kind="collector",
            target_subagent=issue.target_subagent,
            target_competitor=issue.target_competitor,
            rationale=issue.problem,
        )
    return RedoScope(kind="full", rationale="unscoped blocker")
