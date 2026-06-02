from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.paths import runtime_path
from packages.schema.models import CompetitorKnowledge


class KBCacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    dimension: str
    content_hash: str
    kb_slice: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    knowledge: CompetitorKnowledge
    created_at: datetime = Field(default_factory=datetime.utcnow)


class KBCache:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._memory_conn: sqlite3.Connection | None = None
        if str(self._db_path) == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_default_path(cls) -> KBCache:
        return cls(runtime_path("runs", "kb_cache.db"))

    @classmethod
    def in_memory(cls) -> KBCache:
        return cls(Path(":memory:"))

    def get(self, competitor: str, dimension: str, content_hash: str) -> KBCacheEntry | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                select entry_json from kb_cache
                where competitor = ? and dimension = ? and content_hash = ?
                """,
                (competitor, dimension, content_hash),
            ).fetchone()
        finally:
            self._close(conn)
        if row is None:
            return None
        return KBCacheEntry.model_validate_json(row[0])

    def put(self, entry: KBCacheEntry) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                insert into kb_cache (
                    competitor, dimension, content_hash, entry_json, created_at
                )
                values (?, ?, ?, ?, ?)
                on conflict(competitor, dimension, content_hash) do update set
                    entry_json = excluded.entry_json,
                    created_at = excluded.created_at
                """,
                (
                    entry.competitor,
                    entry.dimension,
                    entry.content_hash,
                    entry.model_dump_json(),
                    entry.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            self._close(conn)

    def stats(self) -> dict[str, int]:
        conn = self._connect()
        try:
            row_count = conn.execute("select count(*) from kb_cache").fetchone()[0]
            competitor_count = conn.execute(
                "select count(distinct competitor) from kb_cache"
            ).fetchone()[0]
        finally:
            self._close(conn)
        return {"entries": int(row_count), "competitors": int(competitor_count)}

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        return sqlite3.connect(self._db_path)

    def _close(self, conn: sqlite3.Connection) -> None:
        if conn is not self._memory_conn:
            conn.close()

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                create table if not exists kb_cache (
                    competitor text not null,
                    dimension text not null,
                    content_hash text not null,
                    entry_json text not null,
                    created_at text not null,
                    primary key (competitor, dimension, content_hash)
                )
                """
            )
            conn.execute(
                "create index if not exists idx_kb_cache_competitor "
                "on kb_cache(competitor, dimension)"
            )
            conn.commit()
        finally:
            self._close(conn)
