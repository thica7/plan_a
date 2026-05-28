from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.enterprise import EnterprisePostgresStore, build_enterprise_projection
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
)

DEFAULT_DATABASE_URL = (
    "postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5"
)


def main() -> None:
    database_url = os.getenv("ENTERPRISE_DATABASE_URL") or DEFAULT_DATABASE_URL
    store = EnterprisePostgresStore(database_url)
    now = datetime.utcnow()
    run_id = f"smoke-{uuid4().hex[:8]}"
    detail = RunDetail(
        id=run_id,
        topic="AI coding assistant enterprise smoke",
        status="completed",
        execution_mode="demo",
        created_at=now,
        updated_at=now,
        plan=AnalysisPlan(
            topic="AI coding assistant enterprise smoke",
            competitors=["Cursor"],
            dimensions=["pricing"],
            homepage_hints={"Cursor": "https://cursor.sh"},
        ),
        report_md="Cursor publishes pricing. [source:pricing-1]",
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.sh/pricing",
                snippet="Cursor publishes pricing.",
                content_hash="smoke-hash-1",
                confidence=0.9,
            )
        ],
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                pricing_model=PricingModel(
                    notes=[
                        KnowledgeClaim(
                            claim="Cursor publishes pricing.",
                            source_ids=["pricing-1"],
                            confidence=0.9,
                        )
                    ]
                ),
            )
        },
    )

    context = store.start_run(detail)
    projection = build_enterprise_projection(
        detail,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        competitor_id_map=context.competitor_id_map,
    )
    store.save_projection(projection)
    loaded = store.get_run_projection(run_id)
    if loaded is None:
        raise SystemExit("Postgres enterprise projection was not persisted.")
    if not loaded.evidence_records or not loaded.claim_records:
        raise SystemExit("Postgres enterprise projection is missing evidence or claims.")

    print(
        json.dumps(
            {
                "component": "enterprise_postgres",
                "ok": True,
                "run_id": run_id,
                "project_id": loaded.project_id,
                "evidence_count": len(loaded.evidence_records),
                "claim_count": len(loaded.claim_records),
                "report_version_id": loaded.report_version.id,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
