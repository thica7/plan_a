import shutil
from pathlib import Path

from packages.artifacts import ArtifactStorageError, LocalArtifactStorage
from packages.schema.enterprise import ArtifactCreateRequest


def test_local_artifact_storage_writes_text_payload_with_stable_metadata() -> None:
    root = _artifact_root("write-text")
    storage = LocalArtifactStorage(root)
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
    assert (root / "workspace-a" / artifact.id / artifact.filename).read_text() == (
        "<html>Cursor pricing</html>"
    )
    shutil.rmtree(root, ignore_errors=True)


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
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _artifact_root(name: str) -> Path:
    root = Path("backend/.test-artifacts") / name
    shutil.rmtree(root, ignore_errors=True)
    return root
