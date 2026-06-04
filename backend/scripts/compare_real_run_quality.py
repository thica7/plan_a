from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.business_intel import compare_run_quality
from packages.config import get_settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import KBCache, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.skills.registry import SkillRegistry

DEFAULT_OLD_RUN_ID = "411d3a19-7049-4a7e-aa9f-c5b63e74a69e"
DEFAULT_OLD_DB = Path(r"D:\codex_workspace\plan_a_old\plan_a\runs\run_journal.db")


def load_run_payload_from_sqlite(db_path: Path, run_id: str) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Run journal not found: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select detail_json from runs where id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RuntimeError(f"Run not found in {db_path}: {run_id}")
    payload = json.loads(row[0])
    if not isinstance(payload, dict):
        raise RuntimeError(f"Run payload is not a JSON object: {run_id}")
    return payload


def summarize_run_detail_payload(detail: dict[str, Any]) -> dict[str, object]:
    sources = _list_value(detail.get("raw_sources"))
    report = str(detail.get("report_md") or "")
    return {
        "run_id": detail.get("id"),
        "status": detail.get("status"),
        "execution_mode": detail.get("execution_mode"),
        "plan": detail.get("plan"),
        "report_chars": len(report),
        "raw_sources": len(sources),
        "claims": len(_list_value(detail.get("knowledge_claims"))),
        "qa_findings": len(_list_value(detail.get("qa_findings"))),
        "trace_spans": len(_list_value(detail.get("trace_spans"))),
        "metrics": detail.get("metrics") or {},
        "source_types": dict(
            collections.Counter(_source_field(item, "source_type") for item in sources)
        ),
        "by_competitor": dict(
            collections.Counter(_source_field(item, "competitor") for item in sources)
        ),
        "source_titles": [
            {
                "id": _source_field(item, "id"),
                "competitor": _source_field(item, "competitor"),
                "dimension": _source_field(item, "dimension"),
                "source_type": _source_field(item, "source_type"),
                "title": _source_field(item, "title"),
                "url": _source_field(item, "url"),
            }
            for item in sources[:16]
        ],
        "report_preview": report[:2000],
        "fallback_report": _looks_like_fallback_report(report),
    }


def old_run_summary(db_path: Path, run_id: str) -> dict[str, object]:
    return summarize_run_detail_payload(load_run_payload_from_sqlite(db_path, run_id))


def old_run_detail(db_path: Path, run_id: str) -> RunDetail | None:
    try:
        return RunDetail.model_validate(load_run_payload_from_sqlite(db_path, run_id))
    except Exception:
        return None


async def current_run_summary(
    *,
    topic: str,
    competitors: list[str],
    dimensions: list[str],
    execution_mode: str,
) -> tuple[dict[str, object], RunDetail]:
    settings = get_settings()
    store = EnterpriseMemoryStore()
    checkpoint = GraphCheckpointer.in_memory()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=settings,
        journal=RunJournal.in_memory(),
        kb_cache=KBCache.in_memory(),
        trace_store=TraceStore.in_memory(),
        graph_checkpointer=checkpoint,
        enterprise_store=store,
    )
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic=topic,
                competitors=competitors,
                dimensions=dimensions,
                execution_mode=execution_mode,
                idempotency_key=f"quality-compare-{uuid4().hex}",
            )
        )
        await service.run_pipeline(detail.id)
        completed = service.get_run(detail.id)
        if completed is None:
            raise RuntimeError("Current run did not persist a detail.")
        projection = store.get_run_projection(detail.id)
        payload = summarize_run_detail_payload(completed.model_dump(mode="json"))
        payload.update(
            {
                "enterprise_evidence": len(projection.evidence_records) if projection else 0,
                "enterprise_claims": len(projection.claim_records) if projection else 0,
                "report_version_id": projection.report_version.id if projection else None,
            }
        )
        return payload, completed
    finally:
        await checkpoint.aclose()


def build_summary_delta(
    old_summary: dict[str, object] | None,
    current_summary_value: dict[str, object],
) -> dict[str, object]:
    if not old_summary or old_summary.get("error"):
        return {"baseline_available": False}
    fields = ["report_chars", "raw_sources", "claims", "qa_findings", "trace_spans"]
    delta: dict[str, object] = {"baseline_available": True}
    for field in fields:
        old_value = _numeric(old_summary.get(field))
        current_value = _numeric(current_summary_value.get(field))
        delta[field] = current_value - old_value
    delta["fallback_report_regressed"] = bool(
        current_summary_value.get("fallback_report")
    ) and not bool(old_summary.get("fallback_report"))
    return delta


async def compare_real_run_quality(args: argparse.Namespace) -> dict[str, object]:
    old_summary_payload: dict[str, object] | None
    baseline_detail: RunDetail | None = None
    try:
        old_summary_payload = old_run_summary(args.old_db, args.old_run_id)
        baseline_detail = old_run_detail(args.old_db, args.old_run_id)
    except Exception as exc:
        old_summary_payload = {
            "run_id": args.old_run_id,
            "error": str(exc),
        }

    current_summary_payload, current_detail = await current_run_summary(
        topic=args.topic,
        competitors=args.competitors,
        dimensions=args.dimensions,
        execution_mode=args.execution_mode,
    )
    quality = compare_run_quality(current_detail, baseline=baseline_detail)
    return {
        "old": old_summary_payload,
        "current": current_summary_payload,
        "delta": build_summary_delta(old_summary_payload, current_summary_payload),
        "quality": quality.model_dump(mode="json"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real quality audit and compare it with an old plan_a run journal entry.",
    )
    parser.add_argument("--old-db", type=Path, default=DEFAULT_OLD_DB)
    parser.add_argument("--old-run-id", default=DEFAULT_OLD_RUN_ID)
    parser.add_argument("--topic", default="AI coding")
    parser.add_argument(
        "--competitors",
        nargs="+",
        default=["GitHub Copilot", "Cursor", "Claude Code", "Windsurf"],
    )
    parser.add_argument("--dimensions", nargs="+", default=["pricing", "feature", "persona"])
    parser.add_argument("--execution-mode", choices=["demo", "real"], default="real")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    payload = await compare_real_run_quality(args)
    encoded = json.dumps(payload, ensure_ascii=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print("COMPARE_JSON_START")
    print(encoded)
    print("COMPARE_JSON_END")


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _source_field(value: object, field: str) -> object:
    return value.get(field) if isinstance(value, dict) else None


def _looks_like_fallback_report(report: str) -> bool:
    lowered = report.casefold()
    return "fallback report" in lowered or "transient generation error" in lowered


def _numeric(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    asyncio.run(main())
