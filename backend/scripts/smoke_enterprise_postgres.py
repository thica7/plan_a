from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings
from packages.enterprise import EnterprisePostgresStore
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry

DEFAULT_DATABASE_URL = (
    "postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5"
)
PHASE1_TABLES = {
    "workspaces",
    "users",
    "projects",
    "competitors",
    "project_competitors",
    "runs",
    "evidence_records",
    "claim_records",
    "claim_evidence",
    "report_versions",
    "report_version_claims",
    "report_version_evidence",
    "audit_logs",
}


async def main() -> None:
    database_url = os.getenv("ENTERPRISE_DATABASE_URL") or DEFAULT_DATABASE_URL
    store = EnterprisePostgresStore(database_url)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=30,
            llm_temperature=0.2,
        ),
        enterprise_store=store,
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant enterprise smoke",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    await service.run_pipeline(detail.id)
    completed = service.get_run(detail.id)
    if completed is None or completed.status != "completed":
        trace = service.get_trace(detail.id) if completed is not None else []
        print(
            json.dumps(
                {
                    "component": "enterprise_postgres",
                    "ok": False,
                    "run_id": detail.id,
                    "status": completed.status if completed else None,
                    "current_node": completed.current_node if completed else None,
                    "last_events": [
                        {
                            "type": event.type,
                            "agent": event.agent,
                            "message": event.message,
                        }
                        for event in (trace or [])[-5:]
                    ],
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit("Postgres enterprise demo run did not complete.")

    loaded = store.get_run_projection(detail.id)
    if loaded is None:
        raise SystemExit("Postgres enterprise projection was not persisted.")
    if not loaded.evidence_records or not loaded.claim_records:
        raise SystemExit("Postgres enterprise projection is missing evidence or claims.")
    table_names = _phase1_table_names(store)
    if table_names != PHASE1_TABLES:
        missing = sorted(PHASE1_TABLES - table_names)
        extra = sorted(table_names - PHASE1_TABLES)
        raise SystemExit(f"Postgres Phase 1 table mismatch. missing={missing} extra={extra}")
    link_counts = _phase1_link_counts(store, loaded.report_version.id)
    if link_counts["claim_evidence"] < len(loaded.claim_records):
        raise SystemExit("Postgres claim_evidence links were not persisted.")
    if link_counts["report_version_claims"] != len(loaded.report_version.claim_ids):
        raise SystemExit("Postgres report_version_claim links were not persisted.")
    if link_counts["report_version_evidence"] != len(loaded.report_version.evidence_ids):
        raise SystemExit("Postgres report_version_evidence links were not persisted.")
    audit_action_count = _audit_action_count(store, detail.id)
    if audit_action_count < 5:
        raise SystemExit("Postgres audit action coverage is below Phase 1 minimum.")

    print(
        json.dumps(
            {
                "component": "enterprise_postgres",
                "ok": True,
                "run_id": completed.id,
                "status": completed.status,
                "project_id": loaded.project_id,
                "evidence_count": len(loaded.evidence_records),
                "claim_count": len(loaded.claim_records),
                "report_version_id": loaded.report_version.id,
                "report_chars": len(completed.report_md),
                "phase1_table_count": len(table_names),
                "link_counts": link_counts,
                "audit_action_count": audit_action_count,
            },
            ensure_ascii=False,
        )
    )


def _phase1_table_names(store: EnterprisePostgresStore) -> set[str]:
    with store._connect(store.database_url, row_factory=store._dict_row) as conn:
        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            (list(PHASE1_TABLES),),
        ).fetchall()
    return {str(row["table_name"]) for row in rows}


def _phase1_link_counts(
    store: EnterprisePostgresStore,
    report_version_id: str,
) -> dict[str, int]:
    with store._connect(store.database_url, row_factory=store._dict_row) as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM claim_evidence) AS claim_evidence,
                (
                    SELECT COUNT(*)
                    FROM report_version_claims
                    WHERE report_version_id = %s
                ) AS report_version_claims,
                (
                    SELECT COUNT(*)
                    FROM report_version_evidence
                    WHERE report_version_id = %s
                ) AS report_version_evidence
            """,
            (report_version_id, report_version_id),
        ).fetchone()
    return {
        "claim_evidence": int(row["claim_evidence"]),
        "report_version_claims": int(row["report_version_claims"]),
        "report_version_evidence": int(row["report_version_evidence"]),
    }


def _audit_action_count(store: EnterprisePostgresStore, run_id: str) -> int:
    with store._connect(store.database_url, row_factory=store._dict_row) as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT action) AS action_count
            FROM audit_logs
            WHERE resource_id = %s
               OR after ->> 'run_id' = %s
            """,
            (run_id, run_id),
        ).fetchone()
    return int(row["action_count"])


if __name__ == "__main__":
    asyncio.run(main())
