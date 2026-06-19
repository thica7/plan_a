from __future__ import annotations

from packages.agents.writer.assembler import StructuredReportAssembler
from test_writer_structured_renderer import _report


def test_structured_assembler_accepts_complete_report_and_emits_coverage_telemetry() -> None:
    report = _report("zh-CN")
    result = StructuredReportAssembler().assemble(
        report=report,
        expected_competitors=["Cursor", "Windsurf"],
    )

    assert result.report is report
    assert result.telemetry["missing_deep_dive_competitors"] == ["Windsurf"]
    assert result.telemetry["duplicate_deep_dive_competitors"] == []
    assert result.telemetry["missing_battlecard_competitors"] == ["Cursor"]


def test_structured_assembler_reports_duplicate_deep_dives() -> None:
    report = _report("zh-CN")
    first = report.core.competitor_deep_dives[0]
    report.core.competitor_deep_dives.append(first.model_copy())

    result = StructuredReportAssembler().assemble(
        report=report,
        expected_competitors=["Cursor", "Windsurf"],
    )

    assert result.telemetry["duplicate_deep_dive_competitors"] == ["Cursor"]
