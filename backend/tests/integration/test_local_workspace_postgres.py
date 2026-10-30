"""Native PG15 tests always use a freshly allocated, explicitly owned workspace."""

import importlib
import shutil
import tempfile
from pathlib import Path

import psycopg
import pytest

from packages.auth.rbac import EnterpriseUserContext
from packages.config.settings import Settings
from packages.enterprise.postgres import EnterprisePostgresStore
from packages.schema.api_dto import RunCreateRequest
from packages.task_center.database import TaskCenterDatabase
from packages.task_center.models import QuotaSeed
from packages.task_center.repository import SubmissionRepository


def module():
    assert importlib.util.find_spec("scripts.local_workspace_postgres") is not None, (
        "persistent workspace PostgreSQL implementation is missing"
    )
    return importlib.import_module("scripts.local_workspace_postgres")


@pytest.fixture
def workspace_postgres():
    mod = module()
    temporary = Path(tempfile.mkdtemp(prefix="persistent-pg-test-")).resolve()
    root = temporary / ("持久工作台" * 10)
    instance = mod.PersistentWorkspacePostgres(root, binary_dir=Path("/opt/homebrew/bin"))
    try:
        yield instance
    finally:
        # A failed ownership/identity verification deliberately retains diagnostic files.
        assert instance.stop()["running"] is False
        assert temporary.name.startswith("persistent-pg-test-")
        assert not temporary.is_symlink()
        shutil.rmtree(temporary)
        if instance.socket_dir.exists():
            (instance.socket_dir / ".workspace-postgres-socket").unlink()
            instance.socket_dir.rmdir()


async def test_native_complete_schema_restricted_pools_and_persistent_restart(workspace_postgres):
    instance = workspace_postgres
    assert instance.initialise()["state"] == "stopped"
    assert instance.marker_path.stat().st_mode & 0o777 == 0o600
    assert instance.data_dir.stat().st_mode & 0o777 == 0o700
    assert instance.socket_dir.stat().st_mode & 0o777 == 0o700
    version_before = (instance.data_dir / "PG_VERSION").stat().st_mtime_ns
    instance.initialise()
    assert (instance.data_dir / "PG_VERSION").stat().st_mtime_ns == version_before
    assert instance.start()["running"] is True
    environment = instance.app_environment()
    dsn = environment["ENTERPRISE_DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SHOW listen_addresses").fetchone() == ("",)
        assert conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        assert (
            conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            ).fetchone()[0]
            >= 19
        )
        assert (
            conn.execute(
                "SELECT rolsuper,rolbypassrls,rolinherit,rolcreatedb,rolcreaterole,rolreplication "
                "FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            == (False,) * 6
        )
        assert conn.execute(
            "SELECT pg_has_role(current_user,'plan_a_workspace_owner','MEMBER')"
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT has_schema_privilege(current_user,'public','CREATE'),"
            "has_database_privilege(current_user,current_database(),'CREATE'),"
            "has_table_privilege(current_user,'projects','TRUNCATE')"
        ).fetchone() == (False, False, False)
        assert conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE usename='plan_a_workspace_owner' "
            "AND backend_type='client backend'"
        ).fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM task_center.schema_migrations").fetchone() == (3,)
    for forbidden in ("CREATE TABLE public.forbidden(id int)", "TRUNCATE projects"):
        with psycopg.connect(dsn) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(forbidden)
    store = EnterprisePostgresStore(dsn, auto_migrate=False)
    database = TaskCenterDatabase(
        Settings(
            task_center_enabled=True,
            task_center_database_url=dsn,
            task_center_pool_min_size=1,
            task_center_pool_max_size=4,
        )
    )
    try:
        assert [row.id for row in store.list_workspaces()] == ["default-workspace"]
        with store._tenant_connection("default-workspace") as conn:
            conn.execute(
                "INSERT INTO projects(id,workspace_id,name,topic,topic_normalized) "
                "VALUES('persistent-project','default-workspace','持久项目','持久任务','持久任务')"
            )
        assert store.get_project("persistent-project").name == "持久项目"
        with psycopg.connect(dsn) as conn:
            with conn.transaction():
                conn.execute(
                    "SELECT set_config('app.service_role','off',true), "
                    "set_config('app.current_workspace_id','workspace-b',true)"
                )
                conn.execute("INSERT INTO workspaces(id,name) VALUES('workspace-b','B')")
                conn.execute(
                    "INSERT INTO projects(id,workspace_id,name,topic,topic_normalized) "
                    "VALUES('project-b','workspace-b','B','B','b')"
                )
            for workspace, expected in (
                ("default-workspace", "persistent-project"),
                ("workspace-b", "project-b"),
                ("default-workspace", "persistent-project"),
            ):
                with conn.transaction():
                    conn.execute(
                        "SELECT set_config('app.service_role','off',true), "
                        "set_config('app.current_workspace_id',%s,true)",
                        (workspace,),
                    )
                    assert conn.execute("SELECT id FROM projects").fetchall() == [(expected,)]
                    assert conn.execute("SELECT id FROM workspaces").fetchall() == [(workspace,)]
            assert conn.execute("SELECT count(*) FROM projects").fetchone() == (0,)
        await database.open()
        repo = SubmissionRepository(database)
        request = RunCreateRequest(
            topic="持久任务",
            dimensions=["product"],
            idempotency_key="persistent-key",
            project_id="persistent-project",
        )
        actor = EnterpriseUserContext(user_id="system-user", role="owner")
        submission = await repo.submit(
            request, actor=actor, seed=QuotaSeed(run_limit=10, enforcement="block")
        )
        assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    finally:
        await database.close()
        store.close()
    same_process = module().PersistentWorkspacePostgres(
        instance.root, binary_dir=instance.binary_dir
    )
    assert same_process.start() == instance.status()
    assert same_process.stop()["state"] == "stopped"
    assert instance.data_dir.exists()
    restarted = module().PersistentWorkspacePostgres(instance.root, binary_dir=instance.binary_dir)
    assert restarted.initialise()["state"] == "stopped"
    restarted.start()
    store = EnterprisePostgresStore(dsn, auto_migrate=False)
    database = TaskCenterDatabase(Settings(task_center_enabled=True, task_center_database_url=dsn))
    try:
        assert store.get_project("persistent-project").name == "持久项目"
        await database.open()
        repo = SubmissionRepository(database)
        assert (await repo.get("default-workspace", submission.id)).id == submission.id
        assert (
            await repo.submit(request, actor=actor, seed=QuotaSeed(10, "block"))
        ).id == submission.id
        assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
        async with database.transaction("default-workspace") as conn:
            assert (
                await (
                    await conn.execute(
                        "SELECT count(*) AS n FROM task_center.quota_entries WHERE action='reserve'"
                    )
                ).fetchone()
            )["n"] == 1
    finally:
        await database.close()
        store.close()
    assert restarted.stop()["state"] == "stopped"
    print(
        "PERSISTENT_PG_VERIFIED full_enterprise=19+ task_migrations=3 app_role=restricted "
        "private_socket=true restart_project=true restart_submission=true reserve=1"
    )


def test_initialization_failure_retains_cluster_and_retry_does_not_reset(
    workspace_postgres, monkeypatch
):
    instance = workspace_postgres

    def fail_migration(store):
        raise RuntimeError("private-owner-connection-must-not-leak")

    with monkeypatch.context() as patch:
        patch.setattr(EnterprisePostgresStore, "migrate", fail_migration)
        with pytest.raises(module().WorkspacePostgresError) as caught:
            instance.initialise()
        assert "private-owner-connection" not in str(caught.value)
    assert instance.status()["state"] == "uninitialized"
    version_before = (instance.data_dir / "PG_VERSION").stat().st_mtime_ns
    assert instance.initialise()["initialized"] is True
    assert (instance.data_dir / "PG_VERSION").stat().st_mtime_ns == version_before
