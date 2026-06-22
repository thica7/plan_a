from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from packages.business_intel.report_sections import (
    SectionLayer,
    build_report_section_index,
    parse_report_section_marker,
)
from packages.i18n.language import repair_mojibake_text, report_label
from packages.schema.api_dto import (
    RunDetail,
    RunQualityComparison,
    RunQualityMetric,
    RunQualitySignalCheck,
)
from packages.schema.models import RawSource
from packages.sources import resolve_source_token, source_token_alias_map, source_tokens

COMMUNITY_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}
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
    *COMMUNITY_SOURCE_TYPES,
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
REVIEW_THEME_SOURCE_TYPES = {
    "review_site",
    *USER_RESEARCH_SOURCE_TYPES,
    *COMMUNITY_SOURCE_TYPES,
}
REVIEW_THEME_DIMENSION_HINTS = {
    "review",
    "persona",
    "user",
    "customer",
    "buyer",
    "feedback",
    "adoption",
    "switching",
}


@dataclass(frozen=True)
class _QualitySnapshot:
    score: int
    values: dict[str, float]
    normalized_values: dict[str, float]
    real_collection_signal: bool
    real_llm_signal: bool
    report_quality_signal: bool


@dataclass(frozen=True)
class _ReportSection:
    heading: str
    body: str
    start: int
    layer: SectionLayer = "core"
    section_key: str | None = None


@dataclass(frozen=True)
class CoreSectionDepthDiagnostic:
    section_key: str
    score: float
    body_chars: int
    substantive_rows: int
    min_chars: int
    min_rows: int
    missing: bool = False


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


def _core_report_markdown(detail: RunDetail) -> str:
    if detail.report_artifact is not None:
        return detail.report_artifact.render_cache.core_markdown
    return _legacy_core_markdown(detail.report_md)


def _support_report_markdown(detail: RunDetail) -> str:
    if detail.report_artifact is not None:
        return detail.report_artifact.render_cache.support_markdown
    return _legacy_support_markdown(detail.report_md)


def _full_report_markdown(detail: RunDetail) -> str:
    if detail.report_artifact is not None:
        return detail.report_artifact.render_cache.full_markdown
    return detail.report_md


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
    core_markdown = _core_report_markdown(detail)
    support_markdown = _support_report_markdown(detail)
    full_markdown = _full_report_markdown(detail)
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
        "report_source_token_count": float(_report_source_token_count(full_markdown)),
        "real_source_rate": _real_source_rate(detail.raw_sources),
        "gap_resolution_rate": _gap_resolution_rate(detail),
        "field_support_rate": _field_support_rate(detail),
        "validated_claim_rate": _validated_claim_rate(detail),
        "llm_call_signal": min(float(detail.metrics.llm_calls) / 3.0, 1.0),
        "report_length_score": min(len(core_markdown) / 2500.0, 1.0),
        "report_structure_score": _report_structure_score(detail),
        "duplicate_section_count": float(_duplicate_section_count(full_markdown)),
        "executive_summary_section_score": _executive_summary_section_score(
            core_markdown
        ),
        "decision_summary_section_score": _decision_summary_section_score(core_markdown),
        "competitive_findings_section_score": _competitive_findings_section_score(
            core_markdown
        ),
        "competitor_deep_dive_section_score": _competitor_deep_dive_section_score(
            core_markdown
        ),
        "layer_analysis_section_score": _layer_analysis_section_score(detail),
        "core_analysis_depth_score": _core_analysis_depth_score(core_markdown),
        "core_section_depth_score": _core_section_depth_score(detail),
        "core_support_balance_score": _core_support_balance_score(full_markdown),
        "claim_risk_section_score": _claim_risk_section_score(support_markdown),
        "scenario_checklist_section_score": _scenario_checklist_section_score(
            support_markdown
        ),
        "memory_context_section_score": _memory_context_section_score(detail),
        "user_research_section_score": _user_research_section_score(detail),
        "review_theme_section_score": _review_theme_section_score(detail),
        "community_evidence_section_score": _community_evidence_section_score(detail),
        "swot_section_score": _swot_section_score(detail),
        "rag_gap_fill_section_score": _rag_gap_fill_section_score(detail),
        "localized_heading_score": _localized_heading_score(detail),
        "battlecard_section_score": _battlecard_section_score(detail),
        "citation_hygiene_score": _citation_hygiene_score(detail.report_md),
        "claim_self_consistency_warning_count": float(
            _claim_self_consistency_warning_count(detail)
        ),
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
        "duplicate_section_count": max(
            0.0, 1.0 - min(values["duplicate_section_count"] / 3.0, 1.0)
        ),
        "executive_summary_section_score": values["executive_summary_section_score"],
        "decision_summary_section_score": values["decision_summary_section_score"],
        "competitive_findings_section_score": values["competitive_findings_section_score"],
        "competitor_deep_dive_section_score": values["competitor_deep_dive_section_score"],
        "layer_analysis_section_score": values["layer_analysis_section_score"],
        "core_analysis_depth_score": values["core_analysis_depth_score"],
        "core_section_depth_score": values["core_section_depth_score"],
        "core_support_balance_score": values["core_support_balance_score"],
        "claim_risk_section_score": values["claim_risk_section_score"],
        "scenario_checklist_section_score": values["scenario_checklist_section_score"],
        "memory_context_section_score": values["memory_context_section_score"],
        "user_research_section_score": values["user_research_section_score"],
        "review_theme_section_score": values["review_theme_section_score"],
        "community_evidence_section_score": values["community_evidence_section_score"],
        "swot_section_score": values["swot_section_score"],
        "rag_gap_fill_section_score": values["rag_gap_fill_section_score"],
        "localized_heading_score": values["localized_heading_score"],
        "battlecard_section_score": values["battlecard_section_score"],
        "citation_hygiene_score": values["citation_hygiene_score"],
        "claim_self_consistency_warning_count": max(
            0.0, 1.0 - min(values["claim_self_consistency_warning_count"] / 3.0, 1.0)
        ),
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
        len(core_markdown) >= 1200
        and values["claim_citation_rate"] >= 0.6
        and values["citation_validity_rate"] >= 0.6
        and values["source_coverage_rate"] >= 0.5
        and values["report_structure_score"] >= 0.7
        and values["duplicate_section_count"] <= 0
        and values["executive_summary_section_score"] >= 1.0
        and values["decision_summary_section_score"] >= 1.0
        and values["competitive_findings_section_score"] >= 1.0
        and values["competitor_deep_dive_section_score"] >= 1.0
        and values["layer_analysis_section_score"] >= 1.0
        and values["core_analysis_depth_score"] >= 0.6
        and values["core_section_depth_score"] >= 1.0
        and values["core_support_balance_score"] >= 1.0
        and values["claim_risk_section_score"] >= 1.0
        and values["scenario_checklist_section_score"] >= 1.0
        and values["memory_context_section_score"] >= 1.0
        and values["user_research_section_score"] >= 1.0
        and values["review_theme_section_score"] >= 1.0
        and values["community_evidence_section_score"] >= 1.0
        and values["swot_section_score"] >= 1.0
        and values["rag_gap_fill_section_score"] >= 1.0
        and values["localized_heading_score"] >= 1.0
        and values["battlecard_section_score"] >= 1.0
        and values["citation_hygiene_score"] >= 1.0
        and values["claim_self_consistency_warning_count"] <= 0
        and values["qa_blocker_count"] <= 0
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
        ("evidence_count", 0.05, "higher_is_better"),
        ("source_coverage_rate", 0.06, "higher_is_better"),
        ("verified_source_rate", 0.06, "higher_is_better"),
        ("community_evidence_section_score", 0.02, "higher_is_better"),
        ("claim_citation_rate", 0.08, "higher_is_better"),
        ("citation_validity_rate", 0.08, "higher_is_better"),
        ("real_source_rate", 0.07, "higher_is_better"),
        ("gap_resolution_rate", 0.03, "higher_is_better"),
        ("field_support_rate", 0.03, "higher_is_better"),
        ("validated_claim_rate", 0.03, "higher_is_better"),
        ("llm_call_signal", 0.04, "higher_is_better"),
        ("report_length_score", 0.0, "higher_is_better"),
        ("report_structure_score", 0.03, "higher_is_better"),
        ("duplicate_section_count", 0.01, "lower_is_better"),
        ("executive_summary_section_score", 0.02, "higher_is_better"),
        ("decision_summary_section_score", 0.03, "higher_is_better"),
        ("competitive_findings_section_score", 0.03, "higher_is_better"),
        ("competitor_deep_dive_section_score", 0.03, "higher_is_better"),
        ("layer_analysis_section_score", 0.02, "higher_is_better"),
        ("core_analysis_depth_score", 0.02, "higher_is_better"),
        ("core_section_depth_score", 0.02, "higher_is_better"),
        ("core_support_balance_score", 0.02, "higher_is_better"),
        ("claim_risk_section_score", 0.04, "higher_is_better"),
        ("scenario_checklist_section_score", 0.02, "higher_is_better"),
        ("memory_context_section_score", 0.02, "higher_is_better"),
        ("user_research_section_score", 0.02, "higher_is_better"),
        ("review_theme_section_score", 0.02, "higher_is_better"),
        ("swot_section_score", 0.02, "higher_is_better"),
        ("rag_gap_fill_section_score", 0.02, "higher_is_better"),
        ("localized_heading_score", 0.0, "higher_is_better"),
        ("battlecard_section_score", 0.0, "higher_is_better"),
        ("citation_hygiene_score", 0.0, "higher_is_better"),
        ("claim_self_consistency_warning_count", 0.0, "lower_is_better"),
        ("qa_blocker_count", 0.05, "lower_is_better"),
        ("warning_count", 0.01, "lower_is_better"),
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
    if len(_core_report_markdown(detail)) < 1200:
        report_blockers.append("report_length_score")
    for name, minimum in [
        ("claim_citation_rate", 0.6),
        ("citation_validity_rate", 0.6),
        ("source_coverage_rate", 0.5),
        ("report_structure_score", 0.7),
        ("decision_summary_section_score", 1.0),
        ("competitive_findings_section_score", 1.0),
        ("competitor_deep_dive_section_score", 1.0),
        ("layer_analysis_section_score", 1.0),
        ("core_analysis_depth_score", 0.6),
        ("core_section_depth_score", 1.0),
        ("core_support_balance_score", 1.0),
        ("claim_risk_section_score", 1.0),
        ("scenario_checklist_section_score", 1.0),
        ("memory_context_section_score", 1.0),
        ("user_research_section_score", 1.0),
        ("review_theme_section_score", 1.0),
        ("swot_section_score", 1.0),
        ("rag_gap_fill_section_score", 1.0),
        ("localized_heading_score", 1.0),
        ("battlecard_section_score", 1.0),
        ("citation_hygiene_score", 1.0),
    ]:
        if snapshot.values[name] < minimum:
            report_blockers.append(name)
    if snapshot.values["duplicate_section_count"] > 0:
        report_blockers.append("duplicate_section_count")
    if snapshot.values["claim_self_consistency_warning_count"] > 0:
        report_blockers.append("claim_self_consistency_warning_count")
    if snapshot.values["qa_blocker_count"] > 0:
        report_blockers.append("qa_blocker_count")

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
                "scenario QA, core analysis, no duplicate sections, no QA blockers, and RAG "
                "gap-fill coverage when collector gaps exist.",
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
    tokens = source_tokens(_full_report_markdown(detail), include_malformed=True)
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
        release_issues = release_gate.get("issues")
        if isinstance(release_issues, list):
            release_warning_count = len(
                [
                    issue
                    for issue in release_issues
                    if isinstance(issue, dict)
                    and issue.get("severity") == "warn"
                    and issue.get("rule_id") != "run_qa_findings_unresolved"
                ]
            )
            return non_release_qa_warning_count + release_warning_count
        return non_release_qa_warning_count + int(release_gate["warn_count"])
    return len(qa_warnings)


def _claim_self_consistency_warning_count(detail: RunDetail) -> int:
    release_gate = _quality_metadata(detail).get("release_gate")
    if isinstance(release_gate, dict):
        release_issues = release_gate.get("issues")
        if isinstance(release_issues, list):
            return len(
                [
                    issue
                    for issue in release_issues
                    if isinstance(issue, dict)
                    and issue.get("severity") == "warn"
                    and issue.get("rule_id") == "claim_self_consistency_required"
                ]
            )
        warn_count = release_gate.get("warn_count")
        if isinstance(warn_count, int):
            return len(
                [
                    finding
                    for finding in detail.qa_findings
                    if finding.severity == "warn"
                    and finding.field_path
                    == "release_gate.claim_self_consistency_required"
                ]
            )
    return len(
        [
            finding
            for finding in detail.qa_findings
            if finding.severity == "warn"
            and finding.field_path == "release_gate.claim_self_consistency_required"
        ]
    )


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


_REPORT_LANGUAGES = ("en-US", "zh-CN")
_SECTION_BODY_CHAR_THRESHOLD = 80
_SUBSTANTIVE_ROW_CHAR_THRESHOLD = 30


def _report_label_aliases(*keys: str) -> tuple[str, ...]:
    return tuple(
        report_label(language, key)
        for key in keys
        for language in _REPORT_LANGUAGES
    )


def _review_theme_section_aliases() -> tuple[str, ...]:
    return (
        *_report_label_aliases("review_theme_summary"),
        "User Review Themes",
        "Review Themes",
        "Customer Review Themes",
        "用户评价整理",
        "鐢ㄦ埛璇勪环鏁寸悊",
    )


def _swot_section_aliases() -> tuple[str, ...]:
    return (
        *_report_label_aliases("swot_analysis"),
        "SWOT Analysis",
        "SWOT",
        "SWOT 分析",
        "SWOT 鍒嗘瀽",
    )


SUPPORT_SECTION_NEEDLES = (
    *_report_label_aliases(
        "evidence_support",
        "source_quality",
        "scenario_checklist",
        "claim_risk",
        "next_collection",
        "evidence_appendix",
        "generation_notes",
        "memory_context",
        "user_research_evidence",
        "rag_gap_fill",
        "knowledge_coverage",
        "confidence_notes",
    ),
    "source coverage",
    "source appendix",
    "scenario qa",
    "claim validation",
    "evidence risk",
    "verification plan",
    "evidence gap",
    "buyer research",
    "memoryagent",
    "retrieval",
)

DUPLICATE_SECTION_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "executive_takeaway",
        _report_label_aliases("executive_takeaway", "executive_summary", "executive_overview"),
    ),
    ("decision_summary", _report_label_aliases("decision_summary")),
    ("competitive_findings", _report_label_aliases("competitive_findings")),
    ("dimension_winners", _report_label_aliases("dimension_winners")),
    (
        "comparison_matrix",
        (
            *_report_label_aliases("comparison_matrix", "side_by_side_matrix"),
            "Decision Matrix",
        ),
    ),
    (
        "competitor_deep_dives",
        (
            *_report_label_aliases("competitor_deep_dives"),
            "Competitor Deep Dive",
        ),
    ),
    ("review_theme_summary", _review_theme_section_aliases()),
    ("swot_analysis", _swot_section_aliases()),
    (
        "battlecard",
        (
            *_report_label_aliases("battlecard"),
            "Direct Battlecard",
            "Sales Objection",
        ),
    ),
    (
        "workflow_enterprise_risk",
        (
            *_report_label_aliases("workflow_enterprise_risk"),
            "Workflow",
            "Enterprise Risk",
            "Switching",
        ),
    ),
    (
        "market_landscape",
        (
            *_report_label_aliases("market_landscape"),
            "Market Landscape",
            "Segmentation",
            "Benchmark",
        ),
    ),
    (
        "business_implications",
        (
            *_report_label_aliases("business_implications"),
            "Strategy",
        ),
    ),
    ("evidence_support", _report_label_aliases("evidence_support")),
    (
        "source_quality",
        (
            *_report_label_aliases("source_quality"),
            "Source Coverage",
        ),
    ),
    ("memory_context", _report_label_aliases("memory_context")),
    (
        "user_research_evidence",
        (
            *_report_label_aliases("user_research_evidence"),
            "Buyer Research",
        ),
    ),
    (
        "rag_gap_fill",
        (
            *_report_label_aliases("rag_gap_fill"),
            "Evidence Gap Fill",
            "Retrieval",
        ),
    ),
    (
        "scenario_checklist",
        (
            *_report_label_aliases("scenario_checklist"),
            "Scenario QA",
            "Scenario Checklist",
        ),
    ),
    (
        "knowledge_coverage",
        _report_label_aliases("knowledge_coverage"),
    ),
    ("confidence_notes", _report_label_aliases("confidence_notes")),
    (
        "claim_risk",
        (
            *_report_label_aliases("claim_risk"),
            "Claim Validation",
            "Evidence Risk",
        ),
    ),
    (
        "next_collection",
        (
            *_report_label_aliases("next_collection"),
            "Verification Plan",
            "Evidence Gap",
        ),
    ),
    (
        "evidence_appendix",
        (
            *_report_label_aliases("evidence_appendix"),
            "Source Appendix",
        ),
    ),
    ("generation_notes", _report_label_aliases("generation_notes")),
)


def _executive_summary_section_score(markdown: str) -> float:
    return _section_depth_score(
        markdown,
        _report_label_aliases(
            "executive_takeaway",
            "executive_summary",
            "executive_overview",
        ),
        320,
        3,
    )


def _decision_summary_section_score(markdown: str) -> float:
    return _core_section_score(markdown, _report_label_aliases("decision_summary"))


def _competitive_findings_section_score(markdown: str) -> float:
    return _core_section_score(markdown, _report_label_aliases("competitive_findings"))


def _competitor_deep_dive_section_score(markdown: str) -> float:
    return _core_section_score(
        markdown,
        (
            *_report_label_aliases("competitor_deep_dives"),
            "Competitor Deep Dive",
        ),
    )


def _layer_analysis_section_score(detail: RunDetail) -> float:
    return _core_section_score(_core_report_markdown(detail), _layer_section_aliases(detail))


def _core_analysis_depth_score(markdown: str) -> float:
    sections = [
        section
        for section in _sections_before_support(markdown)
        if _heading_matches(section.heading, _known_core_analysis_aliases())
    ]
    char_count = 0
    bullet_or_table_rows = 0
    for section in sections:
        section_char_count, section_row_count = _body_content_summary(section.body)
        char_count += section_char_count
        bullet_or_table_rows += section_row_count
    return min(1.0, max(char_count / 4600.0, bullet_or_table_rows / 30.0))


def _core_section_depth_score(detail: RunDetail) -> float:
    diagnostics = core_section_depth_diagnostics(detail)
    return min((diagnostic.score for diagnostic in diagnostics), default=0.0)


def core_section_depth_diagnostics(detail: RunDetail) -> list[CoreSectionDepthDiagnostic]:
    specs = [
        (
            "executive_summary",
            _report_label_aliases(
                "executive_takeaway",
                "executive_summary",
                "executive_overview",
            ),
            320,
            3,
        ),
        ("decision_summary", _report_label_aliases("decision_summary"), 450, 3),
        (
            "competitive_findings",
            _report_label_aliases("competitive_findings"),
            600,
            4,
        ),
        (
            "competitor_deep_dives",
            (
                *_report_label_aliases("competitor_deep_dives"),
                "Competitor Deep Dive",
            ),
            500,
            max(3, len(detail.plan.competitors)),
        ),
        ("swot_analysis", _swot_section_aliases(), 280, 4),
        (_layer_section_key(detail), _layer_section_aliases(detail), 600, 4),
        (
            "side_by_side_matrix",
            (
                *_report_label_aliases("side_by_side_matrix", "comparison_matrix"),
                "Side-by-Side Decision Matrix",
                "Decision Matrix",
            ),
            520,
            max(4, len(detail.plan.competitors) * max(1, min(len(detail.plan.dimensions), 3))),
        ),
    ]
    if _needs_review_theme_section(detail):
        specs.insert(2, ("review_theme_summary", _review_theme_section_aliases(), 500, 4))
    diagnostics: list[CoreSectionDepthDiagnostic] = []
    swot_aliases = _swot_section_aliases()
    core_markdown = _core_report_markdown(detail)
    for section_key, aliases, min_chars, min_rows in specs:
        section = _find_section_before_support(core_markdown, aliases)
        if section is None:
            diagnostics.append(
                CoreSectionDepthDiagnostic(
                    section_key=section_key,
                    score=0.0,
                    body_chars=0,
                    substantive_rows=0,
                    min_chars=min_chars,
                    min_rows=min_rows,
                    missing=True,
                )
            )
            continue
        char_count, row_count = _body_content_summary(section.body)
        score = _section_depth_score(core_markdown, aliases, min_chars, min_rows)
        if aliases == swot_aliases:
            if not _has_structured_swot_quadrants(section.body):
                score = min(score, 0.5)
        diagnostics.append(
            CoreSectionDepthDiagnostic(
                section_key=section_key,
                score=score,
                body_chars=char_count,
                substantive_rows=row_count,
                min_chars=min_chars,
                min_rows=min_rows,
            )
        )
    return diagnostics


def _section_depth_score(
    markdown: str,
    aliases: tuple[str, ...],
    min_chars: int,
    min_rows: int,
) -> float:
    section = _find_section_before_support(markdown, aliases)
    if section is None:
        return 0.0
    chars, rows = _body_content_summary(section.body)
    return max(
        min(chars / float(min_chars), 1.0),
        min(rows / float(min_rows), 1.0),
    )


def _core_support_balance_score(markdown: str) -> float:
    report_md = repair_mojibake_text(markdown)
    sections = _report_sections(report_md)
    first_support = _first_support_section(sections)
    if first_support is None:
        core_markdown = report_md
        support_markdown = ""
    else:
        core_markdown = report_md[: first_support.start]
        support_markdown = report_md[first_support.start :]
    core_chars, core_rows = _body_content_summary(core_markdown)
    support_chars, support_rows = _body_content_summary(support_markdown)
    core_units = core_chars + core_rows * 60
    support_units = support_chars + support_rows * 60
    if core_units <= 0:
        return 0.0
    if support_units <= 0:
        return 1.0
    core_ratio = core_units / float(core_units + support_units)
    return min(1.0, core_ratio / 0.65)


def _markdown_before_support_sections(markdown: str) -> str:
    report_md = repair_mojibake_text(markdown)
    first_support = _first_support_section(_report_sections(report_md))
    if first_support is None:
        return report_md
    return report_md[: first_support.start].strip()


def _legacy_core_markdown(markdown: str) -> str:
    return _markdown_before_support_sections(markdown)


def _legacy_support_markdown(markdown: str) -> str:
    report_md = repair_mojibake_text(markdown)
    first_support = _first_support_section(_report_sections(report_md))
    if first_support is None:
        return ""
    return report_md[first_support.start :].strip()


def _core_section_score(markdown: str, aliases: tuple[str, ...]) -> float:
    section = _find_section_before_support(markdown, aliases)
    return 1.0 if section is not None and _section_has_substantive_body(section) else 0.0


def _find_section_before_support(markdown: str, aliases: tuple[str, ...]) -> _ReportSection | None:
    for section in _sections_before_support(markdown):
        if _heading_matches(section.heading, aliases):
            return section
    return None


def _sections_before_support(markdown: str) -> list[_ReportSection]:
    sections = _report_sections(markdown)
    first_support = _first_support_section(sections)
    if first_support is None:
        return sections
    return [section for section in sections if section.start < first_support.start]


def _first_support_section(sections: list[_ReportSection]) -> _ReportSection | None:
    return next(
        (
            section
            for section in sections
            if section.layer in {"support", "audit"}
            or _heading_matches(section.heading, SUPPORT_SECTION_NEEDLES)
        ),
        None,
    )


def _report_sections(markdown: str) -> list[_ReportSection]:
    report_md = repair_mojibake_text(markdown)
    section_index = build_report_section_index(report_md)
    h2_sections = [section for section in section_index.sections if section.level == 2]
    matches = list(
        re.finditer(
            r"^\s*##(?!#)\s+(.+?)\s*#*\s*$",
            report_md,
            flags=re.MULTILINE,
        )
    )
    sections: list[_ReportSection] = []
    for index, match in enumerate(matches):
        indexed_section = h2_sections[index] if index < len(h2_sections) else None
        body_start = match.end()
        if index + 1 < len(h2_sections):
            body_end = h2_sections[index + 1].start
        elif index + 1 < len(matches):
            body_end = matches[index + 1].start()
        else:
            body_end = len(report_md)
        sections.append(
            _ReportSection(
                heading=(
                    indexed_section.heading
                    if indexed_section is not None
                    else _clean_heading(match.group(1))
                ),
                body=report_md[body_start:body_end].strip(),
                start=indexed_section.start if indexed_section is not None else match.start(),
                layer=indexed_section.layer if indexed_section is not None else "core",
                section_key=(
                    indexed_section.section_key if indexed_section is not None else None
                ),
            )
        )
    return sections


def _clean_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", heading.strip().strip("#").strip())


def _normalize_heading(heading: str) -> str:
    cleaned = _clean_heading(heading)
    cleaned = re.sub(
        r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.casefold()


def _compact_heading_text(heading: str) -> str:
    return re.sub(r"\s+", "", _normalize_heading(heading))


def _heading_matches(heading: str, aliases: tuple[str, ...]) -> bool:
    normalized_heading = _normalize_heading(heading)
    compact_heading = _compact_heading_text(heading)
    for alias in aliases:
        normalized_alias = _normalize_heading(alias)
        compact_alias = _compact_heading_text(alias)
        if normalized_heading == normalized_alias or normalized_alias in normalized_heading:
            return True
        if compact_heading == compact_alias or compact_alias in compact_heading:
            return True
    return False


def _duplicate_section_count(markdown: str) -> int:
    report_md = repair_mojibake_text(markdown)
    seen: set[str] = set()
    duplicate_count = 0
    for match in re.finditer(
        r"^\s*##(?!#)\s+(.+?)\s*#*\s*$",
        report_md,
        flags=re.MULTILINE,
    ):
        section_key = _canonical_report_section_key(match.group(1))
        if section_key is None:
            continue
        if section_key in seen:
            duplicate_count += 1
        else:
            seen.add(section_key)
    return duplicate_count


def _canonical_report_section_key(heading: str) -> str | None:
    for section_key, aliases in DUPLICATE_SECTION_ALIAS_GROUPS:
        if _heading_matches(heading, aliases):
            return section_key
    return None


def _section_has_substantive_body(section: _ReportSection) -> bool:
    char_count, bullet_or_table_rows = _body_content_summary(section.body)
    return char_count >= _SECTION_BODY_CHAR_THRESHOLD or bullet_or_table_rows > 0


def _body_content_summary(markdown: str) -> tuple[int, int]:
    char_count = 0
    bullet_or_table_rows = 0
    for line in markdown.splitlines():
        cleaned = _clean_body_line(line)
        if not cleaned:
            continue
        char_count += len(cleaned)
        if _is_bullet_or_table_row(line) and len(cleaned) >= _SUBSTANTIVE_ROW_CHAR_THRESHOLD:
            bullet_or_table_rows += 1
    return char_count, bullet_or_table_rows


def _clean_body_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    if parse_report_section_marker(stripped) is not None:
        return ""
    if re.fullmatch(r"[\s|\-:]+", stripped):
        return ""
    without_citations = re.sub(r"\[source:[^\]]+\]", "", stripped, flags=re.IGNORECASE)
    without_markdown = without_citations.strip().strip("|").strip()
    without_markdown = re.sub(r"^[\-*]\s+", "", without_markdown)
    without_markdown = re.sub(r"\s+", " ", without_markdown).strip()
    if not without_markdown or not re.search(r"\w", without_markdown):
        return ""
    return without_markdown


def _is_bullet_or_table_row(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("-", "*", "|"))


def _known_core_analysis_aliases() -> tuple[str, ...]:
    return (
        *_report_label_aliases(
            "decision_summary",
            "competitive_findings",
            "competitor_deep_dives",
            "review_theme_summary",
            "swot_analysis",
            "battlecard",
            "workflow_enterprise_risk",
            "market_landscape",
            "business_implications",
            "dimension_winners",
            "comparison_matrix",
            "side_by_side_matrix",
        ),
        "Competitor Deep Dive",
        "Sales Objection",
        "User Review Themes",
        "Review Themes",
        "Customer Review Themes",
        "SWOT",
        "Enterprise Risk",
        "Switching",
        "Segmentation",
        "Benchmark",
        "Strategy",
    )


def _layer_section_aliases(detail: RunDetail) -> tuple[str, ...]:
    layer = detail.plan.competitor_layer
    if layer == "L1":
        return (
            *_report_label_aliases("battlecard"),
            "Sales Objection",
            "Direct Battlecard",
        )
    if layer == "L2":
        return (
            *_report_label_aliases("workflow_enterprise_risk"),
            "Workflow",
            "Enterprise Risk",
            "Switching",
        )
    if layer == "L3":
        return (
            *_report_label_aliases("market_landscape"),
            "Market Landscape",
            "Segmentation",
            "Benchmark",
        )
    return (
        *_report_label_aliases(
            "battlecard",
            "workflow_enterprise_risk",
            "market_landscape",
            "business_implications",
        ),
        "Sales Objection",
        "Direct Battlecard",
        "Workflow",
        "Enterprise Risk",
        "Switching",
        "Segmentation",
        "Benchmark",
        "Strategy",
    )


def _layer_section_key(detail: RunDetail) -> str:
    layer = detail.plan.competitor_layer
    if layer == "L1":
        return "battlecard"
    if layer == "L2":
        return "workflow_enterprise_risk"
    if layer == "L3":
        return "market_landscape"
    return "business_implications"


def _report_structure_score(detail: RunDetail) -> float:
    core_markdown = repair_mojibake_text(_core_report_markdown(detail))
    support_markdown = repair_mojibake_text(_support_report_markdown(detail))
    full_markdown = repair_mojibake_text(_full_report_markdown(detail))
    checks = [
        _has_heading(
            core_markdown,
            ("executive summary", "executive overview", "执行摘要", "执行概览"),
        ),
        _decision_summary_section_score(core_markdown) >= 1.0,
        _competitive_findings_section_score(core_markdown) >= 1.0,
        _competitor_deep_dive_section_score(core_markdown) >= 1.0,
        _layer_analysis_section_score(detail) >= 1.0,
        _core_analysis_depth_score(core_markdown) >= 0.6,
        _has_heading(
            support_markdown,
            ("source quality", "source coverage", "来源质量", "来源覆盖"),
        ),
        _has_heading(
            core_markdown,
            ("matrix", "dimension winners", "side-by-side", "决策矩阵", "对比矩阵", "维度结论"),
        ),
        _scenario_checklist_section_score(support_markdown) >= 1.0,
        _claim_risk_section_score(support_markdown) >= 1.0,
        _has_heading(
            support_markdown,
            (
                "next collection",
                "verification plan",
                "evidence gap",
                "下一步采集",
                "验证计划",
                "证据缺口",
            ),
        ),
        _has_heading(
            support_markdown,
            ("evidence appendix", "source appendix", "证据附录", "来源附录"),
        ),
        _memory_context_section_score(detail) >= 1.0,
        _user_research_section_score(detail) >= 1.0,
        _review_theme_section_score(detail) >= 1.0,
        _swot_section_score(detail) >= 1.0,
        _has_layer_heading(detail, report_md=full_markdown),
    ]
    return sum(1 for item in checks if item) / len(checks)


def _has_layer_heading(detail: RunDetail, *, report_md: str | None = None) -> bool:
    markdown = (
        report_md
        if report_md is not None
        else repair_mojibake_text(_core_report_markdown(detail))
    )
    return any(
        _heading_matches(section.heading, _layer_section_aliases(detail))
        for section in _report_sections(markdown)
    )


def _has_heading(markdown: str, needles: tuple[str, ...]) -> bool:
    headings = [
        _normalize_heading(match.group(1))
        for match in re.finditer(r"^\s*#{1,4}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    ]
    normalized_needles = tuple(_normalize_heading(needle) for needle in needles)
    return any(any(needle in heading for needle in normalized_needles) for heading in headings)


def _all_markdown_headings(markdown: str) -> list[str]:
    return [
        _clean_heading(match.group(1))
        for match in re.finditer(r"^\s*#{1,4}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    ]


def _claim_risk_section_score(markdown: str) -> float:
    return (
        1.0
        if _has_heading(markdown, ("claim validation", "evidence risk", "声明校验", "证据风险"))
        else 0.0
    )


def _scenario_checklist_section_score(markdown: str) -> float:
    return (
        1.0
        if _has_heading(markdown, ("scenario qa", "scenario checklist", "场景 qa", "场景清单"))
        else 0.0
    )


def _memory_context_section_score(detail: RunDetail) -> float:
    if not detail.plan.memory_prompt_context and not detail.plan.memory_candidate_ids:
        return 1.0
    report_md = repair_mojibake_text(_full_report_markdown(detail))
    return 1.0 if _has_heading(report_md, ("memory context", "memoryagent", "记忆上下文")) else 0.0


def _user_research_section_score(detail: RunDetail) -> float:
    if not _needs_user_research_section(detail):
        return 1.0
    report_md = repair_mojibake_text(_full_report_markdown(detail))
    return 1.0 if _has_heading(report_md, ("user research", "buyer research", "用户研究")) else 0.0


def _review_theme_section_score(detail: RunDetail) -> float:
    if not _needs_review_theme_section(detail):
        return 1.0
    section = _find_section_before_support(
        _core_report_markdown(detail),
        _review_theme_section_aliases(),
    )
    return 1.0 if section is not None and _section_has_substantive_body(section) else 0.0


def _community_evidence_section_score(detail: RunDetail) -> float:
    if not any(source.metadata.get("community_evidence") for source in detail.raw_sources):
        return 1.0
    section = _find_section_before_support(
        _full_report_markdown(detail),
        _report_label_aliases("community_evidence_triangulation"),
    )
    if section is not None and _section_has_substantive_body(section):
        return 1.0
    body = repair_mojibake_text(_full_report_markdown(detail)).casefold()
    if "community observation" in body and "official" in body:
        return 0.75
    return 0.0


ENGLISH_TEMPLATE_HEADING_PHRASES = (
    "executive summary",
    "decision summary",
    "competitive findings",
    "pricing and packaging",
    "feature and workflow",
    "user persona and adoption",
    "cross-competitor",
    "direct user / community signals",
    "simulated survey and interview signals",
    "adoption blockers",
    "switching triggers",
    "evidence gaps",
    "positioning and core value",
    "feature capabilities",
    "community feedback",
    "competitive plays",
    "strengths",
    "weaknesses",
    "opportunities",
    "threats",
    "official facts vs community observations",
    "repeated signals",
    "contested or low-confidence signals",
    "source quality",
    "evidence appendix",
)


def _localized_heading_score(detail: RunDetail) -> float:
    output_language = (detail.output_language or "").casefold()
    if not output_language.startswith("zh"):
        return 1.0
    if not _has_cjk_heading(detail.report_md):
        return 1.0
    for heading in _all_markdown_headings(detail.report_md):
        normalized = _normalize_heading(heading)
        if any(phrase in normalized for phrase in ENGLISH_TEMPLATE_HEADING_PHRASES):
            return 0.0
    return 1.0


def _has_cjk_heading(markdown: str) -> bool:
    return any(re.search(r"[\u3400-\u9fff]", heading) for heading in _all_markdown_headings(markdown))


BATTLECARD_TEMPLATE_PHRASES = (
    "direct battlecard positioning",
    "objection handling",
    "action bias",
    "deployment check",
    "every battlecard line should",
    "current winner as the short-term",
    "\u76f4\u63a5\u6218\u62a5\u5b9a\u4f4d",
    "\u53cd\u5bf9\u610f\u89c1\u5904\u7406",
    "\u884c\u52a8\u504f\u5411",
    "\u843d\u5730\u68c0\u67e5",
    "\u5f53\u524d\u8d62\u5bb6\u4f5c\u4e3a\u77ed\u671f",
)


def _battlecard_section_score(detail: RunDetail) -> float:
    section = _find_section_before_support(detail.report_md, _report_label_aliases("battlecard"))
    if section is None:
        return 1.0
    normalized_body = repair_mojibake_text(section.body).casefold()
    if any(phrase in normalized_body for phrase in BATTLECARD_TEMPLATE_PHRASES):
        return 0.0
    chars, rows = _body_content_summary(section.body)
    if chars < 520 and rows < 4:
        return 0.0
    competitors = [item for item in detail.plan.competitors if item]
    if competitors:
        mentioned = sum(
            1 for competitor in competitors if competitor.casefold() in normalized_body
        )
        if len(competitors) >= 2 and mentioned < 2:
            return 0.0
    return 1.0


INTERNAL_WRITER_REPORT_TERMS = (
    "Segment Evidence Pack",
    "Writer Evidence Pack",
    "source_registry",
    "allowed_source_ids",
    "represented_by",
)


def _citation_hygiene_score(markdown: str) -> float:
    report_md = repair_mojibake_text(markdown)
    if any(term in report_md for term in INTERNAL_WRITER_REPORT_TERMS):
        return 0.0
    lines = report_md.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") and "[source:" in stripped.casefold():
            return 0.0
        if _table_header_line_has_citation(lines, index):
            return 0.0
    return 1.0


def _table_header_line_has_citation(lines: list[str], index: int) -> bool:
    line = lines[index].strip()
    if not line.startswith("|") or "[source:" not in line.casefold():
        return False
    next_line = ""
    for candidate in lines[index + 1 :]:
        if candidate.strip():
            next_line = candidate.strip()
            break
    return bool(next_line) and re.fullmatch(r"\|?[\s|\-:]+\|?", next_line) is not None


def _swot_section_score(detail: RunDetail) -> float:
    section = _find_section_before_support(_core_report_markdown(detail), _swot_section_aliases())
    if section is None:
        return 0.0
    if _has_structured_swot_quadrants(section.body):
        return 1.0
    return 0.5


def _rag_gap_fill_section_score(detail: RunDetail) -> float:
    if not _needs_rag_gap_fill_section(detail):
        return 1.0
    report_md = repair_mojibake_text(_support_report_markdown(detail))
    rag_section_aliases = (
        "rag gap fill",
        "evidence gap fill",
        "retrieval",
        "RAG 缺口补全",
        "RAG缺口补全",
        "证据缺口补全",
        "RAG 缂哄彛琛ュ叏",
        "RAG缂哄彛琛ュ叏",
        "璇佹嵁缂哄彛琛ュ叏",
    )
    section_index = build_report_section_index(report_md)
    rag_section = next(
        (
            section
            for section in section_index.sections
            if _heading_matches(section.heading, rag_section_aliases)
        ),
        None,
    )
    if rag_section is not None:
        normalized_section = rag_section.body.casefold()
        if any(
            phrase in normalized_section
            for phrase in (
                "suggested retrieval query",
                "retrieval context",
                "grounded context",
                "retrieval candidate",
                "\u5efa\u8bae\u68c0\u7d22",
                "\u5efa\u8bae\u68c0\u7d22/\u53d6\u8bc1",
                "\u68c0\u7d22\u67e5\u8be2",
                "\u68c0\u7d22/\u53d6\u8bc1",
                "\u9700\u8981\u7684\u8bc1\u636e",
                "\u5f53\u524d\u72b6\u6001",
                "\u8bc1\u636e\u7f3a\u53e3",
                "\u5f85\u8865\u5168",
            )
        ):
            return 1.0
        return 0.5
    if not _has_heading(
        report_md,
        (
            "rag gap fill",
            "evidence gap fill",
            "retrieval",
            "RAG 缺口补全",
            "RAG缺口补全",
            "证据缺口补全",
        ),
    ):
        return 0.0
    normalized = report_md.casefold()
    if any(
        phrase in normalized
        for phrase in (
            "suggested retrieval query",
            "retrieval context",
            "grounded context",
            "retrieval candidate",
            "建议的检索查询",
            "检索查询",
            "检索上下文",
            "已填补的差距",
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


def _needs_review_theme_section(detail: RunDetail) -> bool:
    if any(source.source_type in REVIEW_THEME_SOURCE_TYPES for source in detail.raw_sources):
        return True
    return any(
        any(
            hint in dimension.casefold().replace("-", "_")
            for hint in REVIEW_THEME_DIMENSION_HINTS
        )
        for dimension in detail.plan.dimensions
    )


def _has_structured_swot_quadrants(body: str) -> bool:
    found: set[str] = set()
    lines = repair_mojibake_text(body).splitlines()
    for index, line in enumerate(lines):
        quadrant = _swot_quadrant_from_structured_line(line)
        if quadrant is not None:
            found.add(quadrant)
            continue
        heading_quadrant = _swot_quadrant_from_heading(line)
        if heading_quadrant is not None and _heading_has_following_body(lines, index):
            found.add(heading_quadrant)
            continue
        label_quadrant, inline_content = _swot_quadrant_from_markdown_label(line)
        if label_quadrant is None:
            continue
        if _is_substantive_quadrant_content(
            inline_content
        ) or _swot_label_has_following_body(lines, index):
            found.add(label_quadrant)
    return found == {key for key, _ in _swot_quadrant_aliases()}


def _swot_quadrant_from_structured_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    table_cells = _table_cells(stripped)
    if table_cells:
        return _swot_quadrant_from_table_cells(table_cells)
    bullet_match = re.match(r"^\s*[-*]\s*(.+?)\s*[:：]\s*(.+)$", stripped)
    if bullet_match is None:
        return None
    label = bullet_match.group(1)
    content = bullet_match.group(2)
    if not _is_substantive_quadrant_content(content):
        return None
    return _swot_quadrant_from_label(label)


def _swot_quadrant_from_table_cells(cells: list[str]) -> str | None:
    if len(cells) < 2:
        return None
    quadrant = _swot_quadrant_from_label(cells[0])
    if quadrant is None:
        return None
    if any(_is_substantive_quadrant_content(cell) for cell in cells[1:]):
        return quadrant
    return None


def _swot_quadrant_from_heading(line: str) -> str | None:
    match = re.match(r"^\s*#{3,6}\s+(.+?)\s*#*\s*$", line)
    if match is None:
        return None
    return _swot_quadrant_from_label(match.group(1))


def _swot_quadrant_from_markdown_label(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    match = re.match(
        r"^\s*(?:[-*]\s*)?(?:\*\*|__)\s*(.+?)\s*(?:\*\*|__)\s*(.*)$",
        stripped,
    )
    if match is None:
        return None, ""
    quadrant = _swot_quadrant_from_label(match.group(1))
    return quadrant, match.group(2).strip()


def _swot_quadrant_from_label(label: str) -> str | None:
    for cleaned_label in _swot_label_candidates(label):
        normalized_label = _normalize_heading(cleaned_label)
        compact_label = _compact_heading_text(cleaned_label)
        for key, aliases in _swot_quadrant_aliases():
            if any(
                normalized_label == _normalize_heading(alias)
                or compact_label == _compact_heading_text(alias)
                for alias in aliases
            ):
                return key
    return None


def _swot_label_candidates(label: str) -> list[str]:
    cleaned = _clean_swot_quadrant_label(label)
    candidates = [cleaned]
    parenthetical_parts = re.findall(r"[\(\[（【]\s*([^\)\]）】]+?)\s*[\)\]）】]", cleaned)
    without_parenthetical = re.sub(r"\s*[\(\[（【][^\)\]）】]+?[\)\]）】]\s*", " ", cleaned)
    candidates.append(_clean_swot_quadrant_label(without_parenthetical))
    candidates.extend(_clean_swot_quadrant_label(part) for part in parenthetical_parts)
    for part in re.split(r"[/／|｜·・]", cleaned):
        candidates.append(_clean_swot_quadrant_label(part))
    return [candidate for candidate in candidates if candidate]


def _clean_swot_quadrant_label(label: str) -> str:
    cleaned = label.strip()
    cleaned = re.sub(r"^(?:\*\*|__|[*_`])+", "", cleaned)
    cleaned = re.sub(r"(?:\*\*|__|[*_`])+$", "", cleaned)
    return cleaned.strip().strip(":：锛歖").strip()


def _table_cells(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        return []
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if not cells or all(re.fullmatch(r"[-:\s]+", cell) for cell in cells):
        return []
    return cells


def _heading_has_following_body(lines: list[str], heading_index: int) -> bool:
    for line in lines[heading_index + 1 :]:
        if re.match(r"^\s*#{1,6}\s+", line):
            return False
        if _is_substantive_quadrant_content(line):
            return True
    return False


def _swot_label_has_following_body(lines: list[str], label_index: int) -> bool:
    for line in lines[label_index + 1 :]:
        if re.match(r"^\s*#{1,6}\s+", line):
            return False
        if _swot_quadrant_from_markdown_label(line)[0] is not None:
            return False
        if _is_substantive_quadrant_content(line):
            return True
    return False


def _is_substantive_quadrant_content(content: str) -> bool:
    cleaned = _clean_body_line(content)
    return len(cleaned) >= 4 and re.search(r"\w", cleaned) is not None


def _swot_quadrant_aliases() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("strengths", ("strengths", "strength", "优势", "優勢", "浼樺娍")),
        ("weaknesses", ("weaknesses", "weakness", "劣势", "劣勢", "鍔ｅ娍")),
        ("opportunities", ("opportunities", "opportunity", "机会", "機會", "鏈轰細")),
        ("threats", ("threats", "threat", "威胁", "威脅", "濞佽儊")),
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
            "duplicate_section_count",
            "decision_summary_section_score",
            "competitive_findings_section_score",
            "competitor_deep_dive_section_score",
            "layer_analysis_section_score",
            "core_analysis_depth_score",
            "core_section_depth_score",
            "core_support_balance_score",
            "review_theme_section_score",
            "swot_section_score",
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
    if target.values.get("duplicate_section_count", 0.0) > 0:
        recommendations.append(
            "Remove duplicate semantic report sections so the core analysis and evidence support "
            "appear once in a clear review order."
        )
    if target.values.get("qa_blocker_count", 0.0) > 0:
        recommendations.append(
            "Resolve QA blockers before treating the report as release-ready."
        )
    if any(
        target.values.get(name, 0.0) < 1.0
        for name in (
            "decision_summary_section_score",
            "competitive_findings_section_score",
            "competitor_deep_dive_section_score",
            "layer_analysis_section_score",
        )
    ):
        recommendations.append(
            "Add analysis-first sections for Decision Summary, Competitive Findings, Competitor "
            "Deep Dives, and the selected competitor-layer analysis before evidence support."
        )
    if target.values.get("core_analysis_depth_score", 0.0) < 0.6:
        recommendations.append(
            "Expand the core analysis before support sections so the report gives enough business "
            "guidance before source QA, validation, and appendix material."
        )
    if target.values.get("core_section_depth_score", 0.0) < 1.0:
        recommendations.append(
            "Expand required core sections so they contain decision-useful substance rather than "
            "one-line placeholders."
        )
    if target.values.get("core_support_balance_score", 0.0) < 1.0:
        recommendations.append(
            "Move report weight back to core analysis and keep evidence, QA, risk, and appendix "
            "sections concise support material."
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
    if target.values.get("review_theme_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a User Review Themes section so buyer feedback, review signals, adoption "
            "blockers, and switching cues are visible in the core analysis."
        )
    if target.values.get("swot_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a SWOT Analysis section with Strengths, Weaknesses, Opportunities, and Threats "
            "so strategic implications are complete."
        )
    if target.values.get("rag_gap_fill_section_score", 1.0) < 1.0:
        recommendations.append(
            "Add a RAG Gap Fill section with retrieval queries or grounded context for open "
            "collector evidence gaps."
        )
    if target.values.get("localized_heading_score", 1.0) < 1.0:
        recommendations.append(
            "Localize report structure headings so the output language does not mix in English "
            "template labels such as Pricing and Packaging or Strengths/Weaknesses."
        )
    if target.values.get("battlecard_section_score", 1.0) < 1.0:
        recommendations.append(
            "Rewrite the Battlecard as competitor-specific talk tracks with buyer context, "
            "objections, rebuttals, and evidence limits instead of generic battlecard instructions."
        )
    if target.values.get("citation_hygiene_score", 1.0) < 1.0:
        recommendations.append(
            "Repair citation hygiene: remove citations from headings and table headers, and keep "
            "writer-internal source registry terms out of the reader-facing report."
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
