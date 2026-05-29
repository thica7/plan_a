import re
from pathlib import Path


def test_phase1_postgres_schema_has_strict_core_tables() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")
    tables = {
        match.group(1)
        for match in re.finditer(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_]+)",
            sql,
            flags=re.IGNORECASE,
        )
    }

    assert tables == {
        "workspaces",
        "users",
        "workspace_members",
        "notifications",
        "projects",
        "competitors",
        "project_competitors",
        "runs",
        "evidence_records",
        "source_registry",
        "evidence_embeddings",
        "knowledge_claims",
        "claim_evidence",
        "report_versions",
        "report_version_claims",
        "report_version_evidence",
        "audit_logs",
    }


def test_phase4_prereq_columns_are_present_in_postgres_schema() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "idempotency_key TEXT NOT NULL" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency_key" in sql
    assert "canonical_url TEXT NOT NULL DEFAULT ''" in sql
    assert "first_seen_run_id TEXT REFERENCES runs(id)" in sql
    assert "last_seen_run_id TEXT REFERENCES runs(id)" in sql
    assert "seen_count INTEGER NOT NULL DEFAULT 1" in sql
    assert "idx_report_versions_workspace_group_unique" in sql


def test_phase4_workspace_members_schema_is_present() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workspace_members" in sql
    assert "PRIMARY KEY (workspace_id, user_id)" in sql
    assert "idx_workspace_members_user" in sql


def test_phase4_source_registry_schema_is_present() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS source_registry" in sql
    assert "UNIQUE (workspace_id, domain, source_type)" in sql
    assert "trust_level TEXT NOT NULL DEFAULT 'unknown'" in sql
    assert "robots_status TEXT NOT NULL DEFAULT 'unknown'" in sql
    assert "idx_source_registry_workspace_domain" in sql


def test_phase4_pgvector_schema_is_present() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE IF NOT EXISTS evidence_embeddings" in sql
    assert "embedding VECTOR(384) NOT NULL" in sql
    assert "idx_evidence_embeddings_vector" in sql
    assert "idx_evidence_search" in sql


def test_phase5_notifications_schema_is_present() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS notifications" in sql
    assert "scheduled_scan_summary" in sql
    assert "idx_notifications_workspace_created" in sql
    assert "idx_notifications_workspace_status" in sql
