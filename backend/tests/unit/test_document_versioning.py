from __future__ import annotations

import pytest

from app.routes.knowledge import (
    DocumentMergeRequest,
    diff_knowledge_document,
    get_knowledge_document_versions,
    merge_knowledge_document_version,
)
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository


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

        versions = await get_knowledge_document_versions(second.id, repo)
        diff = await diff_knowledge_document(second.id, repo, against=first.id)

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
