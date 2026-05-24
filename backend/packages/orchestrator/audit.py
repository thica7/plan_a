from __future__ import annotations

from packages.schema.api_dto import RunDetail
from packages.schema.models import RedoScope, RevisionRecord


def build_revision_record(
    detail: RunDetail,
    *,
    iteration: int,
    stage: str,
    redo_scope: RedoScope,
    redo_scopes: list[RedoScope],
    before_md: str,
    issue_ids: list[str],
    qa_issue_ids_before: list[str],
    issue_count_before: int,
) -> RevisionRecord:
    return RevisionRecord(
        id=f"rev-{iteration}",
        iteration=iteration,
        stage=stage,
        target_subagent=redo_scope.target_subagent,
        target_competitor=redo_scope.target_competitor,
        target_competitors=redo_scope.target_competitors,
        redo_scopes=redo_scopes,
        before_md=before_md,
        after_md=detail.report_md,
        issue_ids=issue_ids,
        qa_issue_ids_before=qa_issue_ids_before,
        issue_count_before=issue_count_before,
        issue_count_after=len(detail.qa_findings),
        convergence_ratio=convergence_ratio(issue_count_before, len(detail.qa_findings)),
    )


def convergence_ratio(issue_count_before: int, issue_count_after: int) -> float:
    return round(issue_count_after / max(1, issue_count_before), 3)
