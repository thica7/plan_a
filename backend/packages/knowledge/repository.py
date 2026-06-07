"""SQLite-backed repository for Knowledge Base metadata."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite

from .models import (
    DocumentCreate,
    KnowledgeChunk,
    KnowledgeDocument,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id                 TEXT PRIMARY KEY,
    url                TEXT,
    canonical_url      TEXT,
    title              TEXT NOT NULL,
    source_type        TEXT NOT NULL,
    competitor         TEXT,
    dimension          TEXT,
    content_hash       TEXT NOT NULL,
    text               TEXT NOT NULL,
    markdown           TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'active',
    is_active          INTEGER NOT NULL DEFAULT 1,
    version            INTEGER NOT NULL DEFAULT 1,
    parent_document_id TEXT REFERENCES documents(id),
    fetched_at         TEXT NOT NULL,
    indexed_at         TEXT,
    last_seen_at       TEXT,
    metadata_json      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    token_count     INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT NOT NULL DEFAULT '',
    content_hash    TEXT NOT NULL,
    crawl_run_id    TEXT,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS crawl_jobs (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT,
    url                  TEXT NOT NULL,
    competitor           TEXT,
    dimension            TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    attempt_count        INTEGER NOT NULL DEFAULT 0,
    error                TEXT,
    result_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    total_items         INTEGER NOT NULL DEFAULT 0,
    accepted_items      INTEGER NOT NULL DEFAULT 0,
    completed_items     INTEGER NOT NULL DEFAULT 0,
    failed_items        INTEGER NOT NULL DEFAULT 0,
    rejected_items_json TEXT NOT NULL DEFAULT '[]',
    failed_items_json   TEXT NOT NULL DEFAULT '[]',
    result_items_json   TEXT NOT NULL DEFAULT '[]',
    options_json        TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    top_k         INTEGER NOT NULL,
    metrics_json  TEXT NOT NULL,
    labels_json   TEXT NOT NULL,
    results_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_traces (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    query            TEXT NOT NULL,
    preset_used      TEXT,
    dense_hits       INTEGER NOT NULL DEFAULT 0,
    sparse_hits      INTEGER NOT NULL DEFAULT 0,
    reranked_hits    INTEGER NOT NULL DEFAULT 0,
    latency_ms       REAL NOT NULL DEFAULT 0,
    cache_hit        INTEGER NOT NULL DEFAULT 0,
    crawl_run_id     TEXT,
    competitor       TEXT,
    dimension        TEXT,
    source_type      TEXT,
    retrieval_preset TEXT,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_documents_competitor ON documents(competitor);
CREATE INDEX IF NOT EXISTS idx_documents_dimension ON documents(dimension);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_crawl_jobs_status ON crawl_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created_at ON eval_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_traces_created_at ON retrieval_traces(created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_traces_preset ON retrieval_traces(preset_used);
"""

_POST_MIGRATION_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_documents_parent_document_id ON documents(parent_document_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_active_canonical_url
ON documents(canonical_url)
WHERE is_active = 1 AND canonical_url IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_active_content_hash
ON documents(content_hash)
WHERE is_active = 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_chunks_document_chunk_index
ON chunks(document_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    text,
    content='documents',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, text)
    VALUES ('delete', old.rowid, old.title, old.text);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, text)
    VALUES ('delete', old.rowid, old.title, old.text);
    INSERT INTO documents_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""

Migration = tuple[int, str, Callable[["KnowledgeRepository"], Awaitable[None]]]


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class KnowledgeRepository:
    """Async SQLite repository for knowledge base metadata."""

    def __init__(self, db_path: str = "runs/knowledge.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> str:
        return self._db_path

    async def initialise(self) -> None:
        if self._db is not None:
            return

        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        try:
            await self._apply_pragmas()
            await self._db.executescript(_BASE_SCHEMA)
            await self._ensure_migration_table()
            await self._migrate_schema()
            await self._deduplicate_active_documents()
            await self._db.executescript(_POST_MIGRATION_SCHEMA)
            await self._db.execute(
                "INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')"
            )
            await self._db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
            await self._db.commit()
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> KnowledgeRepository:
        await self.initialise()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("KnowledgeRepository.initialise() must be called before use")
        return self._db

    # -- Documents ----------------------------------------------------------

    async def upsert_document(self, doc: DocumentCreate, content_hash: str) -> KnowledgeDocument:
        now = datetime.now(UTC).isoformat()
        doc_id = str(uuid.uuid4())
        db = self._connection
        canonical_url = doc.canonical_url or doc.url
        version = 1
        parent_document_id: str | None = None

        await db.execute("BEGIN")
        try:
            if canonical_url:
                async with db.execute(
                    """
                    SELECT * FROM documents
                    WHERE canonical_url = ? AND is_active = 1
                    ORDER BY version DESC, fetched_at DESC
                    LIMIT 1
                    """,
                    (canonical_url,),
                ) as cur:
                    previous = await cur.fetchone()
                if previous is not None:
                    version = int(previous["version"]) + 1
                    parent_document_id = previous["parent_document_id"] or previous["id"]
                    await db.execute(
                        """
                        UPDATE documents
                        SET is_active = 0, status = 'archived', indexed_at = ?
                        WHERE id = ?
                        """,
                        (now, previous["id"]),
                    )

            await db.execute(
                """
                INSERT INTO documents
                    (id, url, canonical_url, title, source_type, competitor, dimension,
                     content_hash, text, markdown, status, is_active, version,
                     parent_document_id, fetched_at, indexed_at, last_seen_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    doc.url,
                    canonical_url,
                    doc.title,
                    doc.source_type,
                    doc.competitor,
                    doc.dimension,
                    content_hash,
                    doc.text,
                    doc.markdown,
                    version,
                    parent_document_id,
                    now,
                    now,
                    now,
                    json.dumps(doc.metadata),
                ),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return KnowledgeDocument(
            id=doc_id,
            url=doc.url,
            canonical_url=canonical_url,
            title=doc.title,
            source_type=doc.source_type,
            competitor=doc.competitor,
            dimension=doc.dimension,
            content_hash=content_hash,
            text=doc.text,
            markdown=doc.markdown,
            status="active",
            is_active=True,
            version=version,
            parent_document_id=parent_document_id,
            metadata=doc.metadata,
            fetched_at=datetime.fromisoformat(now),
            indexed_at=datetime.fromisoformat(now),
            last_seen_at=datetime.fromisoformat(now),
        )

    async def get_document(self, doc_id: str) -> KnowledgeDocument | None:
        db = self._connection
        async with db.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return self._row_to_document(row)

    async def list_documents(
        self,
        *,
        competitor: str | None = None,
        dimension: str | None = None,
        source_type: str | None = None,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeDocument]:
        db = self._connection
        clauses: list[str] = ["status = ?"]
        params: list[Any] = [status]
        if competitor:
            clauses.append("competitor = ?")
            params.append(competitor)
        if dimension:
            clauses.append("dimension = ?")
            params.append(dimension)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        where = " AND ".join(clauses)
        params.extend([limit, offset])
        async with db.execute(
            f"SELECT * FROM documents WHERE {where} ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_document(r) for r in rows]

    async def count_documents(
        self,
        *,
        competitor: str | None = None,
        dimension: str | None = None,
        source_type: str | None = None,
        status: str = "active",
    ) -> int:
        db = self._connection
        clauses: list[str] = ["status = ?"]
        params: list[Any] = [status]
        if competitor:
            clauses.append("competitor = ?")
            params.append(competitor)
        if dimension:
            clauses.append("dimension = ?")
            params.append(dimension)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        where = " AND ".join(clauses)
        async with db.execute(
            f"SELECT COUNT(*) AS total FROM documents WHERE {where}", params
        ) as cur:
            row = await cur.fetchone()
            return int(row["total"]) if row else 0

    async def delete_document(self, doc_id: str) -> bool:
        db = self._connection
        async with db.execute("SELECT 1 FROM documents WHERE id = ?", (doc_id,)) as cur:
            exists = await cur.fetchone()
        if not exists:
            return False
        await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await db.commit()
        return True

    async def soft_delete(self, document_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        db = self._connection
        cursor = await db.execute(
            """
            UPDATE documents
            SET is_active = 0, status = 'deleted', indexed_at = ?
            WHERE id = ?
            """,
            (now, document_id),
        )
        await db.commit()
        return cursor.rowcount > 0

    async def archive_old_documents(self, before_timestamp: str | datetime) -> int:
        before = (
            before_timestamp.isoformat()
            if isinstance(before_timestamp, datetime)
            else before_timestamp
        )
        now = datetime.now(UTC).isoformat()
        db = self._connection
        cursor = await db.execute(
            """
            UPDATE documents
            SET is_active = 0, status = 'archived', indexed_at = ?
            WHERE fetched_at < ? AND is_active = 1
            """,
            (now, before),
        )
        await db.commit()
        return cursor.rowcount

    async def mark_stale_documents(self, before_days: int = 30) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max(0, before_days))).isoformat()
        now = datetime.now(UTC).isoformat()
        db = self._connection
        cursor = await db.execute(
            """
            UPDATE documents
            SET status = 'stale', indexed_at = ?
            WHERE is_active = 1
              AND status = 'active'
              AND COALESCE(last_seen_at, fetched_at) < ?
            """,
            (now, cutoff),
        )
        await db.commit()
        return cursor.rowcount

    def get_document_weight(self, document: KnowledgeDocument | dict[str, Any]) -> float:
        status = (
            document.status
            if isinstance(document, KnowledgeDocument)
            else str(document.get("status", "active"))
        )
        return 0.5 if status == "stale" else 1.0

    async def search_documents(self, query: str, limit: int = 20) -> list[KnowledgeDocument]:
        """Full-text keyword search via SQLite FTS5."""
        db = self._connection
        match_query = self._to_fts_query(query)
        if not match_query:
            return []
        async with db.execute(
            """
            SELECT d.*
            FROM documents_fts
            JOIN documents d ON d.rowid = documents_fts.rowid
            WHERE documents_fts MATCH ?
              AND d.status IN ('active', 'stale')
              AND d.is_active = 1
            ORDER BY bm25(documents_fts)
            LIMIT ?
            """,
            (match_query, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_document(r) for r in rows]

    async def get_document_by_content_hash(self, content_hash: str) -> KnowledgeDocument | None:
        db = self._connection
        async with db.execute(
            """
            SELECT * FROM documents
            WHERE content_hash = ? AND status = 'active' AND is_active = 1
            LIMIT 1
            """,
            (content_hash,),
        ) as cur:
            row = await cur.fetchone()
            return self._row_to_document(row) if row else None

    async def get_document_versions(self, document_id: str) -> list[KnowledgeDocument]:
        db = self._connection
        async with db.execute(
            "SELECT id, parent_document_id FROM documents WHERE id = ?", (document_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return []
        root_id = row["parent_document_id"] or row["id"]
        async with db.execute(
            """
            SELECT * FROM documents
            WHERE id = ? OR parent_document_id = ?
            ORDER BY version ASC, fetched_at ASC
            """,
            (root_id, root_id),
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_document(r) for r in rows]

    async def merge_document_version(
        self,
        document_id: str,
        target_document_id: str,
    ) -> KnowledgeDocument | None:
        versions = await self.get_document_versions(document_id)
        if not versions or target_document_id not in {doc.id for doc in versions}:
            return None

        now = datetime.now(UTC).isoformat()
        db = self._connection
        root_id = next((doc.parent_document_id or doc.id for doc in versions), document_id)
        await db.execute("BEGIN")
        try:
            await db.execute(
                """
                UPDATE documents
                SET is_active = 0, status = 'archived', indexed_at = ?
                WHERE id = ? OR parent_document_id = ?
                """,
                (now, root_id, root_id),
            )
            await db.execute(
                """
                UPDATE documents
                SET is_active = 1, status = 'active', indexed_at = ?
                WHERE id = ?
                """,
                (now, target_document_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return await self.get_document(target_document_id)

    # -- Chunks -------------------------------------------------------------

    async def insert_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        db = self._connection
        await db.executemany(
            """
            INSERT OR REPLACE INTO chunks
                (id, document_id, chunk_index, text, token_count, embedding_model,
                 content_hash, crawl_run_id, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (c.id, c.document_id, c.chunk_index, c.text, c.token_count,
                 c.embedding_model, c.content_hash, c.crawl_run_id, json.dumps(c.metadata))
                for c in chunks
            ],
        )
        await db.commit()

    async def get_chunks_for_document(self, doc_id: str) -> list[KnowledgeChunk]:
        db = self._connection
        async with db.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index", (doc_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_chunk(r) for r in rows]

    async def get_chunks_for_documents(self, doc_ids: list[str]) -> dict[str, list[KnowledgeChunk]]:
        if not doc_ids:
            return {}
        db = self._connection
        placeholders = ", ".join("?" for _ in doc_ids)
        chunks_by_doc: dict[str, list[KnowledgeChunk]] = {doc_id: [] for doc_id in doc_ids}
        async with db.execute(
            f"""
            SELECT * FROM chunks
            WHERE document_id IN ({placeholders})
            ORDER BY document_id, chunk_index
            """,
            doc_ids,
        ) as cur:
            rows = await cur.fetchall()
            for row in rows:
                chunk = self._row_to_chunk(row)
                chunks_by_doc.setdefault(chunk.document_id, []).append(chunk)
        return chunks_by_doc

    async def count_chunks_per_document(self) -> dict[str, int]:
        db = self._connection
        async with db.execute(
            """
            SELECT document_id, COUNT(*) AS chunk_count
            FROM chunks
            GROUP BY document_id
            """
        ) as cur:
            rows = await cur.fetchall()
            return {row["document_id"]: int(row["chunk_count"]) for row in rows}

    # -- Crawl Jobs ---------------------------------------------------------

    async def create_crawl_job(
        self, url: str, *, run_id: str | None = None,
        competitor: str | None = None, dimension: str | None = None,
    ) -> str:
        now = datetime.now(UTC).isoformat()
        job_id = str(uuid.uuid4())
        db = self._connection
        await db.execute(
            "INSERT INTO crawl_jobs"
            " (id, run_id, url, competitor, dimension, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (job_id, run_id, url, competitor, dimension, now, now),
        )
        await db.commit()
        return job_id

    async def update_crawl_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        result_metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        db = self._connection
        if result_metadata is None:
            await db.execute(
                "UPDATE crawl_jobs SET status = ?, error = ?, updated_at = ?,"
                " attempt_count = attempt_count + 1 WHERE id = ?",
                (status, error, now, job_id),
            )
        else:
            await db.execute(
                "UPDATE crawl_jobs SET status = ?, error = ?, result_metadata_json = ?,"
                " updated_at = ?, attempt_count = attempt_count + 1 WHERE id = ?",
                (status, error, json.dumps(result_metadata), now, job_id),
            )
        await db.commit()

    async def get_crawl_job(self, job_id: str) -> aiosqlite.Row | None:
        db = self._connection
        async with db.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)) as cur:
            return await cur.fetchone()

    async def list_crawl_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[aiosqlite.Row]:
        db = self._connection
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        async with db.execute(
            f"SELECT * FROM crawl_jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            return await cur.fetchall()

    async def count_crawl_jobs(self, *, status: str | None = None) -> int:
        db = self._connection
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with db.execute(f"SELECT COUNT(*) AS total FROM crawl_jobs {where}", params) as cur:
            row = await cur.fetchone()
            return int(row["total"]) if row else 0

    async def list_crawl_runs(self) -> list[dict[str, Any]]:
        db = self._connection
        async with db.execute(
            """
            WITH run_ids AS (
                SELECT crawl_run_id AS id FROM chunks WHERE crawl_run_id IS NOT NULL
                UNION
                SELECT run_id AS id FROM crawl_jobs WHERE run_id IS NOT NULL
            )
            SELECT
                run_ids.id AS crawl_run_id,
                COUNT(DISTINCT chunks.document_id) AS doc_count,
                COUNT(chunks.id) AS chunk_count,
                MIN(crawl_jobs.created_at) AS first_seen_at,
                MAX(crawl_jobs.updated_at) AS last_seen_at
            FROM run_ids
            LEFT JOIN chunks ON chunks.crawl_run_id = run_ids.id
            LEFT JOIN crawl_jobs ON crawl_jobs.run_id = run_ids.id
            GROUP BY run_ids.id
            ORDER BY COALESCE(last_seen_at, first_seen_at, run_ids.id) DESC
            """
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "crawl_run_id": row["crawl_run_id"],
                "doc_count": int(row["doc_count"]),
                "chunk_count": int(row["chunk_count"]),
                "first_seen_at": (
                    datetime.fromisoformat(row["first_seen_at"])
                    if row["first_seen_at"]
                    else None
                ),
                "last_seen_at": (
                    datetime.fromisoformat(row["last_seen_at"])
                    if row["last_seen_at"]
                    else None
                ),
            }
            for row in rows
        ]

    # -- Ingest Jobs --------------------------------------------------------

    async def create_ingest_job(
        self,
        job_id: str,
        *,
        total_items: int,
        accepted_items: int,
        rejected_items: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        db = self._connection
        await db.execute(
            """
            INSERT INTO ingest_jobs
                (id, status, total_items, accepted_items, completed_items,
                 failed_items, rejected_items_json, failed_items_json,
                 result_items_json, options_json, created_at, updated_at)
            VALUES (?, 'pending', ?, ?, 0, 0, ?, '[]', '[]', ?, ?, ?)
            """,
            (
                job_id,
                total_items,
                accepted_items,
                json.dumps(rejected_items),
                json.dumps(options),
                now,
                now,
            ),
        )
        await db.commit()

    async def update_ingest_job_status(self, job_id: str, status: str) -> None:
        now = datetime.now(UTC).isoformat()
        db = self._connection
        await db.execute(
            "UPDATE ingest_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, job_id),
        )
        await db.commit()

    async def record_ingest_job_success(
        self,
        job_id: str,
        *,
        index: int,
        document_id: str,
    ) -> None:
        row = await self.get_ingest_job(job_id)
        if row is None:
            return
        results = json.loads(row["result_items_json"])
        results.append({"index": index, "document_id": document_id})
        await self._update_ingest_job_payload(
            job_id,
            completed_delta=1,
            failed_delta=0,
            result_items=results,
            failed_items=json.loads(row["failed_items_json"]),
        )

    async def record_ingest_job_failure(
        self,
        job_id: str,
        *,
        index: int,
        reason: str,
    ) -> None:
        row = await self.get_ingest_job(job_id)
        if row is None:
            return
        failed = json.loads(row["failed_items_json"])
        failed.append({"index": index, "reason": reason})
        await self._update_ingest_job_payload(
            job_id,
            completed_delta=1,
            failed_delta=1,
            result_items=json.loads(row["result_items_json"]),
            failed_items=failed,
        )

    async def get_ingest_job(self, job_id: str) -> aiosqlite.Row | None:
        db = self._connection
        async with db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)) as cur:
            return await cur.fetchone()

    async def list_ingest_jobs(self, *, limit: int = 50, offset: int = 0) -> list[aiosqlite.Row]:
        db = self._connection
        async with db.execute(
            "SELECT * FROM ingest_jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            return await cur.fetchall()

    async def _update_ingest_job_payload(
        self,
        job_id: str,
        *,
        completed_delta: int,
        failed_delta: int,
        result_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        db = self._connection
        await db.execute(
            """
            UPDATE ingest_jobs
            SET completed_items = completed_items + ?,
                failed_items = failed_items + ?,
                result_items_json = ?,
                failed_items_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                completed_delta,
                failed_delta,
                json.dumps(result_items),
                json.dumps(failed_items),
                now,
                job_id,
            ),
        )
        await db.commit()

    # -- Evaluation --------------------------------------------------------

    async def record_eval_run(
        self,
        *,
        run_id: str,
        top_k: int,
        metrics: dict[str, Any],
        labels: list[dict[str, Any]],
        results: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        await self._connection.execute(
            """
            INSERT INTO eval_runs
                (id, created_at, top_k, metrics_json, labels_json, results_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                now,
                top_k,
                json.dumps(metrics),
                json.dumps(labels),
                json.dumps(results),
            ),
        )
        await self._connection.commit()

    async def list_eval_runs(self, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        async with self._connection.execute(
            """
            SELECT id, created_at, top_k, metrics_json
            FROM eval_runs
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "id": row["id"],
                "created_at": datetime.fromisoformat(row["created_at"]),
                "top_k": int(row["top_k"]),
                "metrics": json.loads(row["metrics_json"]),
            }
            for row in rows
        ]

    async def get_eval_run(self, run_id: str) -> dict[str, Any] | None:
        async with self._connection.execute(
            "SELECT * FROM eval_runs WHERE id = ?",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "created_at": datetime.fromisoformat(row["created_at"]),
            "top_k": int(row["top_k"]),
            "metrics": json.loads(row["metrics_json"]),
            "labels": json.loads(row["labels_json"]),
            "results": json.loads(row["results_json"]),
        }

    async def record_retrieval_trace(self, record: Any) -> str:
        trace_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        payload = (
            record.model_dump(mode="json")
            if hasattr(record, "model_dump")
            else dict(record)
        )
        await self._connection.execute(
            """
            INSERT INTO retrieval_traces
                (id, created_at, query, preset_used, dense_hits, sparse_hits,
                 reranked_hits, latency_ms, cache_hit, crawl_run_id, competitor,
                 dimension, source_type, retrieval_preset, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                now,
                payload.get("query", ""),
                payload.get("preset_used"),
                int(payload.get("dense_hits", 0)),
                int(payload.get("sparse_hits", 0)),
                int(payload.get("reranked_hits", 0)),
                float(payload.get("latency_ms", 0.0)),
                1 if payload.get("cache_hit") else 0,
                payload.get("crawl_run_id"),
                payload.get("competitor"),
                payload.get("dimension"),
                payload.get("source_type"),
                payload.get("retrieval_preset"),
                json.dumps(payload.get("metadata", {})),
            ),
        )
        await self._connection.commit()
        return trace_id

    # -- Stats -------------------------------------------------------------

    async def knowledge_stats(self) -> dict[str, Any]:
        db = self._connection
        async with db.execute(
            """
            SELECT COUNT(*) AS total
            FROM documents
            WHERE status = 'active' AND is_active = 1
            """
        ) as cur:
            row = await cur.fetchone()
            doc_count = int(row["total"]) if row else 0

        async with db.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(AVG(LENGTH(c.text)), 0) AS avg_len
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'active' AND d.is_active = 1
            """
        ) as cur:
            row = await cur.fetchone()
            chunk_count = int(row["total"]) if row else 0
            average_chunk_length = float(row["avg_len"]) if row else 0.0

        async with db.execute(
            """
            SELECT source_type, COUNT(*) AS total
            FROM documents
            WHERE status = 'active' AND is_active = 1
            GROUP BY source_type
            ORDER BY source_type
            """
        ) as cur:
            rows = await cur.fetchall()
            source_breakdown = {row["source_type"]: int(row["total"]) for row in rows}

        since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        async with db.execute(
            """
            SELECT COUNT(*) AS total
            FROM documents
            WHERE status = 'active' AND is_active = 1 AND fetched_at >= ?
            """,
            (since,),
        ) as cur:
            row = await cur.fetchone()
            last_24h_ingest_count = int(row["total"]) if row else 0

        fts_size = 0
        for table_name in ("documents_fts", "chunks_fts"):
            async with db.execute(f"SELECT COUNT(*) AS total FROM {table_name}") as cur:
                row = await cur.fetchone()
                fts_size += int(row["total"]) if row else 0

        return {
            "doc_count": doc_count,
            "chunk_count": chunk_count,
            "average_chunk_length": average_chunk_length,
            "source_breakdown": source_breakdown,
            "last_24h_ingest_count": last_24h_ingest_count,
            "fts_size": fts_size,
        }

    # -- Helpers ------------------------------------------------------------

    async def _apply_pragmas(self) -> None:
        db = self._connection
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute("PRAGMA temp_store = MEMORY")
        await db.execute("PRAGMA cache_size = -20000")
        await db.execute("PRAGMA foreign_keys = ON")

    async def _ensure_migration_table(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_version (
                id INTEGER PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL,
                description TEXT NOT NULL
            )
            """
        )

    async def _migrate_schema(self) -> None:
        migrations: list[Migration] = [
            (1, "add embedding_model to chunks", self._migration_001_chunks_embedding_model),
            (
                2,
                "add document activity and version columns",
                self._migration_002_documents_versioning,
            ),
            (3, "add crawl result metadata", self._migration_003_crawl_result_metadata),
            (4, "add ingest jobs table", self._migration_004_ingest_jobs),
            (5, "add eval runs table", self._migration_005_eval_runs),
            (6, "add document last seen timestamp", self._migration_006_documents_last_seen),
            (7, "add chunk crawl run id", self._migration_007_chunks_crawl_run_id),
            (8, "add retrieval traces table", self._migration_008_retrieval_traces),
        ]
        db = self._connection
        async with db.execute("SELECT id FROM _schema_version") as cur:
            applied = {int(row["id"]) for row in await cur.fetchall()}
        for migration_id, description, migrate in migrations:
            if migration_id in applied:
                continue
            await migrate()
            await db.execute(
                """
                INSERT OR IGNORE INTO _schema_version (id, applied_at, description)
                VALUES (?, ?, ?)
                """,
                (migration_id, datetime.now(UTC).isoformat(), description),
            )
        await db.commit()

    async def _migration_001_chunks_embedding_model(self) -> None:
        await self._add_column_if_missing(
            "chunks",
            "embedding_model",
            "TEXT NOT NULL DEFAULT ''",
        )

    async def _migration_002_documents_versioning(self) -> None:
        await self._add_column_if_missing(
            "documents",
            "is_active",
            "INTEGER NOT NULL DEFAULT 1",
        )
        await self._add_column_if_missing(
            "documents",
            "version",
            "INTEGER NOT NULL DEFAULT 1",
        )
        await self._add_column_if_missing(
            "documents",
            "parent_document_id",
            "TEXT REFERENCES documents(id)",
        )
        await self._connection.execute(
            """
            UPDATE documents
            SET canonical_url = url
            WHERE canonical_url IS NULL AND url IS NOT NULL
            """
        )

    async def _migration_003_crawl_result_metadata(self) -> None:
        await self._add_column_if_missing(
            "crawl_jobs",
            "result_metadata_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )

    async def _migration_004_ingest_jobs(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                id                  TEXT PRIMARY KEY,
                status              TEXT NOT NULL DEFAULT 'pending',
                total_items         INTEGER NOT NULL DEFAULT 0,
                accepted_items      INTEGER NOT NULL DEFAULT 0,
                completed_items     INTEGER NOT NULL DEFAULT 0,
                failed_items        INTEGER NOT NULL DEFAULT 0,
                rejected_items_json TEXT NOT NULL DEFAULT '[]',
                failed_items_json   TEXT NOT NULL DEFAULT '[]',
                result_items_json   TEXT NOT NULL DEFAULT '[]',
                options_json        TEXT NOT NULL DEFAULT '{}',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
            """
        )

    async def _migration_005_eval_runs(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_runs (
                id            TEXT PRIMARY KEY,
                created_at    TEXT NOT NULL,
                top_k         INTEGER NOT NULL,
                metrics_json  TEXT NOT NULL,
                labels_json   TEXT NOT NULL,
                results_json  TEXT NOT NULL
            )
            """
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_eval_runs_created_at ON eval_runs(created_at)"
        )

    async def _migration_006_documents_last_seen(self) -> None:
        await self._add_column_if_missing(
            "documents",
            "last_seen_at",
            "TEXT DEFAULT NULL",
        )
        await self._connection.execute(
            """
            UPDATE documents
            SET last_seen_at = fetched_at
            WHERE last_seen_at IS NULL
            """
        )

    async def _migration_007_chunks_crawl_run_id(self) -> None:
        await self._add_column_if_missing(
            "chunks",
            "crawl_run_id",
            "TEXT DEFAULT NULL",
        )

    async def _migration_008_retrieval_traces(self) -> None:
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS retrieval_traces (
                id               TEXT PRIMARY KEY,
                created_at       TEXT NOT NULL,
                query            TEXT NOT NULL,
                preset_used      TEXT,
                dense_hits       INTEGER NOT NULL DEFAULT 0,
                sparse_hits      INTEGER NOT NULL DEFAULT 0,
                reranked_hits    INTEGER NOT NULL DEFAULT 0,
                latency_ms       REAL NOT NULL DEFAULT 0,
                cache_hit        INTEGER NOT NULL DEFAULT 0,
                crawl_run_id     TEXT,
                competitor       TEXT,
                dimension        TEXT,
                source_type      TEXT,
                retrieval_preset TEXT,
                metadata_json    TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_retrieval_traces_created_at "
            "ON retrieval_traces(created_at)"
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_retrieval_traces_preset "
            "ON retrieval_traces(preset_used)"
        )

    async def _add_column_if_missing(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        async with self._connection.execute(f"PRAGMA table_info({table})") as cur:
            columns = {row["name"] for row in await cur.fetchall()}
        if column not in columns:
            await self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    async def _deduplicate_active_documents(self) -> None:
        await self._deduplicate_active_documents_by("canonical_url")
        await self._deduplicate_active_documents_by("content_hash")

    async def _deduplicate_active_documents_by(self, column: str) -> None:
        db = self._connection
        async with db.execute(
            f"""
            SELECT {column} AS value
            FROM documents
            WHERE is_active = 1 AND {column} IS NOT NULL
            GROUP BY {column}
            HAVING COUNT(*) > 1
            """
        ) as cur:
            duplicate_values = [row["value"] for row in await cur.fetchall()]
        for value in duplicate_values:
            async with db.execute(
                f"""
                SELECT id
                FROM documents
                WHERE is_active = 1 AND {column} = ?
                ORDER BY fetched_at DESC, rowid DESC
                """,
                (value,),
            ) as cur:
                rows = await cur.fetchall()
            for row in rows[1:]:
                await db.execute(
                    "UPDATE documents SET is_active = 0, status = 'archived' WHERE id = ?",
                    (row["id"],),
                )

    @staticmethod
    def _row_to_document(row: aiosqlite.Row) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=row["id"],
            url=row["url"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            source_type=row["source_type"],
            competitor=row["competitor"],
            dimension=row["dimension"],
            content_hash=row["content_hash"],
            text=row["text"],
            markdown=row["markdown"],
            status=row["status"],
            is_active=bool(row["is_active"]),
            version=row["version"],
            parent_document_id=row["parent_document_id"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            indexed_at=datetime.fromisoformat(row["indexed_at"]) if row["indexed_at"] else None,
            last_seen_at=(
                datetime.fromisoformat(row["last_seen_at"]) if row["last_seen_at"] else None
            ),
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _row_to_chunk(row: aiosqlite.Row) -> KnowledgeChunk:
        return KnowledgeChunk(
            id=row["id"],
            document_id=row["document_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            embedding_model=row["embedding_model"],
            content_hash=row["content_hash"],
            crawl_run_id=row["crawl_run_id"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _to_fts_query(query: str) -> str:
        terms = re.findall(r"[\w-]+", query)
        return " ".join(f'"{term}"' for term in terms)
