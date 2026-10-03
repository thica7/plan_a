import json

import httpx
import pytest

from app.deps import get_enterprise_store
from app.main import create_app
from app.middleware import auth
from app.routes import knowledge
from packages.enterprise import EnterpriseMemoryStore
from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository
from packages.schema.enterprise import ProjectRecord


@pytest.fixture
async def scoped_http(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path / "kb.db"))
    await repo.initialise()
    store = EnterpriseMemoryStore()
    for project, workspace in [("p", "a"), ("q", "a"), ("foreign", "b")]:
        store.upsert_project(
            ProjectRecord(
                id=project,
                workspace_id=workspace,
                name=project,
                topic=project,
                topic_normalized=project,
            )
        )
    ids = {}
    for name, workspace, project in [
        ("own", "a", "p"),
        ("library", "a", None),
        ("other", "a", "q"),
        ("foreign", "b", "foreign"),
        ("unknown", None, None),
    ]:
        doc = await repo.upsert_document(
            DocumentCreate(
                title=name,
                source_type="manual",
                text="shared pricing " + name,
                workspace_id=workspace,
                project_id=project,
                url="https://same.test",
            ),
            name,
        )
        ids[name] = doc.id
        await repo.insert_chunks(
            [
                KnowledgeChunk(
                    id=name,
                    document_id=doc.id,
                    chunk_index=0,
                    token_count=3,
                    embedding_model="test",
                    text=doc.text,
                    content_hash=name,
                )
            ]
        )
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps({"token": {"user_id": "owner", "role": "owner", "workspace_id": "a"}}),
    )
    app = create_app()
    app.dependency_overrides[knowledge.get_repository] = lambda: repo
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[knowledge.get_embedding_provider] = lambda: None
    app.dependency_overrides[knowledge.get_reranker_provider] = lambda: None

    class FakeVector:
        async def delete_by_document(self, *args):
            pass

        async def delete_by_documents(self, *args):
            pass

    monkeypatch.setattr(knowledge, "_vector_store_for_search", lambda: FakeVector())
    from packages.knowledge import vector_store

    monkeypatch.setattr(vector_store, "VectorStore", FakeVector)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer token", "X-Workspace-Id": "b"},
    ) as client:
        yield client, repo, ids
    await repo.close()


@pytest.mark.asyncio
async def test_document_scope_is_trusted_and_expansion_explicit(scoped_http):
    client, repo, ids = scoped_http
    response = await client.get("/api/knowledge/documents", params={"project_id": "p", "limit": 1})
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert [d["title"] for d in response.json()] == ["own"]
    library = await client.get("/api/knowledge/documents")
    assert [d["title"] for d in library.json()] == ["library"]
    expanded = await client.get(
        "/api/knowledge/documents", params={"project_id": "p", "include_workspace_library": True}
    )
    assert {d["title"] for d in expanded.json()} == {"own", "library"}
    for project in ["foreign", "missing", " "]:
        assert (
            await client.get("/api/knowledge/documents", params={"project_id": project})
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["other", "foreign", "unknown"])
async def test_private_document_actions_fail_closed(scoped_http, name):
    client, repo, ids = scoped_http
    path = "/api/knowledge/documents/" + ids[name]
    params = {"project_id": "p", "include_workspace_library": True}
    for suffix in ["", "/chunks", "/versions", "/diff"]:
        response = await client.get(path + suffix, params={**params, "against": ids["own"]})
        assert response.status_code == 404
    for method, suffix, body in [
        ("post", "/reindex", None),
        ("delete", "", None),
        ("post", "/merge", {"target_document_id": ids["own"]}),
    ]:
        assert (
            await client.request(method, path + suffix, params=params, json=body)
        ).status_code == 404
    assert (
        await client.post(
            "/api/knowledge/documents/" + ids["own"] + "/merge",
            params=params,
            json={"target_document_id": ids[name]},
        )
    ).status_code == 404
    assert (
        await client.get(
            "/api/knowledge/documents/" + ids["own"] + "/diff",
            params={**params, "against": ids[name]},
        )
    ).status_code == 404
    assert (await repo.get_document(ids[name])).is_active


@pytest.mark.asyncio
async def test_search_overrides_body_workspace_and_checks_project(scoped_http):
    client, repo, ids = scoped_http
    response = await client.post(
        "/api/knowledge/search",
        json={
            "query": "pricing",
            "mode": "sparse",
            "workspace_id": "b",
            "project_id": "p",
            "enable_query_rewrite": False,
        },
    )
    assert response.status_code == 200
    assert {h["document_id"] for h in response.json()["hits"]} == {ids["own"]}
    assert (
        await client.post(
            "/api/knowledge/search", json={"query": "pricing", "project_id": "foreign"}
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/knowledge/search",
            params={"project_id": "q"},
            json={"query": "pricing", "project_id": "p"},
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_library_expansion_never_authorizes_writes(scoped_http):
    client, repo, ids = scoped_http
    params = {"project_id": "p", "include_workspace_library": True}
    path = "/api/knowledge/documents/" + ids["library"]
    for method, suffix, body in [
        ("post", "/reindex", None),
        ("delete", "", None),
        ("post", "/merge", {"target_document_id": ids["own"]}),
    ]:
        assert (
            await client.request(method, path + suffix, params=params, json=body)
        ).status_code == 404
    assert (
        await client.post(
            "/api/knowledge/documents/rollback",
            params=params,
            json={"document_ids": [ids["library"]]},
        )
    ).status_code == 404
    assert (await repo.get_document(ids["library"])).is_active


@pytest.mark.asyncio
async def test_job_http_aliases_eval_and_sse_hide_foreign_payloads(scoped_http, monkeypatch):
    from packages.knowledge.models import KnowledgeScope

    client, repo, ids = scoped_http
    monkeypatch.setenv("KB_DB_PATH", repo.db_path)
    own = KnowledgeScope(workspace_id="a", project_id="p")
    foreign = KnowledgeScope(workspace_id="b", project_id="foreign")
    jobs = {}
    for name, scope in [("own", own), ("foreign", foreign), ("unknown", None)]:
        jobs[name] = await repo.create_crawl_job("https://private.test/" + name, scope=scope)
        await repo.update_crawl_job(jobs[name], status="success", result_metadata={"private": name})
        await repo.create_ingest_job(
            name, total_items=1, accepted_items=1, rejected_items=[], options={}, scope=scope
        )
        await repo.record_ingest_job_success(name, index=0, document_id=ids.get(name, ids["own"]))
        await repo.record_eval_run(
            run_id=name, top_k=1, metrics={}, labels=[], results=[{"private": name}], scope=scope
        )
    for path in ["/api/knowledge/crawl-jobs", "/api/crawl/jobs"]:
        response = await client.get(path, params={"project_id": "p", "limit": 1})
        assert response.status_code == 200
        assert [j["id"] for j in response.json()] == [jobs["own"]]
        for name in ["foreign", "unknown"]:
            assert (
                await client.get(path + "/" + jobs[name], params={"project_id": "p"})
            ).status_code == 404
    for path in ["/api/knowledge/ingest-jobs", "/api/knowledge/eval/runs"]:
        assert [
            j["id"] for j in (await client.get(path, params={"project_id": "p", "limit": 1})).json()
        ] == ["own"]
        for name in ["foreign", "unknown"]:
            assert (
                await client.get(path + "/" + name, params={"project_id": "p"})
            ).status_code == 404
    assert (
        await client.get(
            "/api/crawl/jobs/" + jobs["foreign"] + "/stream", params={"project_id": "p"}
        )
    ).status_code == 404
    response = await client.get(
        "/api/crawl/jobs/" + jobs["own"] + "/stream", params={"project_id": "p"}
    )
    assert response.status_code == 200 and "private.test/own" in response.text
    stats = await client.get("/api/knowledge/stats", params={"project_id": "p"})
    assert stats.json()["doc_count"] == 1
    result = await client.post(
        "/api/knowledge/eval",
        json={
            "project_id": "p",
            "labels": [
                {
                    "query": "pricing",
                    "relevant_doc_ids": [ids["foreign"]],
                    "relevant_chunk_ids": ["foreign"],
                }
            ],
        },
    )
    assert result.status_code == 200
    data = result.json()
    assert data["workspace_id"] == "a" and data["project_id"] == "p"
    assert all(hit["document_id"] == ids["own"] for row in data["results"] for hit in row["hits"])


@pytest.mark.asyncio
async def test_batch_preserves_job_scope_and_typed_source_context(scoped_http, monkeypatch):
    import asyncio
    import base64
    from datetime import UTC, datetime

    from packages.crawler import scheduler
    from packages.crawler.models import CrawlResult, ParsedPage

    client, repo, ids = scoped_http
    old = datetime(2020, 1, 1, tzinfo=UTC)

    class FakeScheduler:
        async def crawl_sync(self, request):
            return CrawlResult(
                request=request,
                success=True,
                page=ParsedPage(
                    url=request.url,
                    title="crawl",
                    text="Full source body. " * 1000,
                    fetched_at=old,
                    content_hash="page",
                ),
            )

        async def stop(self):
            pass

    monkeypatch.setattr(scheduler, "CrawlerScheduler", FakeScheduler)
    response = await client.post(
        "/api/knowledge/batch",
        json={
            "workspace_id": "b",
            "project_id": "p",
            "items": [
                {
                    "source": "text",
                    "title": "typed-text",
                    "text": "Imported text",
                    "market": "US",
                    "source_role": "historical_report",
                    "source_published_at": old.isoformat(),
                },
                {
                    "source": "base64",
                    "filename": "evil.html",
                    "mime": "text/html",
                    "content_b64": base64.b64encode(
                        b'<html><meta name="workspace_id" content="b">'
                        b'<meta name="project_id" content="foreign"><body>Body</body></html>'
                    ).decode(),
                },
                {"source": "url", "url": "https://crawl.test", "market": "CN"},
            ],
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    for _ in range(100):
        job = await repo.get_ingest_job(job_id)
        if job["status"] in {"success", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "success"
    assert job["workspace_id"] == "a" and job["project_id"] == "p"
    import json

    docs = [
        await repo.get_document(row["document_id"]) for row in json.loads(job["result_items_json"])
    ]
    assert len(docs) == 3
    assert {(d.workspace_id, d.project_id) for d in docs} == {("a", "p")}
    text = next(d for d in docs if d.title == "typed-text")
    assert (
        text.market == "US"
        and text.source_role == "historical_report"
        and text.source_published_at == old
    )
    crawl = next(d for d in docs if d.title == "crawl")
    assert crawl.market == "CN" and crawl.fetched_at == old
    assert crawl.last_verified_at == old and len(crawl.text) > 10000


@pytest.mark.asyncio
async def test_sse_rechecks_saved_scope_on_every_poll(scoped_http, monkeypatch):
    from starlette.requests import Request

    from app.routes import crawl
    from packages.auth import EnterpriseUserContext
    from packages.knowledge.models import KnowledgeScope

    client, repo, ids = scoped_http
    monkeypatch.setenv("KB_DB_PATH", repo.db_path)
    job = await repo.create_crawl_job(
        "https://own.test", scope=KnowledgeScope(workspace_id="a", project_id="p")
    )
    user = EnterpriseUserContext(user_id="owner", role="owner", workspace_id="a")
    store = EnterpriseMemoryStore()
    store.upsert_project(
        ProjectRecord(id="p", workspace_id="a", name="p", topic="p", topic_normalized="p")
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []}, receive)
    response = await crawl.stream_crawl_job(job, request, user, store=store, project_id="p")
    event = await response.body_iterator.__anext__()
    assert event["event"] == "job"
    await repo._connection.execute(
        "UPDATE crawl_jobs SET workspace_id='b', result_metadata_json=? WHERE id=?",
        ('{"secret":"foreign"}', job),
    )
    await repo._connection.commit()
    event = await response.body_iterator.__anext__()
    assert event == {"event": "error", "data": "Crawl job not found"}
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_owner_without_workspace_cannot_select_foreign_project(scoped_http, monkeypatch):
    client, repo, ids = scoped_http
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps({"token": {"user_id": "owner", "role": "owner", "workspace_id": None}}),
    )
    assert (
        await client.get("/api/knowledge/documents", params={"project_id": "p"})
    ).status_code == 404
    assert (await client.get("/api/knowledge/documents")).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/knowledge/crawl-jobs", "/api/crawl/jobs"])
async def test_http_crawl_creation_saves_trusted_project(scoped_http, monkeypatch, path):
    import asyncio
    from datetime import UTC, datetime

    from packages.crawler import scheduler
    from packages.crawler.models import CrawlResult, ParsedPage

    client, repo, ids = scoped_http
    monkeypatch.setenv("KB_DB_PATH", repo.db_path)

    async def current_repo():
        return repo

    monkeypatch.setattr(knowledge, "get_repository", current_repo)
    from app.routes import crawl

    monkeypatch.setattr(knowledge, "get_embedding_provider", lambda: None)
    monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)

    class FakeScheduler:
        async def crawl_sync(self, request):
            return CrawlResult(
                request=request,
                success=True,
                page=ParsedPage(
                    url=request.url,
                    title="HTTP job",
                    text="Full page body",
                    content_hash="page",
                    fetched_at=datetime.now(UTC),
                ),
            )

        async def stop(self):
            pass

    monkeypatch.setattr(scheduler, "CrawlerScheduler", FakeScheduler)
    for project in ["foreign", "missing"]:
        assert (
            await client.post(path, json={"url": "https://http.test", "project_id": project})
        ).status_code == 404
    response = await client.post(
        path,
        json={"url": "https://http.test", "project_id": "p", "workspace_id": "b", "market": "US"},
        params={"include_workspace_library": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["workspace_id"] == "a" and body["project_id"] == "p"
    for _ in range(100):
        job = await repo.get_crawl_job(body["id"])
        if job["status"] in {"success", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "success"
    doc = await repo.get_document(json.loads(job["result_metadata_json"])["document_id"])
    assert doc.workspace_id == "a" and doc.project_id == "p" and doc.market == "US"


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_id", [None, "a"])
async def test_enterprise_kb_sync_rejects_foreign_project_before_work(
    scoped_http,
    monkeypatch,
    workspace_id,
):
    from app.routers import enterprise
    from packages.rag.knowledge_bridge import sync_knowledge_to_evidence
    from packages.schema.enterprise import KnowledgeEvidenceSyncRequest

    client, repo, ids = scoped_http
    monkeypatch.setenv("KB_DB_PATH", repo.db_path)
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps(
            {
                "token": {
                    "user_id": "owner",
                    "role": "owner",
                    "workspace_id": workspace_id,
                }
            }
        ),
    )
    store = client._transport.app.dependency_overrides[get_enterprise_store]()
    request = KnowledgeEvidenceSyncRequest()
    await sync_knowledge_to_evidence(
        repo=repo, store=store, workspace_id="b", project_id="foreign", request=request
    )
    monkeypatch.setattr(enterprise, "_KB_SYNC_JOBS", {})
    foreign_job = enterprise._create_kb_sync_job(
        workspace_id="b", project_id="foreign", request=request
    )
    calls = []
    original_create = enterprise._create_kb_sync_job

    def record_create(**kwargs):
        calls.append(kwargs)
        return original_create(**kwargs)

    monkeypatch.setattr(enterprise, "_create_kb_sync_job", record_create)
    path = "/api/enterprise/projects/foreign/evidence/kb-sync"
    responses = [
        await client.post(path, json={}),
        await client.post(path + "/jobs", json={}),
        await client.get(path + "/metrics"),
        await client.get(path + "/jobs/" + foreign_job.id),
    ]
    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert calls == []
    assert all("shared pricing" not in response.text for response in responses)


@pytest.mark.asyncio
async def test_enterprise_kb_sync_job_checks_workspace_and_project(scoped_http, monkeypatch):
    from app.routers import enterprise
    from packages.schema.enterprise import KnowledgeEvidenceSyncRequest

    client, repo, ids = scoped_http
    monkeypatch.setattr(enterprise, "_KB_SYNC_JOBS", {})
    request = KnowledgeEvidenceSyncRequest()
    for workspace, project in [("b", "p"), ("a", "q")]:
        job = enterprise._create_kb_sync_job(
            workspace_id=workspace, project_id=project, request=request
        )
        response = await client.get("/api/enterprise/projects/p/evidence/kb-sync/jobs/" + job.id)
        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_id,project_id", [("a", "p"), (None, "default-project")])
async def test_enterprise_kb_sync_uses_trusted_destination_and_keeps_permissions(
    scoped_http,
    monkeypatch,
    workspace_id,
    project_id,
):
    from app.routers import enterprise
    from packages.enterprise.store import DEFAULT_WORKSPACE_ID

    client, repo, ids = scoped_http
    monkeypatch.setenv("KB_DB_PATH", repo.db_path)
    store = client._transport.app.dependency_overrides[get_enterprise_store]()
    if workspace_id is None:
        store.upsert_project(
            ProjectRecord(
                id=project_id,
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="default",
                topic="default",
                topic_normalized="default",
            )
        )
        await repo.upsert_document(
            DocumentCreate(
                title="default source",
                source_type="manual",
                text="default source",
                workspace_id=DEFAULT_WORKSPACE_ID,
                project_id=project_id,
            ),
            "default",
        )
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps(
            {
                "token": {
                    "user_id": "owner",
                    "role": "owner",
                    "workspace_id": workspace_id,
                }
            }
        ),
    )
    monkeypatch.setattr(enterprise, "_KB_SYNC_JOBS", {})
    path = f"/api/enterprise/projects/{project_id}/evidence/kb-sync"
    response = await client.post(path, json={})
    assert response.status_code == 200
    assert response.json()["workspace_id"] == (workspace_id or DEFAULT_WORKSPACE_ID)
    assert response.json()["loaded_count"] == (2 if workspace_id else 1)
    job = await client.post(path + "/jobs", json={"force_resync": True})
    assert job.status_code == 200
    job_response = await client.get(path + "/jobs/" + job.json()["id"])
    assert job_response.status_code == 200 and job_response.json()["status"] == "succeeded"
    metrics = await client.get(path + "/metrics")
    assert metrics.status_code == 200 and len(metrics.json()) == 2
    assert {row["workspace_id"] for row in metrics.json()} == {workspace_id or DEFAULT_WORKSPACE_ID}
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps(
            {
                "token": {
                    "user_id": "viewer",
                    "role": "viewer",
                    "workspace_id": workspace_id,
                }
            }
        ),
    )
    assert (await client.post(path, json={})).status_code == 403
    assert (await client.post(path + "/jobs", json={})).status_code == 403
    assert (await client.get(path + "/metrics")).status_code == 200
