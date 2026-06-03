from __future__ import annotations

from statistics import mean
from typing import Literal

from packages.business_intel import compare_run_quality
from packages.compliance import build_run_compliance_report
from packages.schema.api_dto import RunDetail, RunQualityComparison
from packages.schema.evals import (
    EvalJudgeMode,
    EvalOpsCaseResult,
    EvalOpsMetric,
    EvalOpsQualityChainStep,
    EvalOpsReport,
    EvalOpsStatus,
)

MANUAL_BASELINE_HOURS_PER_REPORT = 6.0
AUTOMATION_FLOOR_HOURS_PER_REPORT = 0.08
EVAL_REPORT_STATUSES = {"completed"}
USER_RESEARCH_DIMENSION_HINTS = {
    "persona",
    "user",
    "customer",
    "buyer",
    "review",
    "feedback",
    "adoption",
    "switching",
    "use_case",
    "use case",
}
USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
}


def build_enterprise_evalops_report(
    runs: list[RunDetail],
    *,
    baseline: RunDetail | None = None,
    limit: int = 30,
    judge_mode: EvalJudgeMode = "heuristic",
    settings: object | None = None,
) -> EvalOpsReport:
    evaluable_runs = [run for run in runs if run.status in EVAL_REPORT_STATUSES]
    recent_runs = sorted(evaluable_runs, key=lambda item: item.updated_at, reverse=True)[
        : max(1, limit)
    ]
    comparisons = [
        compare_run_quality(
            run,
            baseline=baseline if baseline is not None and baseline.id != run.id else None,
        )
        for run in recent_runs
    ]
    compliance_reports = [
        build_run_compliance_report(run, settings=settings or object()) for run in recent_runs
    ]
    compliance_pass_rate = _ratio([report.status == "pass" for report in compliance_reports])
    compliance_fail_count = sum(1 for report in compliance_reports if report.status == "fail")
    compliance_blocker_count = sum(report.blocker_count for report in compliance_reports)
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
    real_quality_chain_failed_run_ids = [
        comparison.target_run_id
        for comparison in comparisons
        if not (
            comparison.real_collection_signal
            and comparison.real_llm_signal
            and comparison.report_quality_signal
        )
    ]
    quality_chain_steps = _quality_chain_steps(comparisons)
    user_research_evidence_rate = _user_research_evidence_rate(recent_runs)
    rag_gap_fill_context_rate = _rag_gap_fill_context_rate(recent_runs)
    hitl_redo_loop_rate = _hitl_redo_loop_rate(recent_runs)
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
    judge_scores = [_heuristic_judge_score(comparison) for comparison in comparisons]
    judge_avg_score = round(_average_float(judge_scores), 2)
    llm_judge_avg_score = None
    judge_fallback_reason = ""
    if judge_mode == "llm":
        judge_fallback_reason = (
            "LLM judge provider is not configured for the in-product EvalOps report; "
            "deterministic rubric score is used for the regression gate."
        )
    revisions = [revision for run in recent_runs for revision in run.revisions]
    hitl_enabled_run_rate = _ratio([run.hitl_enabled for run in recent_runs])
    human_correction_rate = _average_float(
        [run.metrics.human_override_rate for run in recent_runs]
    )
    redo_iteration_count = len(revisions)
    redo_convergence_ratio = (
        _average_float([revision.convergence_ratio for revision in revisions])
        if revisions
        else 0.0
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
    citation_validity_rate = _average_float(
        [_metric_value(comparison, "citation_validity_rate") for comparison in comparisons]
    )
    schema_pass_rate = _average_float([run.metrics.schema_pass_rate for run in recent_runs])
    report_structure_rate = _average_float(
        [_metric_value(comparison, "report_structure_score") for comparison in comparisons]
    )
    claim_risk_section_rate = _average_float(
        [_metric_value(comparison, "claim_risk_section_score") for comparison in comparisons]
    )
    scenario_checklist_section_rate = _average_float(
        [
            _metric_value(comparison, "scenario_checklist_section_score")
            for comparison in comparisons
        ]
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
    time_savings_rate = task_time_saved_hours / manual_hours if manual_hours else 0.0
    cost_per_report_usd = (
        round(sum(run.metrics.cost_estimate_usd for run in recent_runs) / len(recent_runs), 6)
        if recent_runs
        else 0.0
    )
    coverage_lift_values = [
        metric.delta
        for comparison in comparisons
        for metric in comparison.metrics
        if metric.name == "source_coverage_rate" and metric.delta is not None
    ]
    coverage_lift_rate = (
        round(_average_float([float(value) for value in coverage_lift_values]), 4)
        if coverage_lift_values
        else None
    )
    cases = _golden_cases(
        comparisons,
        report_quality_score=report_quality_score,
        source_recall=source_recall,
        verified_rate=verified_rate,
        citation_rate=citation_rate,
        citation_validity_rate=citation_validity_rate,
        schema_pass_rate=schema_pass_rate,
        report_structure_rate=report_structure_rate,
        claim_risk_section_rate=claim_risk_section_rate,
        scenario_checklist_section_rate=scenario_checklist_section_rate,
        real_collection_rate=real_collection_rate,
        real_llm_rate=real_llm_rate,
        real_quality_chain_rate=real_quality_chain_rate,
        compliance_pass_rate=compliance_pass_rate,
        user_research_evidence_rate=user_research_evidence_rate,
        rag_gap_fill_context_rate=rag_gap_fill_context_rate,
        hitl_redo_loop_rate=hitl_redo_loop_rate,
    )
    golden_set_pass_rate = _ratio([case.status == "pass" for case in cases])
    metrics = [
        _metric("golden_set_pass_rate", golden_set_pass_rate, 0.8, "ratio"),
        _metric("report_quality_score", float(report_quality_score), 72.0, "score"),
        _metric("source_recall", source_recall, 0.6, "ratio"),
        _metric("verified_source_rate", verified_rate, 0.6, "ratio"),
        _metric("claim_citation_rate", citation_rate, 0.6, "ratio"),
        _metric("citation_validity_rate", citation_validity_rate, 0.6, "ratio"),
        _metric("schema_pass_rate", schema_pass_rate, 1.0, "ratio"),
        _metric("report_structure_score", report_structure_rate, 0.7, "ratio"),
        _metric("claim_risk_section_score", claim_risk_section_rate, 1.0, "ratio"),
        _metric("scenario_checklist_section_score", scenario_checklist_section_rate, 1.0, "ratio"),
        _metric("real_collection_rate", real_collection_rate, 0.5, "ratio"),
        _metric("real_llm_rate", real_llm_rate, 0.5, "ratio"),
        _metric("real_quality_chain_rate", real_quality_chain_rate, 0.5, "ratio"),
        _metric("compliance_pass_rate", compliance_pass_rate, 1.0, "ratio"),
        _metric(
            "compliance_fail_count",
            float(compliance_fail_count),
            0.0,
            "count",
            lower_is_better=True,
        ),
        _metric(
            "compliance_blocker_count",
            float(compliance_blocker_count),
            0.0,
            "count",
            lower_is_better=True,
        ),
        _metric("judge_avg_score", judge_avg_score, 72.0, "score"),
        _metric(
            "human_correction_rate",
            human_correction_rate,
            0.35,
            "ratio",
            lower_is_better=True,
        ),
        _metric("time_savings_rate", time_savings_rate, 0.5, "ratio"),
        _metric("task_time_saved_hours", task_time_saved_hours, len(recent_runs) * 3.0, "hours"),
        _metric("cost_per_report_usd", cost_per_report_usd, 5.0, "usd", lower_is_better=True),
    ]
    if average_delta_score is not None:
        metrics.append(_metric("average_delta_score", average_delta_score, 0.0, "score"))
    if coverage_lift_rate is not None:
        metrics.append(_metric("coverage_lift_rate", coverage_lift_rate, 0.0, "ratio"))
    if redo_iteration_count > 0:
        metrics.append(
            _metric(
                "redo_convergence_ratio",
                redo_convergence_ratio,
                0.35,
                "ratio",
                lower_is_better=True,
            )
        )
    gate_status, gate_reason = _regression_gate(comparisons, metrics)
    return EvalOpsReport(
        run_count=len(recent_runs),
        evaluated_run_ids=[run.id for run in recent_runs],
        baseline_run_id=baseline.id if baseline is not None else None,
        real_run_count=real_run_count,
        demo_run_count=demo_run_count,
        real_run_ratio=round(real_run_ratio, 3),
        real_quality_chain_rate=round(real_quality_chain_rate, 3),
        real_quality_chain_failed_run_ids=real_quality_chain_failed_run_ids,
        quality_chain_steps=quality_chain_steps,
        average_delta_score=average_delta_score,
        regressed_run_count=regressed_run_count,
        judge_mode=judge_mode,
        judge_avg_score=judge_avg_score,
        llm_judge_avg_score=llm_judge_avg_score,
        judge_fallback_reason=judge_fallback_reason,
        hitl_enabled_run_rate=round(hitl_enabled_run_rate, 3),
        human_correction_rate=round(human_correction_rate, 3),
        redo_iteration_count=redo_iteration_count,
        redo_convergence_ratio=round(redo_convergence_ratio, 3),
        golden_set_size=len(cases),
        golden_set_pass_rate=round(golden_set_pass_rate, 3),
        report_quality_score=report_quality_score,
        source_recall=round(source_recall, 3),
        compliance_pass_rate=round(compliance_pass_rate, 3),
        compliance_fail_count=compliance_fail_count,
        compliance_blocker_count=compliance_blocker_count,
        manual_baseline_hours_per_report=MANUAL_BASELINE_HOURS_PER_REPORT,
        manual_baseline_hours=round(manual_hours, 2),
        automation_runtime_hours=round(total_duration_hours, 2),
        task_time_saved_hours=round(task_time_saved_hours, 2),
        time_savings_rate=round(time_savings_rate, 3),
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
    citation_validity_rate: float,
    schema_pass_rate: float,
    report_structure_rate: float,
    claim_risk_section_rate: float,
    scenario_checklist_section_rate: float,
    real_collection_rate: float,
    real_llm_rate: float,
    real_quality_chain_rate: float,
    compliance_pass_rate: float,
    user_research_evidence_rate: float,
    rag_gap_fill_context_rate: float,
    hitl_redo_loop_rate: float,
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
            "golden.citation_validity",
            "Citation source validity",
            round(citation_validity_rate * 100),
            60,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.schema_pass",
            "Schema validation pass rate",
            round(schema_pass_rate * 100),
            100,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.report_structure",
            "Report structure completeness",
            round(report_structure_rate * 100),
            70,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.claim_risk_section",
            "Claim validation risk section",
            round(claim_risk_section_rate * 100),
            100,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.scenario_checklist",
            "Scenario QA checklist section",
            round(scenario_checklist_section_rate * 100),
            100,
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
        _case(
            "golden.real_quality_chain",
            "Real quality chain",
            round(real_quality_chain_rate * 100),
            50,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.compliance",
            "Compliance gate",
            round(compliance_pass_rate * 100),
            100,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.user_research_evidence",
            "User research evidence when persona/review dimensions are requested",
            round(user_research_evidence_rate * 100),
            100,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.rag_gap_fill_context",
            "RAG gap-fill context when collector evidence gaps remain",
            round(rag_gap_fill_context_rate * 100),
            100,
            target_run_id,
            baseline_run_id,
        ),
        _case(
            "golden.hitl_redo_loop",
            "HITL or scoped redo loop when QA intervention is needed",
            round(hitl_redo_loop_rate * 100),
            100,
            target_run_id,
            baseline_run_id,
        ),
    ]


def _quality_chain_steps(
    comparisons: list[RunQualityComparison],
) -> list[EvalOpsQualityChainStep]:
    step_specs: list[
        tuple[Literal["real_collection", "real_llm", "report_quality"], str, str]
    ] = [
        (
            "real_collection",
            "Real collection",
            "External evidence collection is distinguishable from demo fixtures.",
        ),
        (
            "real_llm",
            "Real LLM trace",
            "LLM calls or trace spans show model-backed execution.",
        ),
        (
            "report_quality",
            "Report quality",
            "The report is long enough, cited, structured, and review-ready.",
        ),
    ]
    total = len(comparisons)
    steps: list[EvalOpsQualityChainStep] = []
    for step, label, description in step_specs:
        failed_run_ids = [
            comparison.target_run_id
            for comparison in comparisons
            if not _quality_chain_step_passed(comparison, step)
        ]
        passed_count = total - len(failed_run_ids)
        pass_rate = passed_count / total if total else 0.0
        steps.append(
            EvalOpsQualityChainStep(
                step=step,
                label=label,
                total_count=total,
                passed_count=passed_count,
                failed_count=len(failed_run_ids),
                pass_rate=round(pass_rate, 3),
                failed_run_ids=failed_run_ids,
                summary=f"{passed_count}/{total} run(s) passed. {description}",
            )
        )
    return steps


def _user_research_evidence_rate(runs: list[RunDetail]) -> float:
    applicable = [run for run in runs if _run_needs_user_research(run)]
    if not applicable:
        return 1.0
    return _ratio([_run_has_user_research_evidence(run) for run in applicable])


def _run_needs_user_research(run: RunDetail) -> bool:
    return any(
        any(
            hint in dimension.casefold().replace("-", "_")
            for hint in USER_RESEARCH_DIMENSION_HINTS
        )
        for dimension in run.plan.dimensions
    )


def _run_has_user_research_evidence(run: RunDetail) -> bool:
    return any(source.source_type in USER_RESEARCH_SOURCE_TYPES for source in run.raw_sources)


def _rag_gap_fill_context_rate(runs: list[RunDetail]) -> float:
    applicable = [run for run in runs if _run_has_collector_gap_signal(run)]
    if not applicable:
        return 1.0
    return _ratio([_run_has_rag_gap_fill_context(run) for run in applicable])


def _run_has_collector_gap_signal(run: RunDetail) -> bool:
    return any(
        finding.target_agent == "collector" and finding.severity in {"warn", "blocker"}
        for finding in run.qa_findings
    )


def _run_has_rag_gap_fill_context(run: RunDetail) -> bool:
    report = run.report_md.casefold()
    if "## rag gap fill" in report or "rag gap fill" in report:
        return True
    return any(
        span.agent in {"rag_gap_fill", "evidence_gap"}
        or span.name in {"rag_gap_fill", "fill_evidence_gaps"}
        or "retrieval_contexts" in span.metadata
        or "retrieval_record_count" in span.metadata
        for span in run.trace_spans
    )


def _hitl_redo_loop_rate(runs: list[RunDetail]) -> float:
    applicable = [
        run
        for run in runs
        if (
            run.hitl_enabled
            or run.qa_findings
            or run.revisions
            or run.metrics.human_override_rate > 0
        )
    ]
    if not applicable:
        return 1.0
    return _ratio([_run_has_hitl_or_redo_loop(run) for run in applicable])


def _run_has_hitl_or_redo_loop(run: RunDetail) -> bool:
    if run.revisions or run.metrics.human_override_rate > 0:
        return True
    return any(
        "hitl" in message.message_type.casefold()
        or "review" in message.message_type.casefold()
        or "redo" in message.message_type.casefold()
        for message in run.agent_messages
    )


def _quality_chain_step_passed(comparison: RunQualityComparison, step: str) -> bool:
    if step == "real_collection":
        return comparison.real_collection_signal
    if step == "real_llm":
        return comparison.real_llm_signal
    if step == "report_quality":
        return comparison.report_quality_signal
    return False


def _case(
    case_id: str,
    name: str,
    score: int,
    target: int,
    target_run_id: str | None,
    baseline_run_id: str | None,
) -> EvalOpsCaseResult:
    status: EvalOpsStatus = (
        "pass" if score >= target else "warn" if score >= target * 0.75 else "fail"
    )
    return EvalOpsCaseResult(
        case_id=case_id,
        name=name,
        status=status,
        score=max(0, min(100, score)),
        target_run_id=target_run_id,
        baseline_run_id=baseline_run_id,
        summary=f"{score}/100 against target {target}.",
    )


def _heuristic_judge_score(comparison: RunQualityComparison) -> float:
    score = comparison.target_score * 0.45
    score += 12.0 if comparison.real_collection_signal else 0.0
    score += 12.0 if comparison.real_llm_signal else 0.0
    score += 12.0 if comparison.report_quality_signal else 0.0
    score += _metric_value(comparison, "citation_validity_rate") * 10.0
    score += _metric_value(comparison, "schema_pass_rate") * 9.0
    return max(0.0, min(100.0, score))


def _metric(
    name: str,
    value: float,
    target: float,
    unit: str,
    *,
    lower_is_better: bool = False,
) -> EvalOpsMetric:
    if lower_is_better:
        status: EvalOpsStatus = (
            "pass" if value <= target else "warn" if value <= target * 1.5 else "fail"
        )
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
        recommendations.append(
            "Raise golden-set pass rate by fixing the failing quality cases first."
        )
    if metric_names["source_recall"].status != "pass":
        recommendations.append(
            "Improve source recall with more competitor-dimension evidence coverage."
        )
    if metric_names["claim_citation_rate"].status != "pass":
        recommendations.append(
            "Increase claim citation rate before relying on the report in review."
        )
    if metric_names["citation_validity_rate"].status != "pass":
        recommendations.append(
            "Repair unresolved report source tokens before publishing or reviewing the report."
        )
    if metric_names["schema_pass_rate"].status != "pass":
        recommendations.append(
            "Fix schema validation failures before comparing or publishing the report."
        )
    if metric_names["claim_risk_section_score"].status != "pass":
        recommendations.append(
            "Add Claim Validation & Evidence Risk to every report before review."
        )
    if metric_names["scenario_checklist_section_score"].status != "pass":
        recommendations.append(
            "Add Scenario QA Checklist to every report so layer, ScenarioPack, QA rules, "
            "and evidence requirements are reviewable."
        )
    if metric_names["real_collection_rate"].status != "pass":
        recommendations.append(
            "Run more real collection paths so EvalOps is not dominated by demos."
        )
    if metric_names["real_quality_chain_rate"].status != "pass":
        recommendations.append(
            "Close the real run quality chain: collection, LLM trace, and cited report depth."
        )
    if metric_names["compliance_pass_rate"].status != "pass":
        recommendations.append(
            "Fix compliance blockers before treating EvalOps as release-ready."
        )
    if metric_names["judge_avg_score"].status != "pass":
        recommendations.append(
            "Improve judge score by strengthening evidence support, citations, and structure."
        )
    if (
        "average_delta_score" in metric_names
        and metric_names["average_delta_score"].status != "pass"
    ):
        recommendations.append(
            "Compare regressed runs against the baseline and fix the weakest quality metric."
        )
    if metric_names["human_correction_rate"].status != "pass":
        recommendations.append(
            "Review recurring human corrections and convert them into rules or memory."
        )
    if (
        "redo_convergence_ratio" in metric_names
        and metric_names["redo_convergence_ratio"].status != "pass"
    ):
        recommendations.append(
            "Tighten scoped redo routing so repeated revisions reduce QA issues faster."
        )
    if any(
        comparison.delta_score is not None and comparison.delta_score < 0
        for comparison in comparisons
    ):
        recommendations.append(
            "Inspect regressions against the selected baseline before publishing."
        )
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
