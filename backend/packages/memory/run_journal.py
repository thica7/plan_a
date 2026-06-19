from __future__ import annotations

import sqlite3
from pathlib import Path

from app.events import RunEvent
from packages.schema.api_dto import RunDetail, RunSummary


SUMMARY_COLUMNS: dict[str, str] = {
    "idempotency_key": "text not null default ''",
    "workspace_id": "text not null default 'default-workspace'",
    "project_id": "text",
    "topic": "text not null default ''",
    "status": "text not null default 'queued'",
    "execution_mode": "text not null default 'demo'",
}
RUN_SUMMARY_SCHEMA_VERSION = "3"


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
                insert into runs (
                    id, idempotency_key, workspace_id, project_id, topic, status,
                    execution_mode, detail_json, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    idempotency_key = excluded.idempotency_key,
                    workspace_id = excluded.workspace_id,
                    project_id = excluded.project_id,
                    topic = excluded.topic,
                    status = excluded.status,
                    execution_mode = excluded.execution_mode,
                    detail_json = excluded.detail_json,
                    updated_at = excluded.updated_at
                """,
                (
                    detail.id,
                    detail.idempotency_key,
                    detail.workspace_id,
                    detail.project_id,
                    detail.topic,
                    detail.status,
                    detail.execution_mode,
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

    def load_run_summaries(self) -> list[RunSummary]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                select
                    id,
                    idempotency_key,
                    workspace_id,
                    project_id,
                    topic,
                    status,
                    execution_mode,
                    created_at,
                    updated_at
                from runs
                order by updated_at desc
                """
            ).fetchall()
        finally:
            self._close(conn)
        return [_summary_from_row(row) for row in rows]

    def load_run_summary(self, run_id: str) -> RunSummary | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                select
                    id,
                    idempotency_key,
                    workspace_id,
                    project_id,
                    topic,
                    status,
                    execution_mode,
                    created_at,
                    updated_at
                from runs
                where id = ?
                """,
                (run_id,),
            ).fetchone()
        finally:
            self._close(conn)
        if row is None:
            return None
        return _summary_from_row(row)

    def run_exists(self, run_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("select 1 from runs where id = ? limit 1", (run_id,)).fetchone()
        finally:
            self._close(conn)
        return row is not None

    def ping(self) -> bool:
        conn = self._connect()
        try:
            conn.execute("select 1").fetchone()
        finally:
            self._close(conn)
        return True

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
                    idempotency_key text not null default '',
                    workspace_id text not null default 'default-workspace',
                    project_id text,
                    topic text not null default '',
                    status text not null default 'queued',
                    execution_mode text not null default 'demo',
                    detail_json text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            added_summary_columns = self._ensure_summary_columns(conn)
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
            conn.execute(
                """
                create table if not exists meta (
                    key text primary key,
                    value text not null
                )
                """
            )
            conn.execute("create index if not exists idx_events_run on events(run_id, event_id)")
            conn.execute("create index if not exists idx_runs_updated_at on runs(updated_at desc)")
            if added_summary_columns or self._meta_value(conn, "run_summary_schema_version") != RUN_SUMMARY_SCHEMA_VERSION:
                self._backfill_summary_columns(conn)
                self._set_meta_value(conn, "run_summary_schema_version", RUN_SUMMARY_SCHEMA_VERSION)
            conn.commit()
        finally:
            self._close(conn)

    def _ensure_summary_columns(self, conn: sqlite3.Connection) -> bool:
        existing = {row[1] for row in conn.execute("pragma table_info(runs)").fetchall()}
        added = False
        for name, ddl in SUMMARY_COLUMNS.items():
            if name not in existing:
                conn.execute(f"alter table runs add column {name} {ddl}")
                added = True
        return added

    def _backfill_summary_columns(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            update runs
            set
                idempotency_key = coalesce(json_extract(detail_json, '$.idempotency_key'), idempotency_key, ''),
                workspace_id = coalesce(json_extract(detail_json, '$.workspace_id'), workspace_id, 'default-workspace'),
                project_id = json_extract(detail_json, '$.project_id'),
                topic = coalesce(json_extract(detail_json, '$.topic'), topic, ''),
                status = coalesce(json_extract(detail_json, '$.status'), status, 'queued'),
                execution_mode = coalesce(json_extract(detail_json, '$.execution_mode'), execution_mode, 'demo')
            where json_valid(detail_json)
            """
        )

    def _meta_value(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("select value from meta where key = ?", (key,)).fetchone()
        return str(row[0]) if row is not None else None

    def _set_meta_value(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            insert into meta (key, value)
            values (?, ?)
            on conflict(key) do update set value = excluded.value
            """,
            (key, value),
        )


def _summary_from_row(row: sqlite3.Row | tuple[object, ...]) -> RunSummary:
    return RunSummary(
        id=str(row[0]),
        idempotency_key=str(row[1] or ""),
        workspace_id=str(row[2] or "default-workspace"),
        project_id=str(row[3]) if row[3] is not None else None,
        topic=str(row[4] or ""),
        status=row[5],
        execution_mode=row[6],
        created_at=row[7],
        updated_at=row[8],
    )
