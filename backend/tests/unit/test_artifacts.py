from pathlib import Path

import pytest

from packages.artifacts import ArtifactStorageError, LocalArtifactStorage
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
        artifact_type="web_snapshot",
        filename="../Cursor Pricing.html",
        media_type="text/html",
        content_text="<html>Cursor pricing</html>",
        source_url="https://cursor.sh/pricing",
    )

    artifact = storage.store(request, actor_id="analyst-1")
    repeated = storage.store(request, actor_id="analyst-1")

    assert artifact.id == repeated.id
    assert artifact.filename == "Cursor-Pricing.html"
    assert artifact.storage_backend == "local"
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


def _artifact_root(name: str) -> Path:
    return Path("backend/.test-artifacts") / name
