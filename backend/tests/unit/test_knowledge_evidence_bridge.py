from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.deps import get_enterprise_store
from app.main import create_app
from packages.enterprise import EnterpriseMemoryStore
from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository
from packages.rag import sync_knowledge_to_evidence
from packages.schema.enterprise import (
    KnowledgeEvidenceSyncRequest,
    ProjectRecord,
)


@pytest.mark.asyncio
async def test_sync_knowledge_to_evidence_uses_watermark_and_safe_metadata(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        document = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/pricing",
                title="Example pricing",
                source_type="webpage_verified",
                competitor="Example",
                dimension="pricing",
                text="Example pricing page. Starter plan costs 10 USD per seat. " * 20,
                metadata={"robots_status": "allowed", "large_blob": "x" * 1000},
            ),
            "hash-pricing",
        )
        await repo.insert_chunks(
            [
                KnowledgeChunk(
                    id="chunk-pricing-1",
                    document_id=document.id,
                    chunk_index=0,
                    text="Starter plan costs 10 USD per seat.",
                    token_count=8,
                    embedding_model="test",
                    content_hash="chunk-hash-1",
                    crawl_run_id="crawl-run-1",
                ),
                KnowledgeChunk(
                    id="chunk-pricing-2",
                    document_id=document.id,
                    chunk_index=1,
                    text="Enterprise plan adds audit exports and support.",
                    token_count=8,
                    embedding_model="test",
                    content_hash="chunk-hash-2",
                    crawl_run_id="crawl-run-1",
                ),
            ]
        )
        store = EnterpriseMemoryStore()
        request = KnowledgeEvidenceSyncRequest(
            crawl_run_id="crawl-run-1",
            full_text_chars=20,
            max_selected_chunks=1,
        )

        result = await sync_knowledge_to_evidence(
            repo=repo,
            store=store,
            workspace_id="workspace-kb",
            project_id="project-kb",
            request=request,
        )
        skipped = await sync_knowledge_to_evidence(
            repo=repo,
            store=store,
            workspace_id="workspace-kb",
            project_id="project-kb",
            request=request,
        )
        hits = store.search_evidence(
            workspace_id="workspace-kb",
            project_id="project-kb",
            query="Starter plan pricing",
            limit=5,
        )

        assert result.loaded_count == 1
        assert result.ingested_count == 1
        assert result.skipped_count == 0
        assert result.chunk_count == 2
        assert result.indexed_count == 1
        assert result.metric_id is not None
        assert result.crawl_run_ids == ["crawl-run-1"]
        assert skipped.loaded_count == 1
        assert skipped.ingested_count == 0
        assert skipped.skipped_count == 1
        evidence = store.list_evidence(project_id="project-kb")[0]
        assert evidence.metadata["kb_sync"] is True
        # 同步只保存精选 chunk 和截断正文，避免长网页拖慢 evidence 存储与索引。
        assert evidence.metadata["kb_selected_chunk_count"] == 1
        assert evidence.metadata["kb_omitted_chunk_count"] == 1
        assert len(evidence.metadata["full_text"]) <= 20
        assert evidence.metadata["source_text_truncated"] is True
        assert evidence.metadata["kb_source_metadata"] == {
            "omitted_key_count": 1,
            "robots_status": "allowed",
        }
        assert hits
        assert hits[0].evidence.id == evidence.id
    finally:
        await repo.close()


def test_enterprise_router_syncs_project_kb_evidence_and_background_job(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "knowledge.db"
    asyncio.run(_seed_kb_database(str(db_path)))
    monkeypatch.setenv("KB_DB_PATH", str(db_path))
    store = EnterpriseMemoryStore()
    store.upsert_project(
        ProjectRecord(
            id="project-api-kb",
            workspace_id="workspace-api-kb",
            name="Crawler KB import",
            topic="Crawler KB import",
            topic_normalized="crawler-kb-import",
        )
    )
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.post(
        "/api/enterprise/projects/project-api-kb/evidence/kb-sync",
        json={"crawl_run_id": "crawl-run-api", "competitors": ["Acme"]},
        headers={"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-kb"},
    )
    job_response = client.post(
        "/api/enterprise/projects/project-api-kb/evidence/kb-sync/jobs",
        json={
            "crawl_run_id": "crawl-run-api",
            "competitors": ["Acme"],
            "force_resync": True,
        },
        headers={"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-kb"},
    )
    job_body = job_response.json()
    job_status = _wait_for_job(client, job_body["id"])
    metrics = client.get(
        "/api/enterprise/projects/project-api-kb/evidence/kb-sync/metrics",
        headers={"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-kb"},
    )
    search = client.get(
        "/api/enterprise/evidence/search",
        params={
            "workspace_id": "workspace-api-kb",
            "project_id": "project-api-kb",
            "query": "Acme onboarding automation",
        },
        headers={"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-kb"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["loaded_count"] == 1
    assert body["ingested_count"] == 1
    assert body["chunk_count"] == 1
    assert body["competitors"] == ["Acme"]
    assert job_response.status_code == 200
    assert job_status["status"] == "succeeded"
    assert job_status["result"]["ingested_count"] == 1
    assert metrics.status_code == 200
    assert metrics.json()[0]["ingested_count"] == 1
    assert metrics.json()[0]["duration_ms"] >= 0
    assert search.status_code == 200
    assert search.json()[0]["evidence"]["metadata"]["kb_document_id"]


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    headers = {"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-kb"}
    for _ in range(40):
        response = client.get(
            f"/api/enterprise/projects/project-api-kb/evidence/kb-sync/jobs/{job_id}",
            headers=headers,
        )
        body = response.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        time.sleep(0.05)
    return body


async def _seed_kb_database(db_path: str) -> None:
    repo = KnowledgeRepository(db_path)
    await repo.initialise()
    try:
        document = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/acme/onboarding",
                title="Acme onboarding automation",
                source_type="webpage_verified",
                competitor="Acme",
                dimension="feature",
                text="Acme onboarding automation connects CRM events to lifecycle messages.",
            ),
            "hash-acme-onboarding",
        )
        await repo.insert_chunks(
            [
                KnowledgeChunk(
                    id="chunk-api-1",
                    document_id=document.id,
                    chunk_index=0,
                    text="Acme onboarding automation connects CRM events.",
                    token_count=7,
                    embedding_model="test",
                    content_hash="chunk-api-hash",
                    crawl_run_id="crawl-run-api",
                )
            ]
        )
    finally:
        await repo.close()
