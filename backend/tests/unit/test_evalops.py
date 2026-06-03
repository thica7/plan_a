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
        report_md="Decision-grade report with citations. " * 90,
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

    report = build_enterprise_evalops_report([target], baseline=baseline)

    assert report.run_count == 1
    assert report.baseline_run_id == "baseline-run"
    assert report.real_run_count == 1
    assert report.demo_run_count == 0
    assert report.real_run_ratio == 1.0
    assert report.real_quality_chain_rate == 1.0
    assert report.average_delta_score is not None and report.average_delta_score > 0
    assert report.regressed_run_count == 0
    assert report.human_correction_rate == 0.25
    assert report.redo_iteration_count == 1
    assert report.redo_convergence_ratio == 0.25
    assert report.golden_set_size == 6
    assert report.golden_set_pass_rate >= 0.8
    assert report.report_quality_score >= 72
    assert report.source_recall >= 0.6
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
        report_md="Decision-grade report with citations. " * 90,
        project_id="project-a",
    )
    service = _FakeRunService([target])
    app = create_app()
    app.dependency_overrides[get_run_service] = lambda: service
    client = TestClient(app)

    response = client.get("/api/evals/enterprise", params={"project_id": "project-a"})

    assert response.status_code == 200
    assert response.json()["evaluated_run_ids"] == ["real-run"]
    assert response.json()["real_run_count"] == 1
    assert response.json()["real_quality_chain_rate"] == 1.0
    assert response.json()["golden_set_size"] == 6
    assert response.json()["manual_baseline_hours_per_report"] == 6.0
    assert response.json()["time_savings_rate"] > 0.9
    assert response.json()["regression_gate_status"] in {"pass", "warn", "fail"}


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


def _run_detail(
    *,
    run_id: str,
    execution_mode: str,
    source_count: int,
    quality_score: float,
    report_md: str,
    project_id: str = "project-a",
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
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
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
            human_override_rate=human_override_rate,
            revision_count=len(revisions or []),
        ),
    )
