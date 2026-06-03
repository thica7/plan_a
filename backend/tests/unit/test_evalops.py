from datetime import datetime

from fastapi.testclient import TestClient

from app.deps import get_run_service
from app.main import create_app
from packages.evals import build_enterprise_evalops_report
from packages.schema.api_dto import RunDetail, RunSummary
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
    RedoScope,
    RevisionRecord,
    RunMetrics,
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
    }
    assert all(step.pass_rate == 1.0 for step in report.quality_chain_steps)
    assert report.golden_set_size == 13
    assert report.golden_set_pass_rate >= 0.8
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
    assert any(case.case_id == "golden.scenario_checklist" for case in report.cases)
    assert any(case.case_id == "golden.compliance" for case in report.cases)
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
    assert report.task_time_saved_hours > 0
    assert report.time_savings_rate > 0.9
    assert report.regression_gate_status == "pass"


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
    assert response.json()["judge_mode"] == "llm"
    assert response.json()["judge_avg_score"] >= 72
    assert response.json()["llm_judge_avg_score"] is None
    assert "deterministic rubric" in response.json()["judge_fallback_reason"]
    assert response.json()["real_quality_chain_failed_run_ids"] == []
    assert len(response.json()["quality_chain_steps"]) == 3
    assert response.json()["golden_set_size"] == 13
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
    assert response.json()["time_savings_rate"] > 0.9
    assert response.json()["regression_gate_status"] in {"pass", "warn", "fail"}


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
        project_id=project_id,
        topic="Cursor vs Copilot pricing",
        status=status,
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
        if execution_mode == "real"
        else [],
        revisions=revisions or [],
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
