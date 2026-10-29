import asyncio
import logging
import shutil
import subprocess
import time
import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from packages.config.settings import Settings
from packages.task_center.database import TaskCenterDatabase
from packages.task_center.errors import (
    MigrationDriftError,
    TaskCenterConfigurationError,
    TaskCenterDisabled,
    TaskCenterPoolBusy,
    TaskCenterSchemaError,
    TaskCenterStorageError,
    TaskCenterUnavailable,
)
from packages.task_center.migrations import apply_migrations, load_migrations
from scripts.local_postgres import OwnedPostgres, OwnedPostgresError

pytest_plugins = ("postgres_support",)


def test_owned_postgres_uses_private_socket_and_cleans_up() -> None:
    with OwnedPostgres() as postgres:
        assert isinstance(postgres.root, Path), "owned cluster must allocate a private directory"
        root = postgres.root
        assert root.stat().st_mode & 0o777 == 0o700
        with psycopg.connect(postgres.owner_dsn) as conn:
            assert conn.execute("SHOW listen_addresses").fetchone() == ("",)
            assert conn.execute("SELECT current_user").fetchone() == ("task_center_owner",)
        assert postgres.pid > 0
    assert not root.exists()
    assert not postgres.is_running


def test_explicit_migration_creates_real_schema_and_is_idempotent() -> None:
    with OwnedPostgres() as postgres:
        assert apply_migrations(postgres.owner_dsn) == [item.version for item in load_migrations()]
        with psycopg.connect(postgres.owner_dsn) as conn:
            first = conn.execute(
                "SELECT oid FROM pg_class WHERE oid='task_center.submissions'::regclass"
            ).fetchone()
            versions = conn.execute(
                "SELECT version, length(sha256) FROM task_center.schema_migrations"
            ).fetchall()
        assert apply_migrations(postgres.owner_dsn) == []
        with psycopg.connect(postgres.owner_dsn) as conn:
            second = conn.execute(
                "SELECT oid FROM pg_class WHERE oid='task_center.submissions'::regclass"
            ).fetchone()
        assert first == second
        assert sorted(versions) == [(item.version, 64) for item in load_migrations()]


def test_failed_owned_start_removes_only_its_temporary_directory() -> None:
    postgres = OwnedPostgres(binary_dir=Path("/private/tmp/task-center-absent-binaries"))
    with pytest.raises(OwnedPostgresError):
        postgres.start()
    assert postgres.root is not None
    assert not postgres.root.exists()
    assert not postgres.is_running


@pytest.mark.parametrize("stage", ("chmod", "marker", "socket"))
def test_preparation_failure_removes_just_allocated_directory(monkeypatch, stage) -> None:
    postgres = OwnedPostgres()
    original_chmod = Path.chmod
    original_write = Path.write_text
    original_mkdir = Path.mkdir

    def fail_chmod(path, *args, **kwargs):
        if stage == "chmod" and path == postgres.root:
            raise OSError("injected preparation failure")
        return original_chmod(path, *args, **kwargs)

    def fail_write(path, *args, **kwargs):
        if stage == "marker" and path.name == ".owned-postgres" and path.parent == postgres.root:
            raise OSError("injected preparation failure")
        return original_write(path, *args, **kwargs)

    def fail_mkdir(path, *args, **kwargs):
        if stage == "socket" and path.name == "socket" and path.parent == postgres.root:
            raise OSError("injected preparation failure")
        return original_mkdir(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "chmod", fail_chmod)
            patch.setattr(Path, "write_text", fail_write)
            patch.setattr(Path, "mkdir", fail_mkdir)
            with pytest.raises(OSError, match="injected preparation failure"):
                postgres.start()
        assert postgres.root is not None
        assert postgres.pid == 0
        assert not postgres.root.exists(), "preparation failure must clean its allocated directory"
    finally:
        # The injected preparation failures occur before any PostgreSQL command.
        # Remove the red-test allocation even when the cleanup assertion fails.
        if postgres.root is not None and postgres.root.exists():
            shutil.rmtree(postgres.root)


@pytest.mark.parametrize(
    "returncode,diagnostic",
    (
        (2, "ps: diagnostic failure"),
        (1, "ps: permission denied"),
        (1, ""),
        (0, "ps: diagnostic failure"),
    ),
)
def test_ps_failure_never_deletes_or_signals_live_cluster(monkeypatch, returncode, diagnostic):
    with OwnedPostgres() as postgres:
        original_run = subprocess.run
        deletes = []
        stops = []

        def fail_process_observation(command, *args, **kwargs):
            if command[0] == "/bin/ps":
                output = original_run(command, *args, **kwargs).stdout if returncode == 0 else ""
                return subprocess.CompletedProcess(command, returncode, output, diagnostic)
            if Path(command[0]).name == "pg_ctl" and "stop" in command:
                stops.append(command)
                raise AssertionError("must not signal while process observation is uncertain")
            return original_run(command, *args, **kwargs)

        def reject_delete(path, *args, **kwargs):
            deletes.append(path)
            raise AssertionError("must not delete a live cluster on process observation failure")

        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", fail_process_observation)
            patch.setattr(shutil, "rmtree", reject_delete)
            with pytest.raises(OwnedPostgresError):
                postgres.stop()
        assert not deletes
        assert not stops
        assert postgres.is_running
        with psycopg.connect(postgres.owner_dsn) as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
    assert not postgres.root.exists()


def test_confirmed_exited_cluster_with_stale_pid_file_can_be_cleaned() -> None:
    with OwnedPostgres() as postgres:
        assert postgres.is_running
        pid_file = postgres.data_dir / "postmaster.pid"
        previous_pid_file = pid_file.read_bytes()
        postgres._run(
            "pg_ctl",
            "-D",
            str(postgres.data_dir),
            "-m",
            "fast",
            "-w",
            "-t",
            "15",
            "stop",
        )
        pid_file.write_bytes(previous_pid_file)
        assert postgres._server_pid() is None
    assert not postgres.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_path", ("pool", "migration"))
async def test_module_connection_debug_logs_never_include_dsn_secrets(
    owned_postgres,
    caplog,
    connection_path,
) -> None:
    marker = "tc_fake_debug_secret"
    invalid_dsn = make_conninfo(owned_postgres.app_dsn, options=f"-c {marker}=fake")
    driver_logger = logging.getLogger("psycopg")
    with caplog.at_level(logging.DEBUG, logger="psycopg"):
        driver_logger.debug("unrelated diagnostic before connection")
        if connection_path == "pool":
            database = TaskCenterDatabase(
                Settings(
                    task_center_enabled=True,
                    task_center_database_url=invalid_dsn,
                    task_center_pool_timeout_seconds=0.1,
                )
            )
            with pytest.raises(TaskCenterUnavailable) as caught:
                await database.open()
            assert database.pool is None
        else:
            with pytest.raises(TaskCenterSchemaError) as caught:
                apply_migrations(invalid_dsn)
        driver_logger.debug("unrelated diagnostic after connection")
    assert marker not in str(caught.value)
    assert marker not in caplog.text
    assert invalid_dsn not in caplog.text
    assert "unrelated diagnostic before connection" in caplog.text
    assert "unrelated diagnostic after connection" in caplog.text


def test_migration_checksum_drift_is_rejected_without_changes(task_postgres, tmp_path) -> None:
    source = Path("backend/packages/task_center/migrations/001_core.sql")
    for migration_source in source.parent.glob("*.sql"):
        shutil.copy(migration_source, tmp_path / migration_source.name)
    with (tmp_path / source.name).open("a") as handle:
        handle.write("\n-- drift\n")
    with pytest.raises(MigrationDriftError):
        apply_migrations(task_postgres.owner_dsn, tmp_path)
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM task_center.schema_migrations").fetchone() == (
            len(load_migrations()),
        )


def test_all_tenant_tables_force_rls_and_application_has_no_history_mutation(task_postgres) -> None:
    with psycopg.connect(task_postgres.app_dsn) as conn:
        role = conn.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False)
        tables = conn.execute(
            "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE relnamespace='task_center'::regnamespace AND relkind='r' "
            "AND relname <> 'schema_migrations'"
        ).fetchall()
        assert len(tables) == 7
        assert all(rls and forced for _, rls, forced in tables)
        for table in ("quota_entries", "audit_events", "schema_migrations"):
            assert not conn.execute(
                "SELECT has_table_privilege(current_user,%s,'UPDATE,DELETE')",
                (f"task_center.{table}",),
            ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(current_user,'task_center.schema_migrations','INSERT')"
        ).fetchone()[0]


@pytest.mark.asyncio
async def test_open_builds_a_bounded_real_pool(task_database) -> None:
    assert task_database.pool is not None, "enabled database must explicitly open its own pool"
    await task_database.ready()
    assert task_database.stats()["pool_size"] == 1


@pytest.mark.asyncio
async def test_default_disabled_database_does_no_database_io() -> None:
    database = TaskCenterDatabase(Settings(task_center_database_url="invalid secret DSN"))
    await database.open()
    await database.ready()
    assert database.pool is None
    with pytest.raises(TaskCenterDisabled):
        async with database.transaction("ws-a"):
            pytest.fail("disabled transaction must not start")
    await database.close()


@pytest.mark.asyncio
async def test_pool_cannot_be_used_from_another_event_loop(task_database) -> None:
    def other_loop():
        return asyncio.run(task_database.ready())

    with pytest.raises(TaskCenterUnavailable, match="another process or event loop"):
        await asyncio.to_thread(other_loop)
    await task_database.ready()


@pytest.mark.asyncio
async def test_startup_failures_do_not_expose_dsn_or_leave_pool(caplog) -> None:
    for dsn, error in (
        ("password=tc-secret invalid-option", TaskCenterConfigurationError),
        (
            "host=/private/tmp/task-center-absent-socket user=tc-secret password=tc-secret",
            TaskCenterUnavailable,
        ),
    ):
        database = TaskCenterDatabase(
            Settings(
                task_center_enabled=True,
                task_center_database_url=dsn,
                task_center_pool_timeout_seconds=0.1,
            )
        )
        with pytest.raises(error) as caught:
            await database.open()
        assert database.pool is None
        assert "tc-secret" not in str(caught.value)
    assert "tc-secret" not in caplog.text


@pytest.mark.asyncio
async def test_exception_rolls_back_real_transaction(task_database) -> None:
    with pytest.raises(RuntimeError, match="abort"):
        async with task_database.transaction("ws-a") as conn:
            await conn.execute(
                "INSERT INTO task_center.workspace_policies "
                "(workspace_id,run_limit,enforcement) VALUES ('ws-a',1,'block')"
            )
            raise RuntimeError("abort")
    async with task_database.transaction("ws-a") as conn:
        row = await (
            await conn.execute("SELECT count(*) AS n FROM task_center.workspace_policies")
        ).fetchone()
    assert row["n"] == 0


@pytest.mark.asyncio
async def test_real_rls_blocks_cross_tenant_reads_and_writes(task_database) -> None:
    async with task_database.transaction("", service_role=True) as conn:
        await conn.execute(
            "INSERT INTO task_center.workspace_policies (workspace_id,run_limit,enforcement) "
            "VALUES ('ws-a',1,'block'),('ws-b',2,'monitor')"
        )
    async with task_database.transaction("ws-a") as conn:
        rows = await (
            await conn.execute("SELECT workspace_id FROM task_center.workspace_policies")
        ).fetchall()
        assert rows == [{"workspace_id": "ws-a"}]
        result = await conn.execute(
            "UPDATE task_center.workspace_policies SET run_limit=99 WHERE workspace_id='ws-b'"
        )
        assert result.rowcount == 0
    with pytest.raises(TaskCenterStorageError) as caught:
        async with task_database.transaction("ws-a") as conn:
            await conn.execute(
                "INSERT INTO task_center.workspace_policies (workspace_id,run_limit,enforcement) "
                "VALUES ('ws-secret',1,'block')"
            )
    assert caught.value.sqlstate == "42501"
    assert "ws-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_reused_connection_does_not_keep_tenant_or_service_role(task_database) -> None:
    async with task_database.transaction("", service_role=True) as conn:
        first_pid = (await (await conn.execute("SELECT pg_backend_pid() AS pid")).fetchone())["pid"]
        await conn.execute(
            "INSERT INTO task_center.workspace_policies (workspace_id,run_limit,enforcement) "
            "VALUES ('ws-a',1,'block'),('ws-b',2,'monitor')"
        )
    for workspace in ("ws-a", "ws-b", "ws-a"):
        async with task_database.transaction(workspace) as conn:
            row = await (
                await conn.execute(
                    "SELECT pg_backend_pid() AS pid, workspace_id, "
                    "current_setting('app.service_role') AS service_role "
                    "FROM task_center.workspace_policies"
                )
            ).fetchone()
            assert row == {"pid": first_pid, "workspace_id": workspace, "service_role": "off"}
    async with task_database.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT current_setting('app.current_workspace_id',true) AS workspace, "
                "current_setting('app.service_role',true) AS role"
            )
        ).fetchone()
        assert row["workspace"] in (None, "")
        assert row["role"] in (None, "")
        assert (
            await (
                await conn.execute("SELECT count(*) AS n FROM task_center.workspace_policies")
            ).fetchone()
        )["n"] == 0


async def _borrow(database):
    async with database.transaction("ws-a"):
        return True


@pytest.mark.asyncio
async def test_pool_bounds_waiters_timeout_and_close(task_database, task_postgres) -> None:
    async with task_database.transaction("ws-a"):
        waiter = asyncio.create_task(_borrow(task_database))
        try:
            deadline = time.monotonic() + 1
            while task_database.stats().get("requests_waiting", 0) != 1:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.005)
            started = time.monotonic()
            with pytest.raises(TaskCenterPoolBusy):
                await _borrow(task_database)
            assert time.monotonic() - started < 0.15
            with pytest.raises(TaskCenterPoolBusy):
                await waiter
        finally:
            if not waiter.done():
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
    await task_database.close()
    assert task_database.pool is None
    with pytest.raises(TaskCenterUnavailable):
        await _borrow(task_database)
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE application_name='task-center'"
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_readiness_requires_migrations_and_never_creates_schema() -> None:
    with OwnedPostgres() as postgres:
        database = TaskCenterDatabase(
            Settings(
                task_center_enabled=True,
                task_center_database_url=postgres.app_dsn,
                task_center_pool_timeout_seconds=0.3,
            )
        )
        with pytest.raises(TaskCenterSchemaError):
            await database.open()
        assert database.pool is None
        with psycopg.connect(postgres.owner_dsn) as conn:
            assert conn.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname='task_center'"
            ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_readiness_rejects_owner_role(task_postgres) -> None:
    database = TaskCenterDatabase(
        Settings(
            task_center_enabled=True,
            task_center_database_url=task_postgres.owner_dsn,
        )
    )
    try:
        with pytest.raises(TaskCenterSchemaError):
            await database.open()
        assert database.pool is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_sql_timeouts_are_transaction_local(task_database) -> None:
    configured = replace(
        task_database.settings,
        task_center_statement_timeout_ms=80,
        task_center_lock_timeout_ms=40,
    )
    await task_database.close()
    database = TaskCenterDatabase(configured)
    await database.open()
    try:
        async with database.transaction("ws-a") as conn:
            row = await (
                await conn.execute(
                    "SELECT current_setting('statement_timeout') AS statement, "
                    "current_setting('lock_timeout') AS lock"
                )
            ).fetchone()
            assert row == {"statement": "80ms", "lock": "40ms"}
        with pytest.raises(TaskCenterStorageError) as caught:
            async with database.transaction("ws-a") as conn:
                await conn.execute("SELECT pg_sleep(0.2)")
        assert caught.value.sqlstate == "57014"
        async with database.pool.connection() as conn:
            row = await (await conn.execute("SHOW statement_timeout")).fetchone()
            assert row["statement_timeout"] == "0"
    finally:
        await database.close()


def test_schema_rejects_cross_workspace_links_and_mutable_history(task_postgres) -> None:
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "INSERT INTO task_center.workspace_policies (workspace_id,run_limit,enforcement) "
            "VALUES ('ws-a',1,'block'),('ws-b',1,'block')"
        )
        conn.execute(
            "INSERT INTO task_center.quota_buckets (workspace_id,period_start,period_end) "
            "VALUES ('ws-a','2026-10-01','2026-11-01'),('ws-b','2026-10-01','2026-11-01')"
        )
        submission_id = conn.execute(
            "INSERT INTO task_center.submissions (workspace_id,idempotency_key,request_sha,"
            "request_json,server_actor,period_start,period_end,expected_run_id) "
            "VALUES ('ws-a','key',%s,'{}','actor','2026-10-01','2026-11-01','run-a') RETURNING id",
            ("a" * 64,),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO task_center.outbox (workspace_id,submission_id) "
                    "VALUES ('ws-b',%s)",
                    (submission_id,),
                )
        conn.execute(
            "INSERT INTO task_center.quota_entries "
            "(workspace_id,submission_id,period_start,action) "
            "VALUES ('ws-a',%s,'2026-10-01','reserve')",
            (submission_id,),
        )
        conn.execute(
            "INSERT INTO task_center.audit_events (workspace_id,submission_id,event_type,actor) "
            "VALUES ('ws-a',%s,'submitted','actor')",
            (submission_id,),
        )
        for table in ("quota_entries", "audit_events"):
            for verb in ("UPDATE", "DELETE"):
                with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                    with conn.transaction():
                        conn.execute(
                            f"UPDATE task_center.{table} SET id=%s"
                            if verb == "UPDATE"
                            else f"DELETE FROM task_center.{table}",
                            (uuid.uuid4(),) if verb == "UPDATE" else None,
                        )
