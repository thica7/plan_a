from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from packages.artifacts import ArtifactStorage
from packages.enterprise.store import EnterpriseStore, source_registry_id
from packages.identity import compute_evidence_id, normalize_dimension_key
from packages.schema.enterprise import (
    ArtifactCreateRequest,
    EvidenceRecord,
    SourceRegistryRecord,
    SourceSnapshotCreateRequest,
    SourceSnapshotResult,
)


def capture_source_snapshot(
    request: SourceSnapshotCreateRequest,
    *,
    store: EnterpriseStore,
    artifact_storage: ArtifactStorage,
    actor_id: str | None,
) -> SourceSnapshotResult:
    source_type = _snapshot_source_type(request)
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
                "source_type": source_type,
                "source_registry_id": source.id,
                "source_domain": source.domain,
                "snapshot_quality_score": score,
                "snapshot_warnings": warnings,
            },
        ),
        actor_id=actor_id,
    )
    source = store.upsert_source_registry(source)
    evidence = _research_evidence_from_snapshot(
        request,
        artifact=artifact,
        source_registry=source,
    )
    if evidence is not None:
        evidence = store.upsert_evidence(evidence)
        artifact = artifact.model_copy(update={"evidence_id": evidence.id})
    stored_artifact = store.upsert_artifact(artifact)
    return SourceSnapshotResult(
        artifact=stored_artifact,
        source=source,
        evidence_id=evidence.id if evidence is not None else request.evidence_id,
        snapshot_quality_score=score,
        warnings=warnings,
    )


def _source_from_snapshot(request: SourceSnapshotCreateRequest) -> SourceRegistryRecord:
    domain, homepage_url = _source_location(
        str(request.source_url or request.external_uri or "")
    )
    now = datetime.utcnow()
    display_name = request.display_name or domain.replace("-", " ").title()
    source_type = _snapshot_source_type(request)
    return SourceRegistryRecord(
        id=source_registry_id(request.workspace_id, domain, source_type),
        workspace_id=request.workspace_id,
        domain=domain,
        source_type=source_type,
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
    research_snapshot = request.snapshot_kind in {"interview", "survey", "manual"}
    if request.source_url or request.external_uri or research_snapshot:
        score += 20
    else:
        warnings.append("Snapshot is missing a source URL.")
    if request.evidence_id or research_snapshot:
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
    if research_snapshot:
        score += 5
    return min(100, score), warnings


def _research_evidence_from_snapshot(
    request: SourceSnapshotCreateRequest,
    *,
    artifact: object,
    source_registry: SourceRegistryRecord,
) -> EvidenceRecord | None:
    if request.evidence_id is not None:
        return None
    if request.snapshot_kind not in {"interview", "survey", "manual"}:
        return None
    content_hash = str(getattr(artifact, "content_hash", ""))
    source_url = request.source_url
    canonical_url = str(source_url) if source_url else f"artifact:{getattr(artifact, 'id', '')}"
    competitor_id = _metadata_text(
        request.metadata,
        "competitor_id",
        "competitor",
        "competitor_name",
    ) or "manual_research"
    dimension = normalize_dimension_key(
        _metadata_text(request.metadata, "dimension", "research_dimension")
        or "user_research"
    )
    evidence_id = compute_evidence_id(canonical_url, content_hash, competitor_id, dimension)
    source_type = _research_source_type(request)
    snippet = _snapshot_snippet(request)
    return EvidenceRecord(
        id=evidence_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        run_id=request.run_id,
        raw_source_id=f"snapshot-{getattr(artifact, 'id', evidence_id)}",
        competitor_id=competitor_id,
        dimension=dimension,
        source_type=source_type,
        title=request.display_name or request.filename,
        url=source_url,
        canonical_url=canonical_url,
        snippet=snippet,
        content_hash=content_hash,
        reliability_score=_research_reliability_score(request),
        freshness_score=0.82,
        quality_label="unreviewed",
        metadata={
            **request.metadata,
            "manual_research_ingest": True,
            "snapshot_kind": request.snapshot_kind,
            "artifact_id": str(getattr(artifact, "id", "")),
            "source_registry_id": source_registry.id,
            "source_domain": source_registry.domain,
        },
    )


def _research_source_type(request: SourceSnapshotCreateRequest) -> str:
    if request.source_type and request.source_type != "webpage_verified":
        return request.source_type
    if request.snapshot_kind == "interview":
        return "interview_record"
    if request.snapshot_kind == "survey":
        return "survey_response"
    return "manual_transcript"


def _snapshot_source_type(request: SourceSnapshotCreateRequest) -> str:
    if request.snapshot_kind in {"interview", "survey", "manual"}:
        return _research_source_type(request)
    return request.source_type


def _snapshot_snippet(request: SourceSnapshotCreateRequest) -> str:
    summary = _metadata_text(request.metadata, "summary", "snippet", "quote")
    text = request.content_text or summary or request.external_uri or request.filename
    return " ".join(text.split())[:700]


def _research_reliability_score(request: SourceSnapshotCreateRequest) -> float:
    if request.trust_level in {"official", "verified"}:
        return 0.82
    if request.trust_level == "community":
        return 0.68
    return 0.6


def _metadata_text(metadata: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
