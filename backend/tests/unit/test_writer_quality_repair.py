from __future__ import annotations

from packages.agents.writer.quality_gate import WriterQualityGate
from packages.agents.writer.repair_planner import WriterRepairPlanner
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RunMetrics


def _detail(report_md: str = "") -> RunDetail:
    return RunDetail(
        id="run-writer-quality-repair",
        topic="AI coding agent",
        status="running",
        execution_mode="demo",
        created_at="2026-06-20T00:00:00",
        updated_at="2026-06-20T00:00:00",
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Acme"],
            dimensions=["pricing"],
        ),
        metrics=RunMetrics(
            llm_calls=1,
            source_coverage_rate=1.0,
            claim_citation_rate=1.0,
        ),
        report_md=report_md,
    )


def test_quality_gate_returns_named_metrics_and_reasons() -> None:
    result = WriterQualityGate().assemble_repair_gate(
        _detail(),
        "## Decision Summary\nThin report.",
    )

    assert "quality_gate_passed" in result
    assert isinstance(result["quality_gate_reasons"], list)
    assert isinstance(result["quality_gate_metrics"], dict)


def test_repair_planner_replaces_sections_without_exposing_repair_module() -> None:
    planner = WriterRepairPlanner()
    markdown = (
        "## Decision Summary\n"
        "Old decision.\n\n"
        "## Evidence Appendix\n"
        "Keep appendix."
    )

    result = planner.replace_section(
        markdown,
        "decision_summary",
        "en-US",
        "## Decision Summary\nNew decision [source:pricing-1].",
    )

    assert "New decision [source:pricing-1]." in result
    assert "Old decision." not in result
    assert "## Evidence Appendix" in result


def test_repair_planner_detects_protectable_report_without_issues() -> None:
    planner = WriterRepairPlanner()
    plan = planner.plan(
        _detail("## Decision Summary\nExisting report [source:pricing-1]."),
        [],
        upstream_data_changed=True,
    )

    assert plan.mode in {"section", "full"}
    assert plan.reason
