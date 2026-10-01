from packages.schema.models import RevisionRecord


def repair_acceptance(
    revision: RevisionRecord,
    *,
    after_issue_ids: list[str],
    after_report_version_id: str | None,
    before_report_version_id: str | None = None,
    writer_metadata: dict | None = None,
) -> dict[str, object]:
    before_ids = revision.qa_issue_ids_before or revision.issue_ids
    selected = revision.issue_ids or before_ids
    after_set = set(after_issue_ids)
    resolved = [item for item in selected if item not in after_set]
    remaining = [item for item in selected if item in after_set]
    improved = len(after_issue_ids) < revision.issue_count_before
    writer = {**(writer_metadata or {}), **revision.metadata}
    return {
        "revision_id": revision.id, "iteration": revision.iteration,
        "issue_ids": selected, "mode": writer.get("writer_repair_mode") or revision.stage,
        "sections": writer.get("writer_repair_sections") or [],
        "redo_scopes": [scope.model_dump(mode="json") for scope in revision.redo_scopes],
        "before_report_version_id": (
            writer.get("before_report_version_id") or before_report_version_id
        ),
        "after_report_version_id": after_report_version_id,
        "before_issue_count": revision.issue_count_before,
        "after_issue_count": len(after_issue_ids),
        "before_issue_ids": before_ids, "after_issue_ids": after_issue_ids,
        "resolved_issue_ids": resolved, "remaining_issue_ids": remaining,
        "improved": improved, "no_progress": not improved,
    }


def repeated_no_progress(revisions: list[RevisionRecord]) -> bool:
    if len(revisions) < 2:
        return False
    previous, latest = revisions[-2:]
    previous_keys = previous.metadata.get("repair_issue_keys") or previous.issue_ids
    latest_keys = latest.metadata.get("repair_issue_keys") or latest.issue_ids
    if not latest_keys or set(previous_keys) != set(latest_keys):
        return False
    for revision in (previous, latest):
        if revision.issue_count_after < revision.issue_count_before:
            return False
    return True
