from __future__ import annotations

import sqlite3
from pathlib import Path

from app.events import RunEvent
from packages.schema.api_dto import RunDetail


class RunJournal:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._memory_conn: sqlite3.Connection | None = None
        if str(self._db_path) == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_default_path(cls) -> RunJournal:
        return cls(Path("runs") / "run_journal.db")

    @classmethod
    def in_memory(cls) -> RunJournal:
        return cls(Path(":memory:"))

    def save_run(self, detail: RunDetail) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                insert into runs (id, detail_json, created_at, updated_at)
                values (?, ?, ?, ?)
                on conflict(id) do update set
                    detail_json = excluded.detail_json,
                    updated_at = excluded.updated_at
                """,
                (
                    detail.id,
                    detail.model_dump_json(),
                    detail.created_at.isoformat(),
                    detail.updated_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            self._close(conn)

    def append_event(self, event: RunEvent) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                insert or replace into events (run_id, event_id, event_json, created_at)
                values (?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.id,
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            self._close(conn)

    def load_runs(self) -> list[RunDetail]:
        conn = self._connect()
        try:
            rows = conn.execute("select detail_json from runs order by updated_at desc").fetchall()
        finally:
            self._close(conn)
        return [RunDetail.model_validate_json(row[0]) for row in rows]

    def load_run(self, run_id: str) -> RunDetail | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "select detail_json from runs where id = ?",
                (run_id,),
            ).fetchone()
        finally:
            self._close(conn)
        if row is None:
            return None
        return RunDetail.model_validate_json(row[0])

    def load_events(self, run_id: str) -> list[RunEvent]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select event_json from events where run_id = ? order by event_id asc",
                (run_id,),
            ).fetchall()
        finally:
            self._close(conn)
        return [RunEvent.model_validate_json(row[0]) for row in rows]

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
                create table if not exists runs (
                    id text primary key,
                    detail_json text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists events (
                    run_id text not null,
                    event_id integer not null,
                    event_json text not null,
                    created_at text not null,
                    primary key (run_id, event_id)
                )
                """
            )
            conn.execute("create index if not exists idx_events_run on events(run_id, event_id)")
            conn.commit()
        finally:
            self._close(conn)
