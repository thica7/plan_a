"""Explicit, transactional migrations; application readiness never executes DDL."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import psycopg

from .connection_logging import protected_connection_logging
from .errors import MigrationDriftError, TaskCenterSchemaError

MIGRATION_LOCK = 6071226437340582994


@dataclass(frozen=True)
class Migration:
    version: str
    sha256: str
    sql: str


def load_migrations(migration_dir: Path | None = None) -> tuple[Migration, ...]:
    root = migration_dir or files("packages.task_center").joinpath("migrations")
    migrations = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".sql"):
            continue
        if not re.fullmatch(r"[0-9]{3}_[a-z0-9_]+\.sql", path.name):
            raise TaskCenterSchemaError("invalid task center migration filename")
        content = path.read_bytes()
        migrations.append(
            Migration(path.name[:-4], hashlib.sha256(content).hexdigest(), content.decode("utf-8"))
        )
    if not migrations:
        raise TaskCenterSchemaError("task center migrations are missing")
    return tuple(migrations)


def apply_migrations(database_url: str, migration_dir: Path | None = None) -> list[str]:
    migrations = load_migrations(migration_dir)
    applied = []
    try:
        with protected_connection_logging():
            conn = psycopg.connect(database_url, connect_timeout=5)
        with conn:
            # This transaction lock covers bootstrap and every pending migration.
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
            conn.execute("CREATE SCHEMA IF NOT EXISTS task_center")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS task_center.schema_migrations ("
                "version text PRIMARY KEY, sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),"
                "applied_at timestamptz NOT NULL DEFAULT now())"
            )
            current = dict(
                conn.execute("SELECT version, sha256 FROM task_center.schema_migrations").fetchall()
            )
            known = {migration.version: migration.sha256 for migration in migrations}
            if any(known.get(version) != checksum for version, checksum in current.items()):
                raise MigrationDriftError("task center migration checksum does not match")
            for migration in migrations:
                if migration.version in current:
                    continue
                conn.execute(migration.sql)
                conn.execute(
                    "INSERT INTO task_center.schema_migrations (version, sha256) VALUES (%s,%s)",
                    (migration.version, migration.sha256),
                )
                applied.append(migration.version)
    except psycopg.Error:
        raise TaskCenterSchemaError("task center migration failed") from None
    return applied
