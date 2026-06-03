from packages.schema.models import QCIssue, RedoScope


def build_redo_scope(
    *,
    detected_by: str,
    target_agent: str,
    field_path: str,
    problem: str,
    target_subagent: str | None = None,
    target_competitor: str | None = None,
) -> RedoScope:
    if detected_by == "citation" and target_agent == "writer":
        return RedoScope(kind="writer_only", rationale="phantom citation only")
    if detected_by == "consistency" and "matrix" in field_path:
        return RedoScope(
            kind="comparator",
            target_subagent=target_subagent,
            rationale="comparison matrix mismatch",
        )
    if target_agent == "comparator":
        return RedoScope(
            kind="comparator", target_subagent=target_subagent, rationale=problem
        )
    if target_agent == "analyst":
        return RedoScope(
            kind="analyst",
            target_subagent=target_subagent,
            target_competitor=target_competitor,
            rationale=problem,
        )
    if target_agent == "collector":
        return RedoScope(
            kind="collector",
            target_subagent=target_subagent,
            target_competitor=target_competitor,
            rationale=problem,
        )
    return RedoScope(kind="full", rationale="unscoped blocker")


def assign_redo_scope(issue: QCIssue) -> RedoScope:
    return build_redo_scope(
        detected_by=issue.detected_by,
        target_agent=issue.target_agent,
        target_subagent=issue.target_subagent,
        target_competitor=issue.target_competitor,
        field_path=issue.field_path,
        problem=issue.problem,
    )
