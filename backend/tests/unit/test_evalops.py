from datetime import datetime

from fastapi.testclient import TestClient

from app.deps import get_run_service
from app.main import create_app
from packages.evals import build_enterprise_evalops_report
from packages.schema.api_dto import RunDetail, RunSummary
from packages.schema.models import (
    AgentMessage,
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    QCIssue,
    RawSource,
    RedoScope,
    RevisionRecord,
    RunMetrics,
    ToolCallMessage,
    TraceSpan,
)


def test_enterprise_evalops_report_scores_golden_set_and_regression_gate() -> None:
    baseline = _run_detail(
        run_id="baseline-run",
        execution_mode="demo",
        source_count=1,
        quality_score=0.4,
        report_md="Short baseline.",
    )
    target = _run_detail(
        run_id="real-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
        human_override_rate=0.25,
        revisions=[
            RevisionRecord(
                id="rev-1",
                iteration=1,
                stage="collector",
                redo_scopes=[
                    RedoScope(
                        kind="collector",
                        target_subagent="security",
                        rationale="Security evidence gap needs refreshed collection.",
                    )
                ],
                issue_count_before=4,
                issue_count_after=1,
                convergence_ratio=0.25,
            )
        ],
    )
    interrupted = _run_detail(
        run_id="interrupted-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md="",
        project_id="project-a",
        status="interrupted",
    )

    report = build_enterprise_evalops_report([interrupted, target], baseline=baseline)

    assert report.run_count == 1
    assert report.evaluated_run_ids == ["real-run"]
    assert report.baseline_run_id == "baseline-run"
    assert report.real_run_count == 1
    assert report.demo_run_count == 0
    assert report.real_run_ratio == 1.0
    assert report.real_quality_chain_rate == 1.0
    assert report.decision_replay_rate == 1.0
    assert report.decision_replay_failed_run_ids == []
    assert report.average_delta_score is not None and report.average_delta_score > 0
    assert report.regressed_run_count == 0
    assert report.judge_mode == "heuristic"
    assert report.judge_avg_score >= 72
    assert report.llm_judge_avg_score is None
    assert report.judge_fallback_reason == ""
    assert report.human_correction_rate == 0.25
    assert report.redo_iteration_count == 1
    assert report.redo_convergence_ratio == 0.25
    assert report.real_quality_chain_failed_run_ids == []
    assert {step.step for step in report.quality_chain_steps} == {
        "real_collection",
        "real_llm",
        "report_quality",
        "decision_replay",
    }
    assert all(step.pass_rate == 1.0 for step in report.quality_chain_steps)
    assert report.golden_set_size == 17
    assert report.golden_set_pass_rate >= 0.8
    assert report.golden_catalog_size >= 50
    assert report.golden_catalog_coverage_rate == 0.0
    assert {cohort.cohort for cohort in report.golden_catalog_cohorts} >= {
        "core_l1",
        "core_l2",
        "core_l3",
        "observability",
        "pydantic_ai",
        "temporal_cutover",
    }
    assert report.report_quality_score >= 72
    assert report.source_recall >= 0.6
    assert report.compliance_pass_rate == 1.0
    assert report.compliance_fail_count == 0
    assert report.compliance_blocker_count == 0
    assert any(
        metric.name == "schema_pass_rate" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(
        metric.name == "citation_validity_rate" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(case.case_id == "golden.citation_validity" for case in report.cases)
    assert any(
        metric.name == "coverage_lift_rate" and metric.status == "pass"
        for metric in report.metrics
    )
    assert report.coverage_lift_rate is not None and report.coverage_lift_rate > 0
    assert any(case.case_id == "golden.schema_pass" for case in report.cases)
    assert any(
        metric.name == "report_structure_score" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(
        metric.name == "claim_risk_section_score" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(case.case_id == "golden.claim_risk_section" for case in report.cases)
    assert any(
        metric.name == "scenario_checklist_section_score" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(
        metric.name == "memory_context_section_score" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(
        metric.name == "user_research_section_score" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(case.case_id == "golden.scenario_checklist" for case in report.cases)
    assert any(case.case_id == "golden.compliance" for case in report.cases)
    assert any(case.case_id == "golden.user_research_evidence" for case in report.cases)
    assert any(case.case_id == "golden.rag_gap_fill_context" for case in report.cases)
    assert any(case.case_id == "golden.hitl_redo_loop" for case in report.cases)
    assert any(case.case_id == "golden.decision_replay" for case in report.cases)
    assert any(
        metric.name == "compliance_pass_rate" and metric.status == "pass"
        for metric in report.metrics
    )
    assert any(
        metric.name == "judge_avg_score" and metric.status == "pass"
        for metric in report.metrics
    )
    assert report.manual_baseline_hours_per_report == 6.0
    assert report.manual_baseline_hours == 6.0
    assert report.automation_runtime_hours > 0
    assert report.manual_time_saved_hours == report.task_time_saved_hours
    assert report.task_time_saved_hours > 0
    assert report.time_savings_rate > 0.9
    assert report.regression_gate_status == "pass"
    assert report.regression_gate_issues == []


def test_enterprise_evalops_router_exposes_report() -> None:
    target = _run_detail(
        run_id="real-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
    )
    service = _FakeRunService([target])
    app = create_app()
    app.dependency_overrides[get_run_service] = lambda: service
    client = TestClient(app)

    response = client.get(
        "/api/evals/enterprise",
        params={"project_id": "project-a", "judge_mode": "llm"},
    )

    assert response.status_code == 200
    assert response.json()["evaluated_run_ids"] == ["real-run"]
    assert response.json()["real_run_count"] == 1
    assert response.json()["real_quality_chain_rate"] == 1.0
    assert response.json()["decision_replay_rate"] == 1.0
    assert response.json()["judge_mode"] == "llm"
    assert response.json()["judge_avg_score"] >= 72
    assert response.json()["llm_judge_avg_score"] is None
    assert "deterministic rubric" in response.json()["judge_fallback_reason"]
    assert response.json()["real_quality_chain_failed_run_ids"] == []
    assert response.json()["decision_replay_failed_run_ids"] == []
    assert len(response.json()["quality_chain_steps"]) == 4
    assert response.json()["golden_set_size"] == 17
    assert response.json()["golden_catalog_size"] >= 50
    assert response.json()["compliance_pass_rate"] == 1.0
    assert response.json()["compliance_fail_count"] == 0
    assert any(
        metric["name"] == "schema_pass_rate" and metric["status"] == "pass"
        for metric in response.json()["metrics"]
    )
    assert any(
        metric["name"] == "citation_validity_rate" and metric["status"] == "pass"
        for metric in response.json()["metrics"]
    )
    assert any(
        metric["name"] == "report_structure_score" and metric["status"] == "pass"
        for metric in response.json()["metrics"]
    )
    assert any(
        metric["name"] == "claim_risk_section_score" and metric["status"] == "pass"
        for metric in response.json()["metrics"]
    )
    assert any(
        metric["name"] == "scenario_checklist_section_score" and metric["status"] == "pass"
        for metric in response.json()["metrics"]
    )
    assert any(
        metric["name"] == "compliance_pass_rate" and metric["status"] == "pass"
        for metric in response.json()["metrics"]
    )
    assert response.json()["manual_baseline_hours_per_report"] == 6.0
    assert response.json()["manual_time_saved_hours"] == response.json()["task_time_saved_hours"]
    assert response.json()["time_savings_rate"] > 0.9
    assert response.json()["regression_gate_status"] in {"pass", "warn", "fail"}
    assert response.json()["regression_gate_issues"] == []


def test_enterprise_evalops_measures_citation_validity_separately_from_density() -> None:
    target = _run_detail(
        run_id="real-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md()
        .replace("source-0", "missing-0")
        .replace("source-1", "missing-1")
        .replace("source-2", "missing-2")
        .replace("source-3", "missing-3"),
        project_id="project-a",
    )

    report = build_enterprise_evalops_report([target])
    metrics = {metric.name: metric for metric in report.metrics}
    cases = {case.case_id: case for case in report.cases}

    assert metrics["claim_citation_rate"].value == 1.0
    assert metrics["claim_citation_rate"].status == "pass"
    assert metrics["citation_validity_rate"].value == 0.0
    assert metrics["citation_validity_rate"].status == "fail"
    assert cases["golden.citation_validity"].status == "fail"
    assert any("unresolved report source tokens" in item for item in report.recommendations)


def test_enterprise_evalops_maps_runs_to_golden_catalog_cohorts() -> None:
    target = _run_detail(
        run_id="gold-001-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
        topic="AI coding assistant pricing comparison",
        competitors=["Cursor", "GitHub Copilot"],
        competitor_layer="L1",
        dimensions=["pricing"],
    )

    report = build_enterprise_evalops_report([target])
    cohorts = {cohort.cohort: cohort for cohort in report.golden_catalog_cohorts}

    assert report.golden_catalog_size >= 50
    assert report.golden_catalog_covered_case_count == 1
    assert report.golden_catalog_coverage_rate > 0
    assert cohorts["core_l1"].matched_run_count == 1
    assert "L1" in cohorts["core_l1"].expected_layers


def test_enterprise_evalops_golden_catalog_requires_layer_and_dimensions() -> None:
    wrong_layer = _run_detail(
        run_id="gold-001-wrong-layer",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
        topic="AI coding assistant pricing comparison",
        competitors=["Cursor", "GitHub Copilot"],
        competitor_layer="L3",
        dimensions=["pricing"],
    )
    missing_dimension = _run_detail(
        run_id="gold-001-missing-dimension",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
        topic="AI coding assistant pricing comparison",
        competitors=["Cursor", "GitHub Copilot"],
        competitor_layer="L1",
        dimensions=["feature"],
    )

    report = build_enterprise_evalops_report([wrong_layer, missing_dimension])
    cohorts = {cohort.cohort: cohort for cohort in report.golden_catalog_cohorts}

    assert report.golden_catalog_covered_case_count == 0
    assert report.golden_catalog_coverage_rate == 0.0
    assert cohorts["core_l1"].matched_run_count == 0


def test_enterprise_evalops_fails_regression_gate_on_compliance_blockers() -> None:
    target = _run_detail(
        run_id="real-run-with-pii",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=f"{_structured_report_md()}\n\nContact buyer@example.com for procurement.",
        project_id="project-a",
    )

    report = build_enterprise_evalops_report([target])
    metrics = {metric.name: metric for metric in report.metrics}
    cases = {case.case_id: case for case in report.cases}

    assert report.compliance_pass_rate == 0.0
    assert report.compliance_fail_count == 1
    assert report.compliance_blocker_count >= 1
    assert metrics["compliance_pass_rate"].status == "fail"
    assert metrics["compliance_fail_count"].status == "fail"
    assert cases["golden.compliance"].status == "fail"
    assert report.regression_gate_status == "fail"
    assert any(
        issue.kind == "metric" and issue.id == "compliance_pass_rate"
        for issue in report.regression_gate_issues
    )
    assert any(
        issue.kind == "case" and issue.id == "golden.compliance"
        for issue in report.regression_gate_issues
    )
    assert any("compliance blockers" in item for item in report.recommendations)


def test_enterprise_evalops_explains_real_quality_chain_failures() -> None:
    target = _run_detail(
        run_id="weak-real-run",
        execution_mode="real",
        source_count=1,
        quality_score=0.2,
        report_md="Short real run draft.",
        project_id="project-a",
    )

    report = build_enterprise_evalops_report([target])
    steps = {step.step: step for step in report.quality_chain_steps}
    cases = {case.case_id: case for case in report.cases}

    assert report.real_quality_chain_rate == 0.0
    assert report.real_quality_chain_failed_run_ids == ["weak-real-run"]
    assert steps["real_collection"].pass_rate == 0.0
    assert steps["real_collection"].failed_run_ids == ["weak-real-run"]
    assert steps["real_llm"].pass_rate == 1.0
    assert steps["real_llm"].failed_run_ids == []
    assert steps["report_quality"].pass_rate == 0.0
    assert steps["report_quality"].failed_run_ids == ["weak-real-run"]
    assert cases["golden.real_quality_chain"].status == "fail"
    assert any(
        issue.kind == "comparison" and issue.id == "weak-real-run"
        for issue in report.regression_gate_issues
    )
    assert any(
        issue.kind == "case" and issue.id == "golden.real_quality_chain"
        for issue in report.regression_gate_issues
    )


def test_enterprise_evalops_gates_missing_decision_replay_signals() -> None:
    target = _run_detail(
        run_id="missing-replay-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
        include_decision_replay=False,
    )

    report = build_enterprise_evalops_report([target])
    metrics = {metric.name: metric for metric in report.metrics}
    cases = {case.case_id: case for case in report.cases}
    steps = {step.step: step for step in report.quality_chain_steps}

    assert report.real_quality_chain_rate == 1.0
    assert report.decision_replay_rate == 0.0
    assert report.decision_replay_failed_run_ids == ["missing-replay-run"]
    assert steps["decision_replay"].pass_rate == 0.0
    assert steps["decision_replay"].failed_run_ids == ["missing-replay-run"]
    assert metrics["decision_replay_rate"].status == "fail"
    assert cases["golden.decision_replay"].status == "fail"
    assert report.regression_gate_status == "fail"
    assert any(
        issue.kind == "metric" and issue.id == "decision_replay_rate"
        for issue in report.regression_gate_issues
    )
    assert any("decisions can be replayed" in item for item in report.recommendations)


def test_enterprise_evalops_flags_missing_research_and_gap_fill_context() -> None:
    target = _run_detail(
        run_id="persona-gap-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=_structured_report_md(),
        project_id="project-a",
        dimensions=["persona"],
        qa_findings=[
            QCIssue(
                id="missing-persona-survey",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="persona",
                target_competitor="Cursor",
                field_path="raw_sources[persona][Cursor]",
                problem="Persona evidence needs user research and RAG gap fill.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="persona",
                    target_competitor="Cursor",
                    rationale="Collect persona user research.",
                ),
            )
        ],
    )

    report = build_enterprise_evalops_report([target])
    cases = {case.case_id: case for case in report.cases}

    assert cases["golden.user_research_evidence"].status == "fail"
    assert cases["golden.rag_gap_fill_context"].status == "fail"
    assert cases["golden.hitl_redo_loop"].status == "fail"
    assert {
        issue.id for issue in report.regression_gate_issues if issue.kind == "case"
    }.issuperset(
        {
            "golden.user_research_evidence",
            "golden.rag_gap_fill_context",
            "golden.hitl_redo_loop",
        }
    )


def test_enterprise_evalops_accepts_reported_rag_gap_fill_context() -> None:
    target = _run_detail(
        run_id="reported-gap-fill-run",
        execution_mode="real",
        source_count=4,
        quality_score=1.0,
        report_md=(
            f"{_structured_report_md()}\n\n"
            "## RAG Gap Fill\n\n"
            "- Gap `missing-security`: retrieve official security evidence for Cursor. "
            "[source:source-0]\n"
        ),
        project_id="project-a",
        qa_findings=[
            QCIssue(
                id="missing-security",
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
        ],
    )

    report = build_enterprise_evalops_report([target])
    cases = {case.case_id: case for case in report.cases}

    assert cases["golden.rag_gap_fill_context"].status == "pass"


class _FakeRunService:
    def __init__(self, runs: list[RunDetail]) -> None:
        self._runs = {run.id: run for run in runs}

    def list_runs(self) -> list[RunSummary]:
        return [
            RunSummary(
                id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                topic=run.topic,
                status=run.status,
                execution_mode=run.execution_mode,
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
            for run in self._runs.values()
        ]

    def get_run(self, run_id: str) -> RunDetail | None:
        return self._runs.get(run_id)


def _structured_report_md() -> str:
    return """
# Cursor vs Copilot Direct Battlecard

## Executive Summary
Cursor has clearer standalone pricing evidence, while Copilot benefits from broader enterprise
distribution. The recommendation is evidence-backed but still requires security and procurement
verification before publication. [source:source-0] [source:source-1]

## Source Quality & Coverage
The report uses verified webpages for both competitors and separates direct evidence from
remaining validation tasks. Cursor pricing and Copilot pricing are both represented in scoped
sources, and the confidence profile is strong enough for a draft release gate review.
[source:source-0] [source:source-1]

## Side-by-Side Decision Matrix
| Dimension | Cursor | Copilot |
| --- | --- | --- |
| Pricing | clear price [source:source-0] | bundled path [source:source-1] |
| Feature | focused AI workflow [source:source-2] | broad IDE ecosystem [source:source-3] |

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.
- Analyst question: Which plan gates drive perceived value?
- Evidence requirement: Pricing rows require official pricing-page evidence.
- QA rules: claim_has_evidence, source_reliability_min

## Battlecard
Sales should lead with pricing clarity, workflow focus, and switching objections. The battlecard
should avoid absolute claims until enterprise security controls, procurement packaging, and buyer
risk evidence are verified. [source:source-0] [source:source-2]

## Claim Validation & Evidence Risk
Structured claims are cited and no blocker claim-validation risk is open for this draft. Security
and procurement claims remain caveated until official enterprise evidence is collected.
[source:source-0] [source:source-1]

## Next Collection / Verification Plan
Collect official security, SSO, procurement, and current packaging evidence for both competitors.
Then rerun claim validation and release gate review before marking the report publishable.
[source:source-2] [source:source-3]

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
    quality_score: float,
    report_md: str,
    project_id: str = "project-a",
    status: str = "completed",
    human_override_rate: float = 0.0,
    revisions: list[RevisionRecord] | None = None,
    dimensions: list[str] | None = None,
    qa_findings: list[QCIssue] | None = None,
    topic: str = "Cursor vs Copilot pricing",
    competitors: list[str] | None = None,
    competitor_layer: str = "L1",
    include_decision_replay: bool = True,
) -> RunDetail:
    plan_competitors = competitors or ["Cursor", "Copilot"]
    sources = [
        RawSource(
            id=f"source-{index}",
            competitor=plan_competitors[index % len(plan_competitors)],
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
        project_id=project_id,
        topic=topic,
        status=status,
        execution_mode=execution_mode,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic=topic,
            competitors=plan_competitors,
            dimensions=dimensions or ["pricing"],
            competitor_layer=competitor_layer,  # type: ignore[arg-type]
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
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                trace_id="trace-llm-1",
                otel_span_id="span-llm-1",
                traceparent="00-00000000000000000000000000000001-0000000000000001-01",
                kind="llm",
                agent="writer",
                name="writer",
                status="ok",
                provider="openrouter",
                duration_ms=250,
            )
        ]
        if execution_mode == "real" and include_decision_replay
        else [],
        agent_messages=[
            AgentMessage(
                id="msg-plan-1",
                run_id=run_id,
                from_agent="planner",
                to_agent="collector",
                message_type="analysis_plan_ready",
                payload_schema="AnalysisPlan",
                payload={"dimensions": dimensions or ["pricing"]},
                trace_span_ids=["span-llm-1"],
                status="consumed",
                consumed_by="collector",
                consumed_at=datetime.utcnow(),
            ),
            AgentMessage(
                id="msg-report-1",
                run_id=run_id,
                from_agent="writer",
                to_agent="qa",
                message_type="report_ready",
                payload_schema="ReportDraft",
                payload={"source_ids": [source.id for source in sources]},
                trace_span_ids=["span-llm-1"],
                status="queued",
            ),
        ]
        if execution_mode == "real" and include_decision_replay
        else [],
        tool_call_messages=[
            ToolCallMessage(
                id="tool-search-1",
                run_id=run_id,
                agent="collector",
                tool_name="web_search",
                arguments={"query": topic},
                result={"source_ids": [source.id for source in sources]},
                status="ok",
                trace_span_id="span-llm-1",
                source_message_id="msg-plan-1",
            )
        ]
        if execution_mode == "real" and include_decision_replay
        else [],
        revisions=revisions or [],
        qa_findings=qa_findings or [],
        metrics=RunMetrics(
            total_duration_ms=90_000,
            cost_estimate_usd=0.42,
            llm_calls=3 if execution_mode == "real" else 0,
            source_coverage_rate=quality_score,
            verified_source_rate=quality_score,
            claim_citation_rate=quality_score,
            schema_pass_rate=1.0,
            human_override_rate=human_override_rate,
            revision_count=len(revisions or []),
        ),
    )
