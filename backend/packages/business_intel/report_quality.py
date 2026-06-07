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
from packages.sources import resolve_source_token, source_token_alias_map, source_tokens

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
    normalized_values: dict[str, float]
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
            target_normalized_score=target_snapshot.normalized_values[name],
            baseline_normalized_score=(
                baseline_snapshot.normalized_values[name] if baseline_snapshot else None
            ),
            weight=weight,
            direction=direction,
        )
        for name, weight, direction in _metric_specs()
    ]
    delta_score = (
        target_snapshot.score - baseline_snapshot.score if baseline_snapshot is not None else None
    )
    verdict = _verdict(target_snapshot.score, delta_score, target_snapshot)
    gate_status, gate_reasons = _regression_gate(
        target_snapshot,
        baseline_snapshot,
        delta_score,
        metrics,
    )
    return RunQualityComparison(
        target_run_id=target.id,
        baseline_run_id=baseline.id if baseline else None,
        target_execution_mode=target.execution_mode,
        baseline_execution_mode=baseline.execution_mode if baseline else None,
        target_score=target_snapshot.score,
        baseline_score=baseline_snapshot.score if baseline_snapshot else None,
        delta_score=delta_score,
        verdict=verdict,
        regression_gate_status=gate_status,
        regression_gate_passed=gate_status == "pass",
        regression_gate_reasons=gate_reasons,
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
            normalized_values={name: 0.0 for name, _, _ in _metric_specs()},
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
        "gap_resolution_rate": _gap_resolution_rate(detail),
        "field_support_rate": _field_support_rate(detail),
        "validated_claim_rate": _validated_claim_rate(detail),
        "llm_call_signal": min(float(detail.metrics.llm_calls) / 3.0, 1.0),
        "report_length_score": min(len(detail.report_md) / 2500.0, 1.0),
        "report_structure_score": _report_structure_score(detail),
        "claim_risk_section_score": _claim_risk_section_score(detail.report_md),
        "scenario_checklist_section_score": _scenario_checklist_section_score(
            detail.report_md
        ),
        "memory_context_section_score": _memory_context_section_score(detail),
        "user_research_section_score": _user_research_section_score(detail),
        "rag_gap_fill_section_score": _rag_gap_fill_section_score(detail),
        "qa_blocker_count": float(
            len([finding for finding in detail.qa_findings if finding.severity == "blocker"])
        ),
        "warning_count": float(_warning_count(detail)),
    }
    normalized = {
        "evidence_count": min(values["evidence_count"] / 8.0, 1.0),
        "source_coverage_rate": values["source_coverage_rate"],
        "verified_source_rate": values["verified_source_rate"],
        "claim_citation_rate": values["claim_citation_rate"],
        "citation_validity_rate": values["citation_validity_rate"],
        "real_source_rate": values["real_source_rate"],
        "gap_resolution_rate": values["gap_resolution_rate"],
        "field_support_rate": values["field_support_rate"],
        "validated_claim_rate": values["validated_claim_rate"],
        "llm_call_signal": values["llm_call_signal"],
        "report_length_score": values["report_length_score"],
        "report_structure_score": values["report_structure_score"],
        "claim_risk_section_score": values["claim_risk_section_score"],
        "scenario_checklist_section_score": values["scenario_checklist_section_score"],
        "memory_context_section_score": values["memory_context_section_score"],
        "user_research_section_score": values["user_research_section_score"],
        "rag_gap_fill_section_score": values["rag_gap_fill_section_score"],
        "qa_blocker_count": max(0.0, 1.0 - min(values["qa_blocker_count"] / 3.0, 1.0)),
        "warning_count": max(0.0, 1.0 - min(values["warning_count"] / 12.0, 1.0)),
    }
    score = round(
        sum(normalized[name] * weight for name, weight, _ in _metric_specs()) * 100
    )
    real_collection_signal = (
        detail.execution_mode == "real"
        and values["real_source_rate"] >= 0.5
        and values["verified_source_rate"] >= 0.25
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
        and values["rag_gap_fill_section_score"] >= 1.0
    )
    return _QualitySnapshot(
        score=max(0, min(100, score)),
        values=values,
        normalized_values=normalized,
        real_collection_signal=real_collection_signal,
        real_llm_signal=real_llm_signal,
        report_quality_signal=report_quality_signal,
    )


def _metric_specs() -> list[tuple[str, float, Literal["higher_is_better", "lower_is_better"]]]:
    return [
        ("evidence_count", 0.06, "higher_is_better"),
        ("source_coverage_rate", 0.08, "higher_is_better"),
        ("verified_source_rate", 0.10, "higher_is_better"),
        ("claim_citation_rate", 0.09, "higher_is_better"),
        ("citation_validity_rate", 0.09, "higher_is_better"),
        ("real_source_rate", 0.10, "higher_is_better"),
        ("gap_resolution_rate", 0.03, "higher_is_better"),
        ("field_support_rate", 0.04, "higher_is_better"),
        ("validated_claim_rate", 0.03, "higher_is_better"),
        ("llm_call_signal", 0.07, "higher_is_better"),
        ("report_length_score", 0.02, "higher_is_better"),
        ("report_structure_score", 0.07, "higher_is_better"),
        ("claim_risk_section_score", 0.05, "higher_is_better"),
        ("scenario_checklist_section_score", 0.03, "higher_is_better"),
        ("memory_context_section_score", 0.02, "higher_is_better"),
        ("user_research_section_score", 0.02, "higher_is_better"),
        ("rag_gap_fill_section_score", 0.02, "higher_is_better"),
        ("qa_blocker_count", 0.06, "lower_is_better"),
        ("warning_count", 0.02, "lower_is_better"),
    ]


def _metric(
    *,
    name: str,
    target_value: float,
    baseline_value: float | None,
    target_normalized_score: float,
    baseline_normalized_score: float | None,
    weight: float,
    direction: Literal["higher_is_better", "lower_is_better"],
) -> RunQualityMetric:
    delta = target_value - baseline_value if baseline_value is not None else None
    normalized_delta = (
        target_normalized_score - baseline_normalized_score
        if baseline_normalized_score is not None
        else None
    )
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
        target_normalized_score=round(target_normalized_score, 4),
        baseline_normalized_score=(
            round(baseline_normalized_score, 4)
            if baseline_normalized_score is not None
            else None
        ),
        normalized_score_delta=round(normalized_delta, 4) if normalized_delta is not None else None,
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
    if snapshot.values["verified_source_rate"] < 0.25:
        collection_blockers.append("verified_source_rate")
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
        ("rag_gap_fill_section_score", 1.0),
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
                "Run has real-mode external evidence coverage with verified sources.",
                (
                    "Needs real execution, at least two evidence items, >=50% real source "
                    "rate, and at least one verified or official source."
                ),
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
                "Needs a longer cited report with structure, source coverage, claim risk, "
                "scenario QA, and RAG gap-fill coverage when collector gaps exist.",
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
    factual_sources = _factual_sources(sources)
    if not factual_sources:
        return 0.0
    verified = [
        source
        for source in factual_sources
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
    return len(verified) / len(factual_sources)


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
    tokens = source_tokens(detail.report_md, include_malformed=True)
    if not tokens:
        return 0.0
    aliases = _source_alias_map(detail)
    resolved = sum(1 for token in tokens if resolve_source_token(token, aliases))
    return resolved / len(tokens)


def _report_source_token_count(report_md: str) -> int:
    return len(source_tokens(report_md, include_malformed=True))


def _source_alias_map(detail: RunDetail) -> dict[str, str]:
    projection = detail.enterprise_projection
    return source_token_alias_map(
        raw_sources=detail.raw_sources,
        evidence=projection.evidence_records if projection else (),
        scoped_evidence_ids=projection.report_version.evidence_ids if projection else None,
    )


def _real_source_rate(sources: list[RawSource]) -> float:
    factual_sources = _factual_sources(sources)
    if not factual_sources:
        return 0.0
    real_sources = [
        source
        for source in factual_sources
        if source.url is not None and source.source_type.casefold() in REAL_SOURCE_TYPES
    ]
    return len(real_sources) / len(factual_sources)


def _gap_resolution_rate(detail: RunDetail) -> float:
    rag_gap_fill = _quality_metadata(detail).get("rag_gap_fill")
    if isinstance(rag_gap_fill, dict):
        direct_value = rag_gap_fill.get("gap_resolution_rate")
        if isinstance(direct_value, int | float):
            return max(0.0, min(1.0, float(direct_value)))
        before_gap_count = rag_gap_fill.get("before_gap_count")
        after_gap_count = rag_gap_fill.get("after_gap_count")
        if isinstance(before_gap_count, int | float) and isinstance(after_gap_count, int | float):
            if before_gap_count <= 0:
                return 1.0 if after_gap_count <= 0 else 0.0
            return max(0.0, min(1.0, (before_gap_count - after_gap_count) / before_gap_count))
        status = rag_gap_fill.get("gap_resolution_status")
        if isinstance(status, dict) and status:
            resolved = len([value for value in status.values() if value == "resolved"])
            return resolved / len(status)
    return 1.0 if not _needs_rag_gap_fill_section(detail) else 0.0


def _field_support_rate(detail: RunDetail) -> float:
    competitors = detail.plan.competitors or sorted(detail.competitor_knowledge)
    dimensions = detail.plan.dimensions
    if not competitors or not dimensions:
        return 1.0
    expected_fields = [
        (competitor, dimension) for competitor in competitors for dimension in dimensions
    ]
    supported = [
        (competitor, dimension)
        for competitor, dimension in expected_fields
        if any(
            source.dimension == dimension
            and _source_matches_competitor_name(source, competitor)
            and source.confidence >= 0.75
            for source in detail.raw_sources
        )
    ]
    return len(supported) / max(1, len(expected_fields))


def _validated_claim_rate(detail: RunDetail) -> float:
    projection = detail.enterprise_projection
    if projection is None or not projection.claim_records:
        return 1.0 if _claim_citation_rate(detail) >= 1.0 else 0.0
    evidence_ids = {item.id for item in projection.evidence_records}
    validated_claims = [
        claim
        for claim in projection.claim_records
        if claim.evidence_ids
        and all(evidence_id in evidence_ids for evidence_id in claim.evidence_ids)
    ]
    return len(validated_claims) / len(projection.claim_records)


def _warning_count(detail: RunDetail) -> int:
    qa_warnings = [finding for finding in detail.qa_findings if finding.severity == "warn"]
    release_gate = _quality_metadata(detail).get("release_gate")
    if isinstance(release_gate, dict) and isinstance(release_gate.get("warn_count"), int):
        non_release_qa_warning_count = len(
            [
                finding
                for finding in qa_warnings
                if not finding.field_path.startswith("release_gate.")
            ]
        )
        return non_release_qa_warning_count + int(release_gate["warn_count"])
    return len(qa_warnings)


def _quality_metadata(detail: RunDetail) -> dict[str, object]:
    projection = detail.enterprise_projection
    if projection is None:
        return {}
    return dict(projection.report_version.quality_metadata)


def _source_matches_competitor_name(source: RawSource, competitor: str) -> bool:
    if source.covered_competitors:
        return competitor in source.covered_competitors
    return source.competitor == competitor


def _factual_sources(sources: list[RawSource]) -> list[RawSource]:
    return [
        source
        for source in sources
        if source.source_type and source.source_type.casefold() not in USER_RESEARCH_SOURCE_TYPES
    ]


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


def _rag_gap_fill_section_score(detail: RunDetail) -> float:
    if not _needs_rag_gap_fill_section(detail):
        return 1.0
    if not _has_heading(detail.report_md, ("rag gap fill", "evidence gap fill", "retrieval")):
        return 0.0
    normalized = detail.report_md.casefold()
    if any(
        phrase in normalized
        for phrase in (
            "suggested retrieval query",
            "retrieval context",
            "grounded context",
            "retrieval candidate",
        )
    ):
        return 1.0
    return 0.5


def _needs_rag_gap_fill_section(detail: RunDetail) -> bool:
    return any(
        finding.target_agent == "collector" and finding.severity in {"warn", "blocker"}
        for finding in detail.qa_findings
    )


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


def _regression_gate(
    target: _QualitySnapshot,
    baseline: _QualitySnapshot | None,
    delta_score: int | None,
    metrics: list[RunQualityMetric],
) -> tuple[Literal["pass", "warn", "fail"], list[str]]:
    reasons: list[str] = []
    if not target.real_collection_signal:
        reasons.append("real_collection signal is missing.")
    if not target.real_llm_signal:
        reasons.append("real_llm signal is missing.")
    if not target.report_quality_signal:
        reasons.append("report_quality signal is below release threshold.")
    if target.score < 55:
        reasons.append(f"target_score {target.score} is below the hard floor 55.")
    if delta_score is not None and delta_score <= -10:
        reasons.append(f"delta_score {delta_score} regressed by at least 10 points.")

    core_regressions = [
        metric
        for metric in metrics
        if metric.name
        in {
            "source_coverage_rate",
            "verified_source_rate",
            "claim_citation_rate",
            "citation_validity_rate",
            "real_source_rate",
            "gap_resolution_rate",
            "field_support_rate",
            "validated_claim_rate",
            "report_structure_score",
            "qa_blocker_count",
        }
        and metric.normalized_score_delta is not None
        and metric.normalized_score_delta <= -0.15
    ]
    if core_regressions:
        reasons.append(
            "core metric regression: "
            + ", ".join(f"{metric.name} {metric.delta:+.2f}" for metric in core_regressions)
        )

    if reasons:
        return "fail", reasons

    warn_reasons: list[str] = []
    if baseline is None:
        warn_reasons.append("No baseline run was supplied; regression delta was not checked.")
    if target.score < 72:
        warn_reasons.append(f"target_score {target.score} is below the preferred floor 72.")
    if delta_score is not None and delta_score < 0:
        warn_reasons.append(f"delta_score {delta_score} is negative.")
    if warn_reasons:
        return "warn", warn_reasons
    return "pass", ["Quality gate passed against real-chain and baseline thresholds."]


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
            "evidence-indexed output."
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
            "Add a Memory Context section so confirmed MemoryAgent guidance is visible as "
            "guidance, not mistaken for factual evidence."
        )
    if target.values.get("user_research_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a User Research Evidence section so survey, interview, or manual-note signals "
            "are separated from official factual proof."
        )
    if target.values.get("rag_gap_fill_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a RAG Gap Fill section with retrieval queries or grounded context for open "
            "collector evidence gaps."
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
