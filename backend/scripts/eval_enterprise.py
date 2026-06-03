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
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    journal = RunJournal(Path(args.journal))
    runs = [
        run
        for run in journal.load_runs()
        if args.project_id is None or run.project_id == args.project_id
    ]
    baseline = journal.load_run(args.baseline_run_id) if args.baseline_run_id else None
    report = build_enterprise_evalops_report(runs, baseline=baseline, limit=args.limit)
    payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
        return
    print(payload)


if __name__ == "__main__":
    main()
