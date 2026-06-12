import re
from datetime import datetime

from packages.agents.writer.logic import (
    USER_RESEARCH_SOURCE_TYPES,
    WriterAgentMixin,
    writer_user_research_policy_text,
)
from packages.business_intel import compare_run_quality
from packages.i18n.language import report_label
from packages.rag.grounded_prompt import format_retrieval_records_for_prompt
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import EnterpriseRunProjection, EvidenceRecord, ReportVersionRecord
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    ReviewThemeItem,
    ReviewThemeSummary,
    RunMetrics,
    SWOTAnalysis,
    SWOTItem,
    TraceSpan,
)
from packages.schema.rag import RetrievalRecord


class _WriterHarness(WriterAgentMixin):
    def _source_matches_competitor(self, source: RawSource, competitor: str) -> bool:
        if source.covered_competitors:
            return competitor in source.covered_competitors
        return source.competitor == competitor


def test_writer_user_research_policy_names_all_research_source_types() -> None:
    policy = writer_user_research_policy_text()

    assert "official factual proof" in policy
    for source_type in USER_RESEARCH_SOURCE_TYPES:
        assert source_type in policy


def test_compare_run_quality_scores_real_run_against_baseline() -> None:
    baseline = _run_detail(
        run_id="baseline-run",
        execution_mode="demo",
        source_count=1,
        report_md="Short demo report.",
        metrics=RunMetrics(
            source_coverage_rate=0.5,
            verified_source_rate=0.0,
            claim_citation_rate=0.5,
        ),
    )
    target = _run_detail(
        run_id="real-run",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(target, baseline=baseline)

    assert comparison.target_run_id == "real-run"
    assert comparison.baseline_run_id == "baseline-run"
    assert comparison.target_score > comparison.baseline_score
    assert comparison.delta_score is not None and comparison.delta_score > 0
    assert comparison.verdict == "pass"
    assert comparison.regression_gate_status == "pass"
    assert comparison.regression_gate_passed is True
    assert comparison.regression_gate_reasons == [
        "Quality gate passed against real-chain and baseline thresholds."
    ]
    assert comparison.real_collection_signal is True
    assert comparison.real_llm_signal is True
    assert comparison.report_quality_signal is True
    assert {check.signal: check.passed for check in comparison.signal_checks} == {
        "real_collection": True,
        "real_llm": True,
        "report_quality": True,
    }
    assert {metric.name for metric in comparison.metrics} >= {
        "real_source_rate",
        "gap_resolution_rate",
        "field_support_rate",
        "validated_claim_rate",
        "warning_count",
        "llm_call_signal",
        "claim_citation_rate",
        "citation_validity_rate",
        "report_structure_score",
        "decision_summary_section_score",
        "competitive_findings_section_score",
        "competitor_deep_dive_section_score",
        "layer_analysis_section_score",
        "core_analysis_depth_score",
        "claim_risk_section_score",
        "scenario_checklist_section_score",
        "memory_context_section_score",
        "user_research_section_score",
    }
    assert next(
        metric for metric in comparison.metrics if metric.name == "citation_validity_rate"
    ).target_value == 1.0
    assert next(
        metric for metric in comparison.metrics if metric.name == "gap_resolution_rate"
    ).target_value == 1.0
    assert next(
        metric for metric in comparison.metrics if metric.name == "validated_claim_rate"
    ).target_value == 1.0


def test_compare_run_quality_regression_gate_fails_on_core_metric_drop() -> None:
    baseline = _run_detail(
        run_id="baseline-strong-run",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    target = _run_detail(
        run_id="target-regressed-run",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=0.25,
            claim_citation_rate=1.0,
        ),
        trace_spans=baseline.trace_spans,
        source_types=[
            "web_search_result",
            "web_search_result",
            "web_search_result",
            "webpage_verified",
        ],
    )

    comparison = compare_run_quality(target, baseline=baseline)

    assert comparison.regression_gate_status == "fail"
    assert comparison.regression_gate_passed is False
    assert any("core metric regression" in reason for reason in comparison.regression_gate_reasons)


def test_compare_run_quality_regression_gate_fails_on_field_support_drop() -> None:
    baseline = _run_detail(
        run_id="baseline-field-support",
        execution_mode="real",
        source_count=2,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    baseline.plan.dimensions = ["pricing", "feature"]
    baseline.raw_sources[1].dimension = "feature"
    target = _run_detail(
        run_id="target-field-support-regressed",
        execution_mode="real",
        source_count=1,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=baseline.trace_spans,
    )
    target.plan.dimensions = ["pricing", "feature"]

    comparison = compare_run_quality(target, baseline=baseline)
    field_support = next(
        metric for metric in comparison.metrics if metric.name == "field_support_rate"
    )

    assert field_support.baseline_value == 0.5
    assert field_support.target_value == 0.25
    assert comparison.regression_gate_status == "fail"
    assert any("field_support_rate" in reason for reason in comparison.regression_gate_reasons)


def test_compare_run_quality_flags_unresolved_report_source_tokens() -> None:
    detail = _run_detail(
        run_id="invalid-citations",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md()
        .replace("source-0", "missing-0")
        .replace("source-1", "missing-1")
        .replace("source-2", "missing-2")
        .replace("source-3", "missing-3"),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metric = next(
        item for item in comparison.metrics if item.name == "citation_validity_rate"
    )

    assert metric.target_value == 0.0
    assert comparison.report_quality_signal is False
    assert comparison.verdict == "warn"
    assert any("source tokens" in item for item in comparison.recommendations)


def test_compare_run_quality_resolves_enterprise_evidence_source_tokens() -> None:
    detail = _run_detail(
        run_id="enterprise-citations",
        execution_mode="real",
        source_count=1,
        report_md=_structured_report_md().replace("source-0", "evidence-0"),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    evidence = EvidenceRecord(
        id="evidence-0",
        workspace_id="workspace-1",
        project_id="project-1",
        run_id=detail.id,
        raw_source_id="source-0",
        competitor_id="competitor-cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://example.com/source-0",
        snippet="Verified pricing evidence.",
        content_hash="hash-0",
        reliability_score=0.9,
    )
    detail.enterprise_projection = EnterpriseRunProjection(
        workspace_id="workspace-1",
        project_id="project-1",
        run_id=detail.id,
        evidence_records=[evidence],
        claim_records=[],
        report_version=ReportVersionRecord(
            id="report-1",
            workspace_id="workspace-1",
            project_id="project-1",
            run_id=detail.id,
            version_number=1,
            topic_normalized="cursor-pricing",
            competitor_layer="L1",
            competitor_set_hash="set",
            report_md=detail.report_md,
            evidence_ids=["evidence-0"],
        ),
    )

    comparison = compare_run_quality(detail)
    metric = next(
        item for item in comparison.metrics if item.name == "citation_validity_rate"
    )

    assert metric.target_value > 0.0


def test_compare_run_quality_flags_long_unstructured_report() -> None:
    detail = _run_detail(
        run_id="long-unstructured",
        execution_mode="real",
        source_count=4,
        report_md="Cursor has evidence and Copilot has evidence. [source:source-0]\n" * 80,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    structure_metric = next(
        metric for metric in comparison.metrics if metric.name == "report_structure_score"
    )

    assert structure_metric.target_value < 0.7
    assert comparison.report_quality_signal is False
    assert comparison.verdict == "warn"


def test_compare_run_quality_rejects_support_heavy_report_without_core_analysis() -> None:
    support_heavy_report = """
# Cursor vs Copilot Direct Battlecard

## Executive Summary
Cursor and Copilot are compared with citations, but this report skips the decision summary and
competitor deep dives that would turn the evidence into business guidance. [source:source-0]

## Source Quality & Coverage
The run uses verified pages for both target competitors and keeps search snippets out of final
claims. Cursor pricing is supported by a direct verified page, while Copilot evidence is cited
for comparison. [source:source-0] [source:source-1]

## Side-by-Side Decision Matrix
| Dimension | Cursor | Copilot |
| --- | --- | --- |
| Pricing | transparent pricing [source:source-0] | bundled enterprise offer [source:source-1] |
| Feature | focused agent workflow [source:source-2] | broad IDE integration [source:source-3] |

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## Battlecard
Sales should use pricing transparency as an initial talking point, but this section is only a
thin layer-specific note and does not provide competitor deep dives. [source:source-0]

## Claim Validation & Evidence Risk
No unresolved blocker claims were detected in the structured comparison, but enterprise security
and procurement recommendations remain review-gated until additional official sources are linked.
[source:source-0] [source:source-1]

## Next Collection / Verification Plan
Verify procurement and security evidence before publication. Collect official enterprise security
documentation, current procurement packaging, and buyer objection evidence for both competitors.
[source:source-2] [source:source-3]

## Evidence Appendix
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
- source-2: Cursor feature evidence [source:source-2]
- source-3: Copilot feature evidence [source:source-3]
""".strip()
    detail = _run_detail(
        run_id="support-heavy-report",
        execution_mode="real",
        source_count=4,
        report_md=support_heavy_report,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    report_check = next(
        check for check in comparison.signal_checks if check.signal == "report_quality"
    )

    assert metrics["decision_summary_section_score"].target_value == 0.0
    assert metrics["competitor_deep_dive_section_score"].target_value == 0.0
    assert metrics["core_analysis_depth_score"].target_value < 0.6
    assert comparison.report_quality_signal is False
    assert "decision_summary_section_score" in report_check.blocking_metric_names
    assert "competitor_deep_dive_section_score" in report_check.blocking_metric_names
    assert "core_analysis_depth_score" in report_check.blocking_metric_names


def test_compare_run_quality_rejects_support_heavy_report_with_thin_core_sections() -> None:
    long_support = (
        "## Evidence Appendix\n"
        + "\n".join(
            f"- source-{index}: supporting audit detail that should not outweigh "
            "the core analysis. "
            f"[source:source-{index % 4}]"
            for index in range(40)
        )
    )
    report_md = _structured_report_md()
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "decision_summary"),
        "## Decision Summary\nCursor is stronger. [source:source-0]",
    )
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "competitive_findings"),
        "## Competitive Findings\nCursor has a cited edge. [source:source-0]",
    )
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "competitor_deep_dives"),
        "## Competitor Deep Dives\nCursor is ahead. [source:source-0]",
    )
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "evidence_appendix"),
        long_support,
    )
    detail = _run_detail(
        run_id="support-heavy-thin-core",
        execution_mode="real",
        source_count=4,
        report_md=report_md,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    blockers = {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert metrics["core_section_depth_score"].target_value < 1.0
    assert metrics["core_support_balance_score"].target_value < 1.0
    assert comparison.report_quality_signal is False
    assert "core_section_depth_score" in blockers
    assert "core_support_balance_score" in blockers
    assert any("core section depth" in item for item in comparison.recommendations)


def test_compare_run_quality_accepts_substantive_core_with_concise_support() -> None:
    detail = _run_detail(
        run_id="substantive-core-concise-support",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["core_section_depth_score"].target_value == 1.0
    assert metrics["core_support_balance_score"].target_value == 1.0
    assert comparison.report_quality_signal is True


def test_compare_run_quality_blocks_duplicate_semantic_report_sections() -> None:
    report_md = (
        _structured_report_md()
        + """

## 1. Decision Summary
Duplicated decision summary text should be treated as a structural defect, not as additional
analysis depth. [source:source-0]

## 2. Source Quality & Coverage
Duplicated source quality support should be treated as a structural defect. [source:source-1]
""".rstrip()
    )
    detail = _run_detail(
        run_id="duplicate-section-run",
        execution_mode="real",
        source_count=4,
        report_md=report_md,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    duplicate_metric = next(
        (metric for metric in comparison.metrics if metric.name == "duplicate_section_count"),
        None,
    )
    report_check = next(
        check for check in comparison.signal_checks if check.signal == "report_quality"
    )

    assert duplicate_metric is not None
    assert duplicate_metric.target_value == 2.0
    assert duplicate_metric.direction == "lower_is_better"
    assert comparison.report_quality_signal is False
    assert "duplicate_section_count" in report_check.blocking_metric_names


def test_compare_run_quality_blocks_numbered_chinese_duplicate_support_sections() -> None:
    report_md = (
        _structured_report_md()
        + """

## 9. 证据与QA支撑
重复的证据与 QA 支撑应该被识别为结构缺陷。 [source:source-0]

## 证据与 QA 支撑
第二个证据支撑区块不应该绕过重复章节检测。 [source:source-1]

## 13. RAG缺口补全
- 差距 `gap-pricing`: 建议的检索查询：PC 品牌定价 官方页面。 [source:source-2]

## RAG 缺口补全
- 差距 `gap-pricing`: 建议的检索查询：PC 品牌定价 官方页面。 [source:source-3]

## 14. 场景QA清单
- 场景 QA 条目重复。 [source:source-0]

## 场景 QA 清单
- 场景 QA 条目再次重复。 [source:source-1]
""".rstrip()
    )
    detail = _run_detail(
        run_id="duplicate-chinese-section-run",
        execution_mode="real",
        source_count=4,
        report_md=report_md,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    duplicate_metric = next(
        metric for metric in comparison.metrics if metric.name == "duplicate_section_count"
    )

    assert duplicate_metric.target_value == 4.0


def test_compare_run_quality_rejects_empty_core_headings_after_appendix() -> None:
    long_report_with_late_empty_core = (
        """
# Cursor vs Copilot Battlecard

## Executive Summary
"""
        + (
            "This introductory prose is intentionally long and citation-heavy, but it does not "
            "contain the required decision-ready analysis sections before evidence support. "
            "[source:source-0]\n"
            * 12
        )
        + """
## Source Quality & Coverage
The run uses verified pages for both target competitors and keeps search snippets out of final
claims. [source:source-0] [source:source-1]

## Side-by-Side Decision Matrix
| Dimension | Cursor | Copilot |
| --- | --- | --- |
| Pricing | transparent pricing [source:source-0] | bundled offer [source:source-1] |

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## Claim Validation & Evidence Risk
No unresolved blocker claims were detected. [source:source-0] [source:source-1]

## Next Collection / Verification Plan
Verify procurement and security evidence before publication. [source:source-2]

## Evidence Appendix
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
- source-2: Cursor feature evidence [source:source-2]
- source-3: Copilot feature evidence [source:source-3]

## Decision Summary

## Competitive Findings

## Competitor Deep Dives

## Battlecard
""".strip()
    )
    detail = _run_detail(
        run_id="late-empty-core",
        execution_mode="real",
        source_count=4,
        report_md=long_report_with_late_empty_core,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.plan.competitor_layer = "L1"

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["decision_summary_section_score"].target_value == 0.0
    assert metrics["competitive_findings_section_score"].target_value == 0.0
    assert metrics["competitor_deep_dive_section_score"].target_value == 0.0
    assert metrics["layer_analysis_section_score"].target_value == 0.0
    assert metrics["core_analysis_depth_score"].target_value < 0.6
    assert comparison.report_quality_signal is False


def test_compare_run_quality_rejects_core_headings_after_support_sections() -> None:
    report_with_late_core = """
# Cursor vs Copilot Direct Comparison

## Executive Summary
The executive readout is short and leaves the actual decision analysis until after support.
[source:source-0]

## Source Quality & Coverage
The run uses verified pages for both target competitors and keeps search snippets out of final
claims. [source:source-0] [source:source-1]

## Decision Summary
Recommended action: use Cursor pricing clarity only as a qualified opening point, while treating
Copilot distribution as the procurement counter-position until security evidence is verified.
[source:source-0] [source:source-1]

## Competitive Findings
- Pricing: Cursor has clearer standalone pricing evidence for first-response messaging.
[source:source-0]
- Feature: Copilot has broader IDE integration evidence for Microsoft-oriented accounts.
[source:source-3]

## Competitor Deep Dives
- Cursor wins: pricing clarity; weaknesses: procurement proof remains incomplete; implication:
use it as the clarity-led challenger. [source:source-0] [source:source-2]
- Copilot wins: distribution; weaknesses: standalone comparison is harder; implication: treat it
as the incumbent workflow defense. [source:source-1] [source:source-3]

## Battlecard
Sales should use the pricing contrast carefully and avoid absolute winner language.
[source:source-0]

## Side-by-Side Decision Matrix
| Dimension | Cursor | Copilot |
| --- | --- | --- |
| Pricing | transparent pricing [source:source-0] | bundled offer [source:source-1] |

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## Claim Validation & Evidence Risk
No unresolved blocker claims were detected. [source:source-0] [source:source-1]

## Next Collection / Verification Plan
Verify procurement and security evidence before publication. [source:source-2]

## Evidence Appendix
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
- source-2: Cursor feature evidence [source:source-2]
- source-3: Copilot feature evidence [source:source-3]
""".strip()
    detail = _run_detail(
        run_id="late-core-after-support",
        execution_mode="real",
        source_count=4,
        report_md=report_with_late_core,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.plan.competitor_layer = "L1"

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["decision_summary_section_score"].target_value == 0.0
    assert metrics["competitive_findings_section_score"].target_value == 0.0
    assert metrics["competitor_deep_dive_section_score"].target_value == 0.0
    assert metrics["layer_analysis_section_score"].target_value == 0.0
    assert comparison.report_quality_signal is False


def test_compare_run_quality_accepts_localized_core_analysis_headings() -> None:
    zh_report = f"""
# Cursor vs Copilot L1 {report_label("zh-CN", "battlecard")}

## {report_label("zh-CN", "executive_summary")}
本报告比较 Cursor 与 Copilot 的定价清晰度和企业分发路径，并保留所有结论的来源标记。
[source:source-0] [source:source-1]

## {report_label("zh-CN", "decision_summary")}
建议先把 Cursor 的价格透明度作为 L1 战报切入点，同时把 Copilot 的捆绑分发作为采购反驳位。
在安全、SSO 和采购证据单独验证前，不发布绝对赢家判断。 [source:source-0] [source:source-1]

## {report_label("zh-CN", "competitive_findings")}
- 定价：Cursor 的独立定价证据更清晰，销售首轮回应更容易解释。 [source:source-0]
- 功能：Copilot 的 IDE 集成证据更广，在 Microsoft 账户中有稳定采用路径。 [source:source-3]
- 买方影响：应定位为价格清晰度对比工作流覆盖，而不是通用赢家判断。
[source:source-0] [source:source-3]
- 发布约束：安全、采购和 SSO 证据补齐前，只能发布有限结论和待验证风险。 [source:source-1]

## {report_label("zh-CN", "competitor_deep_dives")}
- Cursor 优势是价格透明和聚焦代理工作流；弱点是采购与企业安全证明还需验证；
影响是作为清晰度挑战者使用。
[source:source-0] [source:source-2]
- Copilot 优势是分发和 IDE 覆盖；弱点是包装不易直接比较；影响是作为既有工作流防守方处理。
[source:source-1] [source:source-3]

## {report_label("zh-CN", "battlecard")}
销售应先使用价格透明度打开对话，再用采购、安全和工作流证据限定结论边界，避免把当前证据扩大为绝对产品赢家。
面向买方沟通时，应把 Cursor 作为清晰度挑战者，把 Copilot 作为既有工作流防守方，并明确后续验证任务。
[source:source-0] [source:source-1]

## {report_label("zh-CN", "source_quality")}
来源覆盖 Cursor 和 Copilot，且最终判断只使用已验证网页证据。 [source:source-0] [source:source-1]

## {report_label("zh-CN", "side_by_side_matrix")}
| 维度 | Cursor | Copilot |
| --- | --- | --- |
| 定价 | 独立价格清晰 [source:source-0] | 企业捆绑方案 [source:source-1] |

## {report_label("zh-CN", "scenario_checklist")}
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## {report_label("zh-CN", "claim_risk")}
当前没有未解决的 blocker 声明，但安全和采购建议仍需更多官方证据。
[source:source-0] [source:source-1]

## {report_label("zh-CN", "next_collection")}
继续验证采购、安全和 SSO 证据，并在发布前重新运行声明校验。 [source:source-2]

## {report_label("zh-CN", "evidence_appendix")}
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
- source-2: Cursor feature evidence [source:source-2]
- source-3: Copilot feature evidence [source:source-3]
""".strip()
    detail = _run_detail(
        run_id="zh-core-analysis",
        execution_mode="real",
        source_count=4,
        report_md=zh_report,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.output_language = "zh-CN"
    detail.plan.competitor_layer = "L1"

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["decision_summary_section_score"].target_value == 1.0
    assert metrics["competitive_findings_section_score"].target_value == 1.0
    assert metrics["competitor_deep_dive_section_score"].target_value == 1.0
    assert metrics["layer_analysis_section_score"].target_value == 1.0
    assert metrics["core_analysis_depth_score"].target_value >= 0.6


def test_compare_run_quality_requires_l1_layer_section_not_generic_strategy() -> None:
    strategy_without_battlecard = """
# Cursor vs Copilot Battlecard

## Executive Summary
Cursor and Copilot are compared for L1 selling points, but the body omits the required battlecard
section even though the title says Battlecard. [source:source-0]

## Decision Summary
Recommended action: use Cursor pricing clarity as a qualified opening point while treating
Copilot distribution as the procurement counter-position until security evidence is verified.
[source:source-0] [source:source-1]

## Competitive Findings
- Pricing: Cursor has clearer standalone pricing evidence for first-response messaging.
[source:source-0]
- Feature: Copilot has broader IDE integration evidence for Microsoft-oriented accounts.
[source:source-3]

## Competitor Deep Dives
- Cursor wins: pricing clarity; weaknesses: procurement proof remains incomplete; implication:
use it as the clarity-led challenger. [source:source-0] [source:source-2]
- Copilot wins: distribution; weaknesses: standalone comparison is harder; implication: treat it
as the incumbent workflow defense. [source:source-1] [source:source-3]

## Strategy
This generic strategy section is useful, but it is not the selected L1 battlecard section and
should not satisfy the L1 layer gate. [source:source-0]

## Source Quality & Coverage
The run uses verified pages for both target competitors. [source:source-0] [source:source-1]

## Side-by-Side Decision Matrix
| Dimension | Cursor | Copilot |
| --- | --- | --- |
| Pricing | transparent pricing [source:source-0] | bundled offer [source:source-1] |

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## Claim Validation & Evidence Risk
No unresolved blocker claims were detected. [source:source-0] [source:source-1]

## Next Collection / Verification Plan
Verify procurement and security evidence before publication. [source:source-2]

## Evidence Appendix
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
- source-2: Cursor feature evidence [source:source-2]
- source-3: Copilot feature evidence [source:source-3]
""".strip()
    detail = _run_detail(
        run_id="l1-generic-strategy",
        execution_mode="real",
        source_count=4,
        report_md=strategy_without_battlecard,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.plan.competitor_layer = "L1"

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["layer_analysis_section_score"].target_value == 0.0
    assert comparison.report_quality_signal is False


def test_compare_run_quality_flags_missing_real_chain_signals() -> None:
    detail = _run_detail(
        run_id="weak-run",
        execution_mode="real",
        source_count=0,
        report_md="thin",
        metrics=RunMetrics(),
    )

    comparison = compare_run_quality(detail)

    assert comparison.verdict == "fail"
    assert comparison.real_collection_signal is False
    assert comparison.real_llm_signal is False
    assert comparison.report_quality_signal is False
    signal_checks = {check.signal: check for check in comparison.signal_checks}
    assert signal_checks["real_collection"].blocking_metric_names == [
        "real_source_rate",
        "verified_source_rate",
        "evidence_count",
    ]
    assert signal_checks["real_llm"].blocking_metric_names == ["llm_call_signal"]
    assert "report_length_score" in signal_checks["report_quality"].blocking_metric_names
    assert "report_structure_score" in signal_checks["report_quality"].blocking_metric_names
    assert "real webpage" in comparison.recommendations[0]
    assert all("fallback" not in item.casefold() for item in comparison.recommendations)
    assert any("analysis-first sections" in item for item in comparison.recommendations)
    assert any("core analysis" in item for item in comparison.recommendations)
    assert any("Claim Validation & Evidence Risk" in item for item in comparison.recommendations)
    assert any("Scenario QA Checklist" in item for item in comparison.recommendations)


def test_compare_run_quality_counts_official_business_sources_as_real_verified() -> None:
    detail = _run_detail(
        run_id="official-sources",
        execution_mode="real",
        source_count=2,
        report_md=_structured_report_md()
        .replace("source-2", "source-0")
        .replace("source-3", "source-1"),
        metrics=RunMetrics(llm_calls=3, claim_citation_rate=1.0),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
        source_types=["official_pricing", "trust_center"],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["verified_source_rate"].target_value == 1.0
    assert metrics["real_source_rate"].target_value == 1.0
    assert comparison.real_collection_signal is True


def test_compare_run_quality_excludes_user_research_from_factual_source_rates() -> None:
    detail = _run_detail(
        run_id="mixed-research-and-official-sources",
        execution_mode="real",
        source_count=4,
        report_md=_remove_report_section(
            _structured_report_md(), report_label("en-US", "user_research_evidence")
        ),
        metrics=RunMetrics(llm_calls=3, claim_citation_rate=1.0),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
        source_types=[
            "survey_simulated",
            "interview_record",
            "webpage_verified",
            "official_docs",
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["verified_source_rate"].target_value == 1.0
    assert metrics["real_source_rate"].target_value == 1.0
    assert metrics["user_research_section_score"].target_value == 0.0
    assert comparison.real_collection_signal is True
    assert comparison.report_quality_signal is False


def test_compare_run_quality_requires_verified_source_for_real_collection_signal() -> None:
    detail = _run_detail(
        run_id="search-only-real-run",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(llm_calls=3, claim_citation_rate=1.0),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
        source_types=["web_search_result"],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    checks = {check.signal: check for check in comparison.signal_checks}

    assert metrics["real_source_rate"].target_value == 1.0
    assert metrics["verified_source_rate"].target_value == 0.0
    assert comparison.real_collection_signal is False
    assert "verified_source_rate" in checks["real_collection"].blocking_metric_names


def test_compare_run_quality_flags_missing_memory_and_user_research_sections() -> None:
    detail = _run_detail(
        run_id="missing-memory-research",
        execution_mode="real",
        source_count=4,
        report_md=_remove_report_section(
            _structured_report_md(), report_label("en-US", "user_research_evidence")
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
        source_types=["survey_simulated", "interview_record", "webpage_verified"],
    )
    detail.plan.dimensions = ["pricing", "persona"]
    detail.plan.memory_candidate_ids = ["memory-1"]
    detail.plan.memory_prompt_context = ["Prefer buyer-objection framing."]
    detail.plan.memory_recall_score = 82

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["memory_context_section_score"].target_value == 0.0
    assert metrics["user_research_section_score"].target_value == 0.0
    assert comparison.report_quality_signal is False
    assert "memory_context_section_score" in {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }
    assert any("Memory Context" in item for item in comparison.recommendations)
    assert any("User Research Evidence" in item for item in comparison.recommendations)


def test_compare_run_quality_requires_rag_gap_fill_section_for_collector_gaps() -> None:
    detail = _run_detail(
        run_id="missing-rag-gap-fill",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.qa_findings.append(
        QCIssue(
            id="gap-security-evidence",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="security",
            target_competitor="Cursor",
            field_path="raw_sources[security][Cursor]",
            problem="Missing official security evidence.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="security",
                target_competitor="Cursor",
                rationale="Collect official security evidence.",
            ),
        )
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    blockers = {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert metrics["rag_gap_fill_section_score"].target_value == 0.0
    assert comparison.report_quality_signal is False
    assert "rag_gap_fill_section_score" in blockers
    assert any("RAG Gap Fill" in item for item in comparison.recommendations)

    detail.report_md = (
        f"{detail.report_md}\n\n"
        "## RAG Gap Fill\n"
        "- Gap gap-security-evidence: Suggested retrieval query: Cursor security SOC 2."
    )
    repaired = compare_run_quality(detail)
    repaired_metrics = {metric.name: metric for metric in repaired.metrics}

    assert repaired_metrics["rag_gap_fill_section_score"].target_value == 1.0


def test_report_quality_blocks_review_run_without_review_theme_section() -> None:
    detail = _run_detail(
        run_id="missing-review-themes",
        execution_mode="real",
        source_count=4,
        report_md=_remove_report_section(
            _structured_report_md(), report_label("en-US", "review_theme_summary")
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
        source_types=["webpage_verified", "review_site"],
    )
    detail.plan.dimensions = ["pricing", "review"]

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    blockers = {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert metrics["review_theme_section_score"].target_value == 0.0
    assert comparison.report_quality_signal is False
    assert "review_theme_section_score" in blockers
    assert any("User Review Themes" in item for item in comparison.recommendations)


def test_report_quality_blocks_without_swot_section() -> None:
    without_swot = _remove_report_section(
        _structured_report_md(), report_label("en-US", "swot_analysis")
    )
    incomplete_swot = (
        f"## {report_label('en-US', 'swot_analysis')}\n"
        "The report introduces SWOT but omits quadrant coverage. [source:source-0]"
    )
    heading_only = without_swot.replace(
        "\n\n## Battlecard",
        f"\n\n{incomplete_swot}\n\n## Battlecard",
    )
    missing_detail = _run_detail(
        run_id="missing-swot",
        execution_mode="real",
        source_count=4,
        report_md=without_swot,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    incomplete_detail = _run_detail(
        run_id="incomplete-swot",
        execution_mode="real",
        source_count=4,
        report_md=heading_only,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=missing_detail.trace_spans,
    )

    missing = compare_run_quality(missing_detail)
    incomplete = compare_run_quality(incomplete_detail)
    missing_blockers = {
        name
        for check in missing.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }
    incomplete_blockers = {
        name
        for check in incomplete.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert {metric.name: metric for metric in missing.metrics}[
        "swot_section_score"
    ].target_value == 0.0
    assert {metric.name: metric for metric in incomplete.metrics}[
        "swot_section_score"
    ].target_value == 0.5
    assert "swot_section_score" in missing_blockers
    assert "swot_section_score" in incomplete_blockers
    assert any("SWOT Analysis" in item for item in missing.recommendations)


def test_report_quality_rejects_swot_placeholder_prose() -> None:
    placeholder_swot = (
        f"## {report_label('en-US', 'swot_analysis')}\n"
        "This SWOT must include Strengths, Weaknesses, Opportunities, and Threats before "
        "publication. [source:source-0]"
    )
    detail = _run_detail(
        run_id="placeholder-swot",
        execution_mode="real",
        source_count=4,
        report_md=_replace_report_section(
            _structured_report_md(),
            report_label("en-US", "swot_analysis"),
            placeholder_swot,
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[_llm_trace_span()],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    blockers = {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert metrics["swot_section_score"].target_value == 0.5
    assert "swot_section_score" in blockers
    assert comparison.report_quality_signal is False


def test_report_quality_accepts_structured_english_swot_quadrant_rows() -> None:
    structured_swot = (
        f"## {report_label('en-US', 'swot_analysis')}\n"
        "- Strengths: Cursor pricing clarity gives sales a concrete first proof point. "
        "[source:source-0]\n"
        "- Weaknesses: Enterprise security and procurement proof remains incomplete. "
        "[source:source-2]\n"
        "- Opportunities: Buyer education can focus on standalone value and workflow speed. "
        "[source:source-0]\n"
        "- Threats: Copilot can defend through bundled Microsoft procurement paths. "
        "[source:source-1]"
    )
    detail = _run_detail(
        run_id="structured-english-swot",
        execution_mode="real",
        source_count=4,
        report_md=_replace_report_section(
            _structured_report_md(),
            report_label("en-US", "swot_analysis"),
            structured_swot,
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[_llm_trace_span()],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["swot_section_score"].target_value == 1.0
    assert comparison.report_quality_signal is True


def test_report_quality_accepts_structured_chinese_swot_quadrant_rows() -> None:
    structured_swot = (
        f"## {report_label('zh-CN', 'swot_analysis')}\n"
        "- 优势：Cursor 价格透明度让销售沟通有清晰证据。 [source:source-0]\n"
        "- 劣势：企业安全与采购证明仍需补强。 [source:source-2]\n"
        "- 机会：买方教育可以聚焦独立价值和工作流速度。 [source:source-0]\n"
        "- 威胁：Copilot 可通过微软采购路径防守。 [source:source-1]"
        "\nThe decision implication is to lead with Cursor clarity, qualify Copilot procurement "
        "defense separately, and keep enterprise readiness caveated until stronger evidence "
        "is collected. [source:source-0] [source:source-1]"
    )
    detail = _run_detail(
        run_id="structured-chinese-swot",
        execution_mode="real",
        source_count=4,
        report_md=_replace_report_section(
            _structured_report_md(),
            report_label("en-US", "swot_analysis"),
            structured_swot,
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[_llm_trace_span()],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["swot_section_score"].target_value == 1.0
    assert comparison.report_quality_signal is True


def test_report_quality_does_not_count_swot_or_review_child_headings_as_duplicates() -> None:
    nested_sections = (
        f"## {report_label('en-US', 'review_theme_summary')}\n"
        "Review themes are organized by competitor without duplicating the parent section. "
        "The decision implication is to separate explainable pricing interest from Microsoft "
        "workflow familiarity before treating either theme as a universal preference. "
        "[source:source-0]\n"
        "### Cursor Review Themes\n"
        "- Pricing clarity supports fast buyer evaluation and gives sales a concrete discovery "
        "question for direct-tool buyers. [source:source-0]\n"
        "### Copilot Review Themes\n"
        "- Existing Microsoft familiarity supports adoption, but should be tested against "
        "standalone value perception before assuming lower switching friction. "
        "[source:source-1]\n\n"
        f"## {report_label('en-US', 'swot_analysis')}\n"
        "### Cursor SWOT\n"
        "- Strengths: Cursor pricing clarity gives sales a concrete proof point. "
        "[source:source-0]\n"
        "- Weaknesses: Enterprise security and procurement proof remains incomplete. "
        "[source:source-2]\n"
        "### Copilot SWOT\n"
        "- Opportunities: Buyer education can focus on standalone value and workflow speed. "
        "[source:source-0]\n"
        "- Threats: Copilot can defend through bundled Microsoft procurement paths. "
        "[source:source-1]"
    )
    detail = _run_detail(
        run_id="nested-review-swot-headings",
        execution_mode="real",
        source_count=4,
        report_md=_replace_report_sections(
            _structured_report_md(),
            {
                report_label("en-US", "review_theme_summary"): "",
                report_label("en-US", "swot_analysis"): nested_sections,
            },
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[_llm_trace_span()],
        source_types=["webpage_verified", "review_site"],
    )
    detail.plan.dimensions = ["pricing", "review"]

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["duplicate_section_count"].target_value == 0.0
    assert metrics["review_theme_section_score"].target_value == 1.0
    assert metrics["swot_section_score"].target_value == 1.0
    assert comparison.report_quality_signal is True


def test_report_quality_accepts_review_and_swot_sections() -> None:
    detail = _run_detail(
        run_id="review-and-swot",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
        source_types=["webpage_verified", "review_site"],
    )
    detail.plan.dimensions = ["pricing", "review"]

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["review_theme_section_score"].target_value == 1.0
    assert metrics["swot_section_score"].target_value == 1.0
    assert comparison.report_quality_signal is True


def test_report_quality_does_not_require_review_section_for_non_review_run() -> None:
    detail = _run_detail(
        run_id="non-review-missing-review-themes",
        execution_mode="real",
        source_count=4,
        report_md=_remove_report_section(
            _structured_report_md(), report_label("en-US", "review_theme_summary")
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    blockers = {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert metrics["review_theme_section_score"].target_value == 1.0
    assert metrics["swot_section_score"].target_value == 1.0
    assert "review_theme_section_score" not in blockers
    assert comparison.report_quality_signal is True


def test_compare_run_quality_accepts_chinese_rag_gap_fill_section() -> None:
    detail = _run_detail(
        run_id="localized-rag-gap-fill",
        execution_mode="real",
        source_count=4,
        report_md=(
            f"{_structured_report_md()}\n\n"
            "## RAG 缺口补全\n"
            "- 差距 `gap-security-evidence`：建议的检索查询：Cursor 安全合规 官方文档。"
            " [source:source-0]\n"
        ),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.qa_findings.append(
        QCIssue(
            id="gap-security-evidence",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="security",
            target_competitor="Cursor",
            field_path="raw_sources[security][Cursor]",
            problem="Missing official security evidence.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="security",
                target_competitor="Cursor",
                rationale="Collect official security evidence.",
            ),
        )
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["rag_gap_fill_section_score"].target_value == 1.0


def _assert_headings_in_order(markdown: str, headings: list[str]) -> None:
    positions = [markdown.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_writer_fallback_puts_core_analysis_before_evidence_support() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="analysis-first-fallback",
        execution_mode="real",
        source_count=4,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    detail.plan.scenario_recommended_dimensions = ["pricing", "feature", "persona"]
    detail.plan.qa_rule_ids = ["claim_has_evidence", "source_reliability_min"]
    detail.comparison_matrix = ComparisonMatrix(
        competitors=detail.plan.competitors,
        dimensions=detail.plan.dimensions,
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Cursor has transparent standalone pricing.",
                source_ids=["source-0"],
                confidence=0.9,
            ),
            ComparisonCell(
                competitor="Cursor",
                dimension="feature",
                value="Cursor has focused agent workflow evidence.",
                source_ids=["source-2"],
                confidence=0.86,
            ),
            ComparisonCell(
                competitor="Copilot",
                dimension="pricing",
                value="Copilot is commonly evaluated through bundled enterprise packaging.",
                source_ids=["source-1"],
                confidence=0.84,
            ),
            ComparisonCell(
                competitor="Copilot",
                dimension="feature",
                value="Copilot has broad IDE integration evidence.",
                source_ids=["source-3"],
                confidence=0.88,
            ),
        ],
        winner_by_dimension={"pricing": "Cursor", "feature": "Copilot"},
    )

    report = writer._fallback_report_markdown(detail, "timeout")

    _assert_headings_in_order(
        report,
        [
            "## Executive Takeaway",
            "## Decision Summary",
            "## Competitive Findings",
            "## Competitor Deep Dives",
            "## Battlecard",
            "## Evidence & QA Support",
            "## Source Quality & Coverage",
            "## Scenario QA Checklist",
            "## Claim Validation & Evidence Risk",
            "## Next Collection / Verification Plan",
            "## Evidence Appendix",
        ],
    )
    assert "Recommended action:" in report
    assert "Do not overstate" in report
    assert "wins:" in report
    assert "weaknesses:" in report
    assert "watchouts:" in report
    assert report.index("## Evidence & QA Support") > report.index("## Battlecard")


def test_writer_hardening_inserts_review_and_swot_core_sections() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="review-swot-core-sections",
        execution_mode="real",
        source_count=4,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "review"]
    detail.comparison_matrix = ComparisonMatrix(
        competitors=detail.plan.competitors,
        dimensions=detail.plan.dimensions,
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="review",
                value="Users praise speed but need onboarding proof.",
                source_ids=["source-0"],
                confidence=0.86,
            )
        ],
        winner_by_dimension={"review": "Cursor"},
    )
    detail.competitor_knowledge["Cursor"].review_summary = ReviewThemeSummary(
        competitor="Cursor",
        dimension="review",
        praise_themes=[
            ReviewThemeItem(
                theme="Fast workflow",
                evidence="Users praise fast repository-aware editing.",
                source_ids=["source-0"],
                confidence=0.82,
            )
        ],
        complaint_themes=[
            ReviewThemeItem(
                theme="Onboarding friction",
                evidence="Users complain onboarding takes effort.",
                source_ids=["source-1"],
                confidence=0.64,
            )
        ],
        adoption_blockers=[
            ReviewThemeItem(
                theme="Security review",
                evidence="Security review slows team adoption.",
                source_ids=["source-2"],
                confidence=0.7,
            )
        ],
        switching_triggers=[
            ReviewThemeItem(
                theme="Repository context",
                evidence="Teams switch for repository context.",
                source_ids=["source-3"],
                confidence=0.78,
            )
        ],
        source_ids=["source-0", "source-1", "source-2", "source-3"],
        confidence=0.74,
    )
    detail.competitor_knowledge["Cursor"].swot_analysis = SWOTAnalysis(
        competitor="Cursor",
        strengths=[
            SWOTItem(
                text="Fast workflow is review-backed.",
                source_ids=["source-0"],
                confidence=0.82,
            )
        ],
        weaknesses=[
            SWOTItem(
                text="Onboarding evidence remains thin.",
                evidence_gap=True,
            )
        ],
        opportunities=[
            SWOTItem(
                text="Repository context can motivate switching.",
                source_ids=["source-3"],
                confidence=0.78,
            )
        ],
        threats=[
            SWOTItem(
                text="Procurement proof needs more cited evidence.",
                evidence_gap=True,
            )
        ],
        source_ids=["source-0", "source-3"],
        confidence=0.74,
    )
    markdown = """
# Cursor vs Copilot

## Competitive Findings
Cursor has a review-backed workflow signal. [source:source-0]

## Battlecard
Layer analysis exists before hardening. [source:source-0]

## Source Quality & Coverage
Source coverage exists. [source:source-0]
""".strip()

    report = writer._ensure_report_required_sections(detail, markdown)

    review_heading = f"## {report_label('en-US', 'review_theme_summary')}"
    swot_heading = f"## {report_label('en-US', 'swot_analysis')}"
    layer_heading = f"## {report_label('en-US', 'battlecard')}"
    assert f"## {report_label('zh-CN', 'review_theme_summary')}" == "## 用户评价整理"
    assert f"## {report_label('zh-CN', 'swot_analysis')}" == "## SWOT 分析"
    _assert_headings_in_order(
        report,
        [
            "## Competitive Findings",
            review_heading,
            "## Competitor Deep Dives",
            swot_heading,
            layer_heading,
        ],
    )
    assert "Fast workflow" in report
    assert "Onboarding friction" in report
    assert "Repository context" in report
    assert "- Strengths: Fast workflow is review-backed." in report
    assert "- Weaknesses: Onboarding evidence remains thin. Evidence gap." in report
    assert "- Opportunities: Repository context can motivate switching." in report
    assert "- Threats: Procurement proof needs more cited evidence. Evidence gap." in report


def test_writer_hardening_inserts_review_gap_without_review_evidence() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="review-gap-core-section",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    markdown = """
# Cursor vs Copilot

## Competitive Findings
Pricing and feature evidence exists. [source:source-0]

## Competitor Deep Dives
Cursor and Copilot have cited deep dives. [source:source-1]

## Battlecard
Layer analysis exists. [source:source-0]
""".strip()

    report = writer._ensure_report_required_sections(detail, markdown)

    review_heading = f"## {report_label('en-US', 'review_theme_summary')}"
    swot_heading = f"## {report_label('en-US', 'swot_analysis')}"
    _assert_headings_in_order(
        report,
        [
            "## Competitive Findings",
            review_heading,
            "## Competitor Deep Dives",
            swot_heading,
            "## Battlecard",
        ],
    )
    review_body = report[
        report.index(review_heading) : report.index("## Competitor Deep Dives")
    ]
    assert "Evidence gap" in review_body


def test_writer_hardening_does_not_cite_explicit_swot_gap_lines() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="swot-gap-lines-uncited",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    markdown = """
# Cursor vs Copilot

## Competitive Findings
Pricing and feature evidence exists. [source:source-0]

## Competitor Deep Dives
Cursor and Copilot have cited deep dives. [source:source-1]

## Battlecard
Layer analysis exists. [source:source-0]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)

    swot_heading = f"## {report_label('en-US', 'swot_analysis')}"
    layer_heading = f"## {report_label('en-US', 'battlecard')}"
    swot_body = report[report.index(swot_heading) : report.index(layer_heading)]
    gap_lines = [
        line
        for line in swot_body.splitlines()
        if "Evidence gap" in line or "no cited SWOT" in line
    ]
    assert gap_lines
    assert all("[source:" not in line for line in gap_lines)


def test_writer_hardening_generates_chinese_review_and_swot_headings() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="zh-review-swot-headings",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "zh-CN"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]

    report = writer._ensure_report_required_sections(
        detail,
        "# Cursor vs Copilot\n\n## 竞争发现\n已有竞争发现。[source:source-0]",
    )

    assert "## 用户评价整理" in report
    assert "## SWOT 分析" in report
    assert "优势" in report
    assert "劣势" in report
    assert "机会" in report
    assert "威胁" in report
    assert "证据缺口（Evidence gap）" in report


def test_writer_fallback_keeps_layer_specific_report_floor() -> None:
    writer = _WriterHarness()
    expected_sections = {
        "L1": ("## Battlecard", "Objection handling"),
        "L2": ("## Workflow & Enterprise Risk", "switching-cost exposure"),
        "L3": ("## Market Landscape", "Category view"),
    }
    scenario_ids = {
        "L1": "l1_pricing_pack",
        "L2": "l2_adjacent_workflow",
        "L3": "l3_market_landscape",
    }

    for layer, (section, phrase) in expected_sections.items():
        detail = _run_detail(
            run_id=f"fallback-{layer}",
            execution_mode="real",
            source_count=3,
            report_md="",
            metrics=RunMetrics(),
        )
        detail.output_language = "en-US"
        detail.plan.competitor_layer = layer  # type: ignore[assignment]
        detail.plan.scenario_id = scenario_ids[layer]
        detail.plan.dimensions = ["pricing", "feature"]
        detail.plan.scenario_recommended_dimensions = ["pricing", "feature", "persona"]
        detail.plan.qa_rule_ids = ["claim_has_evidence", "source_reliability_min"]
        detail.comparison_matrix = ComparisonMatrix(
            competitors=detail.plan.competitors,
            dimensions=detail.plan.dimensions,
            cells=[
                ComparisonCell(
                    competitor="Cursor",
                    dimension="pricing",
                    value="Cursor has transparent pricing.",
                    source_ids=["source-0"],
                    confidence=0.9,
                ),
                ComparisonCell(
                    competitor="Copilot",
                    dimension="feature",
                    value="Copilot has broad IDE integration.",
                    source_ids=["source-1"],
                    confidence=0.85,
                ),
            ],
            winner_by_dimension={"pricing": "Cursor", "feature": "Copilot"},
        )

        report = writer._fallback_report_markdown(detail, "timeout")

        assert section in report
        assert "fallback" not in report.casefold()
        assert phrase in report
        assert "## Executive Takeaway" in report
        assert "## Decision Summary" in report
        assert "## Competitive Findings" in report
        assert "## Competitor Deep Dives" in report
        assert "## Evidence & QA Support" in report
        assert "## Scenario QA Checklist" in report
        assert "Analyst question:" in report
        assert "Evidence requirement:" in report
        assert "claim_has_evidence" in report
        assert "## Source Quality & Coverage" in report
        assert "## Claim Validation & Evidence Risk" in report
        assert "## Next Collection / Verification Plan" in report
        assert "## Evidence Appendix" in report
        assert "## Generation Notes" in report
        assert "Internal reason: timeout" in report
        assert "[source:source-0]" in report
        assert "[source:source-1]" in report


def test_writer_hardens_thin_success_report_without_fallback_labels() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="thin-success",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]

    report = writer._harden_report_markdown(
        detail,
        "# Cursor vs Copilot\n\nCursor has a clearer pricing position than Copilot.",
    )

    assert "## Battlecard" in report
    assert "fallback" not in report.casefold()
    assert "## Executive Takeaway" in report
    assert "## Decision Summary" in report
    assert "## Competitive Findings" in report
    assert "## Competitor Deep Dives" in report
    assert "## Evidence & QA Support" in report
    assert "## Source Quality & Coverage" in report
    assert "## Claim Validation & Evidence Risk" in report
    assert "## Next Collection / Verification Plan" in report
    assert "## Evidence Appendix" in report
    assert "Cursor has a clearer pricing position than Copilot. [source:source-0]" in report


def test_writer_hardening_inserts_missing_core_sections_before_support_sections() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="thin-analysis-first-hardening",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]

    report = writer._harden_report_markdown(
        detail,
        "# Cursor vs Copilot\n\nCursor has a clearer pricing position than Copilot.",
    )

    _assert_headings_in_order(
        report,
        [
            "## Executive Takeaway",
            "## Decision Summary",
            "## Competitive Findings",
            "## Competitor Deep Dives",
            "## Battlecard",
            "## Evidence & QA Support",
            "## Source Quality & Coverage",
            "## Scenario QA Checklist",
            "## Claim Validation & Evidence Risk",
            "## Next Collection / Verification Plan",
            "## Evidence Appendix",
        ],
    )
    assert "Recommended action:" in report
    assert "Do not overstate" in report
    assert "wins:" in report
    assert "weaknesses:" in report
    assert "watchouts:" in report
    assert "Cursor has a clearer pricing position than Copilot. [source:source-0]" in report


def test_writer_hardening_repairs_chinese_mojibake_before_quality_checks() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="zh-mojibake",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "zh-CN"
    detail.plan.competitor_layer = "L1"

    report = writer._harden_report_markdown(
        detail,
        """
# AI Coding Agent L1 ææ¥

## æ§è¡æè¦
Cursor å®ä»·ä¿¡æ¯å¯ç¨äºç´æ¥ææ¥ã [source:source-0]

## æ¨ªåå³ç­ç©éµ
| ç«å | å®ä»·æ ¸å¿ä¿¡æ¯ |
| --- | --- |
| Cursor | å·²éªè¯ã [source:source-0] |
""".strip(),
    )

    assert "执行摘要" in report
    assert "横向决策矩阵" in report
    assert "竞品" in report
    assert "定价核心信息" in report
    assert "æ" not in report
    assert "ç" not in report


def test_writer_hardens_report_with_claim_validation_risk_section() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="claim-risk-section",
        execution_mode="real",
        source_count=1,
        report_md="",
        metrics=RunMetrics(),
        source_types=["web_search_result"],
    )
    detail.output_language = "en-US"
    detail.raw_sources[0].confidence = 0.52
    detail.competitor_knowledge["Cursor"].pricing_model.notes = [
        KnowledgeClaim(
            claim="Cursor is the recommended enterprise-ready security choice.",
            source_ids=["source-0"],
            confidence=0.52,
        )
    ]
    detail.qa_findings.append(
        QCIssue(
            id="qa-weak-security",
            severity="warn",
            detected_by="coverage",
            target_agent="writer",
            field_path="report.security",
            problem="Security recommendation is based on search-only evidence.",
            redo_scope=RedoScope(kind="writer_only", rationale="tighten security caveat"),
        )
    )
    detail.reflections.append(
        ReflectionRecord(
            iteration=1,
            coverage_gaps=["Missing official trust-center evidence for Copilot."],
        )
    )

    report = writer._harden_report_markdown(
        detail,
        "# Cursor vs Copilot\n\nCursor is recommended for enterprise security.",
    )

    assert "## Claim Validation & Evidence Risk" in report
    assert "confidence 0.52" in report
    assert "weak source mix" in report
    assert "needs triangulation" in report
    assert "QA warn `qa-weak-security`" in report
    assert "Missing official trust-center evidence" in report
    assert "[source:source-0]" in report


def test_writer_hardens_report_with_rag_gap_fill_context() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="rag-gap-fill-section",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitors = ["Cursor", "Copilot"]
    detail.qa_findings.append(
        QCIssue(
            id="gap-security-evidence",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="security",
            target_competitor="Cursor",
            field_path="raw_sources[security][Cursor]",
            problem="Missing official trust-center evidence for security claims.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="security",
                target_competitor="Cursor",
                rationale="Collect official security evidence.",
            ),
        )
    )

    report = writer._harden_report_markdown(
        detail,
        "# Cursor vs Copilot\n\nSecurity evidence needs follow-up.",
    )

    assert "## RAG Gap Fill" in report
    assert "gap-security-evidence" in report
    assert "Suggested retrieval query: Cursor security Missing official trust-center" in report
    assert "Run the Evidence Gap Fill action" in report
    assert "[source:source-0]" in report


def test_writer_grounding_prompt_lists_allowed_sources_and_gap_queries() -> None:
    import asyncio
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="writer-grounding-contract",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
        source_types=["webpage_verified", "survey_simulated", "web_search_result"],
    )
    detail.raw_sources[2].confidence = 0.61
    detail.qa_findings.append(
        QCIssue(
            id="gap-security-evidence",
            severity="blocker",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="security",
            target_competitor="Cursor",
            field_path="raw_sources[security][Cursor]",
            problem="Missing official security evidence.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="security",
                target_competitor="Cursor",
                rationale="Collect official security evidence.",
            ),
        )
    )

    prompt = asyncio.run(writer._writer_grounding_prompt(detail))

    assert "Grounded evidence contract" in prompt
    assert "[source:source-0]" in prompt
    assert "directional_user_research" in prompt
    assert "lead_not_proof" in prompt
    assert "low_confidence" in prompt
    assert "gap=gap-security-evidence" in prompt
    assert "suggested_query=Cursor security Missing official security evidence." in prompt


def test_retrieval_prompt_preserves_chunk_level_source_tokens() -> None:
    prompt = format_retrieval_records_for_prompt(
        [
            RetrievalRecord(
                evidence_id="evidence-security-1",
                chunk_id="chunk-1",
                chunk_index=2,
                score=0.82,
                vector_score=0.7,
                bm25_score=3.5,
                rerank_score=0.82,
                title="Cursor trust center",
                source_type="webpage_verified",
                dimension="security",
                snippet="Cursor documents SOC 2 and SSO controls for enterprise buyers.",
                source_url="https://example.com/trust",
            )
        ]
    )

    assert "[source:evidence-security-1#chunk:2]" in prompt
    assert "dimension=security" in prompt
    assert "hybrid=0.82" in prompt
    assert "rerank=0.82" in prompt


def test_writer_hardens_report_with_memory_and_user_research_sections() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="memory-user-research",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
        source_types=["survey_simulated", "interview_record", "webpage_verified"],
    )
    detail.output_language = "en-US"
    detail.plan.dimensions = ["pricing", "persona"]
    detail.plan.memory_candidate_ids = ["memory-battlecard-1"]
    detail.plan.memory_recall_score = 86
    detail.plan.memory_prompt_context = [
        "Prefer concise battlecard tables with buyer objections.",
        "[domain fact; weight=0.76] Enterprise buyers compare category benchmarks.",
        "Always separate user research from official evidence.",
    ]

    report = writer._harden_report_markdown(
        detail,
        "# Cursor vs Copilot\n\nCursor is preferred by developer teams.",
    )

    assert "## Memory Context" in report
    assert "memory-battlecard-1" in report
    assert "Guidance: Prefer concise battlecard tables" in report
    assert "Domain fact: [domain fact; weight=0.76]" in report
    assert "still needs current evidence" in report
    assert "## User Research Evidence" in report
    assert "directional buyer or user signals" in report
    assert "Survey, interview, and manual-note inputs" in report
    assert "[source:source-0]" in report
    assert "[source:source-1]" in report


def test_writer_hardening_orders_conditional_support_before_later_appendices() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="memory-user-research-support-order",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
        source_types=["survey_simulated", "interview_record", "webpage_verified"],
    )
    detail.output_language = "en-US"
    detail.plan.dimensions = ["pricing", "persona"]
    detail.plan.memory_candidate_ids = ["memory-battlecard-1"]
    detail.plan.memory_recall_score = 86
    detail.plan.memory_prompt_context = [
        "Prefer concise battlecard tables with buyer objections.",
        "[domain fact; weight=0.76] Enterprise buyers compare category benchmarks.",
        "Always separate user research from official evidence.",
    ]

    report = writer._harden_report_markdown(
        detail,
        writer._fallback_report_markdown(detail, "timeout"),
    )

    _assert_headings_in_order(
        report,
        [
            "## Evidence & QA Support",
            "## Source Quality & Coverage",
            "## Memory Context",
            "## User Research Evidence",
            "## Scenario QA Checklist",
            "## Claim Validation & Evidence Risk",
            "## Next Collection / Verification Plan",
            "## Evidence Appendix",
            "## Generation Notes",
        ],
    )


def test_writer_hardening_reorders_existing_core_sections_before_support() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="misordered-existing-sections",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    markdown = """
# Cursor vs Copilot

## Executive Summary
Executive readout already exists. [source:source-0]

## Source Quality & Coverage
Source quality was written too early. [source:source-0]

## Decision Summary
Original decision body should survive. [source:source-0]

## Competitive Findings
Original competitive finding should survive. [source:source-1]

## Competitor Deep Dives
Original deep dive should survive. [source:source-1]

## Battlecard
Original battlecard should survive. [source:source-2]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)

    _assert_headings_in_order(
        report,
        [
            "## Executive Summary",
            "## Decision Summary",
            "## Competitive Findings",
            "## Competitor Deep Dives",
            "## Battlecard",
            "## Evidence & QA Support",
            "## Source Quality & Coverage",
            "## Claim Validation & Evidence Risk",
            "## Next Collection / Verification Plan",
            "## Evidence Appendix",
        ],
    )
    assert "Original decision body should survive." in report
    assert report.count("## Decision Summary") == 1
    assert report.count("## Source Quality & Coverage") == 1


def test_writer_hardening_keeps_unknown_analysis_sections_before_support() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="unknown-analysis-section",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    markdown = """
# Cursor vs Copilot

## Executive Summary
Executive readout already exists. [source:source-0]

## Decision Summary
Original decision body should survive. [source:source-0]

## Strategic Recommendations
Keep the launch response focused on pricing proof points. [source:source-1]

## Competitive Findings
Original competitive finding should survive. [source:source-1]

## Competitor Deep Dives
Original deep dive should survive. [source:source-1]

## Battlecard
Original battlecard should survive. [source:source-2]

## Source Quality & Coverage
Source quality was written after analysis. [source:source-0]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)

    assert "## Strategic Recommendations" in report
    assert "Keep the launch response focused on pricing proof points." in report
    assert (
        report.index("## Battlecard")
        < report.index("## Strategic Recommendations")
        < report.index("## Evidence & QA Support")
        < report.index("## Source Quality & Coverage")
        < report.index("## Evidence Appendix")
    )


def test_writer_hardening_uses_localized_support_headings_once_for_zh_cn() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="zh-localized-support-headings",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
        source_types=["survey_simulated", "interview_record", "webpage_verified"],
    )
    detail.output_language = "zh-CN"
    detail.plan.dimensions = ["pricing", "persona"]
    detail.plan.memory_candidate_ids = ["memory-battlecard-1"]
    detail.plan.memory_recall_score = 86
    detail.plan.memory_prompt_context = [
        "Prefer concise battlecard tables with buyer objections.",
        "[domain fact; weight=0.76] Enterprise buyers compare category benchmarks.",
    ]
    detail.qa_findings.append(
        QCIssue(
            id="gap-persona-evidence",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="persona",
            target_competitor="Cursor",
            field_path="raw_sources[persona][Cursor]",
            problem="Missing verified persona evidence.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="persona",
                target_competitor="Cursor",
                rationale="Collect verified persona evidence.",
            ),
        )
    )

    report = writer._harden_report_markdown(
        detail,
        writer._fallback_report_markdown(detail, "timeout"),
    )

    for key in [
        "memory_context",
        "user_research_evidence",
        "rag_gap_fill",
        "claim_risk",
    ]:
        assert report.count(f"## {report_label(detail.output_language, key)}") == 1
    assert "## Memory Context" not in report
    assert "## User Research Evidence" not in report
    assert "## RAG Gap Fill" not in report
    assert "## Claim Validation & Evidence Risk" not in report


def test_writer_hardening_recognizes_compact_chinese_support_headings() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="zh-compact-support-headings",
        execution_mode="real",
        source_count=4,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "zh-CN"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    detail.qa_findings.append(
        QCIssue(
            id="gap-pricing-evidence",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="pricing",
            target_competitor="Cursor",
            field_path="raw_sources[pricing][Cursor]",
            problem="Missing official pricing evidence.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="pricing",
                target_competitor="Cursor",
                rationale="Collect official pricing evidence.",
            ),
        )
    )
    markdown = """
# Cursor vs Copilot

## 1. 执行摘要
核心判断已经存在。 [source:source-0]

## 2. 决策摘要
建议先围绕定价透明度组织战报。 [source:source-0]

## 3. 竞争发现
- Cursor 在定价表达上更清晰。 [source:source-0]

## 4. 竞品深挖
Cursor 与 Copilot 的优劣势已经覆盖。 [source:source-0] [source:source-1]

## 5. 战报
销售响应应保持在已验证证据范围内。 [source:source-0]

## 9. 证据与QA支撑
证据支撑父区块已经存在。 [source:source-0]

## 13. RAG缺口补全
- 差距 `gap-pricing-evidence`：建议的检索查询：Cursor 定价 官方页面。 [source:source-1]

## 14. 场景QA清单
- 场景：l1_pricing_pack。 [source:source-2]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)

    assert "## 证据与 QA 支撑" not in report
    assert "## RAG 缺口补全" not in report
    assert "## 场景 QA 清单" not in report


def test_writer_hardening_treats_english_headings_as_zh_cn_aliases() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="zh-english-heading-aliases",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
        source_types=["survey_simulated", "interview_record", "webpage_verified"],
    )
    detail.output_language = "zh-CN"
    detail.plan.dimensions = ["pricing", "persona"]
    detail.plan.memory_candidate_ids = ["memory-battlecard-1"]
    detail.plan.memory_recall_score = 86
    detail.plan.memory_prompt_context = ["Prefer concise battlecard tables."]
    detail.qa_findings.append(
        QCIssue(
            id="gap-persona-evidence",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="persona",
            target_competitor="Cursor",
            field_path="raw_sources[persona][Cursor]",
            problem="Missing verified persona evidence.",
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="persona",
                target_competitor="Cursor",
                rationale="Collect verified persona evidence.",
            ),
        )
    )
    markdown = """
# Cursor vs Copilot

## Source Quality & Coverage
Original English source body. [source:source-0]

## Memory Context
Original English memory body. [source:source-0]

## User Research Evidence
Original English user research body. [source:source-1]

## RAG Gap Fill
Original English RAG body. [source:source-0]

## Claim Validation & Evidence Risk
Original English claim-risk body. [source:source-0]

## Next Collection / Verification Plan
Original English next-collection body. [source:source-0]

## Evidence Appendix
- source-0: Existing appendix row. [source:source-0]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)

    semantic_heading_pairs = {
        "memory_context": "Memory Context",
        "user_research_evidence": "User Research Evidence",
        "rag_gap_fill": "RAG Gap Fill",
        "claim_risk": "Claim Validation & Evidence Risk",
    }
    for key, english_heading in semantic_heading_pairs.items():
        zh_heading = report_label("zh-CN", key)
        assert report.count(f"## {english_heading}") + report.count(f"## {zh_heading}") == 1
    assert "Original English memory body." in report
    assert "Original English user research body." in report
    assert "Original English RAG body." in report
    assert "Original English claim-risk body." in report


def test_writer_hardening_keeps_nested_subsections_with_parent_section() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="nested-decision-subsection",
        execution_mode="real",
        source_count=3,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    markdown = """
# Cursor vs Copilot

## Source Quality & Coverage
Source quality was written too early. [source:source-0]

## Decision Summary
Original decision body should survive. [source:source-0]

### Rationale
Nested rationale should stay attached to decision summary. [source:source-1]

## Competitive Findings
Competitive finding follows the nested rationale. [source:source-1]

## Competitor Deep Dives
Deep dive body. [source:source-1]

## Battlecard
Battlecard body. [source:source-2]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)

    assert (
        report.index("## Decision Summary")
        < report.index("### Rationale")
        < report.index("## Competitive Findings")
    )
    assert "Nested rationale should stay attached to decision summary." in report


def test_writer_hardening_treats_numbered_headings_as_existing_sections() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="numbered-headings",
        execution_mode="real",
        source_count=4,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.output_language = "en-US"
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]
    markdown = """
# Cursor vs Copilot

## 1. Executive Takeaway
The executive decision is already present. [source:source-0]

## 2. Decision Summary
Recommended action: keep the L1 message focused on pricing clarity while preserving procurement
caveats for security and bundling. [source:source-0] [source:source-1]

## 3. Competitive Findings
- Cursor has pricing transparency evidence. [source:source-0]
- Copilot has distribution evidence. [source:source-1]

## 4. Competitor Deep Dives
Cursor wins on transparent pricing but needs deeper security validation. Copilot wins on bundled
distribution but is harder to compare directly. [source:source-0] [source:source-1]

## 5. Direct Battlecard
Use pricing clarity as the first sales response and keep bundled distribution as the objection
handling path. [source:source-0] [source:source-1]

## 6. Evidence & QA Support
Evidence support is already present. [source:source-0]

### 7. Source Quality & Coverage
Source quality is already present. [source:source-0] [source:source-1]

### 8. Scenario QA Checklist
- Scenario: l1_pricing_pack
- QA rules: claim_has_evidence, source_reliability_min

### 9. Claim Validation & Evidence Risk
No unresolved blocker claims are asserted as final proof. [source:source-0]

### 10. Next Collection / Verification Plan
Collect procurement and security proof before publication. [source:source-2]

### 11. Evidence Appendix
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
""".strip()

    report = writer._harden_report_markdown(detail, markdown)
    headings = [
        match.group(1).strip()
        for match in re.finditer(r"^\s*#{2,3}\s+(.+?)\s*$", report, flags=re.MULTILINE)
    ]

    for expected in [
        "Executive Takeaway",
        "Decision Summary",
        "Competitive Findings",
        "Competitor Deep Dives",
        "Battlecard",
        "Evidence & QA Support",
        "Source Quality & Coverage",
        "Scenario QA Checklist",
        "Claim Validation & Evidence Risk",
        "Next Collection / Verification Plan",
        "Evidence Appendix",
    ]:
        assert sum(expected in heading for heading in headings) == 1
    assert "This report is structured as decision analysis first" not in report
    assert "## Battlecard" not in report
    assert "## Source Quality & Coverage" not in report


def test_writer_repairs_dimension_named_source_tokens() -> None:
    writer = _WriterHarness()
    detail = _run_detail(
        run_id="dimension-source-token",
        execution_mode="real",
        source_count=2,
        report_md="",
        metrics=RunMetrics(),
    )
    detail.raw_sources[0].dimension = "pricing"
    detail.raw_sources[1].dimension = "feature"

    report = writer._harden_report_markdown(
        detail,
        """
# Cursor vs Copilot

## Executive Summary
Pricing is material. [source:pricing]
Feature parity is still under review. [source:feature]
Already valid. [source:source-0]
""".strip(),
    )

    assert "[source:pricing]" not in report
    assert "[source:feature]" not in report
    assert "Pricing is material. [source:source-0]" in report
    assert "Feature parity is still under review. [source:source-1]" in report
    assert "Already valid. [source:source-0]" in report


def test_compare_run_quality_exposes_normalized_metric_score_for_deductions() -> None:
    detail = _run_detail(
        run_id="quality-blocker-run",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.qa_findings.append(
        QCIssue(
            id="release-gate-blocker",
            severity="blocker",
            detected_by="coverage",
            target_agent="collector",
            field_path="release_gate",
            problem="Release gate blocker.",
            redo_scope=RedoScope(kind="collector", rationale="Collect stronger evidence."),
        )
    )

    comparison = compare_run_quality(detail)
    qa_metric = next(metric for metric in comparison.metrics if metric.name == "qa_blocker_count")
    report_check = next(
        check for check in comparison.signal_checks if check.signal == "report_quality"
    )

    assert comparison.target_score < 100
    assert comparison.report_quality_signal is False
    assert comparison.verdict == "warn"
    assert comparison.regression_gate_status == "fail"
    assert "qa_blocker_count" in report_check.blocking_metric_names
    assert qa_metric.target_value == 1.0
    assert qa_metric.target_normalized_score == 0.6667
    assert qa_metric.direction == "lower_is_better"


def test_compare_run_quality_deduplicates_release_gate_warning_count() -> None:
    detail = _run_detail(
        run_id="quality-warning-run",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )
    detail.qa_findings.extend(
        [
            QCIssue(
                id="collector-warning",
                severity="warn",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="persona",
                target_competitor="Cursor",
                field_path="raw_sources[0]",
                problem="Persona evidence is incomplete.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="persona",
                    target_competitor="Cursor",
                    rationale="Collect stronger persona evidence.",
                ),
            ),
            QCIssue(
                id="release-gate-run-qa-warning",
                severity="warn",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="persona",
                target_competitor="Cursor",
                field_path="release_gate.run_qa_findings_unresolved",
                problem="Original QA finding is unresolved.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="persona",
                    target_competitor="Cursor",
                    rationale="Run scoped redo for the original QA finding.",
                ),
            ),
            QCIssue(
                id="release-gate-claim-warning",
                severity="warn",
                detected_by="schema",
                target_agent="analyst",
                target_subagent="feature",
                target_competitor="Cursor",
                field_path="release_gate.claim_self_consistency_required",
                problem="Claim validation is weak.",
                redo_scope=RedoScope(
                    kind="analyst",
                    target_subagent="feature",
                    target_competitor="Cursor",
                    rationale="Rewrite weak claim.",
                ),
            ),
        ]
    )
    detail.enterprise_projection = EnterpriseRunProjection(
        workspace_id="workspace-1",
        project_id="project-1",
        run_id=detail.id,
        evidence_records=[],
        claim_records=[],
        report_version=ReportVersionRecord(
            id="report-1",
            workspace_id="workspace-1",
            project_id="project-1",
            run_id=detail.id,
            version_number=1,
            topic_normalized="cursor-pricing",
            competitor_layer="L1",
            competitor_set_hash="set",
            report_md=detail.report_md,
            evidence_ids=[],
            quality_metadata={
                "release_gate": {
                    "warn_count": 2,
                    "issues": [
                        {
                            "id": "release-gate-run-qa-warning",
                            "severity": "warn",
                            "rule_id": "run_qa_findings_unresolved",
                        },
                        {
                            "id": "release-gate-claim-warning",
                            "severity": "warn",
                            "rule_id": "claim_self_consistency_required",
                        },
                    ],
                }
            },
        ),
    )

    comparison = compare_run_quality(detail)
    warning_metric = next(
        metric for metric in comparison.metrics if metric.name == "warning_count"
    )

    assert warning_metric.target_value == 2.0


def _remove_report_section(markdown: str, heading: str) -> str:
    return re.sub(
        rf"\n\n## {re.escape(heading)}\n.*?(?=\n\n## |\Z)",
        "",
        markdown,
        flags=re.DOTALL,
    )


def _replace_report_section(markdown: str, heading: str, replacement: str) -> str:
    return re.sub(
        rf"\n\n## {re.escape(heading)}\n.*?(?=\n\n## |\Z)",
        f"\n\n{replacement}",
        markdown,
        flags=re.DOTALL,
    )


def _replace_report_sections(markdown: str, replacements: dict[str, str]) -> str:
    updated = markdown
    for heading, replacement in replacements.items():
        if replacement:
            updated = _replace_report_section(updated, heading, replacement)
        else:
            updated = _remove_report_section(updated, heading)
    return updated


def _llm_trace_span() -> TraceSpan:
    return TraceSpan(
        id="span-llm-1",
        kind="llm",
        agent="writer",
        name="real writer",
        status="ok",
        model="deepseek/deepseek-v4-pro",
        provider="openrouter",
        duration_ms=120,
    )


def _structured_report_md() -> str:
    return """
# Cursor vs Copilot Direct Battlecard

## Executive Summary
Cursor has stronger pricing transparency, while Copilot has integration breadth.
[source:source-0] [source:source-1]

## Decision Summary
Recommended action: use Cursor's pricing transparency as the initial L1 battlecard point, while
keeping Copilot's bundled distribution as the procurement counter-position. Do not publish an
absolute winner claim until security, SSO, and procurement evidence are separately verified.
Immediate next move: run the buyer conversation with Cursor as the clarity-led challenger and
Copilot as the bundled incumbent, then collect procurement proof for whichever path the account
prefers before turning the recommendation into a deployment decision.
[source:source-0] [source:source-1]

## Competitive Findings
- Pricing: Cursor has clearer standalone pricing evidence, which makes the first sales response
easier to explain. [source:source-0]
- Feature: Copilot has broad IDE integration evidence, which gives it a defensible adoption path
inside Microsoft-oriented accounts. [source:source-3]
- Buyer implication: The comparison should be framed as pricing clarity versus bundled workflow
reach, not as a universal product winner. [source:source-0] [source:source-3]
- Decision guardrail: if the buyer values explainable standalone spend, Cursor gets the first
proof point; if the buyer values Microsoft adjacency, Copilot needs a separate total-cost
comparison before the analyst calls the account winnable. [source:source-0] [source:source-1]

## Competitor Deep Dives
- Cursor wins: pricing transparency and focused agent workflow; weaknesses: procurement and
enterprise security proof still need official validation; watchouts: avoid claiming enterprise
readiness until trust-center evidence is linked; implication: use it as the clarity-led challenger.
[source:source-0] [source:source-2]
- Copilot wins: distribution and IDE breadth; weaknesses: packaging can be harder to compare
directly; watchouts: separate bundled value from standalone feature parity; implication: treat it
as the incumbent workflow defense. [source:source-1] [source:source-3]

## User Review Themes
User review themes show Cursor is easier to explain during procurement, while Copilot benefits
from existing Microsoft workflow familiarity. [source:source-0] [source:source-1]
- Customer theme: pricing clarity supports fast evaluation. [source:source-0]
- Adoption blocker: security review and procurement packaging still need deeper evidence.
[source:source-2]
- Switching trigger: teams that need a visible standalone buying path can treat Cursor as easier
to trial, while teams already standardized on Microsoft need proof that incremental workflow
speed outweighs procurement simplicity. [source:source-0] [source:source-1]

## SWOT Analysis
- Strengths: Cursor has pricing clarity that sales can explain quickly. [source:source-0]
- Weaknesses: Enterprise procurement proof remains incomplete. [source:source-2]
- Opportunities: Buyer education can focus on standalone value and workflow speed.
[source:source-0]
- Threats: Copilot can defend through Microsoft distribution and bundled procurement.
[source:source-1]

## Battlecard
Sales should use pricing transparency and switching objections as the first battlecard line.
[source:source-0]
The battlecard should avoid absolute winner language until security, SSO, and procurement evidence
are independently verified. Cursor is easier to explain on standalone pricing, while Copilot can
defend through bundled distribution and existing Microsoft procurement paths.
[source:source-0] [source:source-1]
The practical talk track is to lead with a verified pricing contrast, ask whether the buyer wants
a standalone workflow change or a Microsoft-adjacent default, and escalate only the unresolved
security and procurement proof as follow-up work. [source:source-0] [source:source-2]

## Side-by-Side Decision Matrix
| Dimension | Cursor | Copilot |
| --- | --- | --- |
| Pricing | transparent pricing [source:source-0] | bundled enterprise offer [source:source-1] |
| Feature | focused agent workflow [source:source-2] | broad IDE integration [source:source-3] |
| Persona | direct evaluation [source:source-0] | workflow defense [source:source-1] |

## Source Quality & Coverage
The run uses verified pages for both target competitors. [source:source-0] [source:source-1]
The source set separates verified webpages from lower-confidence leads, so the recommendation
does not treat search snippets as final proof. Cursor pricing is supported by a direct verified
page, while Copilot evidence is treated as adequate for comparison but still needs procurement
review before publication. [source:source-0] [source:source-1]

## User Research Evidence
Review and buyer-feedback inputs are treated as directional demand evidence, not official factual
proof. [source:source-0] [source:source-1]

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## Claim Validation & Evidence Risk
No unresolved blocker claims were detected in the structured comparison, but enterprise security
and procurement recommendations remain review-gated until additional official sources are linked.
[source:source-0] [source:source-1]

## Next Collection / Verification Plan
Verify procurement and security evidence before publication. [source:source-2]
Collect official enterprise security documentation, current procurement packaging, and buyer
objection evidence for both competitors. Re-run claim validation after those sources are linked
to the pricing and feature claims. [source:source-2] [source:source-3]

## Evidence Appendix
- source-0: Cursor pricing [source:source-0]
- source-1: Copilot pricing [source:source-1]
- source-2: Cursor feature evidence [source:source-2]
- source-3: Copilot feature evidence [source:source-3]
""".strip()


def _run_detail(
    *,
    run_id: str,
    execution_mode: str,
    source_count: int,
    report_md: str,
    metrics: RunMetrics,
    trace_spans: list[TraceSpan] | None = None,
    source_types: list[str] | None = None,
) -> RunDetail:
    sources = [
        RawSource(
            id=f"source-{index}",
            competitor="Cursor" if index % 2 == 0 else "Copilot",
            dimension="pricing",
            source_type=(source_types or ["webpage_verified"])[
                index % len(source_types or ["webpage_verified"])
            ],
            title=f"Source {index}",
            url=f"https://example.com/source-{index}",
            snippet="Verified pricing evidence.",
            content_hash=f"hash-{index}",
            confidence=0.9,
        )
        for index in range(source_count)
    ]
    return RunDetail(
        id=run_id,
        workspace_id="workspace-1",
        topic="Cursor vs Copilot pricing",
        status="completed",
        execution_mode=execution_mode,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="Cursor vs Copilot pricing",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing"],
        ),
        report_md=report_md,
        raw_sources=sources,
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                pricing_model=PricingModel(
                    notes=[
                        KnowledgeClaim(
                            claim="Cursor publishes pricing.",
                            source_ids=[source.id for source in sources[:1]] or ["missing"],
                            confidence=0.9,
                        )
                    ]
                ),
            )
        },
        trace_spans=trace_spans or [],
        metrics=metrics,
    )
