from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from pathlib import Path

from app.events import RunEvent

from packages.infrastructure.execution_control import (
    ExecutionConflictError,
    ExecutionPolicy,
    ExecutionTicket,
    ExecutionUnavailableError,
    SQLiteExecutionCoordinator,
)
from packages.schema.api_dto import RunDetail, RunSummary
from packages.schema.enterprise import EnterpriseRunProjection

SUMMARY_COLUMNS: dict[str, str] = {
    "idempotency_key": "text not null default ''",
    "workspace_id": "text not null default 'default-workspace'",
    "project_id": "text",
    "topic": "text not null default ''",
    "status": "text not null default 'queued'",
    "execution_mode": "text not null default 'demo'",
}
RUN_SUMMARY_SCHEMA_VERSION = "3"


def _storage_errors(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (sqlite3.Error, OSError) as exc:
            raise ExecutionUnavailableError("Run journal storage is unavailable") from exc
    return checked


class RunJournal:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._control_conn: ContextVar[sqlite3.Connection | None] = ContextVar(
            "journal_control", default=None,
        )
        self._execution: SQLiteExecutionCoordinator | None = None
        self._memory_conn: sqlite3.Connection | None = None
        if str(self._db_path) == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def require_execution(self, coordinator: SQLiteExecutionCoordinator) -> None:
        if str(self._db_path) == ":memory:" or self._db_path.resolve() != coordinator.db_path:
            raise ExecutionConflictError("Execution journal path differs")
        self._execution = coordinator

    def _authorize_write(
        self, conn: sqlite3.Connection, run_id: str, *, expected_revision: int | None,
        token: str | None, generation: int | None, control_event: bool = False,
    ) -> None:
        shared = conn.execute(
            "select 1 from sqlite_master where type='table' and name='execution_control_pool'"
        ).fetchone()
        if token is not None or generation is not None:
            if not shared or token is None or generation is None:
                raise ExecutionConflictError("Incomplete execution fence")
            coordinator = self._execution
            if coordinator is None:
                row = conn.execute("select policy_json from execution_control_pool where id=1")
                coordinator = SQLiteExecutionCoordinator(
                    self._db_path, ExecutionPolicy(**json.loads(row.fetchone()[0]))
                )
            coordinator.assert_fence(conn, run_id, token, generation)
            return
        if not shared or control_event:
            return
        if expected_revision is None:
            raise ExecutionConflictError("Shared journal writes require a revision or lease")
        if conn.execute(
            "select 1 from execution_control_runs where run_id=? and token is not null",
            (run_id,),
        ).fetchone():
            raise ExecutionConflictError("Run has an active execution owner")

    @contextmanager
    def control_write(self, run_id: str, expected_revision: int, *, allow_missing: bool = False):
        """Serialize a synchronous idle control mutation with execution claims."""
        conn = self._connect()
        context = None
        try:
            conn.execute("begin immediate")
            self._authorize_write(conn, run_id, expected_revision=expected_revision,
                                  token=None, generation=None)
            row = conn.execute("select revision from runs where id=?", (run_id,)).fetchone()
            if (row is None and not (allow_missing and expected_revision == 0)) or (
                row is not None and row[0] != expected_revision
            ):
                raise ExecutionConflictError("Run revision has changed")
            context = self._control_conn.set(conn)
            yield
            conn.commit()
        finally:
            if context is not None:
                self._control_conn.reset(context)
            self._close(conn)

    def _begin_write(self, conn: sqlite3.Connection) -> None:
        if self._control_conn.get() is not conn:
            conn.execute("begin immediate")

    def _commit_write(self, conn: sqlite3.Connection) -> None:
        if self._control_conn.get() is not conn:
            conn.commit()

    @classmethod
    def from_default_path(cls) -> RunJournal:
        return cls(Path("runs") / "run_journal.db")

    @classmethod
    def in_memory(cls) -> RunJournal:
        return cls(Path(":memory:"))

    @_storage_errors
    def save_run(
        self,
        detail: RunDetail,
        *,
        projections: list[EnterpriseRunProjection] | None = None,
        expected_revision: int | None = None,
        token: str | None = None,
        generation: int | None = None,
    ) -> int:
        for projection in projections or []:
            version = projection.report_version
            if (projection.run_id, projection.workspace_id, projection.project_id) != (
                detail.id,
                detail.workspace_id,
                detail.project_id,
            ) or (version.run_id, version.workspace_id, version.project_id) != (
                detail.id,
                detail.workspace_id,
                detail.project_id,
            ):
                raise ValueError("Journal projection scope mismatch")
        conn = self._connect()
        try:
            self._begin_write(conn)
            self._authorize_write(conn, detail.id, expected_revision=expected_revision,
                                  token=token, generation=generation)
            current = conn.execute("select revision from runs where id=?", (detail.id,)).fetchone()
            revision = current[0] if current else 0
            if expected_revision is not None and revision != expected_revision:
                raise ExecutionConflictError("Run revision has changed")
            conn.execute(
                """
                insert into runs (
                    id, idempotency_key, workspace_id, project_id, topic, status,
                    execution_mode, detail_json, created_at, updated_at, revision
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    idempotency_key = excluded.idempotency_key,
                    workspace_id = excluded.workspace_id,
                    project_id = excluded.project_id,
                    topic = excluded.topic,
                    status = excluded.status,
                    execution_mode = excluded.execution_mode,
                    detail_json = excluded.detail_json,
                    updated_at = excluded.updated_at,
                    revision = excluded.revision
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
                    revision + 1,
                ),
            )
            for projection in projections or []:
                conn.execute(
                    """insert into report_projections (run_id, version_id, projection_json)
                    values (?, ?, ?) on conflict(run_id, version_id) do update set
                    projection_json = excluded.projection_json""",
                    (detail.id, projection.report_version.id, projection.model_dump_json()),
                )
            self._commit_write(conn)
            return revision + 1
        finally:
            self._close(conn)

    @_storage_errors
    def load_report_projections(self, run_id: str) -> list[EnterpriseRunProjection]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select projection_json from report_projections where run_id = ?",
                (run_id,),
            ).fetchall()
        finally:
            self._close(conn)
        return sorted(
            (EnterpriseRunProjection.model_validate_json(row[0]) for row in rows),
            key=lambda item: item.report_version.version_number,
        )

    @_storage_errors
    def append_event(
        self, event: RunEvent, *, expected_revision: int | None = None,
        token: str | None = None, generation: int | None = None,
        control_event: bool = False, command_id: str | None = None,
    ) -> RunEvent:
        conn = self._connect()
        try:
            self._begin_write(conn)
            self._authorize_write(conn, event.run_id, expected_revision=expected_revision,
                                  token=token, generation=generation, control_event=control_event)
            if command_id:
                old = conn.execute(
                    "select event_json from events where run_id=? and command_id=?",
                    (event.run_id, command_id),
                ).fetchone()
                if old:
                    self._commit_write(conn)
                    return RunEvent.model_validate_json(old[0])
            if expected_revision is not None and not control_event:
                row = conn.execute(
                    "select revision from runs where id=?", (event.run_id,),
                ).fetchone()
                if row is None or row[0] != expected_revision:
                    raise ExecutionConflictError("Run revision has changed")
            next_id = conn.execute(
                "select coalesce(max(event_id), 0)+1 from events where run_id=?", (event.run_id,)
            ).fetchone()[0]
            event = event.model_copy(update={"id": next_id})
            conn.execute(
                "insert into events (run_id,event_id,event_json,created_at,command_id) "
                "values (?,?,?,?,?)",
                (event.run_id, event.id, event.model_dump_json(),
                 event.created_at.isoformat(), command_id),
            )
            self._commit_write(conn)
            return event
        finally:
            self._close(conn)

    @_storage_errors
    def load_runs(self) -> list[RunDetail]:
        conn = self._connect()
        try:
            rows = conn.execute("select detail_json from runs order by updated_at desc").fetchall()
        finally:
            self._close(conn)
        return [RunDetail.model_validate_json(row[0]) for row in rows]

    @_storage_errors
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

    @_storage_errors
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

    @_storage_errors
    def run_exists(self, run_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("select 1 from runs where id = ? limit 1", (run_id,)).fetchone()
        finally:
            self._close(conn)
        return row is not None

    @_storage_errors
    def ping(self) -> bool:
        conn = self._connect()
        try:
            conn.execute("select 1").fetchone()
        finally:
            self._close(conn)
        return True

    @_storage_errors
    def load_active_operation(self, run_id: str) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """select operation_id from execution_control_tickets
                where run_id=? and state in ('queued','running') order by id desc limit 1""",
                (run_id,),
            ).fetchone()
            return row[0] if row else None
        finally:
            self._close(conn)

    @_storage_errors
    def finish_admission_failure(
        self, ticket: ExecutionTicket, event: RunEvent,
    ) -> tuple[RunDetail, int] | None:
        """CAS-finish only the latest abandoned ticket's still queued snapshot."""
        if event.run_id != ticket.run_id:
            raise ValueError("Admission failure event scope differs")
        snapshot = self.load_run_snapshot(ticket.run_id)
        if snapshot is None or snapshot[0].status != "queued":
            return None
        detail, revision = snapshot
        try:
            with self.control_write(ticket.run_id, revision):
                row = self._connect().execute(
                    "select id,state from execution_control_tickets "
                    "where run_id=? order by id desc limit 1", (ticket.run_id,),
                ).fetchone()
                if row is None or row[0] != ticket.id or row[1] not in {"cancelled", "timedout"}:
                    return None
                detail.status, detail.current_node = "failed", None
                detail.updated_at = datetime.utcnow()
                revision = self.save_run(detail, expected_revision=revision)
                self.append_event(event, control_event=True)
                return detail, revision
        except ExecutionConflictError:
            # A newer owner or control revision has authority now.
            return None

    @_storage_errors
    def load_run_snapshot(self, run_id: str) -> tuple[RunDetail, int] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "select detail_json, revision from runs where id=?", (run_id,),
            ).fetchone()
        finally:
            self._close(conn)
        if row is None:
            return None
        return RunDetail.model_validate_json(row[0]), row[1]

    def load_run(self, run_id: str) -> RunDetail | None:
        snapshot = self.load_run_snapshot(run_id)
        return snapshot[0] if snapshot else None

    @_storage_errors
    def load_events(self, run_id: str, *, after_event_id: int = 0) -> list[RunEvent]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select event_json from events where run_id=? and event_id>? order by event_id asc",
                (run_id, after_event_id),
            ).fetchall()
        finally:
            self._close(conn)
        return [RunEvent.model_validate_json(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        if self._control_conn.get() is not None:
            return self._control_conn.get()
        if self._memory_conn is not None:
            return self._memory_conn
        return sqlite3.connect(self._db_path)

    def _close(self, conn: sqlite3.Connection) -> None:
        if self._control_conn.get() is conn:
            return
        if conn.in_transaction:
            conn.rollback()
        if conn is not self._memory_conn:
            conn.close()

    @_storage_errors
    def _init_db(self) -> None:
        conn = self._connect()
        try:
            # Lock before inspecting schema so concurrent legacy migrations
            # cannot both decide to add the same column. This is synchronous.
            conn.execute("begin immediate")
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
            conn.execute("""create table if not exists report_projections (
                run_id text not null, version_id text not null, projection_json text not null,
                primary key (run_id, version_id))""")
            if "revision" not in {row[1] for row in conn.execute("pragma table_info(runs)")}:
                conn.execute("alter table runs add column revision integer not null default 1")
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
            if "command_id" not in {row[1] for row in conn.execute("pragma table_info(events)")}:
                conn.execute("alter table events add column command_id text")
            conn.execute(
                "create unique index if not exists event_command_id on events(run_id, command_id)"
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
