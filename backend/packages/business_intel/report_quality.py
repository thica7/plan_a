from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from packages.schema.api_dto import RunDetail, RunQualityComparison, RunQualityMetric
from packages.schema.models import RawSource

REAL_SOURCE_TYPES = {
    "official_docs",
    "pricing_page",
    "review_site",
    "news",
    "web_search_result",
    "webpage_verified",
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
    verdict = _verdict(target_snapshot.score, delta_score)
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
        metrics=metrics,
        recommendations=_recommendations(target_snapshot, baseline_snapshot),
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
        "real_source_rate": _real_source_rate(detail.raw_sources),
        "llm_call_signal": min(float(detail.metrics.llm_calls) / 3.0, 1.0),
        "report_length_score": min(len(detail.report_md) / 2500.0, 1.0),
        "qa_blocker_count": float(
            len([finding for finding in detail.qa_findings if finding.severity == "blocker"])
        ),
    }
    normalized = {
        "evidence_count": min(values["evidence_count"] / 8.0, 1.0),
        "source_coverage_rate": values["source_coverage_rate"],
        "verified_source_rate": values["verified_source_rate"],
        "claim_citation_rate": values["claim_citation_rate"],
        "real_source_rate": values["real_source_rate"],
        "llm_call_signal": values["llm_call_signal"],
        "report_length_score": values["report_length_score"],
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
        and values["source_coverage_rate"] >= 0.5
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
        ("evidence_count", 0.12, "higher_is_better"),
        ("source_coverage_rate", 0.14, "higher_is_better"),
        ("verified_source_rate", 0.14, "higher_is_better"),
        ("claim_citation_rate", 0.16, "higher_is_better"),
        ("real_source_rate", 0.16, "higher_is_better"),
        ("llm_call_signal", 0.1, "higher_is_better"),
        ("report_length_score", 0.1, "higher_is_better"),
        ("qa_blocker_count", 0.08, "lower_is_better"),
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
        if source.competitor and source.competitor.casefold() in {item.casefold() for item in competitors}
    }
    return len(covered) / len(competitors)


def _verified_source_rate(sources: list[RawSource]) -> float:
    if not sources:
        return 0.0
    verified = [
        source
        for source in sources
        if source.source_type in {"webpage_verified", "official_docs", "pricing_page", "review_site"}
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


def _real_source_rate(sources: list[RawSource]) -> float:
    if not sources:
        return 0.0
    real_sources = [
        source
        for source in sources
        if source.url is not None and source.source_type.casefold() in REAL_SOURCE_TYPES
    ]
    return len(real_sources) / len(sources)


def _verdict(score: int, delta_score: int | None) -> Literal["pass", "warn", "fail"]:
    if score < 55:
        return "fail"
    if delta_score is not None and delta_score <= -10:
        return "fail"
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
