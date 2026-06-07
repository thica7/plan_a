"""SQLite persistence for crawler sources and durable frontier."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urldefrag, urlparse, urlunparse

import aiosqlite

from .models import CrawlFrontierItem, CrawlFrontierStats, CrawlSource, CrawlSourceType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_source (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    competitor  TEXT,
    dimension   TEXT,
    priority    INTEGER NOT NULL DEFAULT 100,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_frontier (
    id            TEXT PRIMARY KEY,
    source_id     TEXT,
    source_type   TEXT NOT NULL,
    url           TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    competitor    TEXT,
    dimension     TEXT,
    priority      INTEGER NOT NULL DEFAULT 100,
    depth         INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    next_run_at   TEXT NOT NULL,
    last_error    TEXT,
    parent_id     TEXT,
    discovered_at TEXT NOT NULL,
    run_id        TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_source_type ON crawl_source(type);
CREATE INDEX IF NOT EXISTS idx_crawl_frontier_source_id ON crawl_frontier(source_id);
CREATE INDEX IF NOT EXISTS idx_crawl_frontier_status_next_run
ON crawl_frontier(status, next_run_at, priority);
CREATE INDEX IF NOT EXISTS idx_crawl_frontier_run_id ON crawl_frontier(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_crawl_frontier_canonical_url
ON crawl_frontier(canonical_url);
"""


class CrawlerRepository:
    """Async SQLite repository for crawl sources and frontier rows."""

    def __init__(self, db_path: str = "runs/knowledge.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialise(self) -> None:
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(
            self._db_path,
            uri=self._db_path.startswith("file:"),
        )
        self._db.row_factory = aiosqlite.Row
        try:
            await self._apply_pragmas()
            await self._db.executescript(_SCHEMA)
            await self._migrate_schema()
            await self._db.commit()
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> CrawlerRepository:
        await self.initialise()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("CrawlerRepository.initialise() must be called before use")
        return self._db

    async def create_source(
        self,
        source_type: CrawlSourceType,
        config: dict[str, Any],
        *,
        competitor: str | None = None,
        dimension: str | None = None,
        priority: int = 100,
    ) -> CrawlSource:
        now = datetime.now(UTC).isoformat()
        source_id = str(uuid.uuid4())
        await self._connection.execute(
            """
            INSERT INTO crawl_source
                (id, type, competitor, dimension, priority, config_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, source_type, competitor, dimension, priority, json.dumps(config), now),
        )
        await self._connection.commit()
        return CrawlSource(
            id=source_id,
            type=source_type,
            config=config,
            competitor=competitor,
            dimension=dimension,
            priority=priority,
            created_at=datetime.fromisoformat(now),
        )

    async def list_sources(self) -> list[CrawlSource]:
        async with self._connection.execute(
            "SELECT * FROM crawl_source ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_source(row) for row in rows]

    async def get_source(self, source_id: str) -> CrawlSource | None:
        async with self._connection.execute(
            "SELECT * FROM crawl_source WHERE id = ?",
            (source_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_source(row) if row else None

    async def delete_source(self, source_id: str) -> bool:
        cursor = await self._connection.execute(
            "DELETE FROM crawl_source WHERE id = ?",
            (source_id,),
        )
        await self._connection.execute(
            "UPDATE crawl_frontier SET status = 'cancelled' WHERE source_id = ? OR run_id = ?",
            (source_id, source_id),
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    async def add_frontier_items(
        self,
        urls: list[str],
        *,
        source_type: CrawlSourceType,
        source_id: str | None = None,
        competitor: str | None = None,
        dimension: str | None = None,
        priority: int = 100,
        depth: int = 0,
        parent_id: str | None = None,
        run_id: str | None = None,
        next_run_at: datetime | None = None,
        max_urls: int | None = None,
    ) -> int:
        now = datetime.now(UTC)
        next_at = (next_run_at or now).isoformat()
        discovered_at = now.isoformat()
        rows: list[tuple[Any, ...]] = []
        for url in urls[:max_urls]:
            canonical_url = canonicalize_url(url)
            if not canonical_url:
                continue
            rows.append((
                str(uuid.uuid4()),
                source_id,
                source_type,
                url,
                canonical_url,
                competitor,
                dimension,
                priority,
                depth,
                "pending",
                0,
                next_at,
                None,
                parent_id,
                discovered_at,
                run_id,
            ))
        if not rows:
            return 0

        before = self._connection.total_changes
        await self._connection.executemany(
            """
            INSERT OR IGNORE INTO crawl_frontier
                (id, source_id, source_type, url, canonical_url, competitor, dimension, priority,
                 depth, status, attempts, next_run_at, last_error, parent_id,
                 discovered_at, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self._connection.commit()
        return self._connection.total_changes - before

    async def claim_pending(self, *, limit: int = 10) -> list[CrawlFrontierItem]:
        now = datetime.now(UTC).isoformat()
        async with self._connection.execute(
            """
            UPDATE crawl_frontier
            SET status = 'running',
                attempts = attempts + 1,
                last_error = NULL
            WHERE id IN (
                SELECT id
                FROM crawl_frontier
                WHERE status = 'pending' AND next_run_at <= ?
                ORDER BY priority ASC, discovered_at ASC
                LIMIT ?
            )
            RETURNING *
            """,
            (now, limit),
        ) as cur:
            rows = await cur.fetchall()
        await self._connection.commit()
        return [self._row_to_frontier_item(row) for row in rows]

    async def mark_done(self, item_id: str) -> None:
        await self._connection.execute(
            "UPDATE crawl_frontier SET status = 'done', last_error = NULL WHERE id = ?",
            (item_id,),
        )
        await self._connection.commit()

    async def mark_failed(
        self,
        item_id: str,
        error: str,
        *,
        retry: bool = False,
        retry_after_seconds: float = 60.0,
    ) -> None:
        if retry:
            next_run_at = (datetime.now(UTC) + timedelta(seconds=retry_after_seconds)).isoformat()
            await self._connection.execute(
                """
                UPDATE crawl_frontier
                SET status = 'pending', next_run_at = ?, last_error = ?
                WHERE id = ?
                """,
                (next_run_at, error, item_id),
            )
        else:
            await self._connection.execute(
                "UPDATE crawl_frontier SET status = 'failed', last_error = ? WHERE id = ?",
                (error, item_id),
            )
        await self._connection.commit()

    async def retry_failed(self, source_id: str | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        if source_id:
            cursor = await self._connection.execute(
                """
                UPDATE crawl_frontier
                SET status = 'pending', next_run_at = ?, last_error = NULL
                WHERE status = 'failed' AND (source_id = ? OR run_id = ?)
                """,
                (now, source_id, source_id),
            )
        else:
            cursor = await self._connection.execute(
                """
                UPDATE crawl_frontier
                SET status = 'pending', next_run_at = ?, last_error = NULL
                WHERE status = 'failed'
                """,
                (now,),
            )
        await self._connection.commit()
        return cursor.rowcount

    async def stats(self, *, source_id: str | None = None) -> CrawlFrontierStats:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("(source_id = ? OR run_id = ?)")
            params.extend([source_id, source_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._connection.execute(
            f"""
            SELECT status, COUNT(*) AS total
            FROM crawl_frontier
            {where}
            GROUP BY status
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        counts = {row["status"]: int(row["total"]) for row in rows}
        return CrawlFrontierStats(
            queued=counts.get("pending", 0),
            running=counts.get("running", 0),
            done=counts.get("done", 0),
            failed=counts.get("failed", 0),
            cancelled=counts.get("cancelled", 0),
        )

    async def list_frontier(
        self,
        *,
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[CrawlFrontierItem]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("(source_id = ? OR run_id = ?)")
            params.extend([source_id, source_id])
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with self._connection.execute(
            f"""
            SELECT *
            FROM crawl_frontier
            {where}
            ORDER BY priority ASC, discovered_at ASC
            LIMIT ?
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_frontier_item(row) for row in rows]

    async def _apply_pragmas(self) -> None:
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA busy_timeout = 5000")
        await self._connection.execute("PRAGMA synchronous = NORMAL")
        await self._connection.execute("PRAGMA temp_store = MEMORY")
        await self._connection.execute("PRAGMA cache_size = -20000")
        await self._connection.execute("PRAGMA foreign_keys = ON")

    async def _migrate_schema(self) -> None:
        await self._ensure_column("crawl_source", "competitor", "TEXT")
        await self._ensure_column("crawl_source", "dimension", "TEXT")
        await self._ensure_column("crawl_source", "priority", "INTEGER NOT NULL DEFAULT 100")
        await self._ensure_column("crawl_frontier", "source_id", "TEXT")

    async def _ensure_column(self, table: str, column: str, definition: str) -> None:
        async with self._connection.execute(f"PRAGMA table_info({table})") as cur:
            rows = await cur.fetchall()
        if column not in {row["name"] for row in rows}:
            await self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _row_to_source(row: aiosqlite.Row) -> CrawlSource:
        return CrawlSource(
            id=row["id"],
            type=row["type"],
            config=json.loads(row["config_json"]),
            competitor=row["competitor"],
            dimension=row["dimension"],
            priority=row["priority"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_frontier_item(row: aiosqlite.Row) -> CrawlFrontierItem:
        return CrawlFrontierItem(
            id=row["id"],
            source_id=row["source_id"],
            source_type=row["source_type"],
            url=row["url"],
            canonical_url=row["canonical_url"],
            competitor=row["competitor"],
            dimension=row["dimension"],
            priority=row["priority"],
            depth=row["depth"],
            status=row["status"],
            attempts=row["attempts"],
            next_run_at=datetime.fromisoformat(row["next_run_at"]),
            last_error=row["last_error"],
            parent_id=row["parent_id"],
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            run_id=row["run_id"],
        )


def canonicalize_url(url: str) -> str:
    parsed = urlparse(urldefrag(url)[0].strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    hostname = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{hostname}{port}"
    if parsed.username or parsed.password:
        netloc = parsed.netloc.rsplit("@", 1)[-1].lower()
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))
