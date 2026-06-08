from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from packages.artifacts import ArtifactStorage, ArtifactStorageError
from packages.enterprise.source_snapshots import capture_source_snapshot
from packages.enterprise.store import EnterpriseStore
from packages.schema.enterprise import (
    EvidenceGapFillDecisionEvent,
    EvidenceGapFillResult,
    EvidenceRecord,
    ReportVersionRecord,
    SourceSnapshotCreateRequest,
)


def capture_gap_fill_source_snapshots(
    result: EvidenceGapFillResult,
    *,
    store: EnterpriseStore,
    artifact_storage: ArtifactStorage,
    actor_id: str | None,
) -> EvidenceGapFillResult:
    """Assetize online gap-fill evidence so every fetched source is replayable."""

    online_collected_evidence_ids = _online_collected_evidence_ids(result)
    if not online_collected_evidence_ids:
        return result

    evidence_by_id = {
        item.id: item for item in store.list_evidence(project_id=result.project_id)
    }
    artifact_ids: list[str] = []
    source_registry_ids: list[str] = []
    quality_scores: dict[str, int] = {}
    failures: list[dict[str, str]] = []

    for evidence_id in online_collected_evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            failures.append(
                {
                    "evidence_id": evidence_id,
                    "stage": "evidence_lookup",
                    "error": "Online-collected EvidenceRecord was not found.",
                }
            )
            continue
        request = _snapshot_request_from_online_evidence(evidence)
        if request is None:
            failures.append(
                {
                    "evidence_id": evidence.id,
                    "stage": "snapshot_request",
                    "error": "Evidence has no source URL, content, or external pointer.",
                }
            )
            continue
        try:
            snapshot = capture_source_snapshot(
                request,
                store=store,
                artifact_storage=artifact_storage,
                actor_id=actor_id,
            )
        except ArtifactStorageError as exc:
            failures.append(
                {
                    "evidence_id": evidence.id,
                    "stage": "artifact_store",
                    "error": str(exc),
                }
            )
            continue
        artifact_ids.append(snapshot.artifact.id)
        source_registry_ids.append(snapshot.source.id)
        quality_scores[snapshot.artifact.id] = snapshot.snapshot_quality_score
        _link_snapshot_back_to_evidence(
            evidence,
            store=store,
            artifact_id=snapshot.artifact.id,
            source_registry_id=snapshot.source.id,
            snapshot_quality_score=snapshot.snapshot_quality_score,
            snapshot_warnings=snapshot.warnings,
        )

    if not artifact_ids and not failures:
        return result

    decision_event = EvidenceGapFillDecisionEvent(
        event_type="tool.called",
        agent="source_snapshot",
        message=(
            f"Captured {len(artifact_ids)} source snapshot artifact(s) for "
            f"{len(online_collected_evidence_ids)} online gap-fill evidence item(s)."
        ),
        evidence_ids=online_collected_evidence_ids,
        payload={
            "tool": "source_snapshot",
            "online_collected_evidence_ids": online_collected_evidence_ids,
            "online_snapshot_artifact_ids": artifact_ids,
            "online_source_registry_ids": _unique_ids(source_registry_ids),
            "online_snapshot_quality_scores": quality_scores,
            "online_snapshot_failure_count": len(failures),
            "online_snapshot_failures": failures,
        },
    )
    decision_events = [*result.decision_events, decision_event]
    updated_version = _attach_snapshot_metadata_to_report_version(
        result.updated_report_version,
        store=store,
        artifact_ids=artifact_ids,
        source_registry_ids=source_registry_ids,
        quality_scores=quality_scores,
        failures=failures,
        decision_events=decision_events,
    )
    return result.model_copy(
        update={
            "decision_events": decision_events,
            "updated_report_version": updated_version,
        }
    )


def _online_collected_evidence_ids(result: EvidenceGapFillResult) -> list[str]:
    if result.updated_report_version is not None:
        gap_fill = result.updated_report_version.quality_metadata.get("rag_gap_fill")
        if isinstance(gap_fill, dict):
            metadata_ids = _string_list(gap_fill.get("online_collected_evidence_ids"))
            if metadata_ids:
                return metadata_ids
    for event in result.decision_events:
        ids = _string_list(event.payload.get("online_collected_evidence_ids"))
        if ids:
            return ids
    return []


def _snapshot_request_from_online_evidence(
    evidence: EvidenceRecord,
) -> SourceSnapshotCreateRequest | None:
    if not _metadata_bool(evidence.metadata, "online_gap_fill"):
        return None
    source_url = _source_url(evidence)
    full_text = _metadata_text(evidence.metadata, "full_text")
    content_text = full_text or evidence.snippet or None
    if source_url is None and content_text is None:
        return None
    return SourceSnapshotCreateRequest(
        workspace_id=evidence.workspace_id,
        project_id=evidence.project_id,
        evidence_id=evidence.id,
        run_id=evidence.run_id,
        snapshot_kind="webpage",
        artifact_type="web_snapshot",
        filename=_snapshot_filename(evidence),
        media_type="text/plain",
        content_text=content_text,
        source_url=source_url,
        source_type=evidence.source_type,
        display_name=evidence.title,
        trust_level="verified" if evidence.source_type == "webpage_verified" else "unknown",
        robots_status="allowed" if _metadata_bool(evidence.metadata, "fetch_ok") else "unknown",
        metadata={
            "captured_from": "online_gap_fill",
            "online_gap_fill": True,
            "source_evidence_id": evidence.id,
            "gap_id": _metadata_text(evidence.metadata, "gap_id"),
            "query": _metadata_text(evidence.metadata, "query"),
            "recommended_query": _metadata_text(evidence.metadata, "recommended_query"),
            "competitor_id": evidence.competitor_id,
            "dimension": evidence.dimension,
            "content_hash": evidence.content_hash,
            "fetch_status_code": _metadata_value(evidence.metadata, "fetch_status_code"),
        },
    )


def _link_snapshot_back_to_evidence(
    evidence: EvidenceRecord,
    *,
    store: EnterpriseStore,
    artifact_id: str,
    source_registry_id: str,
    snapshot_quality_score: int,
    snapshot_warnings: list[str],
) -> None:
    metadata = {
        **evidence.metadata,
        "source_snapshot_artifact_id": artifact_id,
        "source_registry_id": source_registry_id,
        "snapshot_quality_score": snapshot_quality_score,
        "snapshot_warnings": snapshot_warnings,
    }
    store.upsert_evidence(evidence.model_copy(update={"metadata": metadata}))


def _attach_snapshot_metadata_to_report_version(
    version: ReportVersionRecord | None,
    *,
    store: EnterpriseStore,
    artifact_ids: list[str],
    source_registry_ids: list[str],
    quality_scores: dict[str, int],
    failures: list[dict[str, str]],
    decision_events: list[EvidenceGapFillDecisionEvent],
) -> ReportVersionRecord | None:
    if version is None:
        return None
    metadata = dict(version.quality_metadata)
    gap_fill = dict(metadata.get("rag_gap_fill") or {})
    gap_fill["online_snapshot_artifact_ids"] = artifact_ids
    gap_fill["online_source_registry_ids"] = _unique_ids(source_registry_ids)
    gap_fill["online_snapshot_quality_scores"] = quality_scores
    gap_fill["online_snapshot_failure_count"] = len(failures)
    gap_fill["online_snapshot_failures"] = failures
    gap_fill["decision_events"] = [
        event.model_dump(mode="json") for event in decision_events
    ]
    metadata["rag_gap_fill"] = gap_fill
    return store.upsert_report_version(version.model_copy(update={"quality_metadata": metadata}))


def _source_url(evidence: EvidenceRecord) -> str | None:
    value = str(evidence.url or evidence.canonical_url or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    return None


def _snapshot_filename(evidence: EvidenceRecord) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", evidence.title.strip()).strip("-._")
    return f"{(stem or evidence.id)[:150]}-gap-fill-snapshot.txt"


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) else ""


def _metadata_bool(metadata: dict[str, Any], key: str) -> bool:
    return metadata.get(key) is True


def _metadata_value(metadata: dict[str, Any], key: str) -> object | None:
    return metadata.get(key)


def _unique_ids(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
