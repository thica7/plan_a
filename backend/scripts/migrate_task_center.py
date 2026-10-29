"""Explicit owner-only task-center migration; preview is the safe default."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--app-role", help="Existing restricted application role to receive DML grants"
    )
    args = parser.parse_args(argv)
    from packages.task_center.migrations import apply_migrations, load_migrations

    if not args.execute:
        print("preview: task-center migration (no connection)")
        for migration in load_migrations():
            print(f"{migration.version} {migration.sha256}")
        print(
            "--execute reads TASK_CENTER_MIGRATION_DATABASE_URL; --app-role grants an existing role"
        )
        return 0
    owner_url = os.getenv("TASK_CENTER_MIGRATION_DATABASE_URL", "").strip()
    if not owner_url or not args.app_role:
        parser.error("--execute requires TASK_CENTER_MIGRATION_DATABASE_URL and --app-role")
    from packages.task_center.errors import TaskCenterError

    try:
        versions = apply_migrations(owner_url)
        grant_application_role(owner_url, args.app_role)
    except TaskCenterError as exc:
        print(f"migration failed: {exc.code}")
        return 1
    print(f"migration complete: {len(versions)} applied; application grants verified")
    return 0


def grant_application_role(owner_url, role):
    import psycopg
    from psycopg import sql

    from packages.task_center.connection_logging import protected_connection_logging
    from packages.task_center.errors import TaskCenterSchemaError

    try:
        with protected_connection_logging():
            conn = psycopg.connect(owner_url, connect_timeout=5)
        with conn:
            record = conn.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone()
            if record is None or any(record):
                raise TaskCenterSchemaError("application role must already exist and be restricted")
            owns_schema = conn.execute(
                "SELECT pg_has_role(%s,nspowner,'USAGE') FROM pg_namespace "
                "WHERE nspname='task_center'",
                (role,),
            ).fetchone()
            if owns_schema and owns_schema[0]:
                raise TaskCenterSchemaError("application role must not own task center schema")
            identifier = sql.Identifier(role)
            for query in (
                "GRANT USAGE ON SCHEMA task_center TO {}",
                "REVOKE CREATE ON SCHEMA task_center FROM {}",
                "REVOKE TRUNCATE ON ALL TABLES IN SCHEMA task_center FROM {}",
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA task_center TO {}",
                "REVOKE INSERT,UPDATE,DELETE ON task_center.schema_migrations FROM {}",
                "REVOKE UPDATE,DELETE ON task_center.quota_entries,"
                "task_center.audit_events FROM {}",
            ):
                conn.execute(sql.SQL(query).format(identifier))
    except psycopg.Error:
        raise TaskCenterSchemaError("application grants failed") from None


if __name__ == "__main__":
    raise SystemExit(main())
