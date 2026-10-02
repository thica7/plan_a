import re

from packages.schema.models import QCIssue, RevisionRecord


def repair_issue_key(issue: QCIssue | dict) -> str:
    payload = issue.model_dump(mode="json") if isinstance(issue, QCIssue) else issue
    scope = payload.get("redo_scope") or {}
    metadata = payload.get("metadata") or {}
    objects = []
    for kind in ("source", "source_token", "claim", "evidence", "object"):
        values = metadata.get(f"{kind}_ids") or metadata.get(f"{kind}_id")
        if kind == "source_token":
            values = metadata.get("source_tokens") or metadata.get("source_token")
        if values:
            objects.extend(f"{kind}:{value}" for value in (
                values if isinstance(values, list) else [values]
            ))
    identity = ",".join(sorted(set(objects))) or re.sub(
        r"\s+", " ", str(payload.get("problem") or ""),
    ).strip()
    return "|".join(str(value or "") for value in (
        payload.get("field_path"), payload.get("target_competitor"),
        payload.get("target_subagent"), scope.get("kind"),
        payload.get("detected_by"), metadata.get("rule_id") or metadata.get("issue_type"), identity,
    ))


def repair_acceptance(
    revision: RevisionRecord,
    *,
    after_issue_ids: list[str],
    after_report_version_id: str | None,
    before_report_version_id: str | None = None,
    writer_metadata: dict | None = None,
    after_issue_keys: dict[str, str] | None = None,
) -> dict[str, object]:
    before_ids = revision.qa_issue_ids_before or revision.issue_ids
    selected = revision.issue_ids or before_ids
    before_keys = revision.metadata.get("repair_issue_keys_by_id") or {}
    after_keys = after_issue_keys or revision.metadata.get("qa_issue_keys_after") or {}
    before_keys = {**after_keys, **before_keys}
    selected_keys = {before_keys.get(item, item) for item in selected}
    after_set = {after_keys.get(item, item) for item in after_issue_ids}
    resolved = [item for item in selected if before_keys.get(item, item) not in after_set]
    remaining = [item for item in after_issue_ids if after_keys.get(item, item) in selected_keys]
    before_count = len({before_keys.get(item, item) for item in before_ids})
    before_count += max(0, revision.issue_count_before - len(before_ids))
    improved = len(after_set) < before_count
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
