from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

SCRIPT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_ROOT.parent
sys.path.insert(0, str(SCRIPT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from eval_baseline import EvalCase, load_cases  # noqa: E402

from packages.compliance import build_run_compliance_report  # noqa: E402
from packages.config import Settings, get_settings  # noqa: E402
from packages.enterprise import EnterpriseMemoryStore  # noqa: E402
from packages.llm import DoubaoClient, LLMError  # noqa: E402
from packages.observability import evaluate_trace_observability  # noqa: E402
from packages.orchestrator.checkpointer import GraphCheckpointer  # noqa: E402
from packages.orchestrator.service import RunService  # noqa: E402
from packages.schema.api_dto import RunCreateRequest  # noqa: E402
from packages.skills.registry import SkillRegistry  # noqa: E402

EvalMode = Literal["demo", "real"]
JudgeMode = Literal["off", "heuristic", "llm"]


async def run_enterprise_case(
    case: EvalCase,
    *,
    settings: Settings,
    eval_mode: EvalMode,
    judge_mode: JudgeMode,
) -> dict[str, Any]:
    checkpoint_path = Path("runs") / f"eval_enterprise_{uuid4().hex}.db"
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings_for_mode(settings, eval_mode),
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
                execution_mode=eval_mode,
            )
        )
        await service.run_pipeline(detail.id)
        completed = service.get_run(detail.id)
        projection = store.get_run_projection(detail.id)
        if completed is None:
            raise RuntimeError(f"{case.id} did not produce a run detail.")

        observability = evaluate_trace_observability(completed.id, completed.trace_spans)
        compliance = build_run_compliance_report(completed, settings=settings)
        row: dict[str, Any] = {
            "case_id": case.id,
            "topic": case.topic,
            "eval_mode": eval_mode,
            "status": completed.status,
            "evidence_count": len(projection.evidence_records) if projection else 0,
            "claim_count": len(projection.claim_records) if projection else 0,
            "report_chars": len(completed.report_md),
            "trace_span_count": len(completed.trace_spans),
            "observability_status": observability.status,
            "observability_score": _observability_score(observability),
            "compliance_status": compliance.status,
            "compliance_blocker_count": compliance.blocker_count,
            "audit_action_count": len({log.action for log in store.list_audit_logs()}),
        }
        row["objective_passed"] = objective_case_passed(row)
        row["judge"] = await judge_case(row, judge_mode=judge_mode, settings=settings)
        row["passed"] = row["objective_passed"] and row["judge"]["passed"]
        return row
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


def objective_case_passed(row: dict[str, Any]) -> bool:
    return bool(
        row["status"] == "completed"
        and row["evidence_count"] > 0
        and row["claim_count"] > 0
        and row["report_chars"] > 0
        and row["observability_score"] >= 0.8
        and row["compliance_blocker_count"] == 0
        and row["audit_action_count"] >= 5
    )


async def judge_case(
    row: dict[str, Any],
    *,
    judge_mode: JudgeMode,
    settings: Settings,
) -> dict[str, Any]:
    if judge_mode == "off":
        return {"mode": "off", "passed": True, "score": None, "rationale": "Judge disabled."}
    if judge_mode == "heuristic":
        score = heuristic_judge_score(row)
        return {
            "mode": "heuristic",
            "passed": score >= 80,
            "score": score,
            "rationale": "Heuristic judge requires evidence, claims, trace, compliance, and audit.",
        }
    if not settings.has_llm_credentials:
        raise LLMError("LLM judge requires ARK or BACKUP_LLM credentials.")
    client = DoubaoClient(settings)
    verdict = await client.complete_json(
        system=(
            "You are an enterprise competitive-intelligence evaluation judge. "
            "Score whether the run is evidence-backed, auditable, compliant, and useful."
        ),
        user=json.dumps(row, ensure_ascii=False, indent=2),
        schema_hint='{"passed": true, "score": 0, "rationale": "short"}',
    )
    score = int(verdict.get("score", 0))
    return {
        "mode": "llm",
        "passed": bool(verdict.get("passed", False)) and score >= 80,
        "score": score,
        "rationale": str(verdict.get("rationale", "")),
    }


def heuristic_judge_score(row: dict[str, Any]) -> int:
    score = 0
    if row["status"] == "completed":
        score += 15
    if row["evidence_count"] > 0:
        score += 20
    if row["claim_count"] > 0:
        score += 20
    if row["report_chars"] > 0:
        score += 10
    if row["observability_score"] >= 0.8:
        score += 15
    if row["compliance_blocker_count"] == 0:
        score += 15
    if row["audit_action_count"] >= 5:
        score += 5
    return score


def build_enterprise_summary(
    rows: list[dict[str, Any]],
    *,
    eval_mode: EvalMode,
    judge_mode: JudgeMode,
) -> dict[str, Any]:
    passed_count = sum(1 for row in rows if row["passed"])
    pass_rate = passed_count / len(rows) if rows else 0.0
    return {
        "component": "enterprise_eval",
        "ok": bool(rows) and pass_rate >= 0.8,
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "case_count": len(rows),
        "passed_count": passed_count,
        "pass_rate": pass_rate,
        "average_observability_score": (
            sum(float(row["observability_score"]) for row in rows) / len(rows)
            if rows
            else 0.0
        ),
        "compliance_fail_count": sum(
            1 for row in rows if row["compliance_status"] == "fail"
        ),
        "rows": rows,
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Enterprise Eval Report",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Eval mode: {summary['eval_mode']}",
        f"- Judge mode: {summary['judge_mode']}",
        f"- Case count: {summary['case_count']}",
        f"- Passed count: {summary['passed_count']}",
        f"- Pass rate: {summary['pass_rate']:.2%}",
        f"- Average observability score: {summary['average_observability_score']:.2f}",
        f"- Compliance fail count: {summary['compliance_fail_count']}",
        f"- Overall: {'PASS' if summary['ok'] else 'FAIL'}",
        "",
        "| Case | Status | Evidence | Claims | Obs | Compliance | Judge |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {case_id} | {status} | {evidence_count} | {claim_count} | "
            "{observability_score:.2f} | {compliance_status} | {judge_score} |".format(
                case_id=row["case_id"],
                status=row["status"],
                evidence_count=row["evidence_count"],
                claim_count=row["claim_count"],
                observability_score=row["observability_score"],
                compliance_status=row["compliance_status"],
                judge_score=row["judge"]["score"],
            )
        )
    lines.extend(
        [
            "",
            "## Method",
            "",
            "The enterprise eval runs golden cases through the product pipeline and checks "
            "evidence, claims, report output, audit actions, OpenTelemetry trace readiness, "
            "and compliance blockers. `--judge-mode llm` adds an external model judge when "
            "credentials are available; `heuristic` is the deterministic CI gate.",
        ]
    )
    return "\n".join(lines) + "\n"


def _settings_for_mode(settings: Settings, eval_mode: EvalMode) -> Settings:
    if eval_mode == "real":
        return replace(settings, demo_mode=False)
    return replace(
        settings,
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        backup_llm_api_key=None,
        backup_llm_model=None,
        pplx_api_key=None,
    )


def _observability_score(report: object) -> float:
    return min(
        1.0,
        (
            float(getattr(report, "trace_id_coverage", 0.0))
            + float(getattr(report, "traceparent_coverage", 0.0))
            + float(getattr(report, "otel_span_id_coverage", 0.0))
        )
        / 3.0,
    )


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    if args.mode == "real" and not settings.has_llm_credentials:
        raise SystemExit("Real eval mode requires ARK or BACKUP_LLM credentials.")
    cases = load_cases(limit=args.limit)
    rows = [
        await run_enterprise_case(
            case,
            settings=settings,
            eval_mode=args.mode,
            judge_mode=args.judge_mode,
        )
        for case in cases
    ]
    summary = build_enterprise_summary(rows, eval_mode=args.mode, judge_mode=args.judge_mode)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        raise SystemExit("Enterprise eval failed.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run enterprise-grade eval cases.")
    parser.add_argument("--limit", type=int, default=5, help="Use 0 for all cases.")
    parser.add_argument("--mode", choices=["demo", "real"], default="demo")
    parser.add_argument("--judge-mode", choices=["off", "heuristic", "llm"], default="heuristic")
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    if args.limit <= 0:
        args.limit = None
    return args


if __name__ == "__main__":
    asyncio.run(main())
