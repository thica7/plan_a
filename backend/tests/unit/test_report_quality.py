from datetime import datetime

from packages.agents.writer.logic import (
    USER_RESEARCH_SOURCE_TYPES,
    WriterAgentMixin,
    writer_user_research_policy_text,
)
from packages.business_intel import compare_run_quality
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
    RunMetrics,
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
        "llm_call_signal",
        "claim_citation_rate",
        "citation_validity_rate",
        "report_structure_score",
        "claim_risk_section_score",
        "scenario_checklist_section_score",
        "memory_context_section_score",
        "user_research_section_score",
    }
    assert next(
        metric for metric in comparison.metrics if metric.name == "citation_validity_rate"
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
    assert len(comparison.recommendations) == 5
    assert "real webpage" in comparison.recommendations[0]
    assert all("fallback" not in item.casefold() for item in comparison.recommendations)
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
    detail.plan.competitor_layer = "L1"
    detail.plan.dimensions = ["pricing", "feature"]

    report = writer._harden_report_markdown(
        detail,
        "# Cursor vs Copilot\n\nCursor has a clearer pricing position than Copilot.",
    )

    assert "## Battlecard" in report
    assert "fallback" not in report.casefold()
    assert "## Source Quality & Coverage" in report
    assert "## Claim Validation & Evidence Risk" in report
    assert "## Next Collection / Verification Plan" in report
    assert "## Evidence Appendix" in report
    assert "Cursor has a clearer pricing position than Copilot. [source:source-0]" in report


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

    prompt = writer._writer_grounding_prompt(detail)

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


def _structured_report_md() -> str:
    return """
# Cursor vs Copilot Direct Battlecard

## Executive Summary
Cursor has stronger pricing transparency, while Copilot has integration breadth.
[source:source-0] [source:source-1]

## Source Quality & Coverage
The run uses verified pages for both target competitors. [source:source-0] [source:source-1]
The source set separates verified webpages from lower-confidence leads, so the recommendation
does not treat search snippets as final proof. Cursor pricing is supported by a direct verified
page, while Copilot evidence is treated as adequate for comparison but still needs procurement
review before publication. [source:source-0] [source:source-1]

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
Sales should use pricing transparency and switching objections as the first battlecard line.
[source:source-0]
The battlecard should avoid absolute winner language until security, SSO, and procurement evidence
are independently verified. Cursor is easier to explain on standalone pricing, while Copilot can
defend through bundled distribution and existing Microsoft procurement paths.
[source:source-0] [source:source-1]

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
