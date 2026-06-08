from __future__ import annotations

import os
from uuid import uuid4

import pytest


def test_postgres_rls_filters_workspace_scoped_tables_with_real_connection() -> None:
    database_url = os.getenv("ENTERPRISE_RLS_SMOKE_DATABASE_URL")
    if not database_url:
        pytest.skip("Set ENTERPRISE_RLS_SMOKE_DATABASE_URL to run the live RLS smoke test.")

    psycopg = pytest.importorskip("psycopg")
    run_key = uuid4().hex[:12]
    workspace_a = f"rls-ws-a-{run_key}"
    workspace_b = f"rls-ws-b-{run_key}"
    ids = {
        "workspaces": (workspace_a, workspace_b),
        "projects": (f"rls-project-a-{run_key}", f"rls-project-b-{run_key}"),
        "artifacts": (f"rls-artifact-a-{run_key}", f"rls-artifact-b-{run_key}"),
        "report_versions": (f"rls-report-a-{run_key}", f"rls-report-b-{run_key}"),
        "audit_logs": (f"rls-audit-a-{run_key}", f"rls-audit-b-{run_key}"),
    }

    conn = psycopg.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET LOCAL row_security = on")
            cur.execute("SELECT set_config('app.service_role', 'on', true)")
            try:
                for table in ids:
                    cur.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            except Exception as exc:  # noqa: BLE001 - opt-in smoke explains DB readiness.
                conn.rollback()
                if exc.__class__.__name__ in {
                    "InsufficientPrivilege",
                    "UndefinedTable",
                    "UndefinedObject",
                }:
                    pytest.skip(f"Postgres RLS smoke database is not ready: {exc}")
                raise

            cur.execute(
                "INSERT INTO workspaces (id, name, description) VALUES (%s, %s, %s), (%s, %s, %s)",
                (
                    workspace_a,
                    "RLS Workspace A",
                    "RLS smoke workspace A",
                    workspace_b,
                    "RLS Workspace B",
                    "RLS smoke workspace B",
                ),
            )
            cur.execute(
                """
                INSERT INTO projects (
                    id, workspace_id, name, topic, topic_normalized, competitor_set_hash
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s),
                    (%s, %s, %s, %s, %s, %s)
                """,
                (
                    ids["projects"][0],
                    workspace_a,
                    "RLS Project A",
                    "RLS Topic A",
                    "rls-topic-a",
                    "rls-set-a",
                    ids["projects"][1],
                    workspace_b,
                    "RLS Project B",
                    "RLS Topic B",
                    "rls-topic-b",
                    "rls-set-b",
                ),
            )
            cur.execute(
                """
                INSERT INTO artifacts (
                    id, workspace_id, project_id, artifact_type, filename, uri, content_hash
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s),
                    (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ids["artifacts"][0],
                    workspace_a,
                    ids["projects"][0],
                    "web_snapshot",
                    "rls-a.html",
                    "local://rls-a.html",
                    f"hash-a-{run_key}",
                    ids["artifacts"][1],
                    workspace_b,
                    ids["projects"][1],
                    "web_snapshot",
                    "rls-b.html",
                    "local://rls-b.html",
                    f"hash-b-{run_key}",
                ),
            )
            cur.execute(
                """
                INSERT INTO report_versions (
                    id, workspace_id, project_id, version_number, topic_normalized,
                    competitor_layer, competitor_set_hash, status, report_md
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s),
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ids["report_versions"][0],
                    workspace_a,
                    ids["projects"][0],
                    1,
                    "rls-topic-a",
                    "L1",
                    "rls-set-a",
                    "draft",
                    "RLS report A",
                    ids["report_versions"][1],
                    workspace_b,
                    ids["projects"][1],
                    1,
                    "rls-topic-b",
                    "L1",
                    "rls-set-b",
                    "draft",
                    "RLS report B",
                ),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (
                    id, workspace_id, actor_type, actor_id, action, resource_type, resource_id
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s),
                    (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ids["audit_logs"][0],
                    workspace_a,
                    "system",
                    "rls-smoke",
                    "rls.test",
                    "project",
                    ids["projects"][0],
                    ids["audit_logs"][1],
                    workspace_b,
                    "system",
                    "rls-smoke",
                    "rls.test",
                    "project",
                    ids["projects"][1],
                ),
            )

            cur.execute("SELECT set_config('app.service_role', 'off', true)")
            _assert_workspace_visible(cur, ids, workspace_a, expected_index=0)
            _assert_workspace_visible(cur, ids, workspace_b, expected_index=1)
            cur.execute("SELECT set_config('app.current_workspace_id', '', true)")
            for table, pair in ids.items():
                assert _visible_ids(cur, table, pair) == set()
    finally:
        conn.rollback()
        conn.close()


def _assert_workspace_visible(
    cur: object,
    ids: dict[str, tuple[str, str]],
    workspace_id: str,
    *,
    expected_index: int,
) -> None:
    cur.execute("SELECT set_config('app.current_workspace_id', %s, true)", (workspace_id,))
    hidden_index = 1 - expected_index
    for table, pair in ids.items():
        visible = _visible_ids(cur, table, pair)
        assert pair[expected_index] in visible
        assert pair[hidden_index] not in visible


def _visible_ids(cur: object, table: str, pair: tuple[str, str]) -> set[str]:
    cur.execute(f"SELECT id FROM {table} WHERE id IN (%s, %s) ORDER BY id", pair)
    return {row[0] for row in cur.fetchall()}
