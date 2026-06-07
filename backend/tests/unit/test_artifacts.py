from pathlib import Path

import pytest

from packages.artifacts import (
    ArtifactStorageError,
    ExternalArtifactStorage,
    LocalArtifactStorage,
    build_artifact_storage,
)
from packages.schema.enterprise import ArtifactCreateRequest


def test_local_artifact_storage_writes_text_payload_with_stable_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _artifact_root("write-text")
    storage = LocalArtifactStorage(root)
    written_files: dict[Path, bytes] = {}

    def fake_mkdir(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        return None

    def fake_write_bytes(self: Path, data: bytes) -> int:
        written_files[self] = data
        return len(data)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    monkeypatch.setattr(Path, "write_bytes", fake_write_bytes)

    request = ArtifactCreateRequest(
        workspace_id="workspace-a",
        project_id="project-a",
        evidence_id="evidence-a",
        report_version_id="report-v1",
        artifact_type="web_snapshot",
        filename="../Cursor Pricing.html",
        media_type="text/html",
        content_text="<html>Cursor pricing</html>",
        source_url="https://cursor.sh/pricing",
        retention_policy="90d",
        compliance_metadata={"robots_status": "allowed"},
    )

    artifact = storage.store(request, actor_id="analyst-1")
    repeated = storage.store(request, actor_id="analyst-1")

    assert artifact.id == repeated.id
    assert artifact.filename == "Cursor-Pricing.html"
    assert artifact.storage_backend == "local"
    assert artifact.report_version_id == "report-v1"
    assert artifact.retention_policy == "90d"
    assert artifact.compliance_metadata["robots_status"] == "allowed"
    assert artifact.byte_size == len(b"<html>Cursor pricing</html>")
    assert artifact.uri.startswith("local://workspace-a/")
    assert written_files[
        (root / "workspace-a" / artifact.id / artifact.filename).resolve()
    ] == b"<html>Cursor pricing</html>"


def test_local_artifact_storage_rejects_empty_payload() -> None:
    root = _artifact_root("empty-payload")
    storage = LocalArtifactStorage(root)
    request = ArtifactCreateRequest(
        workspace_id="workspace-a",
        project_id="project-a",
        filename="empty.txt",
    )

    try:
        storage.store(request)
    except ArtifactStorageError as exc:
        assert "required" in str(exc)
    else:
        raise AssertionError("Artifact storage accepted a request without content.")


def test_external_artifact_storage_records_s3_pointer() -> None:
    storage = ExternalArtifactStorage("s3")
    request = ArtifactCreateRequest(
        workspace_id="workspace-a",
        project_id="project-a",
        evidence_id="evidence-a",
        report_version_id="report-v1",
        artifact_type="web_snapshot",
        filename="cursor-pricing.html",
        external_uri="s3://ci-bucket/workspace-a/cursor-pricing.html",
        source_url="https://cursor.sh/pricing",
        retention_policy="legal_hold",
        compliance_metadata={"source_policy": "approved"},
    )

    artifact = storage.store(request, actor_id="collector")

    assert artifact.storage_backend == "s3"
    assert artifact.report_version_id == "report-v1"
    assert artifact.retention_policy == "legal_hold"
    assert artifact.compliance_metadata["source_policy"] == "approved"
    assert artifact.uri == "s3://ci-bucket/workspace-a/cursor-pricing.html"
    assert artifact.byte_size == 0
    assert artifact.metadata["external_pointer"] is True
    assert artifact.metadata["configured_storage_backend"] == "s3"
    assert artifact.metadata["detected_storage_backend"] == "s3"


def test_external_artifact_storage_rejects_wrong_scheme() -> None:
    storage = ExternalArtifactStorage("oss")
    request = ArtifactCreateRequest(
        workspace_id="workspace-a",
        project_id="project-a",
        filename="cursor-pricing.html",
        external_uri="s3://ci-bucket/workspace-a/cursor-pricing.html",
    )

    with pytest.raises(ArtifactStorageError, match="oss://"):
        storage.store(request)


def test_build_artifact_storage_selects_pointer_backend() -> None:
    storage = build_artifact_storage("external", _artifact_root("factory"))
    request = ArtifactCreateRequest(
        workspace_id="workspace-a",
        project_id="project-a",
        filename="external.txt",
        external_uri="https://example.com/artifacts/external.txt",
    )

    artifact = storage.store(request)

    assert artifact.storage_backend == "external"
    assert artifact.metadata["configured_storage_backend"] == "external"


def _artifact_root(name: str) -> Path:
    return Path("backend/.test-artifacts") / name
