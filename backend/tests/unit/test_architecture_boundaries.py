from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_temporal_competitive_intel_shell_invokes_langgraph_activity() -> None:
    text = _read("packages/workflows/competitive_intel.py")

    assert "CREATE_RUN_ACTIVITY" in text
    assert "RUN_LANGGRAPH_ACTIVITY" in text
    assert "LOAD_PROJECTION_ACTIVITY" in text
    assert "build_real_analysis_graph" not in text
    assert "build_demo_analysis_graph" not in text
    assert "build_scoped_redo_graph" not in text


def test_runtime_command_layer_owns_create_run_orchestration_boundary() -> None:
    runs_text = _read("app/routers/runs.py")
    command_text = _read("packages/runtime/service.py")

    assert "runtime.create_run" in runs_text
    assert "decide_temporal_cutover" not in runs_text
    assert "start_competitive_intel" not in runs_text
    assert "self._workflow_service.start_competitive_intel(request)" in command_text
    assert "detail = await self._run_service.create_run(request)" in command_text

    cutover_index = command_text.index("cutover = decide_temporal_cutover(self._settings, request)")
    temporal_start_index = command_text.index(
        "self._workflow_service.start_competitive_intel(request)"
    )
    direct_create_index = command_text.index("detail = await self._run_service.create_run(request)")

    assert cutover_index < temporal_start_index < direct_create_index


def test_enterprise_router_delegates_report_runtime_commands() -> None:
    text = _read("app/routers/enterprise.py")

    assert "runtime.revise_report" in text
    assert "runtime.publish_report" in text
    assert "mark_report_published" not in text


def test_langgraph_and_agents_do_not_own_report_publication() -> None:
    forbidden = (
        "mark_report_published",
        "report_version.published",
        "ReportApprovalWorkflow",
        "request_report_approval",
        "approve_report_version",
        "reject_report_version",
    )
    checked_paths = [
        *list((BACKEND_ROOT / "packages" / "agents").rglob("*.py")),
        BACKEND_ROOT / "packages" / "orchestrator" / "graph.py",
    ]

    offenders = _find_forbidden(checked_paths, forbidden)

    assert offenders == {}


def test_research_pipeline_does_not_own_enterprise_publication_state() -> None:
    forbidden = (
        "mark_report_published",
        "report_version.published",
        "ReportApprovalWorkflow",
        "request_report_approval",
        "approve_report_version",
        "reject_report_version",
        "upsert_report_version",
        "approval_workflow",
    )
    checked_paths = list((BACKEND_ROOT / "packages" / "research").rglob("*.py"))

    offenders = _find_forbidden(checked_paths, forbidden)

    assert offenders == {}


def _read(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")


def _find_forbidden(
    paths: list[Path],
    forbidden: tuple[str, ...],
) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        matches = [item for item in forbidden if item in text]
        if matches:
            offenders[str(path.relative_to(BACKEND_ROOT))] = matches
    return offenders
