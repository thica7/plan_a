from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest

from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository


def _db_path() -> Path:
    root = Path(__file__).resolve().parent / ".tmp_knowledge_rollback"
    root.mkdir(exist_ok=True)
    return root / f"knowledge-{uuid4().hex}.db"


def _cleanup_db(path: Path) -> None:
    for candidate in (path, path.with_suffix(".db-shm"), path.with_suffix(".db-wal")):
        with suppress(FileNotFoundError):
            candidate.unlink()


@pytest.mark.asyncio
async def test_rollback_documents_restores_previous_version_by_collector_metadata() -> None:
    db_path = _db_path()
    repo = KnowledgeRepository(str(db_path))
    await repo.initialise()
    try:
        original = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/security",
                title="Security",
                source_type="webpage_verified",
                competitor="Example",
                dimension="security",
                text="Example supports SSO and SCIM for enterprise workspaces.",
                metadata={"run_id": "collector-run-good", "raw_source_id": "raw-good"},
            ),
            "hash-good",
        )
        polluted = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/security",
                title="Security",
                source_type="webpage_verified",
                competitor="Example",
                dimension="security",
                text="Example does not support SSO for enterprise workspaces.",
                metadata={"run_id": "collector-run-bad", "raw_source_id": "raw-bad"},
            ),
            "hash-bad",
        )
        await repo.insert_chunks(
            [
                KnowledgeChunk(
                    id="chunk-polluted",
                    document_id=polluted.id,
                    chunk_index=0,
                    text="Example does not support SSO for enterprise workspaces.",
                    token_count=8,
                    embedding_model="test",
                    content_hash="chunk-hash-bad",
                    crawl_run_id="crawl-run-bad",
                )
            ]
        )

        result = await repo.rollback_documents(
            run_id="collector-run-bad",
            raw_source_id="raw-bad",
            crawl_run_id="crawl-run-bad",
        )
        original_after = await repo.get_document(original.id)
        polluted_after = await repo.get_document(polluted.id)
        versions = await repo.get_document_versions(original.id)

        assert result.matched_count == 1
        assert result.rolled_back_count == 1
        assert result.restored_count == 1
        assert result.archived_document_ids == [polluted.id]
        assert result.restored_document_ids == [original.id]
        assert original_after is not None
        assert polluted_after is not None
        assert original_after.status == "active"
        assert original_after.is_active is True
        assert polluted_after.status == "archived"
        assert polluted_after.is_active is False
        assert [doc.id for doc in versions] == [original.id, polluted.id]
    finally:
        await repo.close()
        _cleanup_db(db_path)


@pytest.mark.asyncio
async def test_rollback_documents_requires_selector() -> None:
    db_path = _db_path()
    repo = KnowledgeRepository(str(db_path))
    await repo.initialise()
    try:
        with pytest.raises(ValueError, match="rollback selector"):
            await repo.rollback_documents()
    finally:
        await repo.close()
        _cleanup_db(db_path)