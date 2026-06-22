from __future__ import annotations

import pytest

from app.routes.knowledge import (
    DocumentMergeRequest,
    diff_knowledge_document,
    get_knowledge_document_chunks,
    get_knowledge_document_versions,
    merge_knowledge_document_version,
)
from packages.auth import EnterpriseUserContext
from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository


def _user(role: str = "owner") -> EnterpriseUserContext:
    return EnterpriseUserContext(
        user_id=f"{role}-user",
        role=role,  # type: ignore[arg-type]
        workspace_id="default-workspace",
    )


@pytest.mark.asyncio
async def test_reingest_same_canonical_url_creates_version_chain(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        first = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/product",
                title="Product",
                source_type="manual",
                text="Line one\nOld price",
            ),
            "hash-v1",
        )
        second = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/product",
                title="Product",
                source_type="manual",
                text="Line one\nNew price",
            ),
            "hash-v2",
        )

        versions = await get_knowledge_document_versions(second.id, repo, user=_user())
        diff = await diff_knowledge_document(second.id, repo, user=_user(), against=first.id)

        assert [doc.version for doc in versions] == [1, 2]
        assert versions[0].is_active is False
        assert versions[1].is_active is True
        assert second.parent_document_id == first.id
        assert "-Old price" in diff.diff
        assert "+New price" in diff.diff
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_merge_document_version_marks_target_active(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        first = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/product",
                title="Product",
                source_type="manual",
                text="Version 1",
            ),
            "hash-v1",
        )
        second = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/product",
                title="Product",
                source_type="manual",
                text="Version 2",
            ),
            "hash-v2",
        )

        merged = await merge_knowledge_document_version(
            second.id,
            DocumentMergeRequest(target_document_id=first.id),
            repo,
            user=_user(),
        )
        first_after = await repo.get_document(first.id)
        second_after = await repo.get_document(second.id)

        assert merged.id == first.id
        assert first_after is not None
        assert second_after is not None
        assert first_after.is_active is True
        assert first_after.status == "active"
        assert second_after.is_active is False
        assert second_after.status == "archived"
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_get_knowledge_document_chunks_returns_ordered_chunks(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        document = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/security",
                title="Security",
                source_type="manual",
                text="Security text",
            ),
            "hash-security",
        )
        await repo.insert_chunks(
            [
                KnowledgeChunk(
                    id="chunk-2",
                    document_id=document.id,
                    chunk_index=2,
                    text="Second chunk.",
                    token_count=2,
                    embedding_model="hash",
                    content_hash="hash-chunk-2",
                ),
                KnowledgeChunk(
                    id="chunk-1",
                    document_id=document.id,
                    chunk_index=1,
                    text="First chunk.",
                    token_count=2,
                    embedding_model="hash",
                    content_hash="hash-chunk-1",
                ),
            ]
        )

        chunks = await get_knowledge_document_chunks(document.id, repo, user=_user())

        assert [chunk.id for chunk in chunks] == ["chunk-1", "chunk-2"]
        assert chunks[0].text == "First chunk."
    finally:
        await repo.close()

