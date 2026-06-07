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
from packages.quality.findings import quality_findings_from_qc_issues
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import QCIssue
from packages.skills.registry import SkillRegistry

DEFAULT_OLD_RUN_ID = "411d3a19-7049-4a7e-aa9f-c5b63e74a69e"
DEFAULT_OLD_DB = Path(r"D:\codex_workspace\plan_a_old\plan_a\runs\run_journal.db")
TERMINAL_RUN_STATUSES = {"completed", "completed_with_blockers"}


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
    agent_messages = _list_value(detail.get("agent_messages"))
    tool_call_messages = _list_value(detail.get("tool_call_messages"))
    qa_findings = _list_value(detail.get("qa_findings"))
    report = str(detail.get("report_md") or "")
    return {
        "run_id": detail.get("id"),
        "status": detail.get("status"),
        "current_node": detail.get("current_node"),
        "execution_mode": detail.get("execution_mode"),
        "plan": detail.get("plan"),
        "report_chars": len(report),
        "raw_sources": len(sources),
        "claims": len(_list_value(detail.get("knowledge_claims"))),
        "qa_findings": len(qa_findings),
        "qa_issue_diagnostics": _qa_issue_diagnostics(qa_findings),
        "retained_warning_actions": _retained_warning_actions(qa_findings),
        "agent_messages": len(agent_messages),
        "tool_call_messages": len(tool_call_messages),
        "last_agent_messages": _agent_message_diagnostics(agent_messages),
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
    hitl_enabled: bool,
    auto_redo_warn_enabled: bool,
    timeout_seconds: float,
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
                hitl_enabled=hitl_enabled,
                auto_redo_warn_enabled=auto_redo_warn_enabled,
                idempotency_key=f"quality-compare-{uuid4().hex}",
            )
        )
        pipeline_timed_out = False
        try:
            await asyncio.wait_for(
                service.run_pipeline(detail.id),
                timeout=max(1.0, float(timeout_seconds)),
            )
        except TimeoutError:
            pipeline_timed_out = True
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
        if pipeline_timed_out:
            timeout = max(1.0, float(timeout_seconds))
            payload.update(
                {
                    "pipeline_timed_out": True,
                    "timeout_seconds": timeout,
                    "comparison_error": f"pipeline timeout after {timeout:g} seconds",
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
        hitl_enabled=args.hitl_enabled,
        auto_redo_warn_enabled=args.auto_redo_warn_enabled,
        timeout_seconds=args.timeout_seconds,
    )
    quality = apply_pipeline_completion_gate(
        compare_run_quality(current_detail, baseline=baseline_detail).model_dump(mode="json"),
        current_summary_payload,
    )
    payload: dict[str, object] = {
        "old": old_summary_payload,
        "current": current_summary_payload,
        "delta": build_summary_delta(old_summary_payload, current_summary_payload),
        "quality": quality,
    }
    if current_summary_payload.get("comparison_error"):
        payload["comparison_error"] = current_summary_payload["comparison_error"]
    return payload


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
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument(
        "--hitl-enabled",
        action="store_true",
        help=(
            "Allow HITL interrupts during automated comparison. By default the audit "
            "runs without HITL so it can reach a terminal report state."
        ),
    )
    parser.add_argument(
        "--auto-redo-warn-enabled",
        action="store_true",
        help=(
            "Allow warning-only final QA findings to trigger scoped redo during the "
            "comparison. Disabled by default so audits can reach a terminal report state."
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = await asyncio.wait_for(
            compare_real_run_quality(args),
            timeout=max(1.0, float(args.timeout_seconds)) + 30.0,
        )
    except TimeoutError:
        payload = build_timeout_payload(args)
    encoded = (
        render_compare_markdown(payload)
        if args.format == "markdown"
        else json.dumps(payload, ensure_ascii=True, indent=2)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded.rstrip() + "\n", encoding="utf-8")
    if args.format == "markdown":
        print(encoded.rstrip())
        return
    print("COMPARE_JSON_START")
    print(encoded)
    print("COMPARE_JSON_END")


def render_compare_markdown(payload: dict[str, object]) -> str:
    old = _dict_value(payload.get("old"))
    current = _dict_value(payload.get("current"))
    delta = _dict_value(payload.get("delta"))
    quality = _dict_value(payload.get("quality"))
    baseline_run_id = _text(old.get("run_id")) or _text(quality.get("baseline_run_id"))
    lines = [
        "# Real Run Quality Comparison",
        "",
        f"- Current run: {_text(current.get('run_id')) or 'unknown'}",
        f"- Baseline run: {baseline_run_id or 'none'}",
        f"- Current status: {_text(current.get('status')) or 'unknown'}",
        f"- Current node: {_text(current.get('current_node')) or 'none'}",
        f"- Execution mode: {_text(current.get('execution_mode')) or 'unknown'}",
        f"- Quality verdict: {_text(quality.get('verdict')) or 'unknown'}",
        f"- Regression gate: {_text(quality.get('regression_gate_status')) or 'unknown'}",
    ]
    if quality.get("pipeline_incomplete") is True:
        lines.append("- Pipeline incomplete: yes")
    if payload.get("comparison_error"):
        lines.append(f"- Comparison error: {_escape_table(_text(payload.get('comparison_error')))}")
    lines.extend(
        [
            "",
            "## Score",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Target score | {_number_text(quality.get('target_score'))} |",
            f"| Baseline score | {_number_text(quality.get('baseline_score'))} |",
            f"| Delta score | {_signed_number_text(quality.get('delta_score'))} |",
            "",
            "## Shape Delta",
            "",
        ]
    )
    if delta.get("baseline_available") is False:
        lines.append("- Baseline unavailable; shape deltas were not computed.")
    else:
        lines.extend(
            [
                "| Field | Delta |",
                "|---|---:|",
                f"| Report chars | {_signed_number_text(delta.get('report_chars'))} |",
                f"| Raw sources | {_signed_number_text(delta.get('raw_sources'))} |",
                f"| Claims | {_signed_number_text(delta.get('claims'))} |",
                f"| QA findings | {_signed_number_text(delta.get('qa_findings'))} |",
                f"| Trace spans | {_signed_number_text(delta.get('trace_spans'))} |",
                (
                    "| Fallback report regressed | "
                    f"{'yes' if delta.get('fallback_report_regressed') is True else 'no'} |"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Current Evidence",
            "",
            "| Field | Value |",
            "|---|---:|",
            f"| Raw sources | {_number_text(current.get('raw_sources'))} |",
            f"| Enterprise evidence | {_number_text(current.get('enterprise_evidence'))} |",
            f"| Claims | {_number_text(current.get('claims'))} |",
            f"| Enterprise claims | {_number_text(current.get('enterprise_claims'))} |",
            f"| QA findings | {_number_text(current.get('qa_findings'))} |",
            f"| Agent messages | {_number_text(current.get('agent_messages'))} |",
            f"| Tool calls | {_number_text(current.get('tool_call_messages'))} |",
            f"| Trace spans | {_number_text(current.get('trace_spans'))} |",
            f"| Report chars | {_number_text(current.get('report_chars'))} |",
            "",
            "## Quality Metrics",
            "",
            "| Metric | Target | Baseline | Delta | Status |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for metric in _list_of_dicts(quality.get("metrics")):
        lines.append(
            "| {name} | {target} | {baseline} | {delta_value} | {status} |".format(
                name=_escape_table(_text(metric.get("name"))),
                target=_number_text(metric.get("target_value")),
                baseline=_number_text(metric.get("baseline_value")),
                delta_value=_signed_number_text(metric.get("delta")),
                status=_escape_table(_text(metric.get("status"))),
            )
        )

    last_messages = _list_of_dicts(current.get("last_agent_messages"))
    qa_diagnostics = _list_of_dicts(current.get("qa_issue_diagnostics"))
    retained_warning_actions = _list_of_dicts(current.get("retained_warning_actions"))
    if qa_diagnostics:
        lines.extend(
            [
                "",
                "## QA Issue Diagnostics",
                "",
                "| ID | Severity | Agent | Dimension | Competitor | Problem |",
                "|---|---|---|---|---|---|",
            ]
        )
        for issue in qa_diagnostics:
            lines.append(
                "| {id} | {severity} | {target_agent} | {dimension} | "
                "{competitor} | {problem} |".format(
                    id=_escape_table(_text(issue.get("id"))),
                    severity=_escape_table(_text(issue.get("severity"))),
                    target_agent=_escape_table(_text(issue.get("target_agent"))),
                    dimension=_escape_table(_text(issue.get("target_subagent"))),
                    competitor=_escape_table(_text(issue.get("target_competitor"))),
                    problem=_escape_table(_text(issue.get("problem")))[:240],
                )
            )

    if retained_warning_actions:
        lines.extend(
            [
                "",
                "## Retained Warning Actions",
                "",
                (
                    "Every retained warning below has a typed unresolved reason, "
                    "a typed required action, and an acceptance rule."
                ),
                "",
                "| ID | Reason code | Action | Acceptance rule | Next action |",
                "|---|---|---|---|---|",
            ]
        )
        for warning in retained_warning_actions:
            lines.append(
                "| {id} | {reason_code} | {required_action} | {acceptance_rule} | "
                "{next_action} |".format(
                    id=_escape_table(_text(warning.get("id"))),
                    reason_code=_escape_table(_text(warning.get("reason_code"))),
                    required_action=_escape_table(_text(warning.get("required_action"))),
                    acceptance_rule=_escape_table(_text(warning.get("acceptance_rule")))[:220],
                    next_action=_escape_table(_text(warning.get("next_action")))[:220],
                )
            )

    if last_messages:
        lines.extend(
            [
                "",
                "## Last Agent Messages",
                "",
                "| From | To | Type | Status | Detail |",
                "|---|---|---|---|---|",
            ]
        )
        for message in last_messages:
            lines.append(
                "| {from_agent} | {to_agent} | {message_type} | {status} | {detail} |".format(
                    from_agent=_escape_table(_text(message.get("from_agent"))),
                    to_agent=_escape_table(_text(message.get("to_agent"))),
                    message_type=_escape_table(_text(message.get("message_type"))),
                    status=_escape_table(_text(message.get("status"))),
                    detail=_escape_table(_text(message.get("detail")))[:180],
                )
            )

    gate_reasons = _string_list(quality.get("regression_gate_reasons"))
    if gate_reasons:
        lines.extend(["", "## Gate Reasons", ""])
        lines.extend(f"- {item}" for item in gate_reasons)

    recommendations = _string_list(quality.get("recommendations"))
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)

    lines.extend(
        [
            "",
            "## Method",
            "",
            (
                "This card is generated by `backend/scripts/compare_real_run_quality.py` "
                "from the current run, the selected old plan_a baseline, and the same "
                "RunQualityComparison gate used by the API."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _source_field(value: object, field: str) -> object:
    return value.get(field) if isinstance(value, dict) else None


def _agent_message_diagnostics(messages: list[Any]) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for message in messages[-8:]:
        if not isinstance(message, dict):
            continue
        payload = message.get("payload")
        detail = ""
        if isinstance(payload, dict):
            detail_parts: list[str] = []
            writer_mode = payload.get("writer_mode")
            if writer_mode:
                detail_parts.append(f"writer_mode={_summarize_payload_value(writer_mode)}")
            error = payload.get("error")
            if error:
                detail_parts.append(f"error={_summarize_payload_value(error)}")
            if detail_parts:
                detail = "; ".join(detail_parts)
            else:
                for key in (
                    "decision",
                    "feedback_id",
                    "report_md",
                    "qa_feedback",
                ):
                    value = payload.get(key)
                    if value:
                        detail = _summarize_payload_value(value)
                        break
        diagnostics.append(
            {
                "from_agent": message.get("from_agent"),
                "to_agent": message.get("to_agent"),
                "message_type": message.get("message_type"),
                "status": message.get("status"),
                "detail": detail,
            }
        )
    return diagnostics


def _qa_issue_diagnostics(issues: list[Any]) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for issue in issues[:12]:
        if not isinstance(issue, dict):
            continue
        diagnostics.append(
            {
                "id": issue.get("id"),
                "severity": issue.get("severity"),
                "target_agent": issue.get("target_agent"),
                "target_subagent": issue.get("target_subagent"),
                "target_competitor": issue.get("target_competitor"),
                "problem": issue.get("problem"),
            }
        )
    return diagnostics


def _retained_warning_actions(issues: list[Any]) -> list[dict[str, object]]:
    parsed_issues: list[QCIssue] = []
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("severity") != "warn":
            continue
        try:
            parsed_issues.append(QCIssue.model_validate(issue))
        except Exception:
            continue

    actions: list[dict[str, object]] = []
    for finding in quality_findings_from_qc_issues(parsed_issues):
        actions.append(
            {
                "id": finding.id,
                "source_id": finding.source_id,
                "reason_code": _warning_reason_code(finding),
                "source_agent": finding.source_agent,
                "dimension": finding.dimension,
                "competitor": finding.competitor_name,
                "required_action": finding.required_action,
                "acceptance_rule": finding.acceptance_rule,
                "next_action": finding.recommendation
                or _next_action_for_required_action(finding.required_action),
                "message": finding.message,
            }
        )
    return actions


def _warning_reason_code(finding: object) -> str:
    field_path = _text(getattr(finding, "field_path", ""))
    issue_type = _text(getattr(finding, "issue_type", ""))
    message = _text(getattr(finding, "message", "")).casefold()
    dimension = _text(getattr(finding, "dimension", "")).casefold()
    if field_path.startswith("release_gate."):
        if "claim_self_consistency" in message or "validation is weak" in message:
            return "claim_validation_followup"
        return "release_gate_followup"
    if dimension == "persona":
        if "truncated" in message or "incomplete" in message:
            return "persona_field_incomplete"
        return "persona_evidence_depth"
    if "timeout" in message:
        return "agent_timeout_followup"
    if "confidence" in message:
        return "confidence_outlier"
    return issue_type or "quality_warning"


def _next_action_for_required_action(action: str) -> str:
    return {
        "none": "No follow-up action is required.",
        "add_evidence": "Collect accepted evidence for the affected field or claim.",
        "rewrite_claim": "Rewrite the claim so it directly matches cited evidence.",
        "downgrade_claim": "Mark the claim as weak, caveated, or non-decisive.",
        "delete_claim": "Remove the unsupported claim from release scope.",
        "rewrite_report": "Regenerate the affected report section and re-check citations.",
        "rerun_scope": "Run scoped redo and confirm the warning no longer appears.",
        "human_review": "Record a reviewer decision or follow-up before publication.",
        "monitor": "Track the warning without blocking publication.",
    }.get(action, "Review this warning before publication.")


def _summarize_payload_value(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split())[:220]
    if isinstance(value, list):
        return f"{len(value)} item(s)"
    if isinstance(value, dict):
        return ", ".join(sorted(str(key) for key in value)[:6])
    return str(value)[:220]


def _looks_like_fallback_report(report: str) -> bool:
    lowered = report.casefold()
    return "fallback report" in lowered or "transient generation error" in lowered


def _numeric(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def apply_pipeline_completion_gate(
    quality: dict[str, object],
    current_summary_value: dict[str, object],
) -> dict[str, object]:
    reasons = _pipeline_completion_reasons(current_summary_value)
    if not reasons:
        quality["pipeline_incomplete"] = False
        return quality

    existing_reasons = _string_list(quality.get("regression_gate_reasons"))
    existing_recommendations = _string_list(quality.get("recommendations"))
    quality.update(
        {
            "verdict": "fail",
            "regression_gate_status": "fail",
            "regression_gate_passed": False,
            "pipeline_incomplete": True,
            "regression_gate_reasons": [*reasons, *existing_reasons],
            "recommendations": [
                (
                    "Resolve pipeline completion before judging narrative quality: "
                    "the automated comparison must finish with a non-empty report_md."
                ),
                *existing_recommendations,
            ],
        }
    )
    return quality


def _pipeline_completion_reasons(current_summary_value: dict[str, object]) -> list[str]:
    status = _text(current_summary_value.get("status")) or "unknown"
    current_node = _text(current_summary_value.get("current_node")) or "none"
    reasons: list[str] = []
    if current_summary_value.get("pipeline_timed_out") is True:
        timeout = _numeric(current_summary_value.get("timeout_seconds"))
        reasons.append(f"current run pipeline timed out after {timeout:g} seconds")
    if status not in TERMINAL_RUN_STATUSES:
        reasons.append(
            f"current run did not complete: status={status}, current_node={current_node}"
        )
    if _numeric(current_summary_value.get("report_chars")) <= 0:
        reasons.append("current run did not produce report_md")
    return reasons


def build_timeout_payload(args: argparse.Namespace) -> dict[str, object]:
    timeout_seconds = max(1.0, float(args.timeout_seconds))
    try:
        old_summary_payload = old_run_summary(args.old_db, args.old_run_id)
    except Exception as exc:
        old_summary_payload = {
            "run_id": args.old_run_id,
            "error": str(exc),
        }
    current_summary_payload = {
        "run_id": None,
        "status": "timeout",
        "current_node": None,
        "execution_mode": args.execution_mode,
        "report_chars": 0,
        "raw_sources": 0,
        "claims": 0,
        "qa_findings": 0,
        "agent_messages": 0,
        "tool_call_messages": 0,
        "trace_spans": 0,
        "timeout_seconds": timeout_seconds,
    }
    return {
        "old": old_summary_payload,
        "current": current_summary_payload,
        "delta": {
            "baseline_available": not bool(old_summary_payload.get("error")),
            "timed_out": True,
        },
        "quality": {
            "target_score": 0,
            "baseline_score": None,
            "delta_score": None,
            "verdict": "fail",
            "regression_gate_status": "fail",
            "regression_gate_passed": False,
            "regression_gate_reasons": [
                f"real run comparison timed out after {timeout_seconds:g} seconds"
            ],
            "metrics": [],
            "recommendations": [
                (
                    "Inspect external search, fetch, and LLM stages; reduce scenario size or "
                    "raise --timeout-seconds only after stage-level progress is visible."
                )
            ],
        },
        "comparison_error": f"timeout after {timeout_seconds:g} seconds",
    }


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _text(value: object) -> str:
    return str(value) if value is not None else ""


def _number_text(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return _escape_table(str(value))
    return f"{parsed:.3f}".rstrip("0").rstrip(".")


def _signed_number_text(value: object) -> str:
    if value is None:
        return "n/a"
    number = _numeric(value)
    prefix = "+" if number > 0 else ""
    return f"{prefix}{_number_text(number)}"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    asyncio.run(main())
