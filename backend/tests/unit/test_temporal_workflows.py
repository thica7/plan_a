from pathlib import Path

import pytest

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore, build_enterprise_projection
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import ReportVersionRecord
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
)
from packages.skills.registry import SkillRegistry
from packages.workflows.activities import (
    CompetitiveIntelActivities,
    MonitorActivities,
    ReportApprovalActivities,
    ScheduledScanActivities,
    _detect_monitor_anomalies,
)
from packages.workflows.competitive_intel import (
    CompetitiveIntelWorkflow,
    _coerce_projection_state,
    _coerce_run_state,
    _workflow_result,
)
from packages.workflows.models import (
    APPROVE_REPORT_VERSION_ACTIVITY,
    CREATE_RUN_ACTIVITY,
    LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY,
    RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
    REJECT_REPORT_VERSION_ACTIVITY,
    REQUEST_REPORT_APPROVAL_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    RUN_MONITOR_CYCLE_ACTIVITY,
    RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
    CompetitiveIntelWorkflowInput,
    MonitorAnomaly,
    MonitorAnomalyNotificationInput,
    MonitorCycleInput,
    MonitorCycleResult,
    MonitorSnapshot,
    MonitorWorkflowInput,
    ReportApprovalDecisionInput,
    ReportApprovalWorkflowInput,
    ScheduledScanNotificationInput,
    ScheduledScanProjectInput,
    ScheduledScanProjectResult,
    ScheduledScanWorkflowInput,
    WorkflowProjectionState,
    WorkflowRunState,
)
from packages.workflows.monitor import MonitorWorkflow, _monitor_result
from packages.workflows.report_approval import ReportApprovalWorkflow, _coerce_approval_state
from packages.workflows.scheduled_scan import ScheduledScanWorkflow, _scan_result
from packages.workflows.worker import build_competitive_intel_worker_components


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )


def _test_graph_checkpointer() -> GraphCheckpointer:
    return GraphCheckpointer.in_memory()


def test_workflow_package_init_is_temporal_sandbox_safe() -> None:
    init_source = Path("backend/packages/workflows/__init__.py").read_text(encoding="utf-8")

    assert "packages.workflows.activities" not in init_source
    assert "packages.workflows.worker" not in init_source
    assert "packages.orchestrator" not in init_source


@pytest.mark.asyncio
async def test_temporal_activities_are_idempotent_around_existing_langgraph() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        graph_checkpointer=_test_graph_checkpointer(),
    )
    activities = CompetitiveIntelActivities(service)
    request = CompetitiveIntelWorkflowInput(
        topic="AI coding assistant temporal test",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key="temporal-unit-001",
    )

    created = await activities.create_run(request)
    duplicate = await activities.create_run(request)
    completed = await activities.run_langgraph_pipeline(created.run_id)
    event_count = len(service.get_trace(created.run_id) or [])
    completed_again = await activities.run_langgraph_pipeline(created.run_id)
    projection = await activities.load_projection(created.run_id)

    assert duplicate.run_id == created.run_id
    assert duplicate.idempotency_key == "temporal-unit-001"
    assert completed.status == "completed"
    assert completed_again.status == "completed"
    assert len(service.get_trace(created.run_id) or []) == event_count
    assert projection.report_version_id is not None
    assert projection.evidence_count >= 1
    assert projection.claim_count >= 1


def test_temporal_worker_registers_only_the_outer_workflow_and_activities() -> None:
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=_settings())

    components = build_competitive_intel_worker_components(service)
    registered_activity_names = [
        getattr(activity_fn, "__temporal_activity_definition").name
        for activity_fn in components.activities
    ]

    assert components.workflows == [CompetitiveIntelWorkflow]
    assert len(components.activities) == 3
    assert registered_activity_names == components.activity_names
    assert components.activity_names == [
        CREATE_RUN_ACTIVITY,
        RUN_LANGGRAPH_ACTIVITY,
        LOAD_PROJECTION_ACTIVITY,
    ]


def test_temporal_worker_registers_approval_workflow_when_store_is_available() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        graph_checkpointer=_test_graph_checkpointer(),
    )

    components = build_competitive_intel_worker_components(service, enterprise_store=store)
    registered_activity_names = [
        getattr(activity_fn, "__temporal_activity_definition").name
        for activity_fn in components.activities
    ]

    assert components.workflows == [
        CompetitiveIntelWorkflow,
        ReportApprovalWorkflow,
        ScheduledScanWorkflow,
        MonitorWorkflow,
    ]
    assert registered_activity_names == [
        CREATE_RUN_ACTIVITY,
        RUN_LANGGRAPH_ACTIVITY,
        LOAD_PROJECTION_ACTIVITY,
        REQUEST_REPORT_APPROVAL_ACTIVITY,
        APPROVE_REPORT_VERSION_ACTIVITY,
        REJECT_REPORT_VERSION_ACTIVITY,
        LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
        RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
        RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
        RUN_MONITOR_CYCLE_ACTIVITY,
        RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY,
    ]


def test_temporal_workflows_expose_queryable_state() -> None:
    competitive = CompetitiveIntelWorkflow()
    scheduled = ScheduledScanWorkflow()
    monitor = MonitorWorkflow()
    approval = ReportApprovalWorkflow()

    assert competitive.state()["workflow_type"] == "CompetitiveIntelWorkflow"
    assert competitive.state()["status"] == "initialized"
    assert scheduled.state()["workflow_type"] == "ScheduledScanWorkflow"
    assert monitor.state()["workflow_type"] == "MonitorWorkflow"
    assert approval.state()["workflow_type"] == "ReportApprovalWorkflow"
    assert approval.state()["status"] == "initialized"


def test_competitive_intel_workflow_result_preserves_projection_metadata() -> None:
    result = _workflow_result(
        WorkflowRunState(
            run_id="run-1",
            idempotency_key="workflow-1",
            status="completed",
            workspace_id="workspace-1",
            project_id="project-1",
            report_chars=128,
            qa_finding_count=2,
        ),
        WorkflowProjectionState(
            run_id="run-1",
            workspace_id="workspace-1",
            project_id="project-1",
            report_version_id="report-version-1",
            evidence_count=3,
            claim_count=4,
        ),
    )

    assert result.status == "completed"
    assert result.report_version_id == "report-version-1"
    assert result.evidence_count == 3
    assert result.claim_count == 4
    assert result.report_chars == 128
    assert result.qa_finding_count == 2


@pytest.mark.asyncio
async def test_scheduled_scan_activities_scan_projects_and_notify() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        graph_checkpointer=_test_graph_checkpointer(),
    )
    created = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant scheduled scan",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    assert created.project_id is not None
    activities = ScheduledScanActivities(service, store)
    request = ScheduledScanWorkflowInput(
        workspace_id=created.workspace_id,
        schedule_id="weekly",
        project_ids=[created.project_id],
        dimensions=["pricing"],
        execution_mode="demo",
    )

    targets = await activities.list_targets(request)
    result = await activities.run_project_scan(
        ScheduledScanProjectInput(
            request=request,
            target=targets[0],
            scan_started_at="2026-05-29T00:00:00+00:00",
        )
    )
    notification = await activities.record_notification(
        ScheduledScanNotificationInput(
            request=request,
            results=[result],
            scan_started_at="2026-05-29T00:00:00+00:00",
        )
    )

    assert [target.project_id for target in targets] == [created.project_id]
    assert result.status == "completed"
    assert result.run_id is not None
    assert result.report_version_id is not None
    assert notification.notification_id is not None
    assert "scheduled_scan_summary" in {
        item.notification_type for item in store.list_notifications(created.workspace_id)
    }


def test_scheduled_scan_workflow_result_summarizes_partial_runs() -> None:
    result = _scan_result(
        ScheduledScanWorkflowInput(workspace_id="workspace-1", schedule_id="weekly"),
        [
            ScheduledScanProjectResult(
                project_id="project-1",
                run_id="run-1",
                status="completed",
                report_version_id="report-1",
                evidence_count=2,
            ),
            ScheduledScanProjectResult(
                project_id="project-2",
                run_id=None,
                status="failed",
                error="boom",
            ),
        ],
        notification_id="notification-1",
        scan_started_at="2026-05-29T00:00:00+00:00",
    )

    assert result.status == "partial"
    assert result.scanned_project_count == 2
    assert result.completed_count == 1
    assert result.failed_count == 1
    assert result.run_ids == ["run-1"]
    assert result.report_version_ids == ["report-1"]
    assert result.notification_id == "notification-1"


@pytest.mark.asyncio
async def test_monitor_activities_run_cycle_and_record_anomaly_notification() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        graph_checkpointer=_test_graph_checkpointer(),
    )
    created = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant monitor",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    assert created.project_id is not None
    activities = MonitorActivities(service, store)
    request = MonitorWorkflowInput(
        workspace_id=created.workspace_id,
        project_id=created.project_id,
        monitor_id="monitor-unit",
        dimensions=["pricing"],
        execution_mode="demo",
    )

    cycle = await activities.run_cycle(
        MonitorCycleInput(
            request=request,
            cycle_index=0,
            monitor_started_at="2026-05-29T00:00:00+00:00",
        )
    )
    notification = await activities.record_anomaly_notification(
        MonitorAnomalyNotificationInput(
            request=request,
            cycle_result=MonitorCycleResult(
                cycle_index=1,
                project_id=created.project_id,
                status="completed",
                run_id=cycle.run_id,
                report_version_id=cycle.report_version_id,
                anomalies=[
                    MonitorAnomaly(
                        id="anomaly-1",
                        severity="warning",
                        anomaly_type="evidence_drop",
                        message="Evidence dropped.",
                        metadata={"previous": 2, "current": 1},
                    )
                ],
            ),
            monitor_started_at="2026-05-29T00:00:00+00:00",
        )
    )

    assert cycle.status == "completed"
    assert cycle.run_id is not None
    assert cycle.current is not None
    assert notification.notification_id is not None
    stored = next(
        item
        for item in store.list_notifications(created.workspace_id)
        if item.notification_type == "anomaly_alert"
    )
    assert stored.notification_type == "anomaly_alert"
    assert stored.severity == "warning"


def test_monitor_anomaly_detector_flags_report_and_count_changes() -> None:
    previous = MonitorSnapshot(
        project_id="project-1",
        report_version_id="report-1",
        evidence_count=3,
        claim_count=3,
        report_hash="old",
    )
    current = MonitorSnapshot(
        project_id="project-1",
        report_version_id="report-2",
        evidence_count=1,
        claim_count=2,
        report_hash="new",
    )

    anomalies = _detect_monitor_anomalies(previous, current, status="completed")

    assert [item.anomaly_type for item in anomalies] == [
        "report_changed",
        "evidence_drop",
        "claim_drop",
    ]
    assert [item.severity for item in anomalies] == ["info", "warning", "warning"]


def test_monitor_workflow_result_summarizes_cycles() -> None:
    result = _monitor_result(
        MonitorWorkflowInput(
            workspace_id="workspace-1",
            project_id="project-1",
            monitor_id="weekly",
        ),
        [
            MonitorCycleResult(
                cycle_index=0,
                project_id="project-1",
                status="completed",
                run_id="run-1",
                anomalies=[
                    MonitorAnomaly(
                        id="anomaly-1",
                        severity="info",
                        anomaly_type="report_changed",
                        message="changed",
                    )
                ],
            ),
            MonitorCycleResult(
                cycle_index=1,
                project_id="project-1",
                status="failed",
                anomalies=[
                    MonitorAnomaly(
                        id="anomaly-2",
                        severity="critical",
                        anomaly_type="scan_failed",
                        message="failed",
                    )
                ],
            ),
        ],
        notification_ids=["notification-1"],
        monitor_started_at="2026-05-29T00:00:00+00:00",
    )

    assert result.status == "partial"
    assert result.cycle_count == 2
    assert result.failed_count == 1
    assert result.anomaly_count == 2
    assert result.run_ids == ["run-1"]
    assert result.notification_ids == ["notification-1"]


def test_temporal_activity_payloads_can_cross_json_converter_boundary() -> None:
    run_state = _coerce_run_state(
        {
            "run_id": "run-1",
            "idempotency_key": "workflow-1",
            "status": "completed",
            "workspace_id": "workspace-1",
            "project_id": None,
            "current_node": None,
            "report_chars": 128,
            "qa_finding_count": 2,
        }
    )
    projection = _coerce_projection_state(
        {
            "run_id": "run-1",
            "workspace_id": "workspace-1",
            "project_id": "project-1",
            "report_version_id": "report-version-1",
            "evidence_count": 3,
            "claim_count": 4,
        }
    )

    result = _workflow_result(run_state, projection)

    assert result.status == "completed"
    assert result.run_id == "run-1"
    assert result.report_version_id == "report-version-1"
    assert result.evidence_count == 3


@pytest.mark.asyncio
async def test_report_approval_activities_update_report_version_status() -> None:
    store = EnterpriseMemoryStore()
    report_version_id = _seed_valid_report_version(store, "report-version-1")
    activities = ReportApprovalActivities(store)

    requested = await activities.request_report_approval(
        ReportApprovalWorkflowInput(report_version_id=report_version_id)
    )
    approved = await activities.approve_report_version(
        ReportApprovalDecisionInput(
            report_version_id=report_version_id,
            approver_id="approver-1",
            note="looks good",
        )
    )
    stored = store.get_report_version(report_version_id)

    assert requested.status == "in_review"
    assert approved.status == "approved"
    assert approved.approver_id == "approver-1"
    assert stored is not None
    assert stored.status == "approved"


@pytest.mark.asyncio
async def test_report_approval_activities_block_weak_report_version() -> None:
    store = EnterpriseMemoryStore()
    report_version_id = _seed_valid_report_version(store, "report-version-weak")
    version = store.get_report_version(report_version_id)
    assert version is not None
    store.upsert_report_version(version.model_copy(update={"claim_ids": []}))
    activities = ReportApprovalActivities(store)

    with pytest.raises(RuntimeError, match="release gate blocked"):
        await activities.approve_report_version(
            ReportApprovalDecisionInput(
                report_version_id=report_version_id,
                approver_id="approver-1",
            )
        )


@pytest.mark.asyncio
async def test_report_approval_activities_can_reject_report_version() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_report_version(_report_version("report-version-2"))
    activities = ReportApprovalActivities(store)

    await activities.request_report_approval(
        ReportApprovalWorkflowInput(report_version_id="report-version-2")
    )
    rejected = await activities.reject_report_version(
        ReportApprovalDecisionInput(
            report_version_id="report-version-2",
            approver_id="approver-1",
            note="needs revision",
        )
    )
    stored = store.get_report_version("report-version-2")

    assert rejected.status == "rejected"
    assert rejected.note == "needs revision"
    assert stored is not None
    assert stored.status == "rejected"


def test_report_approval_payloads_can_cross_json_converter_boundary() -> None:
    state = _coerce_approval_state(
        {
            "report_version_id": "report-version-1",
            "workspace_id": "workspace-1",
            "project_id": "project-1",
            "status": "in_review",
            "approver_id": None,
            "note": "",
        }
    )

    assert state.report_version_id == "report-version-1"
    assert state.status == "in_review"


def _report_version(version_id: str) -> ReportVersionRecord:
    return ReportVersionRecord(
        id=version_id,
        workspace_id="default-workspace",
        project_id="project-1",
        version_number=1,
        topic_normalized="ai-coding-assistant",
        competitor_set_hash="competitors",
        competitor_layer="L1",
        report_md=_structured_report_md(),
    )


def _seed_valid_report_version(store: EnterpriseMemoryStore, run_id: str) -> str:
    detail = RunDetail(
        id=run_id,
        topic="Cursor vs Copilot pricing comparison",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-29T00:00:00",
        updated_at="2026-05-29T00:05:00",
        plan=AnalysisPlan(
            topic="Cursor vs Copilot pricing comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
            competitor_layer="L1",
            scenario_id="l1_pricing_pack",
            homepage_hints={"Cursor": "https://cursor.sh"},
            homepage_verified={"Cursor": True},
        ),
        report_md=_structured_report_md(),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.sh/pricing",
                snippet="Cursor publishes pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                pricing_model=PricingModel(
                    notes=[
                        KnowledgeClaim(
                            claim="Cursor publishes pricing.",
                            source_ids=["pricing-1"],
                            confidence=0.9,
                        )
                    ]
                ),
            )
        },
    )
    context = store.start_run(detail)
    projection = build_enterprise_projection(
        detail,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        competitor_layer="L1",
        competitor_id_map=context.competitor_id_map,
    )
    store.save_projection(projection)
    return projection.report_version.id


def _structured_report_md(source_id: str = "pricing-1") -> str:
    citation = f"[source:{source_id}]"
    return f"""
# Cursor Direct Battlecard

## Executive Summary
Cursor publishes pricing and the claim is scoped to accepted pricing evidence. {citation}

## Source Quality & Coverage
The report uses verified webpage evidence and keeps broader enterprise claims out of scope.
{citation}

## Side-by-Side Decision Matrix
| Dimension | Cursor |
| --- | --- |
| Pricing | Cursor publishes pricing. {citation} |

## Battlecard
Use pricing transparency as the direct battlecard point, pending feature and procurement review.
{citation}

## Next Collection / Verification Plan
Collect feature, security, and procurement sources before publishing broader recommendations.
{citation}

## Evidence Appendix
- {source_id}: Cursor pricing evidence. {citation}
""".strip()
