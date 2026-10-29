"""One bounded asynchronous pool per process and event loop."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolClosed, PoolTimeout, TooManyRequests

from packages.config.settings import Settings, get_settings

from .connection_logging import protected_connection_logging
from .errors import (
    TaskCenterConfigurationError,
    TaskCenterDisabled,
    TaskCenterPoolBusy,
    TaskCenterSchemaError,
    TaskCenterStorageError,
    TaskCenterUnavailable,
)
from .migrations import load_migrations

TENANT_TABLES = frozenset(
    {
        "workspace_policies",
        "quota_buckets",
        "submissions",
        "quota_entries",
        "outbox",
        "dispatch_attempts",
        "audit_events",
    }
)


class _RedactedAsyncConnection(psycopg.AsyncConnection):
    @classmethod
    async def connect(cls, *args, **kwargs):
        # psycopg_pool logs connection exceptions during its retry loop. Remove
        # driver messages there as well as at our public exception boundary.
        try:
            with protected_connection_logging():
                return await super().connect(*args, **kwargs)
        except psycopg.Error:
            raise psycopg.OperationalError("task center connection failed") from None


class TaskCenterDatabase:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.pool: AsyncConnectionPool | None = None
        self._pid: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._borrowers = 0
        self._drained = asyncio.Event()
        self._drained.set()

    def _check_context(self) -> None:
        if self._pid != os.getpid() or self._loop is not asyncio.get_running_loop():
            raise TaskCenterUnavailable("task center pool belongs to another process or event loop")

    def _active_pool(self) -> AsyncConnectionPool:
        if not self.settings.task_center_enabled:
            raise TaskCenterDisabled("task center is disabled")
        if self.pool is None or self._closing:
            raise TaskCenterUnavailable("task center pool is not open")
        self._check_context()
        return self.pool

    async def open(self) -> None:
        if not self.settings.task_center_enabled:
            return
        if self.pool is not None:
            self._check_context()
            return
        try:
            conninfo_to_dict(self.settings.task_center_database_url)
            pool = AsyncConnectionPool(
                self.settings.task_center_database_url,
                connection_class=_RedactedAsyncConnection,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": max(
                        1, math.ceil(self.settings.task_center_pool_timeout_seconds)
                    ),
                    "application_name": "task-center",
                },
                min_size=self.settings.task_center_pool_min_size,
                max_size=self.settings.task_center_pool_max_size,
                max_waiting=self.settings.task_center_pool_max_waiting,
                timeout=self.settings.task_center_pool_timeout_seconds,
                reconnect_timeout=self.settings.task_center_pool_timeout_seconds,
                open=False,
                name="task-center",
            )
        except (psycopg.Error, ValueError, TypeError):
            raise TaskCenterConfigurationError(
                "invalid task center database configuration"
            ) from None
        self._closing = False
        self.pool = pool
        self._pid = os.getpid()
        self._loop = asyncio.get_running_loop()
        try:
            await pool.open(wait=False)
            await pool.wait(timeout=self.settings.task_center_pool_timeout_seconds)
            await self.ready()
        except BaseException as exc:
            await self.close()
            if isinstance(exc, (PoolTimeout, PoolClosed, psycopg.Error)):
                raise TaskCenterUnavailable("task center database could not become ready") from None
            raise

    async def close(self) -> None:
        if self.pool is None:
            return
        self._check_context()
        self._closing = True
        await self._drained.wait()
        pool = self.pool
        await pool.close(timeout=self.settings.task_center_pool_timeout_seconds)
        self.pool = None
        self._pid = None
        self._loop = None

    @asynccontextmanager
    async def _connection(self):
        pool = self._active_pool()
        self._borrowers += 1
        self._drained.clear()
        try:
            async with pool.connection() as conn:
                yield conn
        finally:
            self._borrowers -= 1
            if not self._borrowers:
                self._drained.set()

    def stats(self) -> dict[str, int]:
        return self.pool.get_stats() if self.pool is not None else {}

    async def _set_timeouts(self, conn: psycopg.AsyncConnection) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout',%s,true), set_config('lock_timeout',%s,true)",
            (
                str(self.settings.task_center_statement_timeout_ms),
                str(self.settings.task_center_lock_timeout_ms),
            ),
        )

    async def ready(self) -> None:
        """Read-only role/schema verification. Never installs or repairs schema."""
        if not self.settings.task_center_enabled:
            return
        self._active_pool()
        expected = {migration.version: migration.sha256 for migration in load_migrations()}
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_timeouts(conn)
                    role = await (
                        await conn.execute(
                            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                        )
                    ).fetchone()
                    if role is None or role["rolsuper"] or role["rolbypassrls"]:
                        raise TaskCenterSchemaError(
                            "task center requires a restricted application role"
                        )
                    versions = await (
                        await conn.execute(
                            "SELECT version,sha256 FROM task_center.schema_migrations"
                        )
                    ).fetchall()
                    if {row["version"]: row["sha256"] for row in versions} != expected:
                        raise TaskCenterSchemaError("task center schema version does not match")
                    tables = await (
                        await conn.execute(
                            "SELECT relname,relrowsecurity,relforcerowsecurity,"
                            "pg_has_role(current_user,relowner,'USAGE') AS owns_table "
                            "FROM pg_class WHERE relnamespace='task_center'::regnamespace "
                            "AND relkind='r' AND relname <> 'schema_migrations'"
                        )
                    ).fetchall()
                    if {row["relname"] for row in tables} != TENANT_TABLES or any(
                        not row["relrowsecurity"]
                        or not row["relforcerowsecurity"]
                        or row["owns_table"]
                        for row in tables
                    ):
                        raise TaskCenterSchemaError("task center tenant protections are not ready")
                    privileges = await (
                        await conn.execute(
                            "SELECT has_schema_privilege("
                            "current_user,'task_center','CREATE') AS ddl, "
                            "has_table_privilege(current_user,'task_center.schema_migrations',"
                            "'INSERT,UPDATE,DELETE,TRUNCATE') AS metadata_write"
                        )
                    ).fetchone()
                    if privileges["ddl"] or privileges["metadata_write"]:
                        raise TaskCenterSchemaError(
                            "task center application role must not own migrations"
                        )
        except (PoolTimeout, TooManyRequests):
            raise TaskCenterPoolBusy("task center connection pool is busy") from None
        except (PoolClosed, psycopg.Error):
            raise TaskCenterSchemaError("task center schema is not ready") from None

    @asynccontextmanager
    async def transaction(
        self,
        workspace_id: str,
        *,
        service_role: bool = False,
    ) -> AsyncIterator[psycopg.AsyncConnection]:
        self._active_pool()
        if not isinstance(workspace_id, str) or (not workspace_id.strip() and not service_role):
            raise TaskCenterConfigurationError("task center transaction requires a workspace")
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_timeouts(conn)
                    # Trusted service code chooses scope. Custom GUCs do not
                    # protect against an attacker with arbitrary SQL execution.
                    await conn.execute(
                        "SELECT set_config('app.current_workspace_id',%s,true), "
                        "set_config('app.service_role',%s,true)",
                        (workspace_id, "on" if service_role else "off"),
                    )
                    yield conn
        except (PoolTimeout, TooManyRequests):
            raise TaskCenterPoolBusy("task center connection pool is busy") from None
        except PoolClosed:
            raise TaskCenterUnavailable("task center pool is closed") from None
        except psycopg.Error as exc:
            raise TaskCenterStorageError(sqlstate=exc.sqlstate) from None
