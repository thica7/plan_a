from __future__ import annotations

import asyncio
import base64

import pytest

from app.routes.knowledge import (
    BatchIngestItem,
    BatchIngestOptions,
    BatchIngestRequest,
    create_knowledge_batch,
)
from packages.knowledge.repository import KnowledgeRepository


@pytest.mark.asyncio
async def test_batch_ingest_accepts_valid_items_and_records_rejections(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        request = BatchIngestRequest(
            items=[
                BatchIngestItem(source="text", text="Pricing starts at 10.", title="Pricing"),
                BatchIngestItem(
                    source="base64",
                    content_b64=base64.b64encode(b"# Plan\n\nTeam plan.").decode("ascii"),
                    mime="text/markdown",
                    filename="plan.md",
                ),
                BatchIngestItem(source="text", text=""),
            ],
            options=BatchIngestOptions(max_concurrent=2, fail_fast=False),
        )

        response = await create_knowledge_batch(request, repo, None)
        job = await _wait_for_job(repo, response.job_id)
        documents = await repo.list_documents(limit=10)

        assert response.accepted == 2
        assert response.rejected[0].index == 2
        assert response.rejected[0].reason == "text is required"
        assert job["status"] == "success"
        assert job["completed_items"] == 2
        assert job["failed_items"] == 0
        assert len(documents) == 2
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_batch_ingest_records_failed_items_without_blocking_batch(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        request = BatchIngestRequest(
            items=[
                BatchIngestItem(source="text", text="Security controls.", title="Security"),
                BatchIngestItem(
                    source="base64",
                    content_b64="not-base64",
                    mime="text/plain",
                    filename="bad.txt",
                ),
            ],
            options=BatchIngestOptions(max_concurrent=2, fail_fast=False),
        )

        response = await create_knowledge_batch(request, repo, None)
        job = await _wait_for_job(repo, response.job_id)

        assert response.accepted == 2
        assert job["status"] == "failed"
        assert job["completed_items"] == 2
        assert job["failed_items"] == 1
        assert "invalid base64 content" in job["failed_items_json"]
    finally:
        await repo.close()


async def _wait_for_job(repo: KnowledgeRepository, job_id: str):
    for _ in range(50):
        row = await repo.get_ingest_job(job_id)
        if row is not None and row["status"] in {"success", "failed"}:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError("ingest job did not finish")
