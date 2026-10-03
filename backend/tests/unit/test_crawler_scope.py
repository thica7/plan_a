"""Durable crawl ownership is authoritative from source creation through ingestion."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import httpx
import pytest

from app.deps import get_enterprise_store
from app.main import create_app
from app.middleware import auth
from app.routes import crawl
from packages.crawler.models import CrawlRequest, CrawlResult, ParsedPage
from packages.crawler.repository import CrawlerRepository
from packages.crawler.scheduler import CrawlerScheduler
from packages.enterprise import EnterpriseMemoryStore
from packages.knowledge.models import KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.schema.enterprise import ProjectRecord

OWN = KnowledgeScope(workspace_id="a", project_id="p")
FOREIGN = KnowledgeScope(workspace_id="b", project_id="foreign")
LIBRARY = KnowledgeScope(workspace_id="a")
OLD_FETCHED = datetime(2020, 1, 1, tzinfo=UTC)


async def _source(repo, scope=OWN, **kwargs):
    return await repo.create_source("manual", kwargs.pop("config", {}), scope=scope, **kwargs)


@pytest.mark.asyncio
async def test_source_ownership_sql_filters_unknown_and_precedes_frontier_limit(tmp_path):
    async with CrawlerRepository(str(tmp_path / "crawler.db")) as repo:
        ids = {}
        for name, scope in [
            ("own", OWN),
            ("library", LIBRARY),
            ("foreign", FOREIGN),
            ("other", KnowledgeScope(workspace_id="a", project_id="q")),
            ("unknown", None),
        ]:
            source = await _source(repo, scope, market="US")
            ids[name] = source.id
            await repo.add_frontier_items(
                [f"https://same.test/{name}"],
                source_type="manual",
                source_id=source.id,
                priority=0 if name != "own" else 10,
            )
        assert [s.id for s in await repo.list_sources(scope=OWN)] == [ids["own"]]
        expanded = OWN.model_copy(update={"include_workspace_library": True})
        assert {s.id for s in await repo.list_sources(scope=expanded)} == {
            ids["own"],
            ids["library"],
        }
        for name in ["foreign", "other", "unknown", "library"]:
            assert await repo.get_source(ids[name], scope=OWN) is None
        assert (await repo.get_source(ids["own"], scope=OWN)).market == "US"
        assert [i.source_id for i in await repo.list_frontier(scope=OWN, limit=1)] == [ids["own"]]
        assert (await repo.stats(scope=OWN)).queued == 1
        assert (await repo.stats(scope=expanded)).queued == 2
        assert (await repo.get_source(ids["unknown"])).workspace_id is None


@pytest.mark.asyncio
async def test_delete_retry_and_source_stats_ignore_run_id_collisions(tmp_path):
    async with CrawlerRepository(str(tmp_path / "crawler.db")) as repo:
        own = await _source(repo)
        foreign = await _source(repo, FOREIGN)
        for source in [own, foreign]:
            await repo.add_frontier_items(
                [f"https://same.test/{source.id}"],
                source_type="manual",
                source_id=source.id,
                run_id=own.id,
            )
        rows = await repo.list_frontier()
        for row in rows:
            await repo.mark_failed(row.id, "failed")
        assert len(await repo.list_frontier(source_id=own.id, scope=OWN)) == 1
        assert (await repo.stats(source_id=own.id, scope=OWN)).failed == 1
        assert await repo.retry_failed(own.id, scope=FOREIGN) == 0
        assert await repo.retry_failed(own.id, scope=OWN) == 1
        assert (await repo.list_frontier(source_id=foreign.id))[0].status == "failed"
        assert not await repo.delete_source(own.id, scope=FOREIGN)
        assert (await repo.list_frontier(source_id=own.id))[0].status == "pending"
        assert await repo.delete_source(own.id, scope=OWN)
        assert (await repo.list_frontier(source_id=own.id))[0].status == "cancelled"
        assert (await repo.list_frontier(source_id=foreign.id))[0].status == "failed"
        assert not await repo.delete_source(own.id, scope=OWN)


@pytest.mark.asyncio
async def test_retry_without_source_only_updates_scoped_frontier(tmp_path):
    async with CrawlerRepository(str(tmp_path / "crawler.db")) as repo:
        for scope in [OWN, FOREIGN, None]:
            source = await _source(repo, scope)
            await repo.add_frontier_items(
                [f"https://same.test/{source.id}"], source_type="manual", source_id=source.id
            )
        for row in await repo.list_frontier():
            await repo.mark_failed(row.id, "failed")
        assert await repo.retry_failed(scope=OWN) == 1
        assert (await repo.stats()).failed == 2


@pytest.mark.asyncio
async def test_url_deduplication_is_per_source_and_survives_reopening(tmp_path):
    db_path = str(tmp_path / "crawler.db")
    async with CrawlerRepository(db_path) as repo:
        for scope in [OWN, FOREIGN]:
            source = await _source(repo, scope)
            assert (
                await repo.add_frontier_items(
                    ["https://same.test/a#x", "https://same.test/a"],
                    source_type="manual",
                    source_id=source.id,
                )
                == 1
            )
        assert await repo.add_frontier_items(["https://same.test/a"], source_type="manual") == 1
        assert await repo.add_frontier_items(["https://same.test/a#y"], source_type="manual") == 0
    async with CrawlerRepository(db_path) as reopened:
        assert len(await reopened.list_frontier()) == 3
        assert (await reopened.list_sources(scope=OWN))[0].workspace_id == "a"


@pytest.mark.asyncio
async def test_real_legacy_sqlite_migration_preserves_unknown_ownership(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE crawl_source (id TEXT PRIMARY KEY, type TEXT NOT NULL,
                config_json TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO crawl_source VALUES ('legacy', 'manual',
                '{"workspace_id":"a","project_id":"p"}', '2020-01-01T00:00:00+00:00');
            CREATE TABLE crawl_frontier (id TEXT PRIMARY KEY, source_type TEXT NOT NULL,
                url TEXT NOT NULL, canonical_url TEXT NOT NULL, competitor TEXT, dimension TEXT,
                priority INTEGER NOT NULL DEFAULT 100, depth INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT NOT NULL, last_error TEXT, parent_id TEXT,
                discovered_at TEXT NOT NULL, run_id TEXT);
            CREATE UNIQUE INDEX ux_crawl_frontier_canonical_url
                ON crawl_frontier(canonical_url);
            INSERT INTO crawl_frontier (id, source_type, url, canonical_url, next_run_at,
                discovered_at, run_id) VALUES ('legacy-item', 'manual', 'https://same.test/a',
                'https://same.test/a', '2020-01-01T00:00:00+00:00',
                '2020-01-01T00:00:00+00:00', 'legacy');
        """)
    async with CrawlerRepository(db_path) as repo:
        source = await repo.get_source("legacy")
        assert source.workspace_id is None and source.project_id is None and source.market is None
        assert source.config == {"workspace_id": "a", "project_id": "p"}
        assert await repo.get_source("legacy", scope=OWN) is None
        assert not await repo.delete_source("legacy", scope=OWN)
        legacy_item = (await repo.list_frontier())[0]
        assert legacy_item.source_id is None and legacy_item.run_id == "legacy"
        for scope in [OWN, FOREIGN]:
            trusted = await _source(repo, scope)
            assert (
                await repo.add_frontier_items(
                    ["https://same.test/a"], source_type="manual", source_id=trusted.id
                )
                == 1
            )
    async with CrawlerRepository(db_path) as repo:
        assert (await repo.get_source("legacy")).workspace_id is None
        assert len(await repo.list_frontier()) == 3


def _ignore_task(coro):
    coro.close()
    return None


@pytest.fixture
async def scoped_crawler_http(tmp_path, monkeypatch):
    path = str(tmp_path / "crawler.db")
    repo = CrawlerRepository(path)
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
    for name, scope in [
        ("own", OWN),
        ("library", LIBRARY),
        ("foreign", FOREIGN),
        ("other", KnowledgeScope(workspace_id="a", project_id="q")),
        ("unknown", None),
    ]:
        source = await _source(repo, scope)
        ids[name] = source.id
        await repo.add_frontier_items(
            [f"https://same.test/{name}"],
            source_type="manual",
            source_id=source.id,
            run_id=ids["own"],
        )
    for row in await repo.list_frontier():
        await repo.mark_failed(row.id, "failed")

    async def open_repo():
        current = CrawlerRepository(path)
        await current.initialise()
        return current

    class FakeProcessor:
        async def expand(self, source):
            return ["https://same.test/created"]

    monkeypatch.setattr(crawl, "_open_crawler_repository", open_repo)
    monkeypatch.setattr(crawl, "processor_for", lambda _: FakeProcessor())
    monkeypatch.setattr(crawl.asyncio, "create_task", _ignore_task)
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps(
            {
                "token-a": {"user_id": "owner-a", "role": "owner", "workspace_id": "a"},
                "token-b": {"user_id": "owner-b", "role": "owner", "workspace_id": "b"},
                "viewer": {"user_id": "viewer-a", "role": "viewer", "workspace_id": "a"},
            }
        ),
    )
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer token-a", "X-Workspace-Id": "b"},
        ) as client:
            yield client, repo, ids
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_source_http_creation_uses_subject_project_and_typed_market(scoped_crawler_http):
    client, repo, _ = scoped_crawler_http
    body = {
        "type": "manual",
        "project_id": "p",
        "market": "US",
        "workspace_id": "b",
        "config": {
            "workspace_id": "b",
            "project_id": "foreign",
            "market": "EU",
            "competitor": "Acme",
            "dimension": "pricing",
        },
    }
    created = await client.post("/api/crawl/sources", json=body)
    assert created.status_code == 201
    source = created.json()["source"]
    assert (source["workspace_id"], source["project_id"], source["market"]) == ("a", "p", "US")
    saved = await repo.get_source(source["id"], scope=OWN)
    assert saved.competitor == "Acme" and saved.dimension == "pricing"
    default = await client.post("/api/crawl/sources", json={"type": "manual"})
    assert default.json()["source"]["workspace_id"] == "a"
    assert default.json()["source"]["project_id"] is None
    other_workspace = await client.post(
        "/api/crawl/sources", json={"type": "manual"}, headers={"Authorization": "Bearer token-b"}
    )
    assert other_workspace.status_code == 201
    assert len([i for i in await repo.list_frontier() if i.url == "https://same.test/created"]) == 3
    conflict = await client.post("/api/crawl/sources", params={"project_id": "q"}, json=body)
    assert conflict.status_code == 400
    for project in ["foreign", "missing", " "]:
        assert (
            await client.post("/api/crawl/sources", json={"type": "manual", "project_id": project})
        ).status_code == 404
    assert (
        await client.post(
            "/api/crawl/sources",
            json={"type": "manual"},
            headers={"Authorization": "Bearer viewer"},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_source_http_read_and_stats_only_expand_same_workspace_library(scoped_crawler_http):
    client, _, ids = scoped_crawler_http
    params = {"project_id": "p"}
    own = await client.get("/api/crawl/sources", params=params)
    assert [s["id"] for s in own.json()] == [ids["own"]]
    library = await client.get("/api/crawl/sources")
    assert [s["id"] for s in library.json()] == [ids["library"]]
    expanded = {**params, "include_workspace_library": True}
    assert {s["id"] for s in (await client.get("/api/crawl/sources", params=expanded)).json()} == {
        ids["own"],
        ids["library"],
    }
    assert (await client.get("/api/crawl/frontier/stats", params=params)).json()["failed"] == 1
    assert (await client.get("/api/crawl/frontier/stats", params=expanded)).json()["failed"] == 2
    assert (await client.get("/api/crawl/sources/" + ids["own"], params=params)).json()["progress"][
        "failed"
    ] == 1
    for name in ["foreign", "other", "unknown"]:
        assert (
            await client.get("/api/crawl/sources/" + ids[name], params=expanded)
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["library", "other", "foreign", "unknown"])
async def test_source_http_write_never_expands_library_or_cancels_foreign(
    scoped_crawler_http, name
):
    client, repo, ids = scoped_crawler_http
    path = "/api/crawl/sources/" + ids[name]
    params = {"project_id": "p", "include_workspace_library": True}
    assert (await client.post(path + "/retry", params=params)).status_code == 404
    assert (await client.delete(path, params=params)).status_code == 404
    assert await repo.get_source(ids[name]) is not None
    assert (await repo.list_frontier(source_id=ids[name]))[0].status == "failed"


class FakeFetcher:
    def __init__(self):
        self.requests = []

    async def fetch(self, request):
        self.requests.append(request)
        return CrawlResult(
            request=request,
            success=True,
            page=ParsedPage(
                url=request.url,
                html=f"<main>{request.url} "
                + "Full source. " * 1000
                + '</main><a href="/child">Child</a><a href="/child#duplicate">Duplicate</a>',
                fetched_at=OLD_FETCHED,
                content_hash="page",
            ),
        )

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_scheduler_uses_saved_source_not_run_id_and_children_inherit(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_JS_RENDER", "off")
    db_path = str(tmp_path / "crawler.db")
    monkeypatch.setenv("KB_DB_PATH", db_path)
    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "1")
    monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)
    async with CrawlerRepository(db_path) as repo:
        source = await _source(
            repo,
            config={"max_depth": 1, "max_urls": 5},
            competitor="Acme",
            dimension="pricing",
            market="US",
        )
        wrong = await _source(repo, FOREIGN, config={"max_depth": 0, "max_urls": 1})
        await repo.add_frontier_items(
            ["https://same.test/root"],
            source_type="manual",
            source_id=source.id,
            run_id=wrong.id,
            competitor="spoof",
            dimension="spoof",
        )
        received = []

        async def callback(result):
            received.append(result)
            await crawl._ingest_frontier_result(result)

        scheduler = CrawlerScheduler(repository=repo, on_result=callback)
        fetcher = FakeFetcher()
        scheduler._fetcher = fetcher
        try:
            root = (await repo.claim_pending())[0]
            await scheduler._handle_frontier_item(root)
            assert fetcher.requests[0].max_depth == 1
            assert fetcher.requests[0].source_id == source.id
            assert fetcher.requests[0].competitor == "Acme"
            children = [i for i in await repo.list_frontier(source_id=source.id) if i.parent_id]
            assert len(children) == 1
            child = children[0]
            assert child.source_id == source.id and child.run_id == wrong.id
            assert child.competitor == "Acme" and child.dimension == "pricing"
            await scheduler._handle_frontier_item((await repo.claim_pending())[0])
            assert len(await repo.list_frontier(source_id=source.id)) == 2
            assert all(r.request.source_id == source.id for r in received)
            async with KnowledgeRepository(db_path) as kb:
                docs = await kb.list_documents(scope=OWN)
                assert len(docs) == 2
                assert all(d.market == "US" and len(d.text) > 10000 for d in docs)
                assert all(d.fetched_at == d.last_verified_at == OLD_FETCHED for d in docs)
                assert await kb.count_documents(scope=FOREIGN) == 0
        finally:
            await scheduler.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["missing", "legacy", "run_id_only"])
async def test_scheduler_quarantines_unknown_source_before_fetch(tmp_path, source_kind):
    async with CrawlerRepository(str(tmp_path / "crawler.db")) as repo:
        legacy = await _source(repo, None, config={"workspace_id": "a", "project_id": "p"})
        trusted = await _source(repo)
        source_id = {"missing": "deleted", "legacy": legacy.id, "run_id_only": None}[source_kind]
        await repo.add_frontier_items(
            ["https://same.test/root"], source_type="manual", source_id=source_id, run_id=trusted.id
        )
        callbacks = []

        async def callback(result):
            callbacks.append(result)

        scheduler = CrawlerScheduler(repository=repo, on_result=callback)
        fetcher = FakeFetcher()
        scheduler._fetcher = fetcher
        try:
            await scheduler._handle_frontier_item((await repo.claim_pending())[0])
            assert fetcher.requests == []
            assert (await repo.list_frontier())[0].status == "failed"
            assert not any(r.success for r in callbacks)
        finally:
            await scheduler.stop()


@pytest.mark.asyncio
async def test_frontier_callback_uses_saved_scope_market_model_and_full_body(tmp_path, monkeypatch):
    db_path = str(tmp_path / "kb.db")
    monkeypatch.setenv("KB_DB_PATH", db_path)
    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "1")
    monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)
    async with CrawlerRepository(db_path) as crawler_repo:
        source = await _source(
            crawler_repo,
            market="US",
            competitor="Acme",
            dimension="pricing",
            config={"workspace_id": "b", "project_id": "foreign", "market": "EU"},
        )
        wrong = await _source(crawler_repo, FOREIGN, market="EU")
    result = CrawlResult(
        request=CrawlRequest(
            url="https://same.test/root",
            source_id=source.id,
            run_id=wrong.id,
            competitor="spoof",
            dimension="spoof",
        ),
        success=True,
        page=ParsedPage(
            url="https://same.test/root",
            title="root",
            text="Full source. " * 1000,
            html='<meta name="workspace_id" content="b">',
            fetched_at=OLD_FETCHED,
            content_hash="page",
        ),
    )
    await crawl._ingest_frontier_result(result)
    async with KnowledgeRepository(db_path) as kb:
        docs = await kb.list_documents(scope=OWN)
        assert len(docs) == 1
        doc = docs[0]
        assert (doc.workspace_id, doc.project_id, doc.market, doc.competitor, doc.dimension) == (
            "a",
            "p",
            "US",
            "Acme",
            "pricing",
        )
        assert doc.text == result.page.text and len(doc.text) > 10000
        assert doc.fetched_at == doc.last_verified_at == OLD_FETCHED
        assert await kb.count_documents(scope=FOREIGN) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "legacy", "deleted", "run_id_only"])
async def test_frontier_callback_unknown_or_deleted_source_never_publishes(
    tmp_path, monkeypatch, kind
):
    db_path = str(tmp_path / "kb.db")
    monkeypatch.setenv("KB_DB_PATH", db_path)
    monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)
    async with CrawlerRepository(db_path) as repo:
        legacy = await _source(repo, None, config={"workspace_id": "a", "project_id": "p"})
        trusted = await _source(repo)
        await repo.delete_source(trusted.id)
    source_id = {
        "missing": "missing",
        "legacy": legacy.id,
        "deleted": trusted.id,
        "run_id_only": None,
    }[kind]
    request = CrawlRequest(url="https://same.test/root", source_id=source_id, run_id=legacy.id)
    result = CrawlResult(
        request=request,
        success=True,
        page=ParsedPage(
            url=request.url, text="Full source body", fetched_at=OLD_FETCHED, content_hash="x"
        ),
    )
    await crawl._ingest_frontier_result(result)
    async with KnowledgeRepository(db_path) as repo:
        assert await repo.count_documents() == 0


@pytest.mark.asyncio
async def test_frontier_callback_keeps_disabled_ingestion_a_noop(tmp_path, monkeypatch):
    db_path = str(tmp_path / "kb.db")
    monkeypatch.setenv("KB_DB_PATH", db_path)
    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "0")
    monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)
    async with CrawlerRepository(db_path) as repo:
        source = await _source(repo)
    result = CrawlResult(
        request=CrawlRequest(url="https://same.test/root", source_id=source.id),
        success=True,
        page=ParsedPage(
            url="https://same.test/root", text="Body", fetched_at=OLD_FETCHED, content_hash="page"
        ),
    )
    await crawl._ingest_frontier_result(result)
    async with KnowledgeRepository(db_path) as repo:
        assert await repo.count_documents() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_delete_during_fetch_preserves_cancelled_and_never_emits_children_or_callback(
    tmp_path, monkeypatch, success
):
    import asyncio

    monkeypatch.setenv("KB_JS_RENDER", "off")
    path = str(tmp_path / "crawler.db")
    fetching = asyncio.Event()
    release = asyncio.Event()
    callbacks = []

    class BlockingFetcher:
        async def fetch(self, request):
            fetching.set()
            await release.wait()
            return CrawlResult(
                request=request,
                success=success,
                error=None if success else "fake failure",
                page=ParsedPage(
                    url=request.url,
                    html='<main>Body</main><a href="/child">child</a>',
                    fetched_at=OLD_FETCHED,
                    content_hash="page",
                )
                if success
                else None,
            )

        async def close(self):
            pass

    async def callback(result):
        callbacks.append(result)

    async with CrawlerRepository(path) as repo, CrawlerRepository(path) as deleting:
        source = await _source(repo, config={"max_depth": 1})
        await repo.add_frontier_items(
            ["https://same.test/root"], source_type="manual", source_id=source.id
        )
        item = (await repo.claim_pending())[0]
        scheduler = CrawlerScheduler(repository=repo, on_result=callback)
        scheduler._fetcher = BlockingFetcher()
        task = asyncio.create_task(scheduler._handle_frontier_item(item))
        try:
            await asyncio.wait_for(fetching.wait(), 5)
            assert await deleting.delete_source(source.id, scope=OWN)
            assert (await repo.list_frontier(source_id=source.id))[0].status == "cancelled"
            release.set()
            await task
            assert [(r.id, r.status) for r in await repo.list_frontier(source_id=source.id)] == [
                (item.id, "cancelled")
            ]
            assert callbacks == []
        finally:
            release.set()
            await task
            await scheduler.stop()


@pytest.mark.asyncio
async def test_deleted_source_cannot_publish_after_callback_lookup_before_kb_open(
    tmp_path, monkeypatch
):
    import asyncio

    path = str(tmp_path / "crawler.db")
    monkeypatch.setenv("KB_DB_PATH", path)
    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "1")
    monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)
    kb_opening = asyncio.Event()
    release = asyncio.Event()
    real_open = crawl._open_repository

    async def open_after_delete():
        kb_opening.set()
        await release.wait()
        return await real_open()

    monkeypatch.setattr(crawl, "_open_repository", open_after_delete)
    async with CrawlerRepository(path) as deleting:
        source = await _source(deleting)
        result = CrawlResult(
            request=CrawlRequest(url="https://same.test/root", source_id=source.id),
            success=True,
            page=ParsedPage(
                url="https://same.test/root",
                text="Full source body",
                fetched_at=OLD_FETCHED,
                content_hash="page",
            ),
        )
        task = asyncio.create_task(crawl._ingest_frontier_result(result))
        try:
            await asyncio.wait_for(kb_opening.wait(), 5)
            assert await deleting.delete_source(source.id, scope=OWN)
            release.set()
            await task
            async with KnowledgeRepository(path) as repo:
                assert await repo.count_documents(scope=OWN) == 0
        finally:
            release.set()
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["max_urls", "max_total_bytes"])
async def test_zero_positive_budget_config_uses_previous_default_and_finishes(tmp_path, key):
    class FailingFetcher:
        async def fetch(self, request):
            assert request.max_depth == 0
            assert request.max_urls == 1000
            assert request.max_total_bytes == 50_000_000
            return CrawlResult(request=request, success=False, error="fake failure")

        async def close(self):
            pass

    async with CrawlerRepository(str(tmp_path / "crawler.db")) as repo:
        source = await _source(repo, config={key: 0, "max_depth": 0})
        await repo.add_frontier_items(
            ["https://same.test/root"], source_type="manual", source_id=source.id
        )
        scheduler = CrawlerScheduler(repository=repo)
        scheduler._fetcher = FailingFetcher()
        try:
            await scheduler._handle_frontier_item((await repo.claim_pending())[0])
            assert (await repo.list_frontier(source_id=source.id))[0].status == "failed"
        finally:
            await scheduler.stop()


@pytest.mark.asyncio
async def test_cancelled_frontier_stays_cancelled_for_all_failure_and_retry_updates(tmp_path):
    path = str(tmp_path / "crawler.db")
    async with CrawlerRepository(path) as repo, CrawlerRepository(path) as deleting:
        source = await _source(repo)
        await repo.add_frontier_items(
            ["https://same.test/root"], source_type="manual", source_id=source.id
        )
        item = (await repo.claim_pending())[0]
        assert await deleting.delete_source(source.id, scope=OWN)
        await repo.mark_failed(item.id, "failed")
        assert (await repo.list_frontier(source_id=source.id))[0].status == "cancelled"
        await repo.mark_failed(item.id, "retry", retry=True)
        assert (await repo.list_frontier(source_id=source.id))[0].status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("same_body", [True, False])
async def test_ingest_source_guard_rejects_deleted_source_before_dedup_or_archiving(
    tmp_path, monkeypatch, same_body
):
    from app.routes import knowledge

    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "1")
    path = str(tmp_path / "kb.db")
    async with CrawlerRepository(path) as deleting, KnowledgeRepository(path) as repo:
        source = await _source(deleting)
        result = CrawlResult(
            request=CrawlRequest(url="https://same.test/root", source_id=source.id),
            success=True,
            page=ParsedPage(
                url="https://same.test/root",
                text="Committed original full source",
                fetched_at=OLD_FETCHED,
                content_hash="original",
            ),
        )
        original = await knowledge.ingest_crawl_result(repo, result, scope=OWN)
        assert await deleting.delete_source(source.id, scope=OWN)
        if not same_body:
            result.page.text = "Different source arriving after deletion"
        rejected = await knowledge.ingest_crawl_result(
            repo,
            result,
            scope=OWN,
            crawl_source_id=source.id,
        )
        assert rejected == {"ingested": False, "reason": "source_unavailable"}
        assert await repo.count_documents(scope=OWN) == 1
        doc = await repo.get_document(original["document_id"], scope=OWN)
        assert doc.is_active and doc.text == "Committed original full source"
        assert len(await repo.get_document_versions(original["document_id"])) == 1


@pytest.mark.asyncio
async def test_ingest_source_guard_requires_saved_source_exact_workspace_and_project(
    tmp_path, monkeypatch
):
    from app.routes import knowledge

    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "1")
    path = str(tmp_path / "kb.db")
    async with CrawlerRepository(path) as crawler, KnowledgeRepository(path) as repo:
        source = await _source(crawler)
        result = CrawlResult(
            request=CrawlRequest(url="https://same.test/root", source_id=source.id),
            success=True,
            page=ParsedPage(
                url="https://same.test/root",
                text="Full source body",
                fetched_at=OLD_FETCHED,
                content_hash="page",
            ),
        )
        for wrong_scope in [FOREIGN, LIBRARY]:
            rejected = await knowledge.ingest_crawl_result(
                repo,
                result,
                scope=wrong_scope,
                crawl_source_id=source.id,
            )
            assert rejected == {"ingested": False, "reason": "source_unavailable"}
        assert await repo.count_documents() == 0


@pytest.mark.asyncio
async def test_source_deleted_during_expansion_never_enqueues_after_delete(tmp_path, monkeypatch):
    import asyncio

    from packages.auth import EnterpriseUserContext
    from packages.crawler.models import CrawlSourceCreate

    path = str(tmp_path / "crawler.db")
    monkeypatch.setenv("KB_DB_PATH", path)
    expanding = asyncio.Event()
    release = asyncio.Event()
    saved_sources = []

    class BlockingProcessor:
        async def expand(self, source):
            saved_sources.append(source)
            expanding.set()
            await release.wait()
            return ["https://same.test/root"]

    monkeypatch.setattr(crawl, "processor_for", lambda _: BlockingProcessor())
    user = EnterpriseUserContext(user_id="owner-a", role="owner", workspace_id="a")
    task = asyncio.create_task(crawl.create_crawl_source(CrawlSourceCreate(type="manual"), user))
    try:
        await asyncio.wait_for(expanding.wait(), 5)
        async with CrawlerRepository(path) as deleting:
            assert await deleting.delete_source(saved_sources[0].id, scope=LIBRARY)
        # Ignore only the background scheduler spawned after source creation resumes.
        monkeypatch.setattr(crawl.asyncio, "create_task", _ignore_task)
        release.set()
        await task
        async with CrawlerRepository(path) as repo:
            assert await repo.list_frontier(source_id=saved_sources[0].id) == []
    finally:
        release.set()
        await task
