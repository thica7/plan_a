from importlib.util import find_spec
from pathlib import Path

import pytest

from packages.config.settings import DEFAULT_ENTERPRISE_DATABASE_URL, get_settings
from packages.enterprise import EnterprisePostgresStore
from packages.enterprise.postgres import _split_sql


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_enterprise_store_settings_default_to_postgres(monkeypatch) -> None:
    monkeypatch.delenv("ENTERPRISE_STORE_BACKEND", raising=False)
    monkeypatch.delenv("ENTERPRISE_DATABASE_URL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.enterprise_store_backend == "postgres"
    assert settings.enterprise_database_url == DEFAULT_ENTERPRISE_DATABASE_URL


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


def test_postgres_schema_contains_enterprise_core_tables() -> None:
    schema = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    for table in [
        "workspaces",
        "projects",
        "competitors",
        "evidence_records",
        "source_registry",
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
