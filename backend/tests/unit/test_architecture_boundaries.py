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


def test_runs_router_evaluates_temporal_cutover_before_direct_run_create() -> None:
    text = _read("app/routers/runs.py")

    cutover_index = text.index("cutover = decide_temporal_cutover(settings, request)")
    temporal_start_index = text.index("workflow_service.start_competitive_intel(request)")
    direct_create_index = text.index("detail = await service.create_run(request)")

    assert cutover_index < temporal_start_index < direct_create_index


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
