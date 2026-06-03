from datetime import datetime

from packages.agents.writer.logic import WriterAgentMixin
from packages.business_intel import compare_run_quality
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
    RunMetrics,
    TraceSpan,
)


class _WriterHarness(WriterAgentMixin):
    pass


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
        report_md="Real report with evidence. " * 90,
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
    assert comparison.real_collection_signal is True
    assert comparison.real_llm_signal is True
    assert comparison.report_quality_signal is True
    assert {metric.name for metric in comparison.metrics} >= {
        "real_source_rate",
        "llm_call_signal",
        "claim_citation_rate",
    }


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
    assert len(comparison.recommendations) == 3
    assert "real webpage" in comparison.recommendations[0]


def test_writer_fallback_keeps_layer_specific_report_floor() -> None:
    writer = _WriterHarness()
    expected_sections = {
        "L1": ("## Battlecard Fallback", "Objection handling"),
        "L2": ("## Workflow & Enterprise Risk Fallback", "switching-cost exposure"),
        "L3": ("## Market Landscape Fallback", "Category view"),
    }

    for layer, (section, phrase) in expected_sections.items():
        detail = _run_detail(
            run_id=f"fallback-{layer}",
            execution_mode="real",
            source_count=3,
            report_md="",
            metrics=RunMetrics(),
        )
        detail.plan.competitor_layer = layer  # type: ignore[assignment]
        detail.plan.dimensions = ["pricing", "feature"]
        detail.plan.scenario_recommended_dimensions = ["pricing", "feature", "persona"]
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
        assert phrase in report
        assert "## Source Quality & Coverage" in report
        assert "## Next Collection / Verification Plan" in report
        assert "## Evidence Appendix" in report
        assert "[source:source-0]" in report
        assert "[source:source-1]" in report


def _run_detail(
    *,
    run_id: str,
    execution_mode: str,
    source_count: int,
    report_md: str,
    metrics: RunMetrics,
    trace_spans: list[TraceSpan] | None = None,
) -> RunDetail:
    sources = [
        RawSource(
            id=f"source-{index}",
            competitor="Cursor" if index % 2 == 0 else "Copilot",
            dimension="pricing",
            source_type="webpage_verified",
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
