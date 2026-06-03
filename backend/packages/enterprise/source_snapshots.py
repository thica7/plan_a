from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from packages.artifacts import LocalArtifactStorage
from packages.enterprise.store import EnterpriseStore, source_registry_id
from packages.schema.enterprise import (
    ArtifactCreateRequest,
    SourceRegistryRecord,
    SourceSnapshotCreateRequest,
    SourceSnapshotResult,
)


def capture_source_snapshot(
    request: SourceSnapshotCreateRequest,
    *,
    store: EnterpriseStore,
    artifact_storage: LocalArtifactStorage,
    actor_id: str | None,
) -> SourceSnapshotResult:
    source = _source_from_snapshot(request)
    score, warnings = _snapshot_quality(request)
    artifact = artifact_storage.store(
        ArtifactCreateRequest(
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            evidence_id=request.evidence_id,
            run_id=request.run_id,
            artifact_type=request.artifact_type,
            filename=request.filename,
            media_type=request.media_type,
            content_text=request.content_text,
            content_base64=request.content_base64,
            external_uri=request.external_uri,
            source_url=request.source_url,
            metadata={
                **request.metadata,
                "snapshot_kind": request.snapshot_kind,
                "source_type": request.source_type,
                "source_registry_id": source.id,
                "source_domain": source.domain,
                "snapshot_quality_score": score,
                "snapshot_warnings": warnings,
            },
        ),
        actor_id=actor_id,
    )
    stored_artifact = store.upsert_artifact(artifact)
    source = store.upsert_source_registry(source)
    return SourceSnapshotResult(
        artifact=stored_artifact,
        source=source,
        evidence_id=request.evidence_id,
        snapshot_quality_score=score,
        warnings=warnings,
    )


def _source_from_snapshot(request: SourceSnapshotCreateRequest) -> SourceRegistryRecord:
    domain, homepage_url = _source_location(
        str(request.source_url or request.external_uri or "")
    )
    now = datetime.utcnow()
    display_name = request.display_name or domain.replace("-", " ").title()
    return SourceRegistryRecord(
        id=source_registry_id(request.workspace_id, domain, request.source_type),
        workspace_id=request.workspace_id,
        domain=domain,
        source_type=request.source_type,
        display_name=display_name,
        homepage_url=homepage_url,
        trust_level=request.trust_level,
        robots_status=request.robots_status,
        first_seen_run_id=request.run_id,
        last_seen_run_id=request.run_id,
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
        metadata={
            **request.metadata,
            "snapshot_kind": request.snapshot_kind,
            "evidence_id": request.evidence_id,
            "source_url": str(request.source_url) if request.source_url else "",
        },
    )


def _source_location(value: str) -> tuple[str, str | None]:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if host:
        domain = host.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
        return domain, f"{scheme}://{domain}"
    return "manual-source", None


def _snapshot_quality(request: SourceSnapshotCreateRequest) -> tuple[int, list[str]]:
    warnings: list[str] = []
    score = 15
    if request.content_text or request.content_base64 or request.external_uri:
        score += 30
    else:
        warnings.append("Snapshot has no content payload or external pointer.")
    if request.source_url or request.external_uri:
        score += 20
    else:
        warnings.append("Snapshot is missing a source URL.")
    if request.evidence_id:
        score += 15
    else:
        warnings.append("Snapshot is not linked to an evidence record.")
    if request.trust_level in {"official", "verified"}:
        score += 15
    elif request.trust_level == "unknown":
        warnings.append("Snapshot source trust level is unknown.")
    if request.robots_status == "allowed":
        score += 5
    elif request.robots_status == "blocked":
        warnings.append("Snapshot source is blocked by robots policy.")
    if request.snapshot_kind in {"interview", "survey", "manual"}:
        score += 5
    return min(100, score), warnings
