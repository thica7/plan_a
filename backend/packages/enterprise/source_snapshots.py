from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from packages.artifacts import ArtifactStorage
from packages.compliance import redact_text
from packages.enterprise.store import EnterpriseStore, source_registry_id
from packages.identity import (
    compute_evidence_id,
    compute_raw_source_id,
    evidence_source_tokens,
    normalize_dimension_key,
)
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
    request, redaction_counts = _redacted_research_snapshot_request(request)
    source_type = _snapshot_source_type(request)
    linked_evidence = _linked_evidence(request, store=store)
    source = _source_from_snapshot(request)
    if linked_evidence is not None:
        source = source.model_copy(
            update={"metadata": {**source.metadata, **_source_identity_metadata(linked_evidence)}}
        )
    score, warnings = _snapshot_quality(request)
    artifact = artifact_storage.store(
        ArtifactCreateRequest(
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            evidence_id=request.evidence_id,
            run_id=request.run_id,
            report_version_id=request.report_version_id,
            artifact_type=_snapshot_artifact_type(request),
            filename=request.filename,
            media_type=request.media_type,
            content_text=request.content_text,
            content_base64=request.content_base64,
            external_uri=request.external_uri,
            source_url=request.source_url,
            retention_policy=request.retention_policy,
            compliance_metadata=request.compliance_metadata,
            metadata={
                **request.metadata,
                "snapshot_kind": request.snapshot_kind,
                "source_type": source_type,
                "source_registry_id": source.id,
                "source_domain": source.domain,
                "snapshot_quality_score": score,
                "snapshot_warnings": warnings,
                **_source_identity_metadata(linked_evidence),
                **_snapshot_redaction_metadata(redaction_counts),
            },
        ),
        actor_id=actor_id,
    )
    source = store.upsert_source_registry(source, actor_id=actor_id)
    evidence = _research_evidence_from_snapshot(
        request,
        artifact=artifact,
        source_registry=source,
    )
    if evidence is not None:
        evidence = store.upsert_evidence(evidence)
        artifact = artifact.model_copy(
            update={
                "evidence_id": evidence.id,
                "metadata": {
                    **artifact.metadata,
                    **_source_identity_metadata(evidence),
                },
            }
        )
    stored_artifact = store.upsert_artifact(artifact)
    return SourceSnapshotResult(
        artifact=stored_artifact,
        source=source,
        evidence_id=evidence.id if evidence is not None else request.evidence_id,
        snapshot_quality_score=score,
        warnings=warnings,
    )


def _linked_evidence(
    request: SourceSnapshotCreateRequest,
    *,
    store: EnterpriseStore,
) -> EvidenceRecord | None:
    if not request.evidence_id:
        return None
    for evidence in store.list_evidence(project_id=request.project_id):
        if evidence.id == request.evidence_id:
            return evidence
    return None


def _source_identity_metadata(evidence: EvidenceRecord | None) -> dict[str, object]:
    if evidence is None:
        return {}
    return {
        "evidence_id": evidence.id,
        "raw_source_id": evidence.raw_source_id,
        "source_tokens": sorted(evidence_source_tokens(evidence)),
    }


def _source_from_snapshot(request: SourceSnapshotCreateRequest) -> SourceRegistryRecord:
    domain, homepage_url = _source_location(str(request.source_url or request.external_uri or ""))
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
    competitor_id = (
        _metadata_text(
            request.metadata,
            "competitor_id",
            "competitor",
            "competitor_name",
        )
        or "manual_research"
    )
    dimension = normalize_dimension_key(
        _metadata_text(request.metadata, "dimension", "research_dimension") or "user_research"
    )
    evidence_id = compute_evidence_id(canonical_url, content_hash, competitor_id, dimension)
    source_type = _research_source_type(request)
    snippet = _snapshot_snippet(request)
    raw_source_id = compute_raw_source_id(
        source_type=source_type,
        competitor=competitor_id,
        dimension=dimension,
        url=str(source_url) if source_url else canonical_url,
        content_hash=content_hash,
        title=request.display_name or request.filename,
        snippet=snippet,
        run_id=request.run_id,
        source_role=f"snapshot:{request.snapshot_kind}",
    )
    return EvidenceRecord(
        id=evidence_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        run_id=request.run_id,
        raw_source_id=raw_source_id,
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
            "report_version_id": request.report_version_id,
            "source_registry_id": source_registry.id,
            "source_domain": source_registry.domain,
            **_snapshot_redaction_metadata(_metadata_dict(request.metadata, "redaction_counts")),
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


def _snapshot_artifact_type(request: SourceSnapshotCreateRequest) -> str:
    if request.snapshot_kind == "interview":
        return "interview_record"
    if request.snapshot_kind == "survey":
        return "survey_response"
    if request.snapshot_kind == "manual":
        return "manual_transcript"
    if request.snapshot_kind == "pdf":
        return "pdf"
    if request.snapshot_kind == "screenshot":
        return "screenshot"
    return request.artifact_type


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


def _metadata_value(metadata: dict[str, object], key: str) -> object | None:
    return metadata.get(key)


def _metadata_dict(metadata: dict[str, object], key: str) -> dict[str, int]:
    value = _metadata_value(metadata, key)
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for item_key, item_value in value.items():
        if isinstance(item_value, int):
            counts[str(item_key)] = item_value
    return counts


def _redacted_research_snapshot_request(
    request: SourceSnapshotCreateRequest,
) -> tuple[SourceSnapshotCreateRequest, dict[str, int]]:
    if request.snapshot_kind not in {"interview", "survey", "manual"}:
        return request, {}
    counts: dict[str, int] = {}
    content_text = _redact_snapshot_text(request.content_text, counts)
    metadata = _redact_snapshot_metadata(request.metadata, counts)
    metadata.update(_snapshot_redaction_metadata(counts))
    return request.model_copy(update={"content_text": content_text, "metadata": metadata}), counts


def _redact_snapshot_text(value: str | None, counts: dict[str, int]) -> str | None:
    if value is None:
        return None
    result = redact_text(value)
    for key, count in result.counts.items():
        if count:
            counts[key] = counts.get(key, 0) + count
    return result.text


def _redact_snapshot_metadata(
    value: dict[str, object],
    counts: dict[str, int],
) -> dict[str, object]:
    return {key: _redact_snapshot_metadata_value(item, counts) for key, item in value.items()}


def _redact_snapshot_metadata_value(value: object, counts: dict[str, int]) -> object:
    if isinstance(value, str):
        return _redact_snapshot_text(value, counts) or ""
    if isinstance(value, list):
        return [_redact_snapshot_metadata_value(item, counts) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            redacted[str(key)] = _redact_snapshot_metadata_value(item, counts)
        return redacted
    return value


def _snapshot_redaction_metadata(counts: dict[str, int]) -> dict[str, object]:
    positive_counts = {key: value for key, value in counts.items() if value > 0}
    return {
        "redaction_applied": bool(positive_counts),
        "redaction_count": sum(positive_counts.values()),
        "redaction_counts": positive_counts,
    }
