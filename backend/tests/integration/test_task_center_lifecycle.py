"""Owned PostgreSQL pool, cancellation and shutdown ordering acceptance."""

import asyncio
import threading

import psycopg
import pytest

from packages.enterprise import EnterprisePostgresStore
from packages.task_center.errors import TaskCenterPoolBusy, TaskCenterUnavailable
from packages.task_center.offload import MetadataIO

pytest_plugins = ("postgres_support",)


def test_enterprise_pool_rollback_tenant_reuse_timeouts_and_close(task_postgres):
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.pool_probe(workspace_id text, value integer)"
        )
        conn.execute("TRUNCATE public.pool_probe")
        conn.execute("ALTER TABLE public.pool_probe ENABLE ROW LEVEL SECURITY")
        conn.execute("ALTER TABLE public.pool_probe FORCE ROW LEVEL SECURITY")
        conn.execute("DROP POLICY IF EXISTS pool_probe_tenant ON public.pool_probe")
        conn.execute(
            "CREATE POLICY pool_probe_tenant ON public.pool_probe USING "
            "(workspace_id = current_setting('app.current_workspace_id',true)) "
            "WITH CHECK (workspace_id = current_setting('app.current_workspace_id',true))"
        )
        conn.execute("GRANT SELECT,INSERT ON public.pool_probe TO task_center_app")
    store = EnterprisePostgresStore(
        task_postgres.app_dsn,
        auto_migrate=False,
        pool_max_size=1,
        pool_timeout_seconds=0.15,
        statement_timeout_ms=50,
        lock_timeout_ms=30,
    )
    store.open()
    try:
        with pytest.raises(RuntimeError, match="rollback"):
            with store._tenant_connection("a") as conn:
                conn.execute("INSERT INTO public.pool_probe VALUES('a',1)")
                raise RuntimeError("rollback")
        with store._tenant_connection("a") as conn:
            assert conn.execute("SELECT * FROM public.pool_probe").fetchall() == []
            conn.execute("INSERT INTO public.pool_probe VALUES('a',2)")
            assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "50ms"
        with store._tenant_connection("b") as conn:
            assert conn.execute("SELECT * FROM public.pool_probe").fetchall() == []
            assert (
                conn.execute("SELECT current_setting('app.service_role') AS role").fetchone()[
                    "role"
                ]
                == "off"
            )
            with pytest.raises(TaskCenterPoolBusy):
                with store._tenant_connection("a"):
                    pass
        assert store.pool_stats()["pool_size"] == 1
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()

        def borrower():
            with store._tenant_connection("a"):
                entered.set()
                assert release.wait(2)

        thread = threading.Thread(target=borrower)
        thread.start()
        assert entered.wait(2)
        closer = threading.Thread(target=lambda: (store.close(), closed.set()))
        closer.start()
        assert not closed.wait(0.05)
        release.set()
        thread.join(2)
        closer.join(2)
        assert closed.is_set()
        with pytest.raises(TaskCenterUnavailable):
            with store._tenant_connection("a"):
                pass
    finally:
        store.close()


async def test_async_pool_close_joins_borrowed_transaction_before_driver_close(task_database):
    entered, release = asyncio.Event(), asyncio.Event()

    async def borrower():
        async with task_database.transaction("a") as conn:
            await conn.execute("SELECT 1")
            entered.set()
            await release.wait()
            await conn.execute("SELECT 2")

    borrowed = asyncio.create_task(borrower())
    await entered.wait()
    closing = asyncio.create_task(task_database.close())
    await asyncio.sleep(0.03)
    assert not closing.done()
    with pytest.raises(TaskCenterUnavailable):
        async with task_database.transaction("b"):
            pass
    release.set()
    await borrowed
    await closing


@pytest.mark.parametrize("worker_raises", [False, True])
async def test_metadata_cancellation_keeps_worker_slot_and_shutdown_joins(worker_raises):
    io = MetadataIO(concurrency=1, timeout=0.03)
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        release.wait(2)
        if worker_raises:
            raise RuntimeError("private worker failure after cancellation")

    running = asyncio.create_task(io.run(blocked))
    await asyncio.to_thread(entered.wait, 1)
    running.cancel()
    with pytest.raises(TaskCenterPoolBusy):
        await io.run(lambda: 1)
    closing = asyncio.create_task(io.close())
    await asyncio.sleep(0.03)
    assert not closing.done() and not running.done()
    release.set()
    await closing
    with pytest.raises(asyncio.CancelledError):
        await running
    with pytest.raises(TaskCenterUnavailable):
        await io.run(lambda: 1)


def test_migration_cli_grants_existing_quoted_restricted_role(task_postgres, monkeypatch, capsys):
    from psycopg import sql

    from scripts.migrate_task_center import main

    role = 'task app " quoted'
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} NOSUPERUSER NOBYPASSRLS NOLOGIN").format(sql.Identifier(role))
        )
    monkeypatch.setenv("TASK_CENTER_MIGRATION_DATABASE_URL", task_postgres.owner_dsn)
    assert main(["--execute", "--app-role", role]) == 0
    assert task_postgres.owner_dsn not in capsys.readouterr().out
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        assert conn.execute(
            "SELECT has_table_privilege(%s,'task_center.submissions','INSERT')", (role,)
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT has_table_privilege(%s,'task_center.schema_migrations','UPDATE')", (role,)
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT has_table_privilege(%s,'task_center.quota_entries','DELETE')", (role,)
        ).fetchone() == (False,)


def test_enterprise_pool_statement_and_lock_timeouts_are_real(task_postgres):
    from packages.task_center.errors import TaskCenterStorageError

    store = EnterprisePostgresStore(
        task_postgres.app_dsn,
        auto_migrate=False,
        pool_max_size=1,
        statement_timeout_ms=100,
        lock_timeout_ms=30,
    )
    try:
        with pytest.raises(TaskCenterStorageError) as cancelled:
            with store._tenant_connection("a") as conn:
                conn.execute("SELECT pg_sleep(0.3)")
        assert cancelled.value.sqlstate == "57014"
        with store._tenant_connection("a") as conn:
            assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        with psycopg.connect(task_postgres.owner_dsn) as owner:
            owner.execute("CREATE TABLE IF NOT EXISTS public.pool_lock_probe(value integer)")
            owner.execute("GRANT SELECT ON public.pool_lock_probe TO task_center_app")
        with psycopg.connect(task_postgres.owner_dsn) as owner:
            owner.execute("LOCK public.pool_lock_probe IN ACCESS EXCLUSIVE MODE")
            with pytest.raises(TaskCenterStorageError) as locked:
                with store._tenant_connection("a") as conn:
                    conn.execute("SELECT * FROM public.pool_lock_probe")
            assert locked.value.sqlstate == "55P03"
    finally:
        store.close()
