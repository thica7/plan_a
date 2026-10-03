from datetime import UTC, datetime

import pytest

from packages.knowledge.models import DocumentCreate, KnowledgeChunk, KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository


@pytest.mark.asyncio
async def test_jobs_and_eval_filter_before_pagination_and_unknown_stays_private(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb.db"))
    await repo.initialise()
    own = KnowledgeScope(workspace_id="a", project_id="p")
    foreign = KnowledgeScope(workspace_id="b", project_id="q")
    try:
        for suffix, scope in [("own", own), ("foreign", foreign), ("unknown", None)]:
            job = await repo.create_crawl_job("https://same.test", scope=scope)
            await repo.create_ingest_job(
                suffix, total_items=0, accepted_items=0, rejected_items=[], options={}, scope=scope
            )
            await repo.record_eval_run(
                run_id=suffix,
                top_k=1,
                metrics={},
                labels=[],
                results=[{"private": suffix}],
                scope=scope,
            )
            if suffix == "own":
                own_job = job
            else:
                assert await repo.get_crawl_job(job, scope=own) is None
                assert await repo.get_ingest_job(suffix, scope=own) is None
                assert await repo.get_eval_run(suffix, scope=own) is None
        assert [r["id"] for r in await repo.list_crawl_jobs(scope=own, limit=1)] == [own_job]
        assert await repo.count_crawl_jobs(scope=own) == 1
        assert [r["id"] for r in await repo.list_ingest_jobs(scope=own, limit=1)] == ["own"]
        assert await repo.count_ingest_jobs(scope=own) == 1
        assert [r["id"] for r in await repo.list_eval_runs(scope=own, limit=1)] == ["own"]
        assert await repo.count_eval_runs(scope=own) == 1
        assert (await repo.get_eval_run("own", scope=own))["workspace_id"] == "a"
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_crawl_run_counts_do_not_multiply_or_mix_scopes(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb.db"))
    await repo.initialise()
    own = KnowledgeScope(workspace_id="a", project_id="p")
    try:
        for ws, project in [("a", "p"), ("b", "q")]:
            doc = await repo.upsert_document(
                DocumentCreate(
                    workspace_id=ws,
                    project_id=project,
                    title="doc",
                    source_type="manual",
                    text="pricing",
                ),
                ws,
            )
            await repo.insert_chunks(
                [
                    KnowledgeChunk(
                        id=ws,
                        document_id=doc.id,
                        chunk_index=0,
                        token_count=3,
                        embedding_model="test",
                        text="pricing",
                        content_hash=ws,
                        crawl_run_id="shared",
                    )
                ]
            )
            for _ in range(2):
                await repo.create_crawl_job(
                    "https://same.test",
                    run_id="shared",
                    scope=KnowledgeScope(workspace_id=ws, project_id=project),
                )
        rows = await repo.list_crawl_runs(scope=own)
        assert len(rows) == 1
        assert rows[0]["doc_count"] == rows[0]["chunk_count"] == 1
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_crawl_ingest_requires_explicit_scope_and_legacy_workers_do_not_fetch(
    tmp_path, monkeypatch
):
    from app.routes import knowledge
    from packages.crawler import scheduler
    from packages.crawler.models import CrawlRequest, CrawlResult, ParsedPage

    repo = KnowledgeRepository(str(tmp_path / "kb.db"))
    await repo.initialise()
    result = CrawlResult(
        request=CrawlRequest(url="https://same.test"),
        success=True,
        page=ParsedPage(
            url="https://same.test", text="body", fetched_at=datetime.now(UTC), content_hash="x"
        ),
    )
    try:
        with pytest.raises(ValueError, match="scope"):
            await knowledge.ingest_crawl_result(repo, result)
        job_id = await repo.create_crawl_job("https://legacy.test")

        async def current_repo():
            return repo

        monkeypatch.setattr(knowledge, "get_repository", current_repo)

        def unexpected():
            raise AssertionError("legacy job must not crawl")

        monkeypatch.setattr(scheduler, "CrawlerScheduler", unexpected)
        await knowledge._run_crawl_job(job_id)
        assert (await repo.get_crawl_job(job_id))["status"] == "failed"
    finally:
        await repo.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", [False, True])
async def test_saved_crawl_job_scope_reaches_ingestion(tmp_path, monkeypatch, alias):
    from app.routes import crawl, knowledge
    from packages.crawler import scheduler
    from packages.crawler.models import CrawlResult, ParsedPage

    db_path = str(tmp_path / "kb.db")
    monkeypatch.setenv("KB_DB_PATH", db_path)
    repo = KnowledgeRepository(db_path)
    await repo.initialise()
    scope = KnowledgeScope(workspace_id="a", project_id="p")
    old = datetime(2020, 1, 1, tzinfo=UTC)
    try:
        job_id = await repo.create_crawl_job("https://own.test", scope=scope, market="US")

        async def current_repo():
            return repo

        monkeypatch.setattr(knowledge, "get_repository", current_repo)
        monkeypatch.setattr(knowledge, "get_embedding_provider", lambda: None)
        monkeypatch.setattr(crawl, "get_embedding_provider", lambda: None)

        class FakeScheduler:
            async def crawl_sync(self, request):
                return CrawlResult(
                    request=request,
                    success=True,
                    page=ParsedPage(
                        url=request.url,
                        title="job",
                        text="Full source. " * 1000,
                        fetched_at=old,
                        content_hash="page",
                    ),
                )

            async def stop(self):
                pass

        monkeypatch.setattr(scheduler, "CrawlerScheduler", FakeScheduler)
        await (crawl._run_crawl_job(job_id) if alias else knowledge._run_crawl_job(job_id))
        job = await repo.get_crawl_job(job_id, scope=scope)
        assert job["status"] == "success"
        import json

        doc = await repo.get_document(json.loads(job["result_metadata_json"])["document_id"])
        assert doc.workspace_id == "a" and doc.project_id == "p" and doc.market == "US"
        assert doc.fetched_at == old and doc.last_verified_at == old
        assert len(doc.text) > 10000
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_legacy_ingest_worker_does_not_parse_unknown_job(tmp_path, monkeypatch):
    from app.routes import knowledge

    repo = KnowledgeRepository(str(tmp_path / "kb.db"))
    await repo.initialise()
    try:
        await repo.create_ingest_job(
            "legacy", total_items=1, accepted_items=1, rejected_items=[], options={}
        )

        def unexpected(*args):
            raise AssertionError("legacy job must not parse")

        monkeypatch.setattr(knowledge, "parse_document", unexpected)
        await knowledge._process_batch_ingest(
            "legacy",
            [(0, knowledge.BatchIngestItem(source="text", text="body"))],
            repo=repo,
            options={"max_concurrent": 1, "fail_fast": False},
            embedding_provider=None,
        )
        assert (await repo.get_ingest_job("legacy"))["status"] == "failed"
        assert await repo.count_documents() == 0
    finally:
        await repo.close()
