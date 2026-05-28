from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings  # noqa: E402
from packages.enterprise import EnterpriseMemoryStore  # noqa: E402
from packages.orchestrator.checkpointer import GraphCheckpointer  # noqa: E402
from packages.orchestrator.service import RunService  # noqa: E402
from packages.schema.api_dto import RunCreateRequest  # noqa: E402
from packages.skills.registry import SkillRegistry  # noqa: E402


@dataclass(frozen=True)
class EvalCase:
    id: str
    topic: str
    competitors: list[str]
    dimensions: list[str]
    layer: str


FALLBACK_CASES = [
    EvalCase(
        id="phase1-pricing",
        topic="AI coding assistant pricing comparison",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        layer="L1",
    ),
    EvalCase(
        id="phase1-feature",
        topic="Product analytics feature comparison",
        competitors=["Amplitude", "Mixpanel"],
        dimensions=["feature"],
        layer="L1",
    ),
    EvalCase(
        id="phase1-persona",
        topic="Customer support chatbot buyer personas",
        competitors=["Intercom", "Zendesk"],
        dimensions=["persona"],
        layer="L2",
    ),
    EvalCase(
        id="phase1-core-schema",
        topic="Enterprise AI search platform comparison",
        competitors=["Glean", "Coveo"],
        dimensions=["pricing", "feature", "persona"],
        layer="L1",
    ),
    EvalCase(
        id="phase1-topic-only",
        topic="AI meeting assistant market landscape",
        competitors=[],
        dimensions=["pricing", "feature", "persona"],
        layer="L3",
    ),
]


def load_cases(limit: int = 5) -> list[EvalCase]:
    path = Path("data/golden_set.jsonl")
    if not path.exists():
        return FALLBACK_CASES[:limit]
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            EvalCase(
                id=str(row["id"]),
                topic=str(row["topic"]),
                competitors=[str(item) for item in row.get("competitors", [])],
                dimensions=[str(item) for item in row.get("expected_dimensions", [])],
                layer=str(row.get("expected_layer", "L1")),
            )
        )
        if len(cases) >= limit:
            break
    return cases or FALLBACK_CASES[:limit]


async def run_case(case: EvalCase) -> dict[str, object]:
    checkpoint_path = Path("runs") / f"eval_baseline_{uuid4().hex}.db"
    store = EnterpriseMemoryStore()
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
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
        enterprise_store=store,
    )
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic=case.topic,
                competitors=case.competitors,
                dimensions=case.dimensions,
                competitor_layer=case.layer,  # type: ignore[arg-type]
                execution_mode="demo",
            )
        )
        await service.run_pipeline(detail.id)
        completed = service.get_run(detail.id)
        projection = store.get_run_projection(detail.id)
        if completed is None:
            raise RuntimeError(f"{case.id} did not produce a run detail.")

        baseline = {
            "status": "baseline_fixture",
            "evidence_count": 0,
            "claim_count": 0,
            "report_chars": 0,
        }
        system = {
            "status": completed.status,
            "evidence_count": len(projection.evidence_records) if projection else 0,
            "claim_count": len(projection.claim_records) if projection else 0,
            "report_chars": len(completed.report_md),
            "audit_action_count": len({log.action for log in store.list_audit_logs()}),
        }
        return {
            "case_id": case.id,
            "topic": case.topic,
            "baseline": baseline,
            "system": system,
            "passed": bool(
                completed.status == "completed"
                and projection is not None
                and projection.evidence_records
                and projection.claim_records
                and len({log.action for log in store.list_audit_logs()}) >= 5
            ),
        }
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


async def main() -> None:
    rows = [await run_case(case) for case in load_cases(limit=5)]
    summary = {
        "component": "baseline_eval",
        "ok": all(bool(row["passed"]) for row in rows),
        "case_count": len(rows),
        "passed_count": sum(1 for row in rows if row["passed"]),
        "rows": rows,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        raise SystemExit("Phase 1 baseline eval smoke failed.")


if __name__ == "__main__":
    asyncio.run(main())
