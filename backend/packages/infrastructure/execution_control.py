"""Bounded execution admission for processes sharing one local SQLite file.

POSIX flock, rather than heartbeat age or PID inspection, protects in-flight
work. Lock files must remain in place: unlinking them creates independent lock
inodes. This module does not provide cross-host coordination or exactly-once
external effects. All asynchronous database operations use awaited short worker
transactions; no transaction spans graph/model execution.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

try:
    import fcntl
except ImportError:  # pragma: no cover - supported platforms are POSIX only.
    fcntl = None  # type: ignore[assignment]


class ExecutionControlError(RuntimeError):
    status_code = 503
    retry_after_seconds = 1


class ExecutionCapacityError(ExecutionControlError):
    """Admission queue is full; no ticket was created."""

    status_code = 429


class ExecutionConflictError(ExecutionControlError):
    """Run ownership, an idempotency scope, or pool configuration conflicts."""

    status_code = 409


class ExecutionTimeoutError(ExecutionControlError):
    """A queue/model deadline elapsed before execution started."""


class ExecutionUnavailableError(ExecutionControlError):
    """Authoritative local storage or kernel locking is unavailable."""


@dataclass(frozen=True)
class ExecutionPolicy:
    global_running_limit: int = 2
    workspace_running_limit: int = 1
    global_queue_limit: int = 32
    workspace_queue_limit: int = 8
    queue_wait_seconds: float = 60
    model_concurrency: int = 4
    model_wait_seconds: float = 30

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name.endswith("seconds"):
                valid = type(value) in (int, float) and math.isfinite(value) and value > 0
            else:
                valid = type(value) is int and value > 0
            if not valid:
                raise ValueError(f"{name} must be a finite positive number")


@dataclass(frozen=True)
class ExecutionTicket:
    """An immutable admission snapshot; replay returns the persisted state."""

    id: int
    run_id: str
    workspace_id: str
    operation_id: str
    state: str
    enqueued_at: float
    deadline: float
    pool_path: str


class _FileLock:
    def __init__(self, fd: int, slot: int | None = None) -> None:
        self.fd: int | None = fd
        self.slot = slot

    @classmethod
    def try_acquire(cls, path: Path, slot: int | None = None) -> _FileLock | None:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return None
            raise
        return cls(fd, slot)

    def close(self) -> None:
        fd, self.fd = self.fd, None
        if fd is not None:
            os.close(fd)


@dataclass
class ExecutionLauncher:
    """The unique consumer of one admission, including its queued wait."""

    ticket: ExecutionTicket
    lock: _FileLock
    owner_task: asyncio.Task[Any] | None = None


@dataclass
class _Ownership:
    ticket: ExecutionTicket
    token: str
    generation: int
    lock: _FileLock
    launcher: ExecutionLauncher | None = None


_T = TypeVar("_T")
_current_lease: ContextVar[ExecutionLease | None] = ContextVar("execution_lease", default=None)


async def _settle(task: asyncio.Task[_T]) -> _T:
    """Finish bounded cleanup even if the caller is cancelled more than once."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def _thread(
    function: Callable[..., _T],
    *args: Any,
    on_cancel: Callable[[_T], Any] | None = None,
) -> _T:
    worker = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancelling to_thread does not stop its thread. Observe the result and
        # undo any newly committed ticket or acquired FD before propagating.
        try:
            result = await _settle(worker)
        except Exception:
            pass
        else:
            if on_cancel is not None:
                await _settle(asyncio.create_task(asyncio.to_thread(on_cancel, result)))
        raise


class ExecutionLease:
    """Owns the run lock until release or the explicitly handed-off task exits."""

    def __init__(self, coordinator: SQLiteExecutionCoordinator, ownership: _Ownership) -> None:
        self.coordinator = coordinator
        self.ticket = ownership.ticket
        self.token = ownership.token
        self.generation = ownership.generation
        self._ownership = ownership
        self._owner_task = asyncio.current_task()
        self._handoff_task: asyncio.Task[Any] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._released = False
        self._closed = asyncio.Event()
        self._release_error: BaseException | None = None

    def _check_task(self) -> None:
        if self._released or asyncio.current_task() is not self._owner_task:
            raise ExecutionConflictError("Execution lease is released or belongs to another task")

    async def heartbeat(self) -> None:
        self._check_task()
        await _thread(self.coordinator._heartbeat_sync, self)

    def handoff(self, task: asyncio.Task[Any]) -> None:
        """Transfer once to a created task, before the outer guard exits.

        Create the task inside the guard so its ContextVar contains this lease.
        Register immediately after create_task, before yielding to that task.
        The task's completion callback releases the lease for every outcome.
        """
        if not isinstance(task, asyncio.Task):
            raise TypeError("handoff requires an already created asyncio.Task")
        self._check_task()
        if self._handoff_task is not None or task.done() or task is self._owner_task:
            raise ExecutionConflictError("Execution lease can be handed off only once")
        if task.get_loop() is not asyncio.get_running_loop():
            raise ExecutionConflictError("Handoff task must use the current event loop")
        self._handoff_task = task
        self._owner_task = task
        task.add_done_callback(self._background_done)

    def _background_done(self, task: asyncio.Task[Any]) -> None:
        self._cleanup_task = asyncio.create_task(
            self._release_internal("cancelled" if task.cancelled() else "finished")
        )
        # Retrieving cleanup exceptions avoids an unobserved task warning while
        # preserving the error for callers awaiting wait_closed().
        self._cleanup_task.add_done_callback(
            lambda done: done.exception() if not done.cancelled() else None
        )

    async def release(self, state: str = "finished") -> None:
        """Release only from the task currently owning this lease's lifecycle."""
        if asyncio.current_task() is not self._owner_task:
            raise ExecutionConflictError(
                "Only the current owner task may release an execution lease"
            )
        await self._release_internal(state)

    async def _release_internal(self, state: str) -> None:
        """Owner release or the registered handoff completion callback only."""
        if state not in {"finished", "cancelled", "timedout"}:
            raise ValueError("Invalid terminal execution state")
        if self._released:
            await self.wait_closed()
            return
        self._released = True
        try:
            await _thread(self.coordinator._release_sync, self._ownership, state)
        except BaseException as exc:
            self._release_error = exc
            raise
        finally:
            self._closed.set()

    async def wait_closed(self) -> None:
        await self._closed.wait()
        if self._release_error is not None:
            raise self._release_error


class SQLiteExecutionCoordinator:
    """One bounded admission/model pool keyed by a canonical local DB path."""

    _poll_seconds = 0.01

    def __init__(self, db_path: Path, policy: ExecutionPolicy | None = None) -> None:
        if str(db_path) == ":memory:" or fcntl is None:
            raise ExecutionUnavailableError("Execution control requires a POSIX file database")
        self.db_path = Path(db_path).resolve()
        self.policy = policy or ExecutionPolicy()
        self._lock_dir = self.db_path.with_name(self.db_path.name + ".execution-locks")
        normalized = asdict(self.policy)
        for field in ("queue_wait_seconds", "model_wait_seconds"):
            normalized[field] = float(normalized[field])
        self._policy_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=1)
            conn.row_factory = sqlite3.Row
            conn.execute("begin immediate")
            conn.execute("""create table if not exists execution_control_pool (
                id integer primary key check(id = 1), policy_json text not null)""")
            conn.execute("""create table if not exists execution_control_tickets (
                id integer primary key autoincrement,
                run_id text not null, workspace_id text not null, operation_id text not null,
                state text not null, enqueued_at real not null, deadline real not null,
                started_at real, ended_at real, token text, generation integer not null default 0,
                heartbeat_at real, owner_pid integer, reason text,
                unique(run_id, operation_id))""")
            conn.execute("""create index if not exists execution_control_queue
                on execution_control_tickets(state, workspace_id, id)""")
            conn.execute("""create table if not exists execution_control_runs (
                run_id text primary key, generation integer not null default 0,
                token text, ticket_id integer, heartbeat_at real)""")
            conn.execute(
                "insert or ignore into execution_control_pool values (1, ?)", (self._policy_json,)
            )
            actual = conn.execute("select policy_json from execution_control_pool where id=1")
            if actual.fetchone()[0] != self._policy_json:
                raise ExecutionConflictError("Shared execution pool configuration differs")
            yield conn
            conn.commit()
        except (sqlite3.Error, OSError) as exc:
            raise ExecutionUnavailableError("Local execution coordination is unavailable") from exc
        finally:
            if conn is not None:
                conn.close()

    def _run_lock(self, run_id: str) -> _FileLock | None:
        digest = hashlib.sha256(run_id.encode()).hexdigest()
        return _FileLock.try_acquire(self._lock_dir / f"run-{digest}.lock")

    def _sweep(self, conn: sqlite3.Connection) -> None:
        now = time.time()
        conn.execute(
            """update execution_control_tickets set state='timedout', ended_at=?,
            reason='queue_deadline' where state='queued' and deadline <= ?""",
            (now, now),
        )
        active = conn.execute("select * from execution_control_tickets where state='running'")
        for row in active.fetchall():
            lock = self._run_lock(row["run_id"])
            if lock is None:
                continue
            try:
                conn.execute(
                    """update execution_control_tickets set state='cancelled',
                    ended_at=?, reason='owner_exited' where id=? and state='running'""",
                    (now, row["id"]),
                )
                conn.execute(
                    """update execution_control_runs set token=null, ticket_id=null,
                    heartbeat_at=null where run_id=? and token=? and generation=?""",
                    (row["run_id"], row["token"], row["generation"]),
                )
            finally:
                lock.close()

    def _ticket(self, row: sqlite3.Row) -> ExecutionTicket:
        return ExecutionTicket(
            **{
                key: row[key]
                for key in (
                    "id",
                    "run_id",
                    "workspace_id",
                    "operation_id",
                    "state",
                    "enqueued_at",
                    "deadline",
                )
            },
            pool_path=str(self.db_path),
        )

    @staticmethod
    def _validate_scope(value: str) -> None:
        if type(value) is not str or not value or len(value) > 512:
            raise ValueError("Execution identifiers must contain 1 to 512 characters")

    async def admit(self, run_id: str, workspace_id: str, operation_id: str) -> ExecutionTicket:
        for value in (run_id, workspace_id, operation_id):
            self._validate_scope(value)
        result = await _thread(
            self._admit_sync,
            run_id,
            workspace_id,
            operation_id,
            on_cancel=self._cancel_admission_sync,
        )
        return result[0]

    def _admit_sync(
        self, run_id: str, workspace_id: str, operation_id: str
    ) -> tuple[ExecutionTicket, bool]:
        with self._transaction() as conn:
            self._sweep(conn)
            existing = conn.execute(
                """select * from execution_control_tickets
                where run_id=? and operation_id=?""",
                (run_id, operation_id),
            ).fetchone()
            if existing is not None:
                if existing["workspace_id"] != workspace_id:
                    raise ExecutionConflictError("Idempotent operation workspace differs")
                return self._ticket(existing), False
            if conn.execute(
                """select 1 from execution_control_tickets where run_id=?
                and state in ('queued', 'running')""",
                (run_id,),
            ).fetchone():
                raise ExecutionConflictError("Run already has an active operation")
            counts = conn.execute(
                """select count(*), coalesce(sum(workspace_id=?), 0)
                from execution_control_tickets where state='queued'""",
                (workspace_id,),
            ).fetchone()
            if (
                counts[0] >= self.policy.global_queue_limit
                or counts[1] >= self.policy.workspace_queue_limit
            ):
                raise ExecutionCapacityError("Execution admission queue is full")
            now = time.time()
            cursor = conn.execute(
                """insert into execution_control_tickets
                (run_id, workspace_id, operation_id, state, enqueued_at, deadline)
                values (?, ?, ?, 'queued', ?, ?)""",
                (run_id, workspace_id, operation_id, now, now + self.policy.queue_wait_seconds),
            )
            row = conn.execute(
                "select * from execution_control_tickets where id=?", (cursor.lastrowid,)
            ).fetchone()
            return self._ticket(row), True

    def _cancel_admission_sync(self, result: tuple[ExecutionTicket, bool]) -> None:
        if result[1]:
            self._cancel_queued_sync(result[0])

    async def cancel(self, ticket: ExecutionTicket) -> bool:
        """Abandon queued admission after startup failure; never stop a running lease."""
        if ticket.pool_path != str(self.db_path):
            raise ExecutionConflictError("Admission ticket belongs to another database")
        return await _thread(self._cancel_queued_sync, ticket)

    def _cancel_queued_sync(self, ticket: ExecutionTicket) -> bool:
        with self._transaction() as conn:
            self._sweep(conn)
            cursor = conn.execute(
                """update execution_control_tickets set state='cancelled',
                ended_at=?, reason='caller_cancelled' where id=? and state='queued'""",
                (time.time(), ticket.id),
            )
            return cursor.rowcount > 0

    def current_lease(self, run_id: str) -> ExecutionLease | None:
        """Read inherited fence metadata without granting lifecycle ownership."""
        lease = _current_lease.get()
        if (
            lease is None
            or lease.coordinator.db_path != self.db_path
            or lease.ticket.run_id != run_id
        ):
            return None
        if lease._released:
            raise ExecutionConflictError("Execution lease is released")
        return lease

    def _try_launcher_sync(self, ticket: ExecutionTicket) -> ExecutionLauncher | None:
        if ticket.pool_path != str(self.db_path):
            raise ExecutionConflictError("Admission ticket belongs to another database")
        try:
            lock = _FileLock.try_acquire(self._lock_dir / f"launcher-{ticket.id}.lock")
        except OSError as exc:
            raise ExecutionUnavailableError("Execution launcher locking is unavailable") from exc
        return ExecutionLauncher(ticket, lock) if lock is not None else None

    def try_launcher(self, ticket: ExecutionTicket) -> ExecutionLauncher | None:
        """Synchronously reserve a launcher before creating a background task.

        This is one nonblocking local flock attempt; it performs no waiting or
        database transaction. A duplicate never receives cancellation authority.
        """
        launcher = self._try_launcher_sync(ticket)
        if launcher is not None:
            launcher.owner_task = asyncio.current_task()
        return launcher

    def handoff_launcher(self, launcher: ExecutionLauncher, task: asyncio.Task[Any]) -> None:
        if launcher.owner_task is not asyncio.current_task() or launcher.lock.fd is None:
            raise ExecutionConflictError("Launcher belongs to another task or is closed")
        if not isinstance(task, asyncio.Task) or task.done() or task is launcher.owner_task:
            raise ExecutionConflictError("Launcher requires a new background task")
        launcher.owner_task = task

    def _cancel_launcher_sync(self, launcher: ExecutionLauncher | None) -> bool:
        if launcher is None or launcher.lock.fd is None:
            return False
        try:
            # The launcher flock remains held through cancellation, so a replay
            # cannot cancel a different consumer between the check and update.
            return self._cancel_queued_sync(launcher.ticket)
        finally:
            launcher.lock.close()

    @asynccontextmanager
    async def run(
        self, ticket: ExecutionTicket, *, launcher: ExecutionLauncher | None = None,
    ) -> AsyncIterator[ExecutionLease]:
        if ticket.pool_path != str(self.db_path):
            raise ExecutionConflictError("Admission ticket belongs to another database")
        nested = self.current_lease(ticket.run_id)
        if nested is not None:
            nested._check_task()
            await _thread(self._heartbeat_sync, nested)
            yield nested
            return
        if launcher is None:
            launcher = await _thread(
                self._try_launcher_sync, ticket, on_cancel=self._cancel_launcher_sync,
            )
            if launcher is None:
                raise ExecutionConflictError("Admission already has an execution launcher")
            launcher.owner_task = asyncio.current_task()
        elif (
            launcher.ticket.id != ticket.id or launcher.ticket.pool_path != ticket.pool_path
            or launcher.owner_task is not asyncio.current_task() or launcher.lock.fd is None
        ):
            raise ExecutionConflictError("Execution launcher belongs to another task or ticket")
        ownership = None
        try:
            try:
                while ownership is None:
                    ownership = await _thread(
                        self._claim_sync, ticket, on_cancel=self._cancel_claim_sync,
                    )
                    if ownership is None:
                        await asyncio.sleep(self._poll_seconds)
            except asyncio.CancelledError:
                await _settle(asyncio.create_task(
                    asyncio.to_thread(self._cancel_queued_sync, ticket)
                ))
                raise
            except ExecutionConflictError:
                # A scope/policy conflict never grants authority to revoke that ticket.
                raise
            except Exception:
                # This caller still owns the launcher. Finish its abandoned
                # queued admission before releasing that cancellation authority.
                # A second short transaction can outlast a transient SQLite lock;
                # persistent storage failure stays explicit and never retries forever.
                try:
                    await _thread(self._cancel_queued_sync, ticket)
                except ExecutionControlError as cleanup_error:
                    raise ExecutionUnavailableError(
                        "Execution claim failed and admission cleanup storage is unavailable"
                    ) from cleanup_error
                raise
            ownership.launcher = launcher
            launcher = None  # The run lease, including handoff, now owns both locks.
            lease = ExecutionLease(self, ownership)
            context = _current_lease.set(lease)
            state = "finished"
            try:
                yield lease
            except asyncio.CancelledError:
                state = "cancelled"
                raise
            finally:
                _current_lease.reset(context)
                if lease._handoff_task is None:
                    await lease.release(state)
        finally:
            if launcher is not None:
                launcher.lock.close()

    def _claim_sync(self, ticket: ExecutionTicket) -> _Ownership | None:
        lock = None
        try:
            with self._transaction() as conn:
                self._sweep(conn)
                row = conn.execute(
                    "select * from execution_control_tickets where id=?", (ticket.id,)
                ).fetchone()
                if row is None or (row["run_id"], row["workspace_id"], row["operation_id"]) != (
                    ticket.run_id,
                    ticket.workspace_id,
                    ticket.operation_id,
                ):
                    raise ExecutionConflictError("Unknown or mismatched admission ticket")
                if row["state"] == "timedout":
                    # Preserve the expiry transition even though the caller
                    # receives an error rather than an acquired lease.
                    conn.commit()
                    raise ExecutionTimeoutError("Execution queue deadline elapsed")
                if row["state"] != "queued":
                    raise ExecutionConflictError("Admission operation is no longer queued")
                counts = conn.execute(
                    """select count(*), coalesce(sum(workspace_id=?), 0)
                    from execution_control_tickets where state='running'""",
                    (ticket.workspace_id,),
                ).fetchone()
                older = conn.execute(
                    """select 1 from execution_control_tickets
                    where state='queued' and workspace_id=? and id < ? limit 1""",
                    (ticket.workspace_id, ticket.id),
                ).fetchone()
                if (
                    counts[0] >= self.policy.global_running_limit
                    or counts[1] >= self.policy.workspace_running_limit
                    or older
                ):
                    return None
                lock = self._run_lock(ticket.run_id)
                if lock is None:
                    return None
                now = time.time()
                if now >= row["deadline"]:
                    conn.execute(
                        """update execution_control_tickets set state='timedout',
                        ended_at=?, reason='queue_deadline' where id=? and state='queued'""",
                        (now, ticket.id),
                    )
                    conn.commit()
                    raise ExecutionTimeoutError(
                        "Execution queue deadline elapsed acquiring run lock"
                    )
                conn.execute(
                    "insert or ignore into execution_control_runs (run_id) values (?)",
                    (ticket.run_id,),
                )
                generation = (
                    conn.execute(
                        """select generation from execution_control_runs
                    where run_id=?""",
                        (ticket.run_id,),
                    ).fetchone()[0]
                    + 1
                )
                token = uuid.uuid4().hex
                conn.execute(
                    """update execution_control_runs set generation=?, token=?,
                    ticket_id=?, heartbeat_at=? where run_id=?""",
                    (generation, token, ticket.id, now, ticket.run_id),
                )
                conn.execute(
                    """update execution_control_tickets set state='running',
                    token=?, generation=?, started_at=?, heartbeat_at=?, owner_pid=? where id=?""",
                    (token, generation, now, now, os.getpid(), ticket.id),
                )
                row = conn.execute(
                    "select * from execution_control_tickets where id=?", (ticket.id,)
                ).fetchone()
                ownership = _Ownership(self._ticket(row), token, generation, lock)
            return ownership
        except BaseException:
            if lock is not None:
                lock.close()
            raise

    def _cancel_claim_sync(self, ownership: _Ownership | None) -> None:
        if ownership is not None:
            self._release_sync(ownership, "cancelled")

    def _release_sync(self, ownership: _Ownership, state: str) -> None:
        try:
            with self._transaction() as conn:
                conn.execute(
                    """update execution_control_tickets set state=?, ended_at=?
                    where id=? and state='running' and token=? and generation=?""",
                    (
                        state,
                        time.time(),
                        ownership.ticket.id,
                        ownership.token,
                        ownership.generation,
                    ),
                )
                conn.execute(
                    """update execution_control_runs set token=null, ticket_id=null,
                    heartbeat_at=null where run_id=? and token=? and generation=?""",
                    (ownership.ticket.run_id, ownership.token, ownership.generation),
                )
        finally:
            ownership.lock.close()
            if ownership.launcher is not None:
                ownership.launcher.lock.close()

    def assert_fence(
        self, conn: sqlite3.Connection, run_id: str, token: str, generation: int
    ) -> None:
        """Synchronously fence a journal write in its existing DB transaction.

        A writing caller must BEGIN IMMEDIATE before this check and commit its
        journal change in that same transaction. Do not check then later open a
        different write transaction. A released owner never regains validity
        merely because the run is idle; both token and generation must match.
        """
        try:
            valid = conn.execute(
                """select 1 from execution_control_runs as r
                join execution_control_tickets as t on t.id=r.ticket_id
                where r.run_id=? and r.token=? and r.generation=? and t.state='running'
                and t.token=r.token and t.generation=r.generation""",
                (run_id, token, generation),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ExecutionUnavailableError("Execution fence storage is unavailable") from exc
        if valid is None:
            raise ExecutionConflictError("Execution ownership is no longer current")
        # A failed release transaction can leave a running row after its lock
        # was closed. Such a token is already revoked, even before next sweep.
        # The caller's write transaction serializes this probe with claims.
        try:
            unlocked = self._run_lock(run_id)
        except OSError as exc:
            raise ExecutionUnavailableError("Execution fence locking is unavailable") from exc
        if unlocked is not None:
            unlocked.close()
            raise ExecutionConflictError("Execution owner no longer holds the run lock")

    def _heartbeat_sync(self, lease: ExecutionLease) -> None:
        with self._transaction() as conn:
            self.assert_fence(conn, lease.ticket.run_id, lease.token, lease.generation)
            now = time.time()
            conn.execute(
                """update execution_control_runs set heartbeat_at=?
                where run_id=? and token=? and generation=?""",
                (now, lease.ticket.run_id, lease.token, lease.generation),
            )
            conn.execute(
                "update execution_control_tickets set heartbeat_at=? where id=?",
                (now, lease.ticket.id),
            )

    @asynccontextmanager
    async def model_slot(self) -> AsyncIterator[int]:
        deadline = asyncio.get_running_loop().time() + self.policy.model_wait_seconds
        lock = None
        try:
            while lock is None:
                if asyncio.get_running_loop().time() >= deadline:
                    raise ExecutionTimeoutError("Global model slot deadline elapsed")
                lock = await _thread(
                    self._try_model_slot_sync,
                    on_cancel=lambda result: result.close() if result else None,
                )
                if lock is None:
                    await asyncio.sleep(
                        min(
                            self._poll_seconds, max(0, deadline - asyncio.get_running_loop().time())
                        )
                    )
            if asyncio.get_running_loop().time() >= deadline:
                raise ExecutionTimeoutError("Global model slot deadline elapsed")
            yield lock.slot
        finally:
            if lock is not None:
                lock.close()

    def _try_model_slot_sync(self) -> _FileLock | None:
        # Validate the pool before touching slots; differing N values must never
        # silently form different capacity pools against the same database.
        with self._transaction():
            pass
        try:
            for slot in range(self.policy.model_concurrency):
                lock = _FileLock.try_acquire(self._lock_dir / f"model-{slot}.lock", slot)
                if lock is not None:
                    return lock
        except OSError as exc:
            raise ExecutionUnavailableError("Local model locking is unavailable") from exc
        return None

    async def snapshot(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Return capacity metadata; workspace filtering never returns other tickets."""
        return await _thread(self._snapshot_sync, workspace_id)

    def _snapshot_sync(self, workspace_id: str | None) -> dict[str, Any]:
        with self._transaction() as conn:
            self._sweep(conn)
            counts = conn.execute("""select state, count(*) from execution_control_tickets
                where state in ('queued', 'running') group by state""").fetchall()
            totals = {row[0]: row[1] for row in counts}
            if workspace_id is None:
                rows = conn.execute(
                    "select * from execution_control_tickets order by id"
                ).fetchall()
            else:
                rows = conn.execute(
                    """select * from execution_control_tickets
                    where workspace_id=? order by id""",
                    (workspace_id,),
                ).fetchall()
            result = {
                "queued": totals.get("queued", 0),
                "running": totals.get("running", 0),
                "workspace_queued": sum(row["state"] == "queued" for row in rows),
                "workspace_running": sum(row["state"] == "running" for row in rows),
                "tickets": [dict(row) for row in rows],
                "policy": asdict(self.policy),
            }
            model_active = 0
            for slot in range(self.policy.model_concurrency):
                lock = _FileLock.try_acquire(self._lock_dir / f"model-{slot}.lock", slot)
                if lock is None:
                    model_active += 1
                else:
                    lock.close()
            result["model_active"] = model_active
            return result
