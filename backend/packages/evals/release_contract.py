from __future__ import annotations

from packages.quality import quality_findings_from_evalops
from packages.schema.evals import (
    EvalOpsReleaseContract,
    EvalOpsReleaseMetricRequirement,
    EvalOpsReleaseMode,
    EvalOpsReport,
)


def build_evalops_release_contract(
    report: EvalOpsReport,
    *,
    mode: EvalOpsReleaseMode = "advisory",
) -> EvalOpsReleaseContract:
    findings = quality_findings_from_evalops(report)
    blocking_issue_ids = [
        issue.id for issue in report.regression_gate_issues if issue.status == "fail"
    ]
    warning_issue_ids = [
        issue.id for issue in report.regression_gate_issues if issue.status == "warn"
    ]
    decision = _release_decision(report, mode=mode)
    allowed = decision != "blocked"
    return EvalOpsReleaseContract(
        mode=mode,
        decision=decision,
        allowed=allowed,
        status=report.regression_gate_status,
        reason=_release_reason(report, mode=mode, allowed=allowed),
        evaluated_run_ids=report.evaluated_run_ids,
        baseline_run_id=report.baseline_run_id,
        judge_mode=report.judge_mode,
        regression_gate_status=report.regression_gate_status,
        regression_gate_reason=report.regression_gate_reason,
        required_metrics=[
            EvalOpsReleaseMetricRequirement(
                name=metric.name,
                value=metric.value,
                target=metric.target,
                status=metric.status,
                blocking=(mode == "blocking" and metric.status == "fail"),
                summary=metric.summary,
            )
            for metric in report.metrics
        ],
        blocking_issue_ids=blocking_issue_ids,
        warning_issue_ids=warning_issue_ids,
        quality_finding_ids=[finding.id for finding in findings],
        quality_findings=[finding.model_dump(mode="json") for finding in findings],
        metadata={
            "run_count": report.run_count,
            "real_run_count": report.real_run_count,
            "golden_set_pass_rate": report.golden_set_pass_rate,
            "report_quality_score": report.report_quality_score,
            "source_recall": report.source_recall,
            "manual_time_saved_hours": report.manual_time_saved_hours,
            "regressed_run_count": report.regressed_run_count,
        },
    )


def _release_decision(report: EvalOpsReport, *, mode: EvalOpsReleaseMode) -> str:
    if report.regression_gate_status == "pass":
        return "allowed"
    if mode == "blocking" and report.regression_gate_status == "fail":
        return "blocked"
    return "review_required"


def _release_reason(
    report: EvalOpsReport,
    *,
    mode: EvalOpsReleaseMode,
    allowed: bool,
) -> str:
    if allowed and report.regression_gate_status == "pass":
        return "EvalOps regression gate passed."
    if mode == "advisory":
        return (
            "EvalOps is advisory for this environment; publish is allowed but "
            f"requires review attention: {report.regression_gate_reason}"
        )
    if allowed:
        return (
            "EvalOps blocking mode only blocks fail status; warning status requires "
            f"review: {report.regression_gate_reason}"
        )
    return f"EvalOps blocking mode rejected publish: {report.regression_gate_reason}"
