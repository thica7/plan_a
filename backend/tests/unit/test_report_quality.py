from datetime import datetime

from packages.business_intel import compare_run_quality
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
    RunMetrics,
    TraceSpan,
)


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
