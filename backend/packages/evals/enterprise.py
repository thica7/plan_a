from __future__ import annotations

from statistics import mean

from packages.business_intel import compare_run_quality
from packages.schema.api_dto import RunDetail, RunQualityComparison
from packages.schema.evals import EvalOpsCaseResult, EvalOpsMetric, EvalOpsReport, EvalOpsStatus

MANUAL_BASELINE_HOURS_PER_REPORT = 6.0
AUTOMATION_FLOOR_HOURS_PER_REPORT = 0.08


def build_enterprise_evalops_report(
    runs: list[RunDetail],
    *,
    baseline: RunDetail | None = None,
    limit: int = 30,
) -> EvalOpsReport:
    recent_runs = sorted(runs, key=lambda item: item.updated_at, reverse=True)[: max(1, limit)]
    comparisons = [
        compare_run_quality(run, baseline=baseline if baseline is not None and baseline.id != run.id else None)
        for run in recent_runs
    ]
    real_run_count = sum(1 for run in recent_runs if run.execution_mode == "real")
    demo_run_count = len(recent_runs) - real_run_count
    real_run_ratio = _ratio([run.execution_mode == "real" for run in recent_runs])
    real_quality_chain_rate = _ratio(
        [
            comparison.real_collection_signal
            and comparison.real_llm_signal
            and comparison.report_quality_signal
            for comparison in comparisons
        ]
    )
    delta_scores = [
        comparison.delta_score
        for comparison in comparisons
        if comparison.delta_score is not None
    ]
    average_delta_score = (
        round(_average_float([float(score) for score in delta_scores]), 2)
        if delta_scores
        else None
    )
    regressed_run_count = sum(
        1
        for comparison in comparisons
        if comparison.delta_score is not None and comparison.delta_score < 0
    )
    report_quality_score = _average_int([comparison.target_score for comparison in comparisons])
    source_recall = _average_float(
        [_metric_value(comparison, "source_coverage_rate") for comparison in comparisons]
    )
    verified_rate = _average_float(
        [_metric_value(comparison, "verified_source_rate") for comparison in comparisons]
    )
    citation_rate = _average_float(
        [_metric_value(comparison, "claim_citation_rate") for comparison in comparisons]
    )
    real_collection_rate = _ratio(
        [comparison.real_collection_signal for comparison in comparisons],
    )
    real_llm_rate = _ratio([comparison.real_llm_signal for comparison in comparisons])
    total_duration_hours = sum(
        max(run.metrics.total_duration_ms / 3_600_000.0, AUTOMATION_FLOOR_HOURS_PER_REPORT)
        for run in recent_runs
    )
    manual_hours = len(recent_runs) * MANUAL_BASELINE_HOURS_PER_REPORT
    task_time_saved_hours = max(0.0, manual_hours - total_duration_hours)
    cost_per_report_usd = (
        round(sum(run.metrics.cost_estimate_usd for run in recent_runs) / len(recent_runs), 6)
        if recent_runs
        else 0.0
    )
    cases = _golden_cases(
        comparisons,
        report_quality_score=report_quality_score,
        source_recall=source_recall,
        verified_rate=verified_rate,
        citation_rate=citation_rate,
        real_collection_rate=real_collection_rate,
        real_llm_rate=real_llm_rate,
    )
    golden_set_pass_rate = _ratio([case.status == "pass" for case in cases])
    metrics = [
        _metric("golden_set_pass_rate", golden_set_pass_rate, 0.8, "ratio"),
        _metric("report_quality_score", float(report_quality_score), 72.0, "score"),
        _metric("source_recall", source_recall, 0.6, "ratio"),
        _metric("verified_source_rate", verified_rate, 0.6, "ratio"),
        _metric("claim_citation_rate", citation_rate, 0.6, "ratio"),
        _metric("real_collection_rate", real_collection_rate, 0.5, "ratio"),
        _metric("real_llm_rate", real_llm_rate, 0.5, "ratio"),
        _metric("real_quality_chain_rate", real_quality_chain_rate, 0.5, "ratio"),
        _metric("task_time_saved_hours", task_time_saved_hours, len(recent_runs) * 3.0, "hours"),
        _metric("cost_per_report_usd", cost_per_report_usd, 5.0, "usd", lower_is_better=True),
    ]
    if average_delta_score is not None:
        metrics.append(_metric("average_delta_score", average_delta_score, 0.0, "score"))
    gate_status, gate_reason = _regression_gate(comparisons, metrics)
    return EvalOpsReport(
        run_count=len(recent_runs),
        evaluated_run_ids=[run.id for run in recent_runs],
        baseline_run_id=baseline.id if baseline is not None else None,
        real_run_count=real_run_count,
        demo_run_count=demo_run_count,
        real_run_ratio=round(real_run_ratio, 3),
        real_quality_chain_rate=round(real_quality_chain_rate, 3),
        average_delta_score=average_delta_score,
        regressed_run_count=regressed_run_count,
        golden_set_size=len(cases),
        golden_set_pass_rate=round(golden_set_pass_rate, 3),
        report_quality_score=report_quality_score,
        source_recall=round(source_recall, 3),
        task_time_saved_hours=round(task_time_saved_hours, 2),
        cost_per_report_usd=cost_per_report_usd,
        regression_gate_status=gate_status,
        regression_gate_reason=gate_reason,
        metrics=metrics,
        cases=cases,
        recommendations=_recommendations(metrics, comparisons),
    )


def _golden_cases(
    comparisons: list[RunQualityComparison],
    *,
    report_quality_score: int,
    source_recall: float,
    verified_rate: float,
    citation_rate: float,
    real_collection_rate: float,
    real_llm_rate: float,
) -> list[EvalOpsCaseResult]:
    target_run_id = comparisons[0].target_run_id if comparisons else None
    baseline_run_id = comparisons[0].baseline_run_id if comparisons else None
    return [
        _case(
            "golden.report_quality",
            "Report quality score",
            report_quality_score,
            72,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.source_recall",
            "Competitor source recall",
            round(source_recall * 100),
            60,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.verified_sources",
            "Verified evidence rate",
            round(verified_rate * 100),
            60,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.claim_citations",
            "Claim citation rate",
            round(citation_rate * 100),
            60,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.real_collection",
            "Real collection signal",
            round(real_collection_rate * 100),
            50,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.real_llm",
            "Real LLM signal",
            round(real_llm_rate * 100),
            50,
            target_run_id,
            baseline_run_id,
        ),
    ]


def _case(
    case_id: str,
    name: str,
    score: int,
    target: int,
    target_run_id: str | None,
    baseline_run_id: str | None,
) -> EvalOpsCaseResult:
    status: EvalOpsStatus = "pass" if score >= target else "warn" if score >= target * 0.75 else "fail"
    return EvalOpsCaseResult(
        case_id=case_id,
        name=name,
        status=status,
        score=max(0, min(100, score)),
        target_run_id=target_run_id,
        baseline_run_id=baseline_run_id,
        summary=f"{score}/100 against target {target}.",
    )


def _metric(
    name: str,
    value: float,
    target: float,
    unit: str,
    *,
    lower_is_better: bool = False,
) -> EvalOpsMetric:
    if lower_is_better:
        status: EvalOpsStatus = "pass" if value <= target else "warn" if value <= target * 1.5 else "fail"
    else:
        status = "pass" if value >= target else "warn" if value >= target * 0.75 else "fail"
    return EvalOpsMetric(
        name=name,
        value=round(value, 4),
        target=target,
        unit=unit,
        status=status,
        summary=_metric_summary(name, value, target, unit, lower_is_better=lower_is_better),
    )


def _metric_summary(
    name: str,
    value: float,
    target: float,
    unit: str,
    *,
    lower_is_better: bool,
) -> str:
    comparator = "<=" if lower_is_better else ">="
    suffix = f" {unit}" if unit else ""
    return f"{name} {value:.3f}{suffix}; target {comparator} {target:.3f}{suffix}."


def _regression_gate(
    comparisons: list[RunQualityComparison],
    metrics: list[EvalOpsMetric],
) -> tuple[EvalOpsStatus, str]:
    if not comparisons:
        return "fail", "No runs are available for EvalOps regression gating."
    failed_metrics = [metric.name for metric in metrics if metric.status == "fail"]
    warn_metrics = [metric.name for metric in metrics if metric.status == "warn"]
    failed_comparisons = [
        comparison.target_run_id for comparison in comparisons if comparison.verdict == "fail"
    ]
    if failed_comparisons or failed_metrics:
        reason = ", ".join([*failed_comparisons[:3], *failed_metrics[:3]])
        return "fail", f"Regression gate failed on {reason}."
    if any(comparison.verdict == "warn" for comparison in comparisons) or warn_metrics:
        return "warn", f"Regression gate has warnings on {', '.join(warn_metrics[:4])}."
    return "pass", "All EvalOps golden and regression metrics passed."


def _recommendations(
    metrics: list[EvalOpsMetric],
    comparisons: list[RunQualityComparison],
) -> list[str]:
    recommendations: list[str] = []
    metric_names = {metric.name: metric for metric in metrics}
    if metric_names["golden_set_pass_rate"].status != "pass":
        recommendations.append("Raise golden-set pass rate by fixing the failing quality cases first.")
    if metric_names["source_recall"].status != "pass":
        recommendations.append("Improve source recall with more competitor-dimension evidence coverage.")
    if metric_names["claim_citation_rate"].status != "pass":
        recommendations.append("Increase claim citation rate before relying on the report in review.")
    if metric_names["real_collection_rate"].status != "pass":
        recommendations.append("Run more real collection paths so EvalOps is not dominated by demos.")
    if metric_names["real_quality_chain_rate"].status != "pass":
        recommendations.append("Close the real run quality chain: collection, LLM trace, and cited report depth.")
    if (
        "average_delta_score" in metric_names
        and metric_names["average_delta_score"].status != "pass"
    ):
        recommendations.append("Compare regressed runs against the baseline and fix the weakest quality metric.")
    if any(comparison.delta_score is not None and comparison.delta_score < 0 for comparison in comparisons):
        recommendations.append("Inspect regressions against the selected baseline before publishing.")
    return recommendations[:5]


def _metric_value(comparison: RunQualityComparison, name: str) -> float:
    for metric in comparison.metrics:
        if metric.name == name:
            return metric.target_value
    return 0.0


def _average_int(values: list[int]) -> int:
    return round(mean(values)) if values else 0


def _average_float(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _ratio(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)
