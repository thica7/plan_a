from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository


def test_repository_uses_env_db_path_by_default(tmp_path, monkeypatch) -> None:
    env_path = str(tmp_path / "env-knowledge.db")
    explicit_path = str(tmp_path / "explicit-knowledge.db")
    monkeypatch.setenv("KB_DB_PATH", env_path)

    assert KnowledgeRepository().db_path == env_path
    assert KnowledgeRepository(explicit_path).db_path == explicit_path


@pytest.mark.asyncio
async def test_repository_initialise_migrates_existing_schema(tmp_path) -> None:
    db_path = tmp_path / "knowledge.db"
    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE documents (
                id              TEXT PRIMARY KEY,
                url             TEXT,
                canonical_url   TEXT,
                title           TEXT NOT NULL,
                source_type     TEXT NOT NULL,
                competitor      TEXT,
                dimension       TEXT,
                content_hash    TEXT NOT NULL,
                text            TEXT NOT NULL,
                markdown        TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'active',
                fetched_at      TEXT NOT NULL,
                indexed_at      TEXT,
                metadata_json   TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE chunks (
                id              TEXT PRIMARY KEY,
                document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index     INTEGER NOT NULL,
                text            TEXT NOT NULL,
                token_count     INTEGER NOT NULL DEFAULT 0,
                content_hash    TEXT NOT NULL,
                metadata_json   TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE crawl_jobs (
                id              TEXT PRIMARY KEY,
                run_id          TEXT,
                url             TEXT NOT NULL,
                competitor      TEXT,
                dimension       TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',
                attempt_count   INTEGER NOT NULL DEFAULT 0,
                error           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            """
        )
        await db.execute(
            """
            INSERT INTO documents
                (id, url, canonical_url, title, source_type, content_hash, text, fetched_at)
            VALUES (
                'doc-old',
                'https://example.com/a',
                NULL,
                'Old',
                'manual',
                'hash-old',
                'old text',
                ?
            )
            """,
            (now,),
        )
        await db.commit()

    repo = KnowledgeRepository(str(db_path))
    await repo.initialise()
    try:
        db = repo._connection
        async with db.execute("PRAGMA journal_mode") as cur:
            journal_mode = (await cur.fetchone())[0]
        async with db.execute("PRAGMA busy_timeout") as cur:
            busy_timeout = (await cur.fetchone())[0]
        async with db.execute("PRAGMA synchronous") as cur:
            synchronous = (await cur.fetchone())[0]
        async with db.execute("PRAGMA cache_size") as cur:
            cache_size = (await cur.fetchone())[0]
        async with db.execute("SELECT description FROM _schema_version ORDER BY id") as cur:
            migrations = [row["description"] for row in await cur.fetchall()]
        async with db.execute("PRAGMA table_info(documents)") as cur:
            document_columns = {row["name"] for row in await cur.fetchall()}
        async with db.execute("PRAGMA table_info(chunks)") as cur:
            chunk_columns = {row["name"] for row in await cur.fetchall()}
        async with db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name IN ("
            "'chunks_fts', 'ingest_jobs', 'retrieval_traces', "
            "'evidence_sync_state', 'evidence_sync_metrics', "
            "'idx_chunks_crawl_run_document'"
            ")"
        ) as cur:
            objects = {row["name"] for row in await cur.fetchall()}

        assert journal_mode in {"wal", "delete"}
        assert busy_timeout == 30000
        assert synchronous == 1
        assert cache_size == -20000
        assert set(migrations) >= {
            "add embedding_model to chunks",
            "add document activity and version columns",
            "add crawl result metadata",
            "add ingest jobs table",
            "add document last seen timestamp",
            "add chunk crawl run id",
            "add retrieval traces table",
            "add evidence sync tracking",
        }
        assert {"is_active", "version", "parent_document_id", "last_seen_at"} <= document_columns
        assert "crawl_run_id" in chunk_columns
        assert {
            "chunks_fts",
            "ingest_jobs",
            "retrieval_traces",
            "evidence_sync_state",
            "evidence_sync_metrics",
            "idx_chunks_crawl_run_document",
        } <= objects
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_repository_tracks_chunks_and_versions(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        first = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/page",
                title="Page",
                source_type="manual",
                text="first version",
            ),
            "hash-first",
        )
        second = await repo.upsert_document(
            DocumentCreate(
                url="https://example.com/page",
                title="Page",
                source_type="manual",
                text="second version",
            ),
            "hash-second",
        )
        await repo.insert_chunks([
            KnowledgeChunk(
                id="chunk-1",
                document_id=second.id,
                chunk_index=0,
                text="second version",
                token_count=2,
                embedding_model="test",
                content_hash="chunk-hash",
                metadata={"a": 1},
            )
        ])

        old = await repo.get_document(first.id)
        counts = await repo.count_chunks_per_document()
        versions = await repo.get_document_versions(second.id)

        assert old is not None
        assert old.is_active is False
        assert old.status == "archived"
        assert second.version == 2
        assert second.parent_document_id == first.id
        assert counts == {second.id: 1}
        assert [doc.id for doc in versions] == [first.id, second.id]

        row = await repo.get_ingest_job("missing")
        assert row is None
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_repository_marks_stale_documents_and_weights_them(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        old_doc = await repo.upsert_document(
            DocumentCreate(title="Old", source_type="manual", text="old pricing"),
            "hash-old",
        )
        fresh_doc = await repo.upsert_document(
            DocumentCreate(title="Fresh", source_type="manual", text="fresh pricing"),
            "hash-fresh",
        )
        old_seen = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        await repo._connection.execute(
            "UPDATE documents SET last_seen_at = ? WHERE id = ?",
            (old_seen, old_doc.id),
        )
        await repo._connection.commit()

        count = await repo.mark_stale_documents(before_days=30)
        stale = await repo.get_document(old_doc.id)
        fresh = await repo.get_document(fresh_doc.id)

        assert count == 1
        assert stale is not None
        assert fresh is not None
        assert stale.status == "stale"
        assert repo.get_document_weight(stale) == 0.5
        assert repo.get_document_weight(fresh) == 1.0
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_ingestion_persists_crawl_run_id_on_chunks(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        pipeline = IngestionPipeline(repo=repo, vector_store=object())
        document_id = await pipeline.ingest(
            DocumentCreate(
                title="Crawled pricing",
                source_type="webpage_verified",
                text="Pricing page\n\nStarter plan costs 10 per user.",
            ),
            crawl_run_id="crawl-run-1",
        )

        chunks = await repo.get_chunks_for_document(document_id)
        crawl_runs = await repo.list_crawl_runs()

        assert chunks
        assert {chunk.crawl_run_id for chunk in chunks} == {"crawl-run-1"}
        assert crawl_runs[0]["crawl_run_id"] == "crawl-run-1"
        assert crawl_runs[0]["doc_count"] == 1
        assert crawl_runs[0]["chunk_count"] == len(chunks)
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_repository_serializes_concurrent_ingest_job_updates(tmp_path) -> None:
    db_path = str(tmp_path / "knowledge.db")
    setup_repo = KnowledgeRepository(db_path)
    await setup_repo.initialise()
    try:
        await setup_repo.create_ingest_job(
            "job-1",
            total_items=12,
            accepted_items=12,
            rejected_items=[],
            options={},
        )
    finally:
        await setup_repo.close()

    async def record_success(index: int) -> None:
        repo = KnowledgeRepository(db_path)
        await repo.initialise()
        try:
            await repo.record_ingest_job_success(
                "job-1",
                index=index,
                document_id=f"doc-{index}",
            )
        finally:
            await repo.close()

    await asyncio.gather(*(record_success(index) for index in range(12)))

    verify_repo = KnowledgeRepository(db_path)
    await verify_repo.initialise()
    try:
        row = await verify_repo.get_ingest_job("job-1")
        assert row is not None
        results = json.loads(row["result_items_json"])
        assert row["completed_items"] == 12
        assert row["failed_items"] == 0
        assert sorted(item["index"] for item in results) == list(range(12))
    finally:
        await verify_repo.close()


@pytest.mark.asyncio
async def test_repository_recovers_stale_transaction_before_crawl_job_write(tmp_path) -> None:
    repo = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repo.initialise()
    try:
        await repo._connection.execute("BEGIN")
        assert repo._connection.in_transaction is True

        job_id = await repo.create_crawl_job(
            "https://example.com/page",
            run_id="run-1",
            competitor="Example",
            dimension="docs",
        )

        row = await repo.get_crawl_job(job_id)
        assert row is not None
        assert row["url"] == "https://example.com/page"
        assert row["status"] == "pending"
    finally:
        await repo.close()
