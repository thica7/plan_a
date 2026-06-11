from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest

from packages.config.settings import (
    DEFAULT_ENTERPRISE_DATABASE_URL,
    ENV_FILE_LOADING_FLAG,
    _env_file_candidates,
    get_settings,
)
from packages.enterprise import EnterprisePostgresStore
from packages.enterprise.postgres import _split_sql
from packages.enterprise.postgres_sanitizer import sanitize_postgres_text, sanitize_postgres_value
from packages.schema.enterprise import EvidenceRecord


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_enterprise_store_settings_default_to_postgres(monkeypatch) -> None:
    monkeypatch.delenv("ENTERPRISE_STORE_BACKEND", raising=False)
    monkeypatch.delenv("ENTERPRISE_DATABASE_URL", raising=False)
    monkeypatch.delenv("RUN_ORCHESTRATION_BACKEND", raising=False)
    monkeypatch.delenv("TEMPORAL_TRAFFIC_PERCENT", raising=False)
    monkeypatch.delenv("WRITER_TIMEOUT_SECONDS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.enterprise_store_backend == "postgres"
    assert settings.enterprise_database_url == DEFAULT_ENTERPRISE_DATABASE_URL
    assert settings.run_orchestration_backend == "temporal"
    assert settings.temporal_traffic_percent == 100
    assert settings.llm_timeout_seconds == 90.0
    assert settings.writer_timeout_seconds == 90.0


def test_writer_timeout_settings_allow_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("WRITER_TIMEOUT_SECONDS", "45")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.writer_timeout_seconds == 45.0


def test_env_file_candidates_include_source_root_when_cwd_is_backend(tmp_path: Path) -> None:
    project_root = tmp_path / "plan_a"
    backend_root = project_root / "backend"
    backend_root.mkdir(parents=True)

    candidates = _env_file_candidates(cwd=backend_root, project_root=project_root)

    assert project_root / ".env" in candidates
    assert backend_root / ".env" in candidates
    assert len(candidates) == len({path.resolve() for path in candidates})


def test_settings_do_not_load_env_files_when_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_FILE_LOADING_FLAG, "0")
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    (tmp_path / ".env").write_text("LLM_TIMEOUT_SECONDS=12\n", encoding="utf-8")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_timeout_seconds == 90.0


def test_settings_load_env_files_when_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_FILE_LOADING_FLAG, "1")
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    (tmp_path / ".env").write_text("LLM_TIMEOUT_SECONDS=12\n", encoding="utf-8")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_timeout_seconds == 12.0


def test_enterprise_store_settings_allow_explicit_memory(monkeypatch) -> None:
    monkeypatch.setenv("ENTERPRISE_STORE_BACKEND", "memory")
    monkeypatch.delenv("ENTERPRISE_DATABASE_URL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.enterprise_store_backend == "memory"
    assert settings.enterprise_database_url is None


def test_enterprise_store_settings_allow_postgres(monkeypatch) -> None:
    monkeypatch.setenv("ENTERPRISE_STORE_BACKEND", "postgres")
    monkeypatch.setenv("ENTERPRISE_DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.enterprise_store_backend == "postgres"
    assert settings.enterprise_database_url == "postgresql://user:pass@localhost:5432/db"


def test_artifact_storage_settings_allow_external_backends(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("ARTIFACT_STORAGE_ROOT", "unused-for-pointer-backend")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.artifact_storage_backend == "s3"
    assert settings.artifact_storage_root == "unused-for-pointer-backend"


def test_postgres_schema_contains_enterprise_core_tables() -> None:
    schema = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    for table in [
        "workspaces",
        "workspace_members",
        "projects",
        "competitors",
        "evidence_records",
        "source_registry",
        "evidence_embeddings",
        "knowledge_claims",
        "report_versions",
        "audit_logs",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema


def test_postgres_schema_splitter_ignores_comment_semicolons() -> None:
    statements = _split_sql("-- comment with ; semicolon\nCREATE TABLE example (id TEXT);")

    assert statements == ["CREATE TABLE example (id TEXT)"]


def test_postgres_store_can_be_constructed_without_migrating() -> None:
    if find_spec("psycopg") is None:
        pytest.skip("psycopg is not installed")

    store = EnterprisePostgresStore("postgresql://user:pass@localhost:5432/db", auto_migrate=False)

    assert store.database_url == "postgresql://user:pass@localhost:5432/db"


def test_postgres_store_sets_service_role_rls_context_on_connections() -> None:
    fake_conn = _FakePostgresConnection()
    store = object.__new__(EnterprisePostgresStore)
    store.database_url = "postgresql://user:pass@localhost:5432/db"
    store._connect_driver = lambda *args, **kwargs: fake_conn  # noqa: ARG005
    store._dict_row = object()

    with store._service_connection() as conn:
        assert conn is fake_conn

    assert fake_conn.executed[:2] == [
        ("SELECT set_config('app.service_role', %s, true)", ("on",)),
        ("SELECT set_config('app.current_workspace_id', %s, true)", ("",)),
    ]


def test_postgres_store_can_open_tenant_scoped_rls_connection() -> None:
    fake_conn = _FakePostgresConnection()
    store = object.__new__(EnterprisePostgresStore)
    store.database_url = "postgresql://user:pass@localhost:5432/db"
    store._connect_driver = lambda *args, **kwargs: fake_conn  # noqa: ARG005
    store._dict_row = object()

    with store._tenant_connection("workspace-a") as conn:
        assert conn is fake_conn

    assert fake_conn.executed[:2] == [
        ("SELECT set_config('app.service_role', %s, true)", ("off",)),
        ("SELECT set_config('app.current_workspace_id', %s, true)", ("workspace-a",)),
    ]


def test_postgres_store_filters_generated_columns_when_validating_rows() -> None:
    if find_spec("psycopg") is None:
        pytest.skip("psycopg is not installed")

    store = EnterprisePostgresStore("postgresql://user:pass@localhost:5432/db", auto_migrate=False)

    evidence = store._model_from_mapping(
        EvidenceRecord,
        {
            "id": "ev-1",
            "workspace_id": "workspace-1",
            "project_id": "project-1",
            "run_id": "run-1",
            "raw_source_id": "source-1",
            "competitor_id": "competitor-1",
            "dimension": "pricing",
            "source_type": "webpage_verified",
            "title": "Pricing",
            "url": "https://example.com/pricing",
            "content_hash": "hash-1",
            "search_vector": "'pricing':1",
        },
    )

    assert evidence.id == "ev-1"
    assert not hasattr(evidence, "search_vector")


def test_postgres_workspace_usage_read_path_does_not_upsert_workspace() -> None:
    store = object.__new__(EnterprisePostgresStore)
    store.database_url = "postgresql://user:pass@localhost:5432/db"
    store._dict_row = object()
    fake_conn = _FakeWorkspaceUsageConnection()
    store._connect = lambda *args, **kwargs: fake_conn  # noqa: ARG005

    usage = store.get_workspace_usage("workspace-a")

    assert usage.workspace_id == "workspace-a"
    assert usage.run_count == 2
    assert not any("INSERT INTO workspaces" in sql for sql, _ in fake_conn.cursor_obj.executed)
    assert not any("INSERT INTO workspace_members" in sql for sql, _ in fake_conn.cursor_obj.executed)


def test_postgres_sanitizer_removes_nul_and_control_chars_from_text() -> None:
    assert sanitize_postgres_text("alpha\x00beta\x18gamma") == "alphabeta gamma"


def test_postgres_sanitizer_recurses_through_json_payloads() -> None:
    payload = {
        "bad\x00key": [
            "value\x00one",
            {"nested": "alpha\x00beta\x18gamma"},
        ],
    }

    sanitized = sanitize_postgres_value(payload)

    assert sanitized == {"badkey": ["valueone", {"nested": "alphabeta gamma"}]}


def test_postgres_store_json_boundary_sanitizes_payloads() -> None:
    store = object.__new__(EnterprisePostgresStore)
    store._jsonb = lambda value: value

    sanitized = store._json({"detail_json": {"raw": "contains\x00nul"}})

    assert sanitized == {"detail_json": {"raw": "containsnul"}}


class _FakePostgresConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[str, ...]]] = []

    def __enter__(self) -> "_FakePostgresConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        sql: str,
        params: tuple[str, ...] | None = None,
    ) -> "_FakePostgresConnection":
        self.executed.append((sql, params or ()))
        return self


class _FakeWorkspaceUsageConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeWorkspaceUsageCursor()
        self.committed = False

    def __enter__(self) -> "_FakeWorkspaceUsageConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> "_FakeWorkspaceUsageCursor":
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True


class _FakeWorkspaceUsageCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._next_row: dict[str, Any] | None = None

    def __enter__(self) -> "_FakeWorkspaceUsageCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
    ) -> "_FakeWorkspaceUsageCursor":
        self.executed.append((sql, params or ()))
        if "INSERT INTO workspaces" in sql or "INSERT INTO workspace_members" in sql:
            raise AssertionError("workspace usage reads must not upsert workspace records")
        if "SELECT * FROM workspaces" in sql:
            self._next_row = {
                "id": "workspace-a",
                "name": "Workspace A",
                "description": "",
                "is_active": True,
                "monthly_run_quota": 1000,
                "monthly_token_quota": 2_000_000,
                "monthly_cost_quota_usd": 100.0,
                "quota_enforcement": "block",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        elif "FROM runs" in sql:
            self._next_row = {
                "run_count": 2,
                "completed_run_count": 1,
                "failed_run_count": 0,
                "interrupted_run_count": 0,
                "input_tokens_estimate": 100,
                "output_tokens_estimate": 50,
                "cost_estimate_usd": 0.01,
            }
        else:
            self._next_row = None
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return self._next_row
