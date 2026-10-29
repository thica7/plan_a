"""Real, private PostgreSQL fixtures shared by integration and acceptance tests."""

import pytest

from packages.config.settings import Settings
from packages.task_center.database import TaskCenterDatabase
from packages.task_center.migrations import apply_migrations
from scripts.local_postgres import OwnedPostgres


@pytest.fixture(scope="module")
def owned_postgres():
    with OwnedPostgres() as postgres:
        yield postgres


@pytest.fixture
def task_postgres(owned_postgres):
    import psycopg

    apply_migrations(owned_postgres.owner_dsn)
    owned_postgres.grant_app_access()
    with psycopg.connect(owned_postgres.owner_dsn) as conn:
        conn.execute("TRUNCATE task_center.workspace_policies CASCADE")
    return owned_postgres


@pytest.fixture
async def task_database(task_postgres):
    database = TaskCenterDatabase(
        Settings(
            task_center_enabled=True,
            task_center_database_url=task_postgres.app_dsn,
            task_center_pool_min_size=1,
            task_center_pool_max_size=1,
            task_center_pool_max_waiting=1,
            task_center_pool_timeout_seconds=0.2,
        )
    )
    await database.open()
    yield database
    await database.close()
