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
