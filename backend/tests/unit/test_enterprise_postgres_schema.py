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
        "projects",
        "competitors",
        "project_competitors",
        "runs",
        "evidence_records",
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
