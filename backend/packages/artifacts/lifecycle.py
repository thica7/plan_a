from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class ArtifactLifecycleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: str
    filename: str
    material_kind: str = ""
    stage: str = ""
    storage_backend: str = ""
    retention_policy: str = ""
    source_policy_status: str = ""
    pii_redaction_status: str = ""
    links: dict[str, Any] = Field(default_factory=dict)


class ArtifactLifecycleReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = None
    project_id: str | None = None
    evidence_id: str | None = None
    report_version_id: str | None = None
    total_count: int = 0
    replayable_count: int = 0
    by_material_kind: dict[str, int] = Field(default_factory=dict)
    by_storage_backend: dict[str, int] = Field(default_factory=dict)
    by_source_policy_status: dict[str, int] = Field(default_factory=dict)
    by_pii_redaction_status: dict[str, int] = Field(default_factory=dict)
    items: list[ArtifactLifecycleItem] = Field(default_factory=list)


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


def build_artifact_lifecycle_report(
    artifacts: list[ArtifactRecord],
    *,
    workspace_id: str | None = None,
    project_id: str | None = None,
    evidence_id: str | None = None,
    report_version_id: str | None = None,
) -> ArtifactLifecycleReport:
    items = [_artifact_lifecycle_item(artifact) for artifact in artifacts]
    return ArtifactLifecycleReport(
        workspace_id=workspace_id,
        project_id=project_id,
        evidence_id=evidence_id,
        report_version_id=report_version_id,
        total_count=len(items),
        replayable_count=sum(1 for item in items if item.stage == "stored"),
        by_material_kind=_count_by(items, "material_kind"),
        by_storage_backend=_count_by(items, "storage_backend"),
        by_source_policy_status=_count_by(items, "source_policy_status"),
        by_pii_redaction_status=_count_by(items, "pii_redaction_status"),
        items=items,
    )


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


def _artifact_lifecycle_item(artifact: ArtifactRecord) -> ArtifactLifecycleItem:
    lifecycle = artifact.metadata.get("artifact_lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    links = lifecycle.get("links")
    return ArtifactLifecycleItem(
        artifact_id=artifact.id,
        artifact_type=artifact.artifact_type,
        filename=artifact.filename,
        material_kind=_metadata_text(lifecycle, "material_kind"),
        stage=_metadata_text(lifecycle, "stage"),
        storage_backend=_metadata_text(lifecycle, "storage_backend") or artifact.storage_backend,
        retention_policy=_metadata_text(lifecycle, "retention_policy")
        or artifact.retention_policy,
        source_policy_status=_metadata_text(lifecycle, "source_policy_status"),
        pii_redaction_status=_metadata_text(lifecycle, "pii_redaction_status"),
        links=links if isinstance(links, dict) else {},
    )


def _count_by(items: list[ArtifactLifecycleItem], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(getattr(item, field_name) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


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
