from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path
from typing import Literal, Protocol

from packages.identity import compute_content_hash
from packages.schema.enterprise import ArtifactCreateRequest, ArtifactRecord, ArtifactStorageBackend


class ArtifactStorageError(ValueError):
    pass


ArtifactStorageBackendConfig = Literal["local", "external", "s3", "oss"]


class ArtifactStorage(Protocol):
    def store(
        self,
        request: ArtifactCreateRequest,
        *,
        actor_id: str | None = None,
    ) -> ArtifactRecord: ...


class LocalArtifactStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def store(
        self,
        request: ArtifactCreateRequest,
        *,
        actor_id: str | None = None,
    ) -> ArtifactRecord:
        if request.external_uri:
            return external_artifact_record(request, actor_id=actor_id)

        payload = _payload_bytes(request)
        content_hash = compute_content_hash(payload)
        artifact_id = artifact_id_for(
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            evidence_id=request.evidence_id,
            artifact_type=request.artifact_type,
            filename=request.filename,
            content_hash=content_hash,
        )
        safe_filename = _safe_filename(request.filename)
        relative_path = Path(_safe_segment(request.workspace_id)) / artifact_id / safe_filename
        target_path = (self.root / relative_path).resolve()
        root_path = self.root.resolve()
        if root_path != target_path and root_path not in target_path.parents:
            raise ArtifactStorageError("Artifact target path escapes storage root.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)

        return ArtifactRecord(
            id=artifact_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            evidence_id=request.evidence_id,
            run_id=request.run_id,
            artifact_type=request.artifact_type,
            filename=safe_filename,
            media_type=request.media_type,
            storage_backend="local",
            uri=f"local://{relative_path.as_posix()}",
            byte_size=len(payload),
            content_hash=content_hash,
            source_url=request.source_url,
            created_by=actor_id,
            metadata={**request.metadata, "storage_root": str(root_path)},
        )


class ExternalArtifactStorage:
    def __init__(self, backend: Literal["external", "s3", "oss"]) -> None:
        self.backend = backend

    def store(
        self,
        request: ArtifactCreateRequest,
        *,
        actor_id: str | None = None,
    ) -> ArtifactRecord:
        if not request.external_uri:
            raise ArtifactStorageError(
                "External artifact storage requires external_uri; direct payload upload is not "
                "configured for this backend."
            )
        record = external_artifact_record(request, actor_id=actor_id)
        if self.backend != "external" and record.storage_backend != self.backend:
            raise ArtifactStorageError(
                f"Artifact URI must use {self.backend}:// when ARTIFACT_STORAGE_BACKEND="
                f"{self.backend}."
            )
        record.metadata = {**record.metadata, "configured_storage_backend": self.backend}
        return record


def build_artifact_storage(
    backend: ArtifactStorageBackendConfig,
    root: str | Path,
) -> ArtifactStorage:
    if backend == "local":
        return LocalArtifactStorage(root)
    return ExternalArtifactStorage(backend)


def external_artifact_record(
    request: ArtifactCreateRequest,
    *,
    actor_id: str | None,
) -> ArtifactRecord:
    if not request.external_uri:
        raise ArtifactStorageError("external_uri is required for external artifact records.")
    content_hash = hashlib.sha256(request.external_uri.encode("utf-8")).hexdigest()
    artifact_id = artifact_id_for(
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        evidence_id=request.evidence_id,
        artifact_type=request.artifact_type,
        filename=request.filename,
        content_hash=content_hash,
    )
    storage_backend = _external_backend(request.external_uri)
    return ArtifactRecord(
        id=artifact_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        evidence_id=request.evidence_id,
        run_id=request.run_id,
        artifact_type=request.artifact_type,
        filename=_safe_filename(request.filename),
        media_type=request.media_type,
        storage_backend=storage_backend,
        uri=request.external_uri,
        byte_size=0,
        content_hash=content_hash,
        source_url=request.source_url,
        created_by=actor_id,
        metadata={
            **request.metadata,
            "external_pointer": True,
            "detected_storage_backend": storage_backend,
        },
    )


def artifact_id_for(
    *,
    workspace_id: str,
    project_id: str,
    evidence_id: str | None,
    artifact_type: str,
    filename: str,
    content_hash: str,
) -> str:
    raw = "|".join(
        [
            workspace_id,
            project_id,
            evidence_id or "",
            artifact_type,
            _safe_filename(filename).casefold(),
            content_hash,
        ]
    )
    return f"artifact-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _payload_bytes(request: ArtifactCreateRequest) -> bytes:
    if request.content_base64 is not None:
        try:
            return base64.b64decode(request.content_base64, validate=True)
        except binascii.Error as exc:
            raise ArtifactStorageError("content_base64 is not valid base64.") from exc
    if request.content_text is not None:
        return request.content_text.encode("utf-8")
    raise ArtifactStorageError(
        "Artifact content_text, content_base64, or external_uri is required."
    )


def _safe_filename(value: str) -> str:
    candidate = value.replace("\\", "/").split("/")[-1].strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    return candidate[:180] or "artifact.bin"


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or "workspace"


def _external_backend(uri: str | None) -> ArtifactStorageBackend:
    value = (uri or "").strip().lower()
    if value.startswith("s3://"):
        return "s3"
    if value.startswith("oss://"):
        return "oss"
    return "external"
