import importlib.util
from pathlib import Path


def _load_eval_module():
    path = Path("backend/scripts/eval_enterprise.py")
    spec = importlib.util.spec_from_file_location("eval_enterprise", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enterprise_eval_summary_requires_80_percent_pass_rate() -> None:
    module = _load_eval_module()
    rows = [
        {
            "case_id": "ok-1",
            "passed": True,
            "observability_score": 1.0,
            "compliance_status": "pass",
        },
        {
            "case_id": "ok-2",
            "passed": True,
            "observability_score": 0.9,
            "compliance_status": "warn",
        },
        {
            "case_id": "ok-3",
            "passed": True,
            "observability_score": 0.8,
            "compliance_status": "pass",
        },
        {
            "case_id": "ok-4",
            "passed": True,
            "observability_score": 1.0,
            "compliance_status": "pass",
        },
        {
            "case_id": "bad-1",
            "passed": False,
            "observability_score": 0.5,
            "compliance_status": "fail",
        },
    ]

    summary = module.build_enterprise_summary(
        rows,
        eval_mode="demo",
        judge_mode="heuristic",
        gate_policy=module.RegressionGatePolicy(max_compliance_fail_count=1),
    )

    assert summary["ok"] is True
    assert summary["case_count"] == 5
    assert summary["pass_rate"] == 0.8
    assert summary["compliance_fail_count"] == 1
    assert summary["regression_gate"]["passed"] is True
    assert summary["regression_gate"]["policy"]["min_pass_rate"] == 0.8
    assert summary["regression_gate"]["policy"]["max_compliance_fail_count"] == 1


def test_enterprise_eval_objective_gate_and_heuristic_score() -> None:
    module = _load_eval_module()
    row = {
        "status": "completed",
        "evidence_count": 2,
        "claim_count": 2,
        "report_chars": 100,
        "observability_score": 0.9,
        "compliance_blocker_count": 0,
        "audit_action_count": 5,
    }

    assert module.objective_case_passed(row) is True
    assert module.heuristic_judge_score(row) == 100


def test_enterprise_eval_regression_gate_reports_failed_checks() -> None:
    module = _load_eval_module()
    rows = [
        {
            "case_id": "ok-1",
            "passed": True,
            "observability_score": 0.7,
            "compliance_status": "pass",
        },
        {
            "case_id": "bad-1",
            "passed": False,
            "observability_score": 0.6,
            "compliance_status": "fail",
            "judge": {"passed": False},
        },
    ]
    policy = module.RegressionGatePolicy(
        min_pass_rate=0.9,
        min_average_observability_score=0.8,
        max_compliance_fail_count=0,
        require_no_failed_cases=True,
    )

    summary = module.build_enterprise_summary(
        rows,
        eval_mode="demo",
        judge_mode="heuristic",
        gate_policy=policy,
    )

    assert summary["ok"] is False
    assert summary["regression_gate"]["passed"] is False
    assert {item["id"] for item in summary["regression_gate"]["failed_checks"]} == {
        "pass_rate",
        "average_observability_score",
        "compliance_fail_count",
        "failed_count",
    }
