from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from packages.evals import build_enterprise_evalops_report  # noqa: E402
from packages.memory import RunJournal  # noqa: E402


class RegressionGatePolicy:
    def __init__(
        self,
        *,
        min_pass_rate: float = 0.8,
        min_average_observability_score: float = 0.7,
        max_compliance_fail_count: int = 0,
        require_no_failed_cases: bool = False,
    ) -> None:
        self.min_pass_rate = min_pass_rate
        self.min_average_observability_score = min_average_observability_score
        self.max_compliance_fail_count = max_compliance_fail_count
        self.require_no_failed_cases = require_no_failed_cases

    def model_dump(self) -> dict[str, Any]:
        return {
            "min_pass_rate": self.min_pass_rate,
            "min_average_observability_score": self.min_average_observability_score,
            "max_compliance_fail_count": self.max_compliance_fail_count,
            "require_no_failed_cases": self.require_no_failed_cases,
        }


def objective_case_passed(row: dict[str, Any]) -> bool:
    return (
        row.get("status") == "completed"
        and int(row.get("evidence_count") or 0) >= 1
        and int(row.get("claim_count") or 0) >= 1
        and int(row.get("report_chars") or 0) >= 80
        and float(row.get("observability_score") or 0.0) >= 0.5
        and int(row.get("compliance_blocker_count") or 0) == 0
        and int(row.get("audit_action_count") or 0) >= 1
    )


def heuristic_judge_score(row: dict[str, Any]) -> int:
    score = 0
    score += 20 if row.get("status") == "completed" else 0
    score += 20 if int(row.get("evidence_count") or 0) >= 2 else 0
    score += 20 if int(row.get("claim_count") or 0) >= 2 else 0
    score += 20 if float(row.get("observability_score") or 0.0) >= 0.8 else 0
    score += 10 if int(row.get("compliance_blocker_count") or 0) == 0 else 0
    score += 10 if int(row.get("audit_action_count") or 0) >= 3 else 0
    return score


def build_enterprise_summary(
    rows: list[dict[str, Any]],
    *,
    eval_mode: str,
    judge_mode: str,
    gate_policy: RegressionGatePolicy | None = None,
) -> dict[str, Any]:
    policy = gate_policy or RegressionGatePolicy()
    case_count = len(rows)
    passed_count = sum(1 for row in rows if bool(row.get("passed")))
    failed_count = case_count - passed_count
    pass_rate = round(passed_count / case_count, 3) if case_count else 0.0
    average_observability_score = round(
        mean(float(row.get("observability_score") or 0.0) for row in rows),
        3,
    ) if rows else 0.0
    compliance_fail_count = sum(1 for row in rows if row.get("compliance_status") == "fail")
    failed_checks = _failed_regression_checks(
        pass_rate=pass_rate,
        average_observability_score=average_observability_score,
        compliance_fail_count=compliance_fail_count,
        failed_count=failed_count,
        policy=policy,
    )
    gate = {
        "passed": not failed_checks,
        "policy": policy.model_dump(),
        "failed_checks": failed_checks,
    }
    return {
        "ok": gate["passed"],
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "case_count": case_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "pass_rate": pass_rate,
        "average_observability_score": average_observability_score,
        "compliance_fail_count": compliance_fail_count,
        "regression_gate": gate,
    }


def _failed_regression_checks(
    *,
    pass_rate: float,
    average_observability_score: float,
    compliance_fail_count: int,
    failed_count: int,
    policy: RegressionGatePolicy,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if pass_rate < policy.min_pass_rate:
        checks.append(
            {
                "id": "pass_rate",
                "actual": pass_rate,
                "expected": policy.min_pass_rate,
            }
        )
    if average_observability_score < policy.min_average_observability_score:
        checks.append(
            {
                "id": "average_observability_score",
                "actual": average_observability_score,
                "expected": policy.min_average_observability_score,
            }
        )
    if compliance_fail_count > policy.max_compliance_fail_count:
        checks.append(
            {
                "id": "compliance_fail_count",
                "actual": compliance_fail_count,
                "expected": policy.max_compliance_fail_count,
            }
        )
    if policy.require_no_failed_cases and failed_count > 0:
        checks.append({"id": "failed_count", "actual": failed_count, "expected": 0})
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the enterprise EvalOps report.")
    parser.add_argument("--journal", default=str(Path("runs") / "run_journal.db"))
    parser.add_argument("--baseline-run-id", default=None)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--judge-mode", choices=["heuristic", "llm"], default="heuristic")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    journal = RunJournal(Path(args.journal))
    runs = [
        run
        for run in journal.load_runs()
        if args.project_id is None or run.project_id == args.project_id
    ]
    baseline = journal.load_run(args.baseline_run_id) if args.baseline_run_id else None
    report = build_enterprise_evalops_report(
        runs,
        baseline=baseline,
        limit=args.limit,
        judge_mode=args.judge_mode,
    )
    report_payload = report.model_dump(mode="json")
    payload = (
        render_evalops_markdown(report_payload)
        if args.format == "markdown"
        else json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        return
    print(payload, end="")


def render_evalops_markdown(report: dict[str, Any]) -> str:
    metrics = {str(item.get("name")): item for item in _list_of_dicts(report.get("metrics"))}
    lines = [
        "# Enterprise EvalOps Quality Card",
        "",
        f"- Generated at: {report.get('generated_at', 'unknown')}",
        f"- Run count: {report.get('run_count', 0)}",
        f"- Evaluated runs: {', '.join(_string_list(report.get('evaluated_run_ids'))) or 'none'}",
        f"- Baseline run: {report.get('baseline_run_id') or 'none'}",
        f"- Regression gate: {str(report.get('regression_gate_status', 'unknown')).upper()}",
        f"- Gate reason: {report.get('regression_gate_reason', '')}",
        "",
        "## Executive Metrics",
        "",
        "| Metric | Value | Target | Status |",
        "|---|---:|---:|---:|",
    ]
    for metric_name in [
        "golden_set_pass_rate",
        "report_quality_score",
        "source_recall",
        "citation_validity_rate",
        "decision_replay_rate",
        "compliance_pass_rate",
        "real_quality_chain_rate",
        "time_savings_rate",
        "human_correction_rate",
        "redo_convergence_ratio",
    ]:
        metric = metrics.get(metric_name)
        if not metric:
            continue
        lines.append(
            "| {name} | {value} | {target} | {status} |".format(
                name=metric_name,
                value=_format_markdown_value(metric.get("value")),
                target=_format_markdown_value(metric.get("target")),
                status=metric.get("status", ""),
            )
        )

    lines.extend(
        [
            "",
            "## Quality Chain",
            "",
            "| Step | Pass Rate | Failed Runs | Summary |",
            "|---|---:|---:|---|",
        ]
    )
    for step in _list_of_dicts(report.get("quality_chain_steps")):
        failed_ids = _string_list(step.get("failed_run_ids"))
        lines.append(
            "| {label} | {rate} | {failed} | {summary} |".format(
                label=step.get("label") or step.get("step") or "unknown",
                rate=_format_percent(step.get("pass_rate")),
                failed=", ".join(failed_ids) if failed_ids else "none",
                summary=_escape_markdown_table(str(step.get("summary", ""))),
            )
        )

    issues = _list_of_dicts(report.get("regression_gate_issues"))
    if issues:
        lines.extend(
            [
                "",
                "## Gate Issues",
                "",
                "| Kind | ID | Status | Summary |",
                "|---|---|---:|---|",
            ]
        )
        for issue in issues:
            lines.append(
                "| {kind} | {id} | {status} | {summary} |".format(
                    kind=issue.get("kind", ""),
                    id=issue.get("id", ""),
                    status=issue.get("status", ""),
                    summary=_escape_markdown_table(str(issue.get("summary", ""))),
                )
            )

    lines.extend(
        [
            "",
            "## Golden Cases",
            "",
            "| Case | Score | Status | Summary |",
            "|---|---:|---:|---|",
        ]
    )
    for case in _list_of_dicts(report.get("cases"))[:20]:
        lines.append(
            "| {case_id} | {score} | {status} | {summary} |".format(
                case_id=case.get("case_id", ""),
                score=case.get("score", ""),
                status=case.get("status", ""),
                summary=_escape_markdown_table(str(case.get("summary", ""))),
            )
        )

    recommendations = _string_list(report.get("recommendations"))
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)

    lines.extend(
        [
            "",
            "## Method",
            "",
            (
                "This quality card is rendered from the same EvalOps payload consumed by "
                "the Enterprise Workbench. It is intended for repeatable demo-case and "
                "release-gate evidence, not as a hand-written assessment."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _format_markdown_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value if value is not None else "")


def _format_percent(value: object) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.1%}"
    return str(value if value is not None else "")


def _escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
