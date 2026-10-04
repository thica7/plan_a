"""SQLite-backed repository for Knowledge Base metadata."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite

from packages.sqlite_locks import (
    apply_sqlite_pragmas,
    begin_immediate_transaction,
    commit_sqlite_transaction,
    write_lock_for,
)

from .lexical import build_lexical_plan
from .models import (
    DocumentCreate,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeNamespace,
    KnowledgeRollbackResult,
    KnowledgeScope,
    RetrievalHit,
)
from .tokenization import fts_tokens, lexical_tokens

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

CREATE TABLE IF NOT EXISTS evidence_sync_state (
    workspace_id   TEXT NOT NULL,
    project_id     TEXT NOT NULL,
    document_id    TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    evidence_id    TEXT NOT NULL,
    synced_at      TEXT NOT NULL,
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (workspace_id, project_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_sync_state_project_hash
ON evidence_sync_state(workspace_id, project_id, content_hash);

CREATE TABLE IF NOT EXISTS evidence_sync_metrics (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT NOT NULL,
    duration_ms     REAL NOT NULL DEFAULT 0,
    loaded_count    INTEGER NOT NULL DEFAULT 0,
    ingested_count  INTEGER NOT NULL DEFAULT 0,
    skipped_count   INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    indexed_count   INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    request_json    TEXT NOT NULL DEFAULT '{}',
    error           TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_evidence_sync_metrics_project
ON evidence_sync_metrics(workspace_id, project_id, completed_at);
"""

_DOCUMENT_NAMESPACE_SQL = """CASE WHEN workspace_id IS NULL
    THEN json_array(NULL, NULL, NULL, NULL, NULL, NULL)
    ELSE json_array(workspace_id, project_id, competitor, dimension, market, source_role) END"""

_POST_MIGRATION_SCHEMA = f"""
CREATE INDEX IF NOT EXISTS idx_documents_parent_document_id ON documents(parent_document_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_namespace_active_canonical_url
ON documents(({_DOCUMENT_NAMESPACE_SQL}), canonical_url)
WHERE is_active = 1 AND canonical_url IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_namespace_active_content_hash
ON documents(({_DOCUMENT_NAMESPACE_SQL}), content_hash)
WHERE is_active = 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_chunks_document_chunk_index
ON chunks(document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_chunks_crawl_run_document
ON chunks(crawl_run_id, document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    text
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, text)
    VALUES (new.rowid, kb_tokens(new.title), kb_tokens(new.text));
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    DELETE FROM documents_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    DELETE FROM documents_fts WHERE rowid = old.rowid;
    INSERT INTO documents_fts(rowid, title, text)
    VALUES (new.rowid, kb_tokens(new.title), kb_tokens(new.text));
END;

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, kb_tokens(new.text));
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, kb_tokens(new.text));
END;
"""

Migration = tuple[int, str, Callable[["KnowledgeRepository"], Awaitable[None]]]


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class CrawlSourceUnavailableError(ValueError):
    """A durable crawl source no longer authorizes publication in this scope."""


class KnowledgeRepository:
    """Async SQLite repository for knowledge base metadata."""

    def __init__(self, db_path: str | None = None, *, lexical_fallback: bool = True) -> None:
        self._db_path = db_path or os.getenv("KB_DB_PATH", "runs/knowledge.db")
        self._lexical_fallback = lexical_fallback
        self._db: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> str:
        return self._db_path

    async def initialise(self) -> None:
        if self._db is not None:
            return

        self._db = await aiosqlite.connect(
            self._db_path,
            isolation_level=None,
            uri=self._db_path.startswith("file:"),
        )
        self._db.row_factory = aiosqlite.Row
        await self._db.create_function("kb_tokens", 1, fts_tokens, deterministic=True)
        await self._db.create_function(
            "kb_casefold", 1, lambda value: value.casefold() if value is not None else None,
            deterministic=True,
        )
        try:
            async with write_lock_for(self._db_path):
                await self._apply_pragmas()
                await self._db.executescript(_BASE_SCHEMA)
                await self._ensure_migration_table()
                await self._migrate_schema()
                # Older processes can recreate global constraints after the scope migration.
                await self._db.execute("DROP INDEX IF EXISTS ux_documents_active_canonical_url")
                await self._db.execute("DROP INDEX IF EXISTS ux_documents_active_content_hash")
                await self._deduplicate_active_documents()
                await self._db.executescript(_POST_MIGRATION_SCHEMA)
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

    @asynccontextmanager
    async def _write_transaction(self):
        db = self._connection
        async with write_lock_for(self._db_path):
            await begin_immediate_transaction(db)
            try:
                yield db
            except Exception:
                await db.rollback()
                raise
            else:
                await commit_sqlite_transaction(db)

    # -- Documents ----------------------------------------------------------

    async def upsert_document(
        self, doc: DocumentCreate, content_hash: str, *, crawl_source_id: str | None = None,
    ) -> KnowledgeDocument:
        now = datetime.now(UTC).isoformat()
        fetched = doc.fetched_at or datetime.fromisoformat(now)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        fetched_at = fetched.astimezone(UTC).isoformat()
        doc_id = str(uuid.uuid4())
        canonical_url = doc.canonical_url or doc.url
        version = 1
        parent_document_id: str | None = None
        namespace_where, namespace_params = self._namespace_filter(doc.namespace)

        async with self._write_transaction() as db:
            if crawl_source_id is not None:
                # Shares the source-deletion SQLite write lock; check before any dedup or writes.
                async with db.execute(
                    "SELECT 1 FROM crawl_source WHERE id = ? AND workspace_id = ? "
                    "AND project_id IS ? AND trim(workspace_id) != ''",
                    (crawl_source_id, doc.workspace_id, doc.project_id),
                ) as cur:
                    if await cur.fetchone() is None:
                        raise CrawlSourceUnavailableError(
                            "Crawl source is unavailable in this scope"
                        )
            # Recheck inside the transaction so concurrent ingests share a single identity.
            async with db.execute(
                f"""SELECT * FROM documents
                    WHERE content_hash = ? AND is_active = 1 AND {namespace_where}
                    LIMIT 1""",
                [content_hash, *namespace_params],
            ) as cur:
                duplicate = await cur.fetchone()
            if duplicate is not None:
                stored = self._row_to_document(duplicate)
                if (
                    doc.metadata.get("source_material_level") == "full_source"
                    and stored.metadata.get("source_material_level") != "full_source"
                ):
                    stored.metadata["source_material_level"] = "full_source"
                    await db.execute(
                        "UPDATE documents SET metadata_json = ? WHERE id = ?",
                        (json.dumps(stored.metadata), stored.id),
                    )
                return stored

            if canonical_url:
                async with db.execute(
                    f"""SELECT * FROM documents
                        WHERE canonical_url = ? AND is_active = 1 AND {namespace_where}
                        ORDER BY version DESC, fetched_at DESC LIMIT 1""",
                    [canonical_url, *namespace_params],
                ) as cur:
                    previous = await cur.fetchone()
                if previous is not None:
                    if (
                        doc.metadata.get("source_material_level") == "summary"
                        and json.loads(previous["metadata_json"]).get("source_material_level")
                        == "full_source"
                    ):
                        return self._row_to_document(previous)
                    version = int(previous["version"]) + 1
                    parent_document_id = previous["parent_document_id"] or previous["id"]
                    await db.execute(
                        """UPDATE documents SET is_active = 0, status = 'archived', indexed_at = ?
                           WHERE id = ?""",
                        (now, previous["id"]),
                    )

            await db.execute(
                """INSERT INTO documents
                    (id, url, canonical_url, title, source_type, competitor, dimension,
                     content_hash, text, markdown, status, is_active, version,
                     parent_document_id, fetched_at, indexed_at, last_seen_at, metadata_json,
                     workspace_id, project_id, market, source_role, source_published_at,
                     source_updated_at, last_verified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, doc.url, canonical_url, doc.title, doc.source_type, doc.competitor,
                 doc.dimension, content_hash, doc.text, doc.markdown, version,
                 parent_document_id, fetched_at, None, now, json.dumps(doc.metadata),
                 doc.workspace_id, doc.project_id, doc.market, doc.source_role,
                 doc.source_published_at.isoformat() if doc.source_published_at else None,
                 doc.source_updated_at.isoformat() if doc.source_updated_at else None,
                 doc.last_verified_at.isoformat() if doc.last_verified_at else None),
            )
            async with db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)) as cur:
                row = await cur.fetchone()
        return self._row_to_document(row)

    async def get_document(
        self, doc_id: str, *, scope: KnowledgeScope | None = None,
    ) -> KnowledgeDocument | None:
        clauses, params = ["id = ?"], [doc_id]
        self._add_scope_filters(clauses, params, scope=scope)
        async with self._connection.execute(
            f"SELECT * FROM documents WHERE {' AND '.join(clauses)}", params
        ) as cur:
            row = await cur.fetchone()
            return self._row_to_document(row) if row else None

    async def has_active_full_source_for_url(
        self,
        url: str,
        *,
        scope: KnowledgeScope,
        competitor: str,
        dimension: str,
        market: str | None,
    ) -> bool:
        """Check material without loading bodies, within the exact write namespace."""
        async with self._connection.execute(
            """SELECT 1 FROM documents
                WHERE workspace_id = ? AND project_id IS ?
                  AND competitor = ? AND dimension = ? AND market IS ?
                  AND source_role = 'source' AND status = 'active' AND is_active = 1
                  AND rtrim(COALESCE(canonical_url, url, ''), '/') = rtrim(?, '/')
                  AND json_extract(metadata_json, '$.source_material_level') = 'full_source'
                LIMIT 1""",
            [scope.workspace_id, scope.project_id, competitor, dimension, market, url],
        ) as cursor:
            return await cursor.fetchone() is not None

    async def set_indexing_state(
        self, document_id: str, status: str, *, error: str | None = None,
        embedding_model: str | None = None, dimensions: int | None = None,
        index_version: str | None = None,
    ) -> None:
        if status not in {"pending", "ready", "failed"}:
            raise ValueError(f"Invalid indexing state: {status}")
        async with self._write_transaction() as db:
            await db.execute(
                """UPDATE documents SET indexing_status = ?, indexing_error = ?,
                    embedding_model = ?, embedding_dimensions = ?, index_version = ?,
                    indexed_at = ? WHERE id = ?""",
                (status, error, embedding_model, dimensions, index_version,
                 datetime.now(UTC).isoformat() if status == "ready" else None, document_id),
            )
            if status == "ready":
                await db.execute(
                    "UPDATE chunks SET embedding_model = ? WHERE document_id = ?",
                    (embedding_model or "", document_id),
                )

    async def list_documents(
        self,
        *,
        scope: KnowledgeScope | None = None,
        market: str | None = None,
        source_roles: list[str] | None = None,
        max_age_days: int | None = None,
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
        self._add_scope_filters(clauses, params, scope=scope, market=market,
                                source_roles=source_roles, max_age_days=max_age_days)
        where = " AND ".join(clauses)
        params.extend([limit, offset])
        async with db.execute(
            f"SELECT * FROM documents WHERE {where} ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_document(r) for r in rows]

    async def list_documents_for_evidence_sync(
        self,
        *,
        scope: KnowledgeScope | None = None,
        market: str | None = None,
        source_roles: list[str] | None = None,
        max_age_days: int | None = None,
        crawl_run_id: str | None = None,
        competitors: list[str] | None = None,
        dimensions: list[str] | None = None,
        source_types: list[str] | None = None,
        statuses: list[str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[KnowledgeDocument]:
        """按同步条件分页取文档，避免在 Python 层全库扫描。"""
        db = self._connection
        active_statuses = statuses or ["active", "stale"]
        clauses: list[str] = []
        params: list[Any] = []
        if active_statuses:
            placeholders = ", ".join("?" for _ in active_statuses)
            clauses.append(f"d.status IN ({placeholders})")
            params.extend(active_statuses)
        if crawl_run_id:
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM chunks c
                    WHERE c.document_id = d.id AND c.crawl_run_id = ?
                )
                """
            )
            params.append(crawl_run_id)
        if competitors:
            placeholders = ", ".join("?" for _ in competitors)
            clauses.append(f"d.competitor IN ({placeholders})")
            params.extend(competitors)
        if dimensions:
            placeholders = ", ".join("?" for _ in dimensions)
            clauses.append(f"d.dimension IN ({placeholders})")
            params.extend(dimensions)
        if source_types:
            placeholders = ", ".join("?" for _ in source_types)
            clauses.append(f"d.source_type IN ({placeholders})")
            params.extend(source_types)
        self._add_scope_filters(clauses, params, scope=scope, market=market,
                                source_roles=source_roles, max_age_days=max_age_days, prefix="d.")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        async with db.execute(
            f"""
            SELECT d.*
            FROM documents d
            {where}
            ORDER BY COALESCE(d.last_seen_at, d.fetched_at) DESC, d.rowid DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
            return [self._row_to_document(r) for r in rows]

    async def get_evidence_sync_states(
        self,
        *,
        workspace_id: str,
        project_id: str,
        document_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not document_ids:
            return {}
        db = self._connection
        placeholders = ", ".join("?" for _ in document_ids)
        params = [workspace_id, project_id, *document_ids]
        async with db.execute(
            f"""
            SELECT *
            FROM evidence_sync_state
            WHERE workspace_id = ?
              AND project_id = ?
              AND document_id IN ({placeholders})
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        return {
            row["document_id"]: {
                "workspace_id": row["workspace_id"],
                "project_id": row["project_id"],
                "document_id": row["document_id"],
                "content_hash": row["content_hash"],
                "evidence_id": row["evidence_id"],
                "synced_at": row["synced_at"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        }

    async def record_evidence_sync_states(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
            await db.executemany(
                """
                INSERT INTO evidence_sync_state (
                    workspace_id, project_id, document_id, content_hash,
                    evidence_id, synced_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (workspace_id, project_id, document_id) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    evidence_id = excluded.evidence_id,
                    synced_at = excluded.synced_at,
                    metadata_json = excluded.metadata_json
                """,
                [
                    (
                        item["workspace_id"],
                        item["project_id"],
                        item["document_id"],
                        item["content_hash"],
                        item["evidence_id"],
                        item.get("synced_at") or now,
                        json.dumps(item.get("metadata", {})),
                    )
                    for item in records
                ],
            )

    async def record_evidence_sync_metric(
        self,
        *,
        workspace_id: str,
        project_id: str,
        status: str,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: float,
        loaded_count: int,
        ingested_count: int,
        skipped_count: int,
        chunk_count: int,
        indexed_count: int,
        duplicate_count: int,
        request: dict[str, Any],
        error: str = "",
    ) -> str:
        metric_id = str(uuid.uuid4())
        async with self._write_transaction() as db:
            await db.execute(
                """
                INSERT INTO evidence_sync_metrics (
                    id, workspace_id, project_id, status, started_at, completed_at,
                    duration_ms, loaded_count, ingested_count, skipped_count,
                    chunk_count, indexed_count, duplicate_count, request_json, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric_id,
                    workspace_id,
                    project_id,
                    status,
                    started_at.isoformat(),
                    completed_at.isoformat(),
                    duration_ms,
                    loaded_count,
                    ingested_count,
                    skipped_count,
                    chunk_count,
                    indexed_count,
                    duplicate_count,
                    json.dumps(request),
                    error,
                ),
            )
        return metric_id

    async def list_evidence_sync_metrics(
        self,
        *,
        workspace_id: str,
        project_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        db = self._connection
        async with db.execute(
            """
            SELECT *
            FROM evidence_sync_metrics
            WHERE workspace_id = ? AND project_id = ?
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (workspace_id, project_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "id": row["id"],
                "workspace_id": row["workspace_id"],
                "project_id": row["project_id"],
                "status": row["status"],
                "started_at": datetime.fromisoformat(row["started_at"]),
                "completed_at": datetime.fromisoformat(row["completed_at"]),
                "duration_ms": float(row["duration_ms"]),
                "loaded_count": int(row["loaded_count"]),
                "ingested_count": int(row["ingested_count"]),
                "skipped_count": int(row["skipped_count"]),
                "chunk_count": int(row["chunk_count"]),
                "indexed_count": int(row["indexed_count"]),
                "duplicate_count": int(row["duplicate_count"]),
                "request": json.loads(row["request_json"]),
                "error": row["error"],
            }
            for row in rows
        ]

    async def count_documents(
        self,
        *,
        scope: KnowledgeScope | None = None,
        market: str | None = None,
        source_roles: list[str] | None = None,
        max_age_days: int | None = None,
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
        self._add_scope_filters(clauses, params, scope=scope, market=market,
                                source_roles=source_roles, max_age_days=max_age_days)
        where = " AND ".join(clauses)
        async with db.execute(
            f"SELECT COUNT(*) AS total FROM documents WHERE {where}", params
        ) as cur:
            row = await cur.fetchone()
            return int(row["total"]) if row else 0

    async def delete_document(self, doc_id: str) -> bool:
        async with self._write_transaction() as db:
            async with db.execute("SELECT 1 FROM documents WHERE id = ?", (doc_id,)) as cur:
                exists = await cur.fetchone()
            if not exists:
                return False
            await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return True

    async def soft_delete(self, document_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
            cursor = await db.execute(
                """
                UPDATE documents
                SET is_active = 0, status = 'deleted', indexed_at = ?
                WHERE id = ?
                """,
                (now, document_id),
            )
        return cursor.rowcount > 0

    async def archive_old_documents(self, before_timestamp: str | datetime) -> int:
        before = (
            before_timestamp.isoformat()
            if isinstance(before_timestamp, datetime)
            else before_timestamp
        )
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
            cursor = await db.execute(
                """
                UPDATE documents
                SET is_active = 0, status = 'archived', indexed_at = ?
                WHERE fetched_at < ? AND is_active = 1
                """,
                (now, before),
            )
        return cursor.rowcount

    async def mark_stale_documents(self, before_days: int = 30) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max(0, before_days))).isoformat()
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
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
        return cursor.rowcount

    def get_document_weight(self, document: KnowledgeDocument | dict[str, Any]) -> float:
        status = (
            document.status
            if isinstance(document, KnowledgeDocument)
            else str(document.get("status", "active"))
        )
        return 0.5 if status == "stale" else 1.0

    async def search_documents(
        self,
        query: str,
        limit: int = 20,
        *,
        scope: KnowledgeScope | None = None,
        market: str | None = None,
        source_roles: list[str] | None = None,
        max_age_days: int | None = None,
        competitors: list[str] | None = None,
        dimensions: list[str] | None = None,
    ) -> list[KnowledgeDocument]:
        """Full-text keyword search via SQLite FTS5."""
        db = self._connection
        plan = build_lexical_plan(query, competitors) if self._lexical_fallback else None
        if plan is not None and plan.disabled_reason == "question_only":
            return []
        match_query = self._to_fts_query(query)
        if not match_query:
            return []
        clauses = [
            "documents_fts MATCH ?",
            "d.status IN ('active', 'stale')",
            "d.is_active = 1",
        ]
        params: list[Any] = []
        if competitors:
            placeholders = ", ".join("?" for _ in competitors)
            clauses.append(f"kb_casefold(d.competitor) IN ({placeholders})")
            params.extend(item.casefold() for item in competitors)
        if dimensions:
            placeholders = ", ".join("?" for _ in dimensions)
            clauses.append(f"kb_casefold(d.dimension) IN ({placeholders})")
            params.extend(item.casefold() for item in dimensions)
        self._add_scope_filters(clauses, params, scope=scope, market=market,
                                source_roles=source_roles, max_age_days=max_age_days, prefix="d.")
        async def fetch(match: str, count: int) -> list[KnowledgeDocument]:
            async with db.execute(
                f"""
            SELECT d.*
            FROM documents_fts
            JOIN documents d ON d.rowid = documents_fts.rowid
            WHERE {" AND ".join(clauses)}
            ORDER BY bm25(documents_fts)
            LIMIT ?
            """,
                [match, *params, count],
            ) as cur:
                return [self._row_to_document(row) for row in await cur.fetchall()]

        strict = await fetch(match_query, limit)
        if plan is None:
            return strict
        found = {doc.id for doc in strict}
        results = list(strict)
        if len(results) < limit and plan.fallback_query:
            for doc in await fetch(plan.fallback_query, limit):
                if doc.id not in found:
                    found.add(doc.id)
                    results.append(doc)
                if len(results) >= limit:
                    break
        return results

    async def search_chunks(
        self, query: str, limit: int = 20, *,
        scope: KnowledgeScope | None = None,
        market: str | None = None,
        source_roles: list[str] | None = None,
        max_age_days: int | None = None,
        competitors: list[str] | None = None,
        dimensions: list[str] | None = None,
    ) -> list[RetrievalHit]:
        """Recall matching chunks; title-only matches contribute the first chunk."""
        plan = build_lexical_plan(query, competitors) if self._lexical_fallback else None
        if plan is not None and plan.disabled_reason == "question_only":
            return []
        match_query = self._to_fts_query(query)
        if not match_query:
            return []
        filters = ["d.is_active = 1", "d.status IN ('active', 'stale')"]
        params: list[Any] = []
        for column, values in (("competitor", competitors), ("dimension", dimensions)):
            if values:
                filters.append(f"kb_casefold(d.{column}) IN ({', '.join('?' for _ in values)})")
                params.extend(item.casefold() for item in values)
        self._add_scope_filters(filters, params, scope=scope, market=market,
                                source_roles=source_roles, max_age_days=max_age_days, prefix="d.")
        where = " AND ".join(filters)
        hits: dict[str, RetrievalHit] = {}

        async def fetch(table: str, match: str, join: str, extra: str, path: str) -> None:
            async with self._connection.execute(
                f"""SELECT d.*, c.id AS hit_chunk_id, c.text AS hit_text,
                           bm25({table}) AS fts_rank
                    FROM {table}
                    JOIN chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE {join} AND {table} MATCH ? AND {where} {extra}
                    ORDER BY fts_rank, d.id, c.chunk_index LIMIT ?""",
                [match, *params, limit],
            ) as cur:
                rows = await cur.fetchall()
            for rank, row in enumerate(rows, 1):
                doc = self._row_to_document(row)
                weight = self.get_document_weight(doc)
                if plan is None:
                    score = weight / rank
                    metadata = {**doc.metadata}
                    metadata.pop("lexical_retrieval", None)
                else:
                    score = weight * (
                        (0.75 + 0.25 / rank) if path == "strict_body" else
                        (0.5 + 0.25 / rank) if path == "fallback_body" else 0.1 / rank
                    )
                    metadata = {**doc.metadata, "lexical_retrieval": {
                        "version": plan.version, "path": path, "concepts": plan.concepts,
                    }}
                hit = RetrievalHit(
                    chunk_id=row["hit_chunk_id"], document_id=doc.id, text=row["hit_text"],
                    score=score,
                    url=doc.url, title=doc.title, competitor=doc.competitor,
                    dimension=doc.dimension, source_type=doc.source_type,
                    workspace_id=doc.workspace_id, project_id=doc.project_id,
                    market=doc.market, source_role=doc.source_role,
                    source_published_at=doc.source_published_at,
                    source_updated_at=doc.source_updated_at,
                    last_verified_at=doc.last_verified_at, document_version=doc.version,
                    content_hash=doc.content_hash, fetched_at=doc.fetched_at,
                    last_seen_at=doc.last_seen_at, status=doc.status, metadata=metadata,
                )
                if hit.chunk_id not in hits or (
                    plan is not None and hit.score > hits[hit.chunk_id].score
                ):
                    hits[hit.chunk_id] = hit
        await fetch("chunks_fts", match_query, "c.rowid = chunks_fts.rowid", "", "strict_body")
        if plan is not None and len(hits) < limit and plan.fallback_query:
            await fetch("chunks_fts", plan.fallback_query, "c.rowid = chunks_fts.rowid",
                        "", "fallback_body")
        await fetch("documents_fts", f"title : ({match_query})",
                    "d.rowid = documents_fts.rowid",
                    "AND c.chunk_index = (SELECT MIN(c2.chunk_index) "
                    "FROM chunks c2 WHERE c2.document_id = d.id)", "title")
        return sorted(hits.values(), key=lambda hit: hit.score, reverse=True)[:limit]

    async def get_document_by_content_hash(
        self, content_hash: str, *, scope: KnowledgeScope | None = None,
        competitor: str | None = None, dimension: str | None = None,
        market: str | None = None, source_role: str = "source",
    ) -> KnowledgeDocument | None:
        namespace: KnowledgeNamespace = (
            (scope.workspace_id, scope.project_id, competitor, dimension, market, source_role)
            if scope is not None else (None, None, None, None, None, None)
        )
        namespace_where, params = self._namespace_filter(namespace)
        async with self._connection.execute(
            f"""SELECT * FROM documents WHERE content_hash = ?
                AND status IN ('active', 'stale') AND is_active = 1 AND {namespace_where}
                LIMIT 1""",
            [content_hash, *params],
        ) as cur:
            row = await cur.fetchone()
            return self._row_to_document(row) if row else None

    async def get_document_versions(
        self, document_id: str, *, scope: KnowledgeScope | None = None,
    ) -> list[KnowledgeDocument]:
        document = await self.get_document(document_id, scope=scope)
        if document is None:
            return []
        root_id = document.parent_document_id or document.id
        namespace_where, params = self._namespace_filter(document.namespace)
        async with self._connection.execute(
            f"""SELECT * FROM documents
                WHERE (id = ? OR parent_document_id = ?) AND {namespace_where}
                ORDER BY version ASC, fetched_at ASC""",
            [root_id, root_id, *params],
        ) as cur:
            return [self._row_to_document(row) for row in await cur.fetchall()]

    async def merge_document_version(
        self, document_id: str, target_document_id: str, *, scope: KnowledgeScope | None = None,
    ) -> KnowledgeDocument | None:
        if scope is not None:
            scope = scope.model_copy(update={"include_workspace_library": False})
        versions = await self.get_document_versions(document_id, scope=scope)
        if not versions or target_document_id not in {doc.id for doc in versions}:
            return None
        now = datetime.now(UTC).isoformat()
        root_id = versions[0].parent_document_id or versions[0].id
        namespace_where, params = self._namespace_filter(versions[0].namespace)
        async with self._write_transaction() as db:
            await db.execute(
                f"""UPDATE documents SET is_active = 0, status = 'archived', indexed_at = ?
                    WHERE (id = ? OR parent_document_id = ?) AND {namespace_where}""",
                [now, root_id, root_id, *params],
            )
            await db.execute(
                """UPDATE documents SET is_active = 1, status = 'active', indexed_at = ?
                   WHERE id = ?""",
                (now, target_document_id),
            )
        return await self.get_document(target_document_id, scope=scope)

    async def rollback_documents(
        self,
        *,
        scope: KnowledgeScope | None = None,
        document_ids: list[str] | None = None,
        run_id: str | None = None,
        raw_source_id: str | None = None,
        crawl_run_id: str | None = None,
        restore_previous: bool = True,
    ) -> KnowledgeRollbackResult:
        """Archive polluted active documents and optionally restore previous versions."""
        if scope is not None:
            scope = scope.model_copy(update={"include_workspace_library": False})
        selectors_present = any((document_ids, run_id, raw_source_id, crawl_run_id))
        if not selectors_present:
            raise ValueError("At least one rollback selector is required")

        now = datetime.now(UTC).isoformat()
        archived_ids: list[str] = []
        restored_ids: list[str] = []
        skipped_ids: list[str] = []

        async with self._write_transaction() as db:
            clauses = ["d.is_active = 1", "d.status IN ('active', 'stale')"]
            params: list[Any] = []
            self._add_scope_filters(clauses, params, scope=scope, prefix="d.")
            if document_ids:
                unique_document_ids = sorted({item for item in document_ids if item})
                placeholders = ", ".join("?" for _ in unique_document_ids)
                clauses.append(f"d.id IN ({placeholders})")
                params.extend(unique_document_ids)
            if run_id:
                clauses.append(
                    """
                    (
                        json_extract(d.metadata_json, '$.run_id') = ?
                        OR json_extract(d.metadata_json, '$.collector_run_id') = ?
                    )
                    """
                )
                params.extend([run_id, run_id])
            if raw_source_id:
                clauses.append(
                    """
                    (
                        json_extract(d.metadata_json, '$.raw_source_id') = ?
                        OR json_extract(d.metadata_json, '$.kb_raw_source_id') = ?
                    )
                    """
                )
                params.extend([raw_source_id, raw_source_id])
            if crawl_run_id:
                clauses.append(
                    """
                    EXISTS (
                        SELECT 1
                        FROM chunks c
                        WHERE c.document_id = d.id AND c.crawl_run_id = ?
                    )
                    """
                )
                params.append(crawl_run_id)

            async with db.execute(
                f"""
                SELECT d.*
                FROM documents d
                WHERE {' AND '.join(clauses)}
                ORDER BY d.version DESC, d.fetched_at DESC, d.rowid DESC
                """,
                params,
            ) as cur:
                rows = await cur.fetchall()

            archive_ids = [row["id"] for row in rows]
            if not archive_ids:
                return KnowledgeRollbackResult()

            placeholders = ", ".join("?" for _ in archive_ids)
            cursor = await db.execute(
                f"""
                UPDATE documents
                SET is_active = 0, status = 'archived', indexed_at = ?
                WHERE id IN ({placeholders})
                """,
                [now, *archive_ids],
            )
            archived_ids = archive_ids if cursor.rowcount < 0 else archive_ids[: cursor.rowcount]

            if restore_previous:
                archived_set = set(archive_ids)
                seen_identities: set[tuple[Any, ...]] = set()
                for row in rows:
                    canonical_url = row["canonical_url"]
                    if not canonical_url:
                        continue
                    namespace = self._row_to_document(row).namespace
                    identity = (canonical_url, *namespace)
                    if identity in seen_identities:
                        continue
                    seen_identities.add(identity)
                    namespace_where, namespace_params = self._namespace_filter(namespace)
                    async with db.execute(
                        f"""SELECT id FROM documents WHERE canonical_url = ?
                            AND {namespace_where} AND is_active = 1
                            AND status IN ('active', 'stale') LIMIT 1""",
                        [canonical_url, *namespace_params],
                    ) as cur:
                        active = await cur.fetchone()
                    if active is not None:
                        continue
                    exclude_placeholders = ", ".join("?" for _ in archived_set)
                    async with db.execute(
                        f"""SELECT id FROM documents WHERE canonical_url = ?
                            AND {namespace_where} AND id NOT IN ({exclude_placeholders})
                            AND status = 'archived'
                            ORDER BY version DESC, fetched_at DESC, rowid DESC LIMIT 1""",
                        [canonical_url, *namespace_params, *archived_set],
                    ) as cur:
                        previous = await cur.fetchone()
                    if previous is None:
                        skipped_ids.extend(
                            candidate["id"] for candidate in rows
                            if candidate["canonical_url"] == canonical_url
                            and self._row_to_document(candidate).namespace == namespace
                        )
                        continue
                    await db.execute(
                        """UPDATE documents SET is_active = 1, status = 'active', indexed_at = ?
                           WHERE id = ?""",
                        (now, previous["id"]),
                    )
                    restored_ids.append(previous["id"])

        return KnowledgeRollbackResult(
            matched_count=len(archive_ids),
            rolled_back_count=len(archived_ids),
            restored_count=len(restored_ids),
            archived_document_ids=archived_ids,
            restored_document_ids=restored_ids,
            skipped_document_ids=skipped_ids,
        )

    # -- Chunks -------------------------------------------------------------

    async def insert_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        async with self._write_transaction() as db:
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
        scope: KnowledgeScope | None = None, market: str | None = None,
    ) -> str:
        now = datetime.now(UTC).isoformat()
        job_id = str(uuid.uuid4())
        async with self._write_transaction() as db:
            await db.execute(
                "INSERT INTO crawl_jobs"
                " (id, run_id, url, competitor, dimension, status, created_at, updated_at, "
                "workspace_id, project_id, market)"
                " VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                (job_id, run_id, url, competitor, dimension, now, now,
                 scope.workspace_id if scope else None,
                 scope.project_id if scope else None, market),
            )
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
        async with self._write_transaction() as db:
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

    async def _get_scoped_job(
        self, table: str, job_id: str, scope: KnowledgeScope | None,
    ) -> aiosqlite.Row | None:
        clauses, params = ["id = ?"], [job_id]
        self._add_scope_filters(clauses, params, scope=scope)
        async with self._connection.execute(
            f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}", params,
        ) as cur:
            return await cur.fetchone()

    async def _list_scoped_jobs(
        self, table: str, *, scope: KnowledgeScope | None, limit: int, offset: int,
        status: str | None = None,
    ) -> list[aiosqlite.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        self._add_scope_filters(clauses, params, scope=scope)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._connection.execute(
            f"SELECT * FROM {table} {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ) as cur:
            return await cur.fetchall()

    async def _count_scoped_jobs(
        self, table: str, *, scope: KnowledgeScope | None, status: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        self._add_scope_filters(clauses, params, scope=scope)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._connection.execute(
            f"SELECT COUNT(*) AS total FROM {table} {where}", params,
        ) as cur:
            row = await cur.fetchone()
            return int(row["total"]) if row else 0

    async def get_crawl_job(
        self, job_id: str, *, scope: KnowledgeScope | None = None,
    ) -> aiosqlite.Row | None:
        return await self._get_scoped_job("crawl_jobs", job_id, scope)

    async def list_crawl_jobs(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0,
        scope: KnowledgeScope | None = None,
    ) -> list[aiosqlite.Row]:
        return await self._list_scoped_jobs("crawl_jobs", scope=scope, status=status,
                                           limit=limit, offset=offset)

    async def count_crawl_jobs(
        self, *, status: str | None = None, scope: KnowledgeScope | None = None,
    ) -> int:
        return await self._count_scoped_jobs("crawl_jobs", scope=scope, status=status)

    async def list_crawl_runs(
        self, *, scope: KnowledgeScope | None = None,
    ) -> list[dict[str, Any]]:
        doc_clauses: list[str] = []
        doc_params: list[Any] = []
        self._add_scope_filters(doc_clauses, doc_params, scope=scope, prefix="d.")
        job_clauses: list[str] = []
        job_params: list[Any] = []
        self._add_scope_filters(job_clauses, job_params, scope=scope)
        doc_where = " AND ".join(["c.crawl_run_id IS NOT NULL", *doc_clauses])
        job_where = " AND ".join(["run_id IS NOT NULL", *job_clauses])
        async with self._connection.execute(
            f"""
            WITH chunk_counts AS (
                SELECT c.crawl_run_id AS id, COUNT(DISTINCT c.document_id) AS doc_count,
                       COUNT(c.id) AS chunk_count
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE {doc_where} GROUP BY c.crawl_run_id
            ), job_times AS (
                SELECT run_id AS id, MIN(created_at) AS first_seen_at,
                       MAX(updated_at) AS last_seen_at
                FROM crawl_jobs WHERE {job_where} GROUP BY run_id
            ), run_ids AS (SELECT id FROM chunk_counts UNION SELECT id FROM job_times)
            SELECT run_ids.id AS crawl_run_id, COALESCE(c.doc_count, 0) AS doc_count,
                   COALESCE(c.chunk_count, 0) AS chunk_count, j.first_seen_at, j.last_seen_at
            FROM run_ids LEFT JOIN chunk_counts c ON c.id = run_ids.id
            LEFT JOIN job_times j ON j.id = run_ids.id
            ORDER BY COALESCE(j.last_seen_at, j.first_seen_at, run_ids.id) DESC
            """, [*doc_params, *job_params],
        ) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    # -- Ingest Jobs --------------------------------------------------------

    async def create_ingest_job(
        self,
        job_id: str,
        *,
        total_items: int,
        accepted_items: int,
        rejected_items: list[dict[str, Any]],
        options: dict[str, Any],
        scope: KnowledgeScope | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
            await db.execute(
                """
                INSERT INTO ingest_jobs
                    (id, status, total_items, accepted_items, completed_items,
                     failed_items, rejected_items_json, failed_items_json,
                     result_items_json, options_json, created_at, updated_at,
                     workspace_id, project_id)
                VALUES (?, 'pending', ?, ?, 0, 0, ?, '[]', '[]', ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    total_items,
                    accepted_items,
                    json.dumps(rejected_items),
                    json.dumps(options),
                    now,
                    now,
                    scope.workspace_id if scope else None,
                    scope.project_id if scope else None,
                ),
            )

    async def update_ingest_job_status(self, job_id: str, status: str) -> None:
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
            await db.execute(
                "UPDATE ingest_jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, job_id),
            )

    async def record_ingest_job_success(
        self,
        job_id: str,
        *,
        index: int,
        document_id: str,
    ) -> None:
        async with self._write_transaction() as db:
            row = await self._get_ingest_job_in_transaction(db, job_id)
            if row is None:
                return
            results = json.loads(row["result_items_json"])
            results.append({"index": index, "document_id": document_id})
            await self._update_ingest_job_payload_in_transaction(
                db,
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
        async with self._write_transaction() as db:
            row = await self._get_ingest_job_in_transaction(db, job_id)
            if row is None:
                return
            failed = json.loads(row["failed_items_json"])
            failed.append({"index": index, "reason": reason})
            await self._update_ingest_job_payload_in_transaction(
                db,
                job_id,
                completed_delta=1,
                failed_delta=1,
                result_items=json.loads(row["result_items_json"]),
                failed_items=failed,
            )

    async def get_ingest_job(
        self, job_id: str, *, scope: KnowledgeScope | None = None,
    ) -> aiosqlite.Row | None:
        return await self._get_scoped_job("ingest_jobs", job_id, scope)

    async def list_ingest_jobs(
        self, *, limit: int = 50, offset: int = 0, scope: KnowledgeScope | None = None,
    ) -> list[aiosqlite.Row]:
        return await self._list_scoped_jobs("ingest_jobs", scope=scope, limit=limit, offset=offset)

    async def count_ingest_jobs(self, *, scope: KnowledgeScope | None = None) -> int:
        return await self._count_scoped_jobs("ingest_jobs", scope=scope)

    async def _get_ingest_job_in_transaction(
        self,
        db: aiosqlite.Connection,
        job_id: str,
    ) -> aiosqlite.Row | None:
        async with db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)) as cur:
            return await cur.fetchone()

    async def _update_ingest_job_payload_in_transaction(
        self,
        db: aiosqlite.Connection,
        job_id: str,
        *,
        completed_delta: int,
        failed_delta: int,
        result_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(UTC).isoformat()
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

    # -- Evaluation --------------------------------------------------------

    async def record_eval_run(
        self,
        *,
        run_id: str,
        top_k: int,
        metrics: dict[str, Any],
        labels: list[dict[str, Any]],
        results: list[dict[str, Any]],
        scope: KnowledgeScope | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        async with self._write_transaction() as db:
            await db.execute(
                """
                INSERT INTO eval_runs
                    (id, created_at, top_k, metrics_json, labels_json, results_json,
                     workspace_id, project_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    top_k,
                    json.dumps(metrics),
                    json.dumps(labels),
                    json.dumps(results),
                    scope.workspace_id if scope else None,
                    scope.project_id if scope else None,
                ),
            )

    async def list_eval_runs(
        self, *, limit: int = 20, offset: int = 0, scope: KnowledgeScope | None = None,
    ) -> list[dict[str, Any]]:
        rows = await self._list_scoped_jobs("eval_runs", scope=scope, limit=limit, offset=offset)
        return [self._eval_run_payload(row, detail=False) for row in rows]

    async def count_eval_runs(self, *, scope: KnowledgeScope | None = None) -> int:
        return await self._count_scoped_jobs("eval_runs", scope=scope)

    async def get_eval_run(
        self, run_id: str, *, scope: KnowledgeScope | None = None,
    ) -> dict[str, Any] | None:
        row = await self._get_scoped_job("eval_runs", run_id, scope)
        return self._eval_run_payload(row) if row else None

    @staticmethod
    def _eval_run_payload(row: aiosqlite.Row, *, detail: bool = True) -> dict[str, Any]:
        payload = {
            "id": row["id"], "created_at": datetime.fromisoformat(row["created_at"]),
            "top_k": int(row["top_k"]), "metrics": json.loads(row["metrics_json"]),
            "workspace_id": dict(row).get("workspace_id"),
            "project_id": dict(row).get("project_id"),
        }
        if detail:
            payload.update(labels=json.loads(row["labels_json"]),
                           results=json.loads(row["results_json"]))
        return payload

    async def record_retrieval_trace(self, record: Any) -> str:
        trace_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        payload = (
            record.model_dump(mode="json")
            if hasattr(record, "model_dump")
            else dict(record)
        )
        async with self._write_transaction() as db:
            await db.execute(
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
        return trace_id

    # -- Stats -------------------------------------------------------------

    async def knowledge_stats(
        self, *, scope: KnowledgeScope | None = None, market: str | None = None,
        source_roles: list[str] | None = None, max_age_days: int | None = None,
    ) -> dict[str, Any]:
        db = self._connection
        clauses = ["d.status = 'active'", "d.is_active = 1"]
        params: list[Any] = []
        self._add_scope_filters(clauses, params, scope=scope, market=market,
                                source_roles=source_roles, max_age_days=max_age_days, prefix="d.")
        where = " AND ".join(clauses)
        async with db.execute(
            f"SELECT COUNT(*) AS total FROM documents d WHERE {where}", params
        ) as cur:
            row = await cur.fetchone()
            doc_count = int(row["total"]) if row else 0

        async with db.execute(
            f"""SELECT COUNT(*) AS total, COALESCE(AVG(LENGTH(c.text)), 0) AS avg_len
                FROM chunks c JOIN documents d ON d.id = c.document_id WHERE {where}""",
            params,
        ) as cur:
            row = await cur.fetchone()
            chunk_count = int(row["total"]) if row else 0
            average_chunk_length = float(row["avg_len"]) if row else 0.0

        async with db.execute(
            f"""SELECT source_type, COUNT(*) AS total FROM documents d WHERE {where}
                GROUP BY source_type ORDER BY source_type""", params,
        ) as cur:
            source_breakdown = {
                row["source_type"]: int(row["total"]) for row in await cur.fetchall()
            }

        since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        async with db.execute(
            f"SELECT COUNT(*) AS total FROM documents d "
            f"WHERE {where} AND julianday(fetched_at) >= julianday(?)",
            [*params, since],
        ) as cur:
            row = await cur.fetchone()
            last_24h_ingest_count = int(row["total"]) if row else 0

        fts_size = 0
        for table_name, join in (
            ("documents_fts", "JOIN documents d ON d.rowid = documents_fts.rowid"),
            ("chunks_fts", "JOIN chunks c ON c.rowid = chunks_fts.rowid "
                           "JOIN documents d ON d.id = c.document_id"),
        ):
            if scope is None and market is None and not source_roles and max_age_days is None:
                sql, fts_params = f"SELECT COUNT(*) AS total FROM {table_name}", []
            else:
                sql = f"SELECT COUNT(*) AS total FROM {table_name} {join} WHERE {where}"
                fts_params = params
            async with db.execute(sql, fts_params) as cur:
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
        await apply_sqlite_pragmas(self._connection)

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
            (9, "add evidence sync tracking", self._migration_009_evidence_sync_tracking),
            (10, "rebuild FTS with CJK bigrams", self._migration_010_cjk_fts),
            (11, "add recoverable vector indexing state", self._migration_011_indexing_state),
            (12, "add scoped source context and namespace identity",
             self._migration_012_knowledge_scope),
            (13, "add scoped knowledge jobs and eval runs", self._migration_013_job_scope),
            (14, "add typed source updated timestamp", self._migration_014_source_updated),
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

    async def _migration_010_cjk_fts(self) -> None:
        db = self._connection
        for name in (
            "documents_ai", "documents_ad", "documents_au", "chunks_ai", "chunks_ad", "chunks_au"
        ):
            await db.execute(f"DROP TRIGGER IF EXISTS {name}")
        await db.execute("DROP TABLE IF EXISTS documents_fts")
        await db.execute("DROP TABLE IF EXISTS chunks_fts")
        # FTS stores tokenised copies. External-content 'rebuild' would bypass segmentation.
        fts_schema = _POST_MIGRATION_SCHEMA[_POST_MIGRATION_SCHEMA.index("CREATE VIRTUAL TABLE"):]
        await db.executescript(fts_schema)
        await db.execute(
            "INSERT INTO documents_fts(rowid, title, text) "
            "SELECT rowid, kb_tokens(title), kb_tokens(text) FROM documents"
        )
        await db.execute(
            "INSERT INTO chunks_fts(rowid, text) SELECT rowid, kb_tokens(text) FROM chunks"
        )

    async def _migration_011_indexing_state(self) -> None:
        for column, declaration in (
            ("indexing_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("indexing_error", "TEXT"), ("embedding_model", "TEXT"),
            ("embedding_dimensions", "INTEGER"), ("index_version", "TEXT"),
        ):
            await self._add_column_if_missing("documents", column, declaration)
        # Old indexed_at predates vector writes and cannot establish readiness.
        await self._connection.execute(
            "UPDATE documents SET indexed_at = NULL WHERE indexing_status != 'ready'"
        )

    async def _migration_014_source_updated(self) -> None:
        await self._add_column_if_missing("documents", "source_updated_at", "TEXT")

    async def _migration_013_job_scope(self) -> None:
        for table in ("crawl_jobs", "ingest_jobs", "eval_runs"):
            await self._add_column_if_missing(table, "workspace_id", "TEXT")
            await self._add_column_if_missing(table, "project_id", "TEXT")
            await self._connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_scope "
                f"ON {table}(workspace_id, project_id, created_at)"
            )
        await self._add_column_if_missing("crawl_jobs", "market", "TEXT")

    async def _migration_012_knowledge_scope(self) -> None:
        for column, declaration in (
            ("workspace_id", "TEXT"), ("project_id", "TEXT"), ("market", "TEXT"),
            ("source_role", "TEXT NOT NULL DEFAULT 'source'"),
            ("source_published_at", "TEXT"), ("last_verified_at", "TEXT"),
        ):
            await self._add_column_if_missing("documents", column, declaration)
        await self._connection.execute(
            "UPDATE documents SET source_role = 'historical_report' WHERE source_type = 'report'"
        )
        for name in ("ux_documents_active_canonical_url", "ux_documents_active_content_hash"):
            await self._connection.execute(f"DROP INDEX IF EXISTS {name}")

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

    async def _migration_009_evidence_sync_tracking(self) -> None:
        await self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_crawl_run_document
            ON chunks(crawl_run_id, document_id)
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_sync_state (
                workspace_id   TEXT NOT NULL,
                project_id     TEXT NOT NULL,
                document_id    TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                evidence_id    TEXT NOT NULL,
                synced_at      TEXT NOT NULL,
                metadata_json  TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (workspace_id, project_id, document_id)
            )
            """
        )
        await self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_evidence_sync_state_project_hash
            ON evidence_sync_state(workspace_id, project_id, content_hash)
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_sync_metrics (
                id              TEXT PRIMARY KEY,
                workspace_id    TEXT NOT NULL,
                project_id      TEXT NOT NULL,
                status          TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                completed_at    TEXT NOT NULL,
                duration_ms     REAL NOT NULL DEFAULT 0,
                loaded_count    INTEGER NOT NULL DEFAULT 0,
                ingested_count  INTEGER NOT NULL DEFAULT 0,
                skipped_count   INTEGER NOT NULL DEFAULT 0,
                chunk_count     INTEGER NOT NULL DEFAULT 0,
                indexed_count   INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                request_json    TEXT NOT NULL DEFAULT '{}',
                error           TEXT NOT NULL DEFAULT ''
            )
            """
        )
        await self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_evidence_sync_metrics_project
            ON evidence_sync_metrics(workspace_id, project_id, completed_at)
            """
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
        if column not in {"canonical_url", "content_hash"}:
            raise ValueError("Unsupported duplicate identity column")
        async with self._connection.execute(
            f"""SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY {_DOCUMENT_NAMESPACE_SQL}, {column}
                        ORDER BY fetched_at DESC, rowid DESC
                    ) AS duplicate_rank
                    FROM documents WHERE is_active = 1 AND {column} IS NOT NULL
                ) WHERE duplicate_rank > 1"""
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            await self._connection.execute(
                "UPDATE documents SET is_active = 0, status = 'archived' WHERE id = ?",
                (row["id"],),
            )

    @staticmethod
    def _namespace_filter(
        namespace: KnowledgeNamespace, *, prefix: str = "",
    ) -> tuple[str, list[Any]]:
        if namespace[0] is None:
            return f"{prefix}workspace_id IS NULL", []
        columns = ("workspace_id", "project_id", "competitor", "dimension", "market", "source_role")
        return " AND ".join(f"{prefix}{column} IS ?" for column in columns), list(namespace)

    @staticmethod
    def _add_scope_filters(
        clauses: list[str], params: list[Any], *, scope: KnowledgeScope | None = None,
        market: str | None = None, source_roles: list[str] | None = None,
        max_age_days: int | None = None, prefix: str = "",
    ) -> None:
        if scope is not None:
            clauses.append(f"{prefix}workspace_id = ?")
            params.append(scope.workspace_id)
            if scope.project_id is not None and scope.include_workspace_library:
                clauses.append(f"({prefix}project_id = ? OR {prefix}project_id IS NULL)")
                params.append(scope.project_id)
            else:
                clauses.append(f"{prefix}project_id IS ?")
                params.append(scope.project_id)
        if market is not None:
            clauses.append(f"{prefix}market = ?")
            params.append(market)
        if source_roles:
            clauses.append(f"{prefix}source_role IN ({', '.join('?' for _ in source_roles)})")
            params.extend(source_roles)
        if max_age_days is not None:
            if max_age_days < 0:
                raise ValueError("max_age_days must be nonnegative")
            now = datetime.now(UTC)
            cutoff = (now - timedelta(days=max_age_days)).isoformat()
            clauses.append(
                f"julianday(COALESCE({prefix}last_verified_at, "
                f"{prefix}source_updated_at, "
                f"{prefix}source_published_at, {prefix}fetched_at)) "
                "BETWEEN julianday(?) AND julianday(?)"
            )
            params.extend([cutoff, now.isoformat()])

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
            workspace_id=row["workspace_id"], project_id=row["project_id"],
            market=row["market"], source_role=row["source_role"],
            source_published_at=(datetime.fromisoformat(row["source_published_at"])
                                 if row["source_published_at"] else None),
            source_updated_at=(datetime.fromisoformat(row["source_updated_at"])
                               if row["source_updated_at"] else None),
            last_verified_at=(datetime.fromisoformat(row["last_verified_at"])
                              if row["last_verified_at"] else None),
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
            indexing_status=row["indexing_status"], indexing_error=row["indexing_error"],
            embedding_model=row["embedding_model"],
            embedding_dimensions=row["embedding_dimensions"],
            index_version=row["index_version"],
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
        terms = lexical_tokens(query)
        return " ".join(f'"{term}"' for term in terms)
