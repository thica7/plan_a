from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from packages.schema.api_dto import (
    RunDetail,
    RunQualityComparison,
    RunQualityMetric,
    RunQualitySignalCheck,
)
from packages.schema.models import RawSource

REAL_SOURCE_TYPES = {
    "official",
    "official_docs",
    "official_pricing",
    "official_site",
    "official_api",
    "pricing_page",
    "review_site",
    "trust_center",
    "news",
    "web_search_result",
    "webpage_verified",
}
USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}
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


@dataclass(frozen=True)
class _QualitySnapshot:
    score: int
    values: dict[str, float]
    real_collection_signal: bool
    real_llm_signal: bool
    report_quality_signal: bool


def compare_run_quality(
    target: RunDetail,
    *,
    baseline: RunDetail | None = None,
) -> RunQualityComparison:
    """Compare a real run against an optional baseline using product quality signals."""

    target_snapshot = _snapshot(target)
    baseline_snapshot = _snapshot(baseline) if baseline is not None else None
    metrics = [
        _metric(
            name=name,
            target_value=target_snapshot.values[name],
            baseline_value=baseline_snapshot.values[name] if baseline_snapshot else None,
            weight=weight,
            direction=direction,
        )
        for name, weight, direction in _metric_specs()
    ]
    delta_score = (
        target_snapshot.score - baseline_snapshot.score if baseline_snapshot is not None else None
    )
    verdict = _verdict(target_snapshot.score, delta_score, target_snapshot)
    return RunQualityComparison(
        target_run_id=target.id,
        baseline_run_id=baseline.id if baseline else None,
        target_execution_mode=target.execution_mode,
        baseline_execution_mode=baseline.execution_mode if baseline else None,
        target_score=target_snapshot.score,
        baseline_score=baseline_snapshot.score if baseline_snapshot else None,
        delta_score=delta_score,
        verdict=verdict,
        real_collection_signal=target_snapshot.real_collection_signal,
        real_llm_signal=target_snapshot.real_llm_signal,
        report_quality_signal=target_snapshot.report_quality_signal,
        signal_checks=_signal_checks(target, target_snapshot),
        metrics=metrics,
        recommendations=_clean_recommendations(target_snapshot, baseline_snapshot),
    )


def _snapshot(detail: RunDetail | None) -> _QualitySnapshot:
    if detail is None:
        return _QualitySnapshot(
            score=0,
            values={name: 0.0 for name, _, _ in _metric_specs()},
            real_collection_signal=False,
            real_llm_signal=False,
            report_quality_signal=False,
        )
    values = {
        "evidence_count": float(len(detail.raw_sources)),
        "source_coverage_rate": _ratio_or_compute(
            detail.metrics.source_coverage_rate,
            _source_coverage_rate(detail.raw_sources, detail.plan.competitors),
        ),
        "verified_source_rate": _ratio_or_compute(
            detail.metrics.verified_source_rate,
            _verified_source_rate(detail.raw_sources),
        ),
        "claim_citation_rate": _ratio_or_compute(
            detail.metrics.claim_citation_rate,
            _claim_citation_rate(detail),
        ),
        "citation_validity_rate": _citation_validity_rate(detail),
        "report_source_token_count": float(_report_source_token_count(detail.report_md)),
        "real_source_rate": _real_source_rate(detail.raw_sources),
        "llm_call_signal": min(float(detail.metrics.llm_calls) / 3.0, 1.0),
        "report_length_score": min(len(detail.report_md) / 2500.0, 1.0),
        "report_structure_score": _report_structure_score(detail),
        "claim_risk_section_score": _claim_risk_section_score(detail.report_md),
        "scenario_checklist_section_score": _scenario_checklist_section_score(
            detail.report_md
        ),
        "memory_context_section_score": _memory_context_section_score(detail),
        "user_research_section_score": _user_research_section_score(detail),
        "qa_blocker_count": float(
            len([finding for finding in detail.qa_findings if finding.severity == "blocker"])
        ),
    }
    normalized = {
        "evidence_count": min(values["evidence_count"] / 8.0, 1.0),
        "source_coverage_rate": values["source_coverage_rate"],
        "verified_source_rate": values["verified_source_rate"],
        "claim_citation_rate": values["claim_citation_rate"],
        "citation_validity_rate": values["citation_validity_rate"],
        "real_source_rate": values["real_source_rate"],
        "llm_call_signal": values["llm_call_signal"],
        "report_length_score": values["report_length_score"],
        "report_structure_score": values["report_structure_score"],
        "claim_risk_section_score": values["claim_risk_section_score"],
        "scenario_checklist_section_score": values["scenario_checklist_section_score"],
        "memory_context_section_score": values["memory_context_section_score"],
        "user_research_section_score": values["user_research_section_score"],
        "qa_blocker_count": max(0.0, 1.0 - min(values["qa_blocker_count"] / 3.0, 1.0)),
    }
    score = round(
        sum(normalized[name] * weight for name, weight, _ in _metric_specs()) * 100
    )
    real_collection_signal = (
        detail.execution_mode == "real"
        and values["real_source_rate"] >= 0.5
        and values["evidence_count"] >= 2
    )
    real_llm_signal = detail.execution_mode == "real" and (
        detail.metrics.llm_calls > 0
        or any(span.kind == "llm" and (span.provider or span.model) for span in detail.trace_spans)
    )
    report_quality_signal = (
        len(detail.report_md) >= 1200
        and values["claim_citation_rate"] >= 0.6
        and values["citation_validity_rate"] >= 0.6
        and values["source_coverage_rate"] >= 0.5
        and values["report_structure_score"] >= 0.7
        and values["claim_risk_section_score"] >= 1.0
        and values["scenario_checklist_section_score"] >= 1.0
        and values["memory_context_section_score"] >= 1.0
        and values["user_research_section_score"] >= 1.0
    )
    return _QualitySnapshot(
        score=max(0, min(100, score)),
        values=values,
        real_collection_signal=real_collection_signal,
        real_llm_signal=real_llm_signal,
        report_quality_signal=report_quality_signal,
    )


def _metric_specs() -> list[tuple[str, float, Literal["higher_is_better", "lower_is_better"]]]:
    return [
        ("evidence_count", 0.09, "higher_is_better"),
        ("source_coverage_rate", 0.10, "higher_is_better"),
        ("verified_source_rate", 0.10, "higher_is_better"),
        ("claim_citation_rate", 0.09, "higher_is_better"),
        ("citation_validity_rate", 0.09, "higher_is_better"),
        ("real_source_rate", 0.10, "higher_is_better"),
        ("llm_call_signal", 0.09, "higher_is_better"),
        ("report_length_score", 0.04, "higher_is_better"),
        ("report_structure_score", 0.07, "higher_is_better"),
        ("claim_risk_section_score", 0.06, "higher_is_better"),
        ("scenario_checklist_section_score", 0.04, "higher_is_better"),
        ("memory_context_section_score", 0.03, "higher_is_better"),
        ("user_research_section_score", 0.03, "higher_is_better"),
        ("qa_blocker_count", 0.07, "lower_is_better"),
    ]


def _metric(
    *,
    name: str,
    target_value: float,
    baseline_value: float | None,
    weight: float,
    direction: Literal["higher_is_better", "lower_is_better"],
) -> RunQualityMetric:
    delta = target_value - baseline_value if baseline_value is not None else None
    status: Literal["improved", "regressed", "unchanged", "baseline_missing"]
    if delta is None:
        status = "baseline_missing"
    elif abs(delta) < 0.001:
        status = "unchanged"
    elif (delta > 0 and direction == "higher_is_better") or (
        delta < 0 and direction == "lower_is_better"
    ):
        status = "improved"
    else:
        status = "regressed"
    return RunQualityMetric(
        name=name,
        target_value=round(target_value, 4),
        baseline_value=round(baseline_value, 4) if baseline_value is not None else None,
        delta=round(delta, 4) if delta is not None else None,
        weight=weight,
        direction=direction,
        status=status,
    )


def _signal_checks(detail: RunDetail, snapshot: _QualitySnapshot) -> list[RunQualitySignalCheck]:
    collection_blockers: list[str] = []
    if detail.execution_mode != "real":
        collection_blockers.append("execution_mode")
    if snapshot.values["real_source_rate"] < 0.5:
        collection_blockers.append("real_source_rate")
    if snapshot.values["evidence_count"] < 2:
        collection_blockers.append("evidence_count")

    llm_blockers: list[str] = []
    if detail.execution_mode != "real":
        llm_blockers.append("execution_mode")
    if snapshot.values["llm_call_signal"] <= 0 and not any(
        span.kind == "llm" and (span.provider or span.model) for span in detail.trace_spans
    ):
        llm_blockers.append("llm_call_signal")

    report_blockers: list[str] = []
    if len(detail.report_md) < 1200:
        report_blockers.append("report_length_score")
    for name, minimum in [
        ("claim_citation_rate", 0.6),
        ("citation_validity_rate", 0.6),
        ("source_coverage_rate", 0.5),
        ("report_structure_score", 0.7),
        ("claim_risk_section_score", 1.0),
        ("scenario_checklist_section_score", 1.0),
        ("memory_context_section_score", 1.0),
        ("user_research_section_score", 1.0),
    ]:
        if snapshot.values[name] < minimum:
            report_blockers.append(name)

    return [
        RunQualitySignalCheck(
            signal="real_collection",
            label="Real collection",
            passed=snapshot.real_collection_signal,
            reason=_signal_reason(
                snapshot.real_collection_signal,
                "Run has real-mode external evidence coverage.",
                "Needs real execution, at least two evidence items, and >=50% real source rate.",
            ),
            blocking_metric_names=collection_blockers,
        ),
        RunQualitySignalCheck(
            signal="real_llm",
            label="Real LLM",
            passed=snapshot.real_llm_signal,
            reason=_signal_reason(
                snapshot.real_llm_signal,
                "Run has model-backed LLM call or trace evidence.",
                "Needs real execution plus llm_calls or an LLM trace span with provider/model.",
            ),
            blocking_metric_names=llm_blockers,
        ),
        RunQualitySignalCheck(
            signal="report_quality",
            label="Report quality",
            passed=snapshot.report_quality_signal,
            reason=_signal_reason(
                snapshot.report_quality_signal,
                "Report meets citation, coverage, structure, and review-readiness thresholds.",
                "Needs a longer cited report with structure, source coverage, claim risk, and "
                "scenario QA sections.",
            ),
            blocking_metric_names=report_blockers,
        ),
    ]


def _signal_reason(passed: bool, passed_reason: str, failed_reason: str) -> str:
    return passed_reason if passed else failed_reason


def _ratio_or_compute(metric_value: float, computed_value: float) -> float:
    if metric_value > 0:
        return max(0.0, min(1.0, metric_value))
    return computed_value


def _source_coverage_rate(sources: list[RawSource], competitors: list[str]) -> float:
    if not competitors:
        return 0.0
    covered = {
        source.competitor.casefold()
        for source in sources
        if source.competitor
        and source.competitor.casefold() in {item.casefold() for item in competitors}
    }
    return len(covered) / len(competitors)


def _verified_source_rate(sources: list[RawSource]) -> float:
    if not sources:
        return 0.0
    verified = [
        source
        for source in sources
        if source.source_type
        in {
            "webpage_verified",
            "official",
            "official_docs",
            "official_pricing",
            "official_site",
            "official_api",
            "pricing_page",
            "review_site",
            "trust_center",
        }
    ]
    return len(verified) / len(sources)


def _claim_citation_rate(detail: RunDetail) -> float:
    claims = []
    for knowledge in detail.competitor_knowledge.values():
        claims.extend(knowledge.feature_tree.summary_claims)
        for node in knowledge.feature_tree.nodes:
            claims.extend(node.claims)
        claims.extend(knowledge.pricing_model.notes)
        for tier in knowledge.pricing_model.tiers:
            claims.extend(tier.claims)
        claims.extend(knowledge.user_personas.summary_claims)
        for segment in knowledge.user_personas.segments:
            claims.extend(segment.claims)
    if not claims:
        return 0.0
    cited = [claim for claim in claims if claim.source_ids]
    return len(cited) / len(claims)


def _citation_validity_rate(detail: RunDetail) -> float:
    tokens = re.findall(r"\[source:([A-Za-z0-9_.:#-]+)\]", detail.report_md)
    if not tokens:
        return 0.0
    source_ids = {source.id for source in detail.raw_sources}
    resolved = sum(1 for token in tokens if token.split("#", 1)[0] in source_ids)
    return resolved / len(tokens)


def _report_source_token_count(report_md: str) -> int:
    return len(re.findall(r"\[source:([A-Za-z0-9_.:#-]+)\]", report_md))


def _real_source_rate(sources: list[RawSource]) -> float:
    if not sources:
        return 0.0
    real_sources = [
        source
        for source in sources
        if source.url is not None and source.source_type.casefold() in REAL_SOURCE_TYPES
    ]
    return len(real_sources) / len(sources)


def _report_structure_score(detail: RunDetail) -> float:
    checks = [
        _has_heading(detail.report_md, ("executive summary", "executive overview")),
        _has_heading(detail.report_md, ("source quality", "source coverage")),
        _has_heading(detail.report_md, ("matrix", "dimension winners", "side-by-side")),
        _scenario_checklist_section_score(detail.report_md) >= 1.0,
        _claim_risk_section_score(detail.report_md) >= 1.0,
        _has_heading(detail.report_md, ("next collection", "verification plan", "evidence gap")),
        _has_heading(detail.report_md, ("evidence appendix", "source appendix")),
        _memory_context_section_score(detail) >= 1.0,
        _user_research_section_score(detail) >= 1.0,
        _has_layer_heading(detail),
    ]
    return sum(1 for item in checks if item) / len(checks)


def _has_layer_heading(detail: RunDetail) -> bool:
    layer = detail.plan.competitor_layer
    if layer == "L1":
        return _has_heading(detail.report_md, ("battlecard", "sales objection"))
    if layer == "L2":
        return _has_heading(detail.report_md, ("workflow", "enterprise risk", "switching"))
    if layer == "L3":
        return _has_heading(detail.report_md, ("market landscape", "segmentation", "benchmark"))
    return _has_heading(detail.report_md, ("business implication", "strategy"))


def _has_heading(markdown: str, needles: tuple[str, ...]) -> bool:
    headings = [
        match.group(1).casefold()
        for match in re.finditer(r"^\s*#{1,4}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    ]
    return any(any(needle in heading for needle in needles) for heading in headings)


def _claim_risk_section_score(markdown: str) -> float:
    return 1.0 if _has_heading(markdown, ("claim validation", "evidence risk")) else 0.0


def _scenario_checklist_section_score(markdown: str) -> float:
    return 1.0 if _has_heading(markdown, ("scenario qa", "scenario checklist")) else 0.0


def _memory_context_section_score(detail: RunDetail) -> float:
    if not detail.plan.memory_prompt_context and not detail.plan.memory_candidate_ids:
        return 1.0
    return 1.0 if _has_heading(detail.report_md, ("memory context", "memoryagent")) else 0.0


def _user_research_section_score(detail: RunDetail) -> float:
    if not _needs_user_research_section(detail):
        return 1.0
    return 1.0 if _has_heading(detail.report_md, ("user research", "buyer research")) else 0.0


def _needs_user_research_section(detail: RunDetail) -> bool:
    if any(source.source_type in USER_RESEARCH_SOURCE_TYPES for source in detail.raw_sources):
        return True
    return any(
        any(
            hint in dimension.casefold().replace("-", "_")
            for hint in USER_RESEARCH_DIMENSION_HINTS
        )
        for dimension in detail.plan.dimensions
    )


def _verdict(
    score: int,
    delta_score: int | None,
    target: _QualitySnapshot,
) -> Literal["pass", "warn", "fail"]:
    if score < 55:
        return "fail"
    if delta_score is not None and delta_score <= -10:
        return "fail"
    if target.values.get("report_structure_score", 1.0) < 0.7:
        return "warn"
    if not target.report_quality_signal:
        return "warn"
    if score < 72 or (delta_score is not None and delta_score < 0):
        return "warn"
    return "pass"


def _recommendations(
    target: _QualitySnapshot,
    baseline: _QualitySnapshot | None,
) -> list[str]:
    recommendations: list[str] = []
    if not target.real_collection_signal:
        recommendations.append("补足真实网页/搜索采集证据，避免报告只依赖 demo fixture 或弱来源。")
    if not target.real_llm_signal:
        recommendations.append("补足真实 LLM 调用 trace，确保 real mode 不是确定性降级输出。")
    if not target.report_quality_signal:
        recommendations.append("提升报告长度、引用覆盖和竞品覆盖，确保结论可被证据链支撑。")
    if baseline is not None and target.score < baseline.score:
        recommendations.append("与基线 run 相比质量下降，优先检查采集覆盖、引用率和 QA blocker。")
    return recommendations


def _clean_recommendations(
    target: _QualitySnapshot,
    baseline: _QualitySnapshot | None,
) -> list[str]:
    recommendations: list[str] = []
    if not target.real_collection_signal:
        recommendations.append(
            "Add real webpage or search evidence so the report is not relying on demo fixtures "
            "or weak source signals."
        )
    if not target.real_llm_signal:
        recommendations.append(
            "Capture real LLM trace evidence so real mode can be distinguished from deterministic "
            "fallback output."
        )
    if not target.report_quality_signal:
        recommendations.append(
            "Increase report depth, citation coverage, and competitor coverage so conclusions are "
            "supported by an evidence chain."
        )
    if target.values.get("claim_risk_section_score", 0.0) < 1.0:
        recommendations.append(
            "Add a Claim Validation & Evidence Risk section so reviewers can inspect weak claims, "
            "source risk, and follow-up collection tasks."
        )
    if target.values.get("scenario_checklist_section_score", 0.0) < 1.0:
        recommendations.append(
            "Add a Scenario QA Checklist section so the selected layer, ScenarioPack, QA rules, "
            "and evidence requirements are visible in the report."
        )
    if target.values.get("memory_context_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a Memory Context section so confirmed MemoryAgent preferences are visible as "
            "guidance, not mistaken for factual evidence."
        )
    if target.values.get("user_research_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a User Research Evidence section so survey, interview, or manual-note signals "
            "are separated from official factual proof."
        )
    if (
        target.values.get("report_source_token_count", 0.0) > 0
        and target.values.get("citation_validity_rate", 1.0) < 0.6
    ):
        recommendations.append(
            "Repair unresolved report source tokens so citations can jump to collected evidence."
        )
    if baseline is not None and target.score < baseline.score:
        recommendations.append(
            "Quality regressed against the baseline run; inspect collection coverage, citation "
            "rate, and QA blockers first."
        )
    return recommendations
