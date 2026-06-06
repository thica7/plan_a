from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite
import pytest

from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository


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
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('chunks_fts', 'ingest_jobs')"
        ) as cur:
            objects = {row["name"] for row in await cur.fetchall()}

        assert journal_mode == "wal"
        assert busy_timeout == 5000
        assert synchronous == 1
        assert cache_size == -20000
        assert set(migrations) >= {
            "add embedding_model to chunks",
            "add document activity and version columns",
            "add crawl result metadata",
            "add ingest jobs table",
        }
        assert {"is_active", "version", "parent_document_id"} <= document_columns
        assert {"chunks_fts", "ingest_jobs"} <= objects
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
