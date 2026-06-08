from __future__ import annotations

from typing import Any

from packages.schema.enterprise import ArtifactCreateRequest, ArtifactRecord

ARTIFACT_LIFECYCLE_VERSION = "c5.2"
ARTIFACT_LIFECYCLE_STAGES = [
    "captured_or_imported",
    "stored",
    "linked_to_source_or_evidence",
    "governed",
    "retained_or_expired",
    "replayable",
]


def artifact_lifecycle_metadata(
    request: ArtifactCreateRequest,
    *,
    storage_backend: str,
    content_hash: str,
    byte_size: int,
) -> dict[str, Any]:
    return {
        "version": ARTIFACT_LIFECYCLE_VERSION,
        "stage": "stored",
        "stages": list(ARTIFACT_LIFECYCLE_STAGES),
        "material_kind": _material_kind(request),
        "storage_backend": storage_backend,
        "media_type": request.media_type,
        "content_hash": content_hash,
        "byte_size": byte_size,
        "retention_policy": request.retention_policy,
        "pii_redaction_status": _pii_redaction_status(request),
        "source_policy_status": _source_policy_status(request),
        "links": {
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "run_id": request.run_id,
            "raw_source_id": _metadata_text(request.metadata, "raw_source_id"),
            "source_registry_id": _metadata_text(request.metadata, "source_registry_id"),
            "evidence_id": request.evidence_id,
            "report_version_id": request.report_version_id,
        },
        "replay": {
            "has_payload": bool(request.content_text or request.content_base64),
            "external_pointer": bool(request.external_uri),
            "source_url": str(request.source_url) if request.source_url else "",
        },
    }


def merge_artifact_lifecycle_metadata(
    metadata: dict[str, Any],
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    return {**metadata, "artifact_lifecycle": lifecycle}


def with_artifact_lifecycle_links(
    artifact: ArtifactRecord,
    *,
    raw_source_id: str | None = None,
    source_registry_id: str | None = None,
    evidence_id: str | None = None,
    report_version_id: str | None = None,
    source_policy_status: str | None = None,
    pii_redaction_status: str | None = None,
) -> ArtifactRecord:
    lifecycle = dict(artifact.metadata.get("artifact_lifecycle") or {})
    links = dict(lifecycle.get("links") or {})
    if raw_source_id:
        links["raw_source_id"] = raw_source_id
    if source_registry_id:
        links["source_registry_id"] = source_registry_id
    if evidence_id:
        links["evidence_id"] = evidence_id
    if report_version_id:
        links["report_version_id"] = report_version_id
    lifecycle["links"] = links
    if source_policy_status:
        lifecycle["source_policy_status"] = source_policy_status
    if pii_redaction_status:
        lifecycle["pii_redaction_status"] = pii_redaction_status
    return artifact.model_copy(
        update={"metadata": {**artifact.metadata, "artifact_lifecycle": lifecycle}}
    )


def _material_kind(request: ArtifactCreateRequest) -> str:
    snapshot_kind = _metadata_text(request.metadata, "snapshot_kind")
    if snapshot_kind:
        return snapshot_kind
    if request.artifact_type in {"survey_response", "interview_record", "manual_transcript"}:
        return request.artifact_type
    if request.artifact_type == "report_export":
        return "report_export"
    if request.artifact_type in {"web_snapshot", "pdf", "screenshot"}:
        return request.artifact_type
    return "source_material"


def _pii_redaction_status(request: ArtifactCreateRequest) -> str:
    explicit = _metadata_text(request.compliance_metadata, "pii_redaction_status")
    if explicit:
        return explicit
    if _metadata_dict(request.metadata, "redaction_counts"):
        return "redacted"
    if request.artifact_type in {"survey_response", "interview_record", "manual_transcript"}:
        return "required"
    return "not_required"


def _source_policy_status(request: ArtifactCreateRequest) -> str:
    explicit = _metadata_text(request.compliance_metadata, "source_policy_status", "source_policy")
    if explicit:
        return explicit
    robots = _metadata_text(request.compliance_metadata, "robots_status")
    if robots == "allowed":
        return "allowed"
    if robots in {"blocked", "error"}:
        return "review_required"
    if request.source_url:
        return "unknown"
    return "not_required"


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata_dict(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    value = metadata.get(key)
    return value if isinstance(value, dict) else {}
