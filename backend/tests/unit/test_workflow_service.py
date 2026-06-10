from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.deps import (
    get_app_settings,
    get_enterprise_store,
    get_run_service,
    get_temporal_workflow_service,
)
from app.main import create_app
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.orchestrator.service import RunService
from packages.schema.api_dto import (
    MonitorStartRequest,
    MonitorStartResponse,
    ReportApprovalSignalRequest,
    ReportApprovalSignalResponse,
    ReportApprovalStartRequest,
    ReportApprovalStartResponse,
    RunCreateRequest,
    ScheduledScanStartRequest,
    ScheduledScanStartResponse,
    WorkflowStartResponse,
    WorkflowStateResponse,
)
from packages.schema.enterprise import ProjectRecord, ReportVersionRecord
from packages.skills.registry import SkillRegistry
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.monitor import MonitorWorkflow
from packages.workflows.report_approval import ReportApprovalWorkflow
from packages.workflows.scheduled_scan import ScheduledScanWorkflow
from packages.workflows.service import (
    TemporalWorkflowService,
    competitive_intel_input_from_run_request,
    decide_temporal_cutover,
    monitor_input_from_request,
    monitor_workflow_id,
    report_approval_workflow_id,
    run_id_for_idempotency_key,
    scheduled_scan_input_from_request,
    scheduled_scan_workflow_id,
    temporal_cutover_status,
    workflow_idempotency_key,
)


def _settings(**overrides: object) -> Settings:
    values = {
        "demo_mode": True,
        "ark_api_key": None,
        "ark_model": None,
        "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "llm_timeout_seconds": 10,
        "llm_temperature": 0.2,
        "enterprise_store_backend": "memory",
        "enterprise_database_url": None,
        "temporal_task_queue": "test-queue",
    }
    values.update(overrides)
    return Settings(**values)


def _request(idempotency_key: str | None = None, **overrides: object) -> RunCreateRequest:
    values = {
        "topic": "AI coding assistant workflow route",
        "competitors": ["Cursor", "GitHub Copilot"],
        "dimensions": ["pricing"],
        "execution_mode": "demo",
        "idempotency_key": idempotency_key,
    }
    values.update(overrides)
    return RunCreateRequest(
        **values,
    )


def _memory_run_service(settings: Settings | None = None) -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=settings or _settings(),
        enterprise_store=EnterpriseMemoryStore(),
    )


class FakeTemporalHandle:
    def __init__(self, workflow_id: str) -> None:
        self.id = workflow_id
        self.signals: list[dict[str, object]] = []
        self.state: dict[str, object] = {
            "workflow_type": "CompetitiveIntelWorkflow",
            "status": "running",
            "run_id": "run-test",
        }

    async def signal(
        self,
        signal: object,
        *,
        args: list[object],
    ) -> None:
        self.signals.append({"signal": signal, "args": args})

    async def query(self, query: object) -> dict[str, object]:
        assert query == "state"
        return self.state


class FakeTemporalClient:
    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []
        self.handles: dict[str, FakeTemporalHandle] = {}

    async def start_workflow(
        self,
        workflow: object,
        arg: object,
        *,
        id: str,
        task_queue: str,
        cron_schedule: str | None = None,
    ) -> FakeTemporalHandle:
        self.started.append(
            {
                "workflow": workflow,
                "arg": arg,
                "id": id,
                "task_queue": task_queue,
                "cron_schedule": cron_schedule,
            }
        )
        handle = FakeTemporalHandle(id)
        self.handles[id] = handle
        return handle

    def get_workflow_handle(self, workflow_id: str) -> FakeTemporalHandle:
        handle = self.handles.get(workflow_id)
        if handle is None:
            handle = FakeTemporalHandle(workflow_id)
            self.handles[workflow_id] = handle
        return handle


def test_workflow_input_derives_stable_idempotency_key_when_missing() -> None:
    request = _request()

    first = competitive_intel_input_from_run_request(request)
    second = competitive_intel_input_from_run_request(request)

    assert first.idempotency_key == second.idempotency_key
    assert first.idempotency_key.startswith("workflow:")
    assert first.topic == request.topic
    assert run_id_for_idempotency_key(first.idempotency_key).startswith("run-")


def test_workflow_input_preserves_explicit_idempotency_key() -> None:
    request = _request(idempotency_key="approval-demo-001")

    workflow_input = competitive_intel_input_from_run_request(request)

    assert workflow_input.idempotency_key == "approval-demo-001"
    assert workflow_idempotency_key(request) != "approval-demo-001"


def test_workflow_input_preserves_run_level_hitl_setting() -> None:
    request = _request(hitl_enabled=True, auto_redo_warn_enabled=False)

    workflow_input = competitive_intel_input_from_run_request(request)

    assert workflow_input.hitl_enabled is True
    assert workflow_input.auto_redo_warn_enabled is False


def test_temporal_cutover_decision_supports_staged_traffic() -> None:
    request = _request(idempotency_key="temporal-cutover-stable")

    disabled = decide_temporal_cutover(
        _settings(run_orchestration_backend="langgraph", temporal_traffic_percent=100),
        request,
    )
    zero = decide_temporal_cutover(
        _settings(run_orchestration_backend="temporal", temporal_traffic_percent=0),
        request,
    )
    full = decide_temporal_cutover(
        _settings(run_orchestration_backend="temporal", temporal_traffic_percent=100),
        request,
    )

    assert disabled.route == "langgraph"
    assert zero.route == "langgraph"
    assert full.route == "temporal"
    assert 0 <= full.bucket <= 99


def test_temporal_cutover_status_requires_full_temporal_routing() -> None:
    langgraph = temporal_cutover_status(
        _settings(run_orchestration_backend="langgraph", temporal_traffic_percent=100)
    )
    partial = temporal_cutover_status(
        _settings(run_orchestration_backend="temporal", temporal_traffic_percent=80)
    )
    ready = temporal_cutover_status(
        _settings(run_orchestration_backend="temporal", temporal_traffic_percent=100)
    )

    assert langgraph.ready is False
    assert "RUN_ORCHESTRATION_BACKEND" in langgraph.reason
    assert partial.ready is False
    assert "TEMPORAL_TRAFFIC_PERCENT" in partial.reason
    assert ready.ready is True
    assert ready.reason == "100% run traffic is routed through Temporal."


async def test_temporal_workflow_service_starts_competitive_intel_workflow() -> None:
    fake_client = FakeTemporalClient()

    async def client_factory(settings: Settings) -> FakeTemporalClient:
        assert settings.temporal_task_queue == "test-queue"
        return fake_client

    service = TemporalWorkflowService(_settings(), client_factory=client_factory)

    response = await service.start_competitive_intel(_request(idempotency_key="temporal-api-001"))

    assert response.status == "started"
    assert response.idempotency_key == "temporal-api-001"
    assert response.run_id == run_id_for_idempotency_key("temporal-api-001")
    assert response.task_queue == "test-queue"
    assert fake_client.started[0]["workflow"] == CompetitiveIntelWorkflow.run
    assert fake_client.started[0]["task_queue"] == "test-queue"


async def test_temporal_workflow_service_starts_report_approval_workflow() -> None:
    fake_client = FakeTemporalClient()

    async def client_factory(settings: Settings) -> FakeTemporalClient:
        assert settings.temporal_task_queue == "test-queue"
        return fake_client

    service = TemporalWorkflowService(_settings(), client_factory=client_factory)

    response = await service.start_report_approval(
        ReportApprovalStartRequest(
            report_version_id="report-version-1",
            approver_ids=["approver-1"],
            timeout_seconds=60,
        )
    )

    assert response.status == "started"
    assert response.workflow_id == report_approval_workflow_id("report-version-1")
    assert response.report_version_id == "report-version-1"
    assert fake_client.started[0]["workflow"] == ReportApprovalWorkflow.run
    assert fake_client.started[0]["task_queue"] == "test-queue"


async def test_temporal_workflow_service_starts_scheduled_scan_workflow() -> None:
    fake_client = FakeTemporalClient()

    async def client_factory(settings: Settings) -> FakeTemporalClient:
        assert settings.temporal_task_queue == "test-queue"
        return fake_client

    service = TemporalWorkflowService(_settings(), client_factory=client_factory)
    request = ScheduledScanStartRequest(
        workspace_id="workspace-a",
        schedule_id="weekly",
        project_ids=["project-1"],
        dimensions=["pricing"],
        execution_mode="demo",
        cron_schedule="0 2 * * 1",
    )

    response = await service.start_scheduled_scan(request)

    workflow_input = scheduled_scan_input_from_request(request)
    assert response.status == "started"
    assert response.workflow_id == scheduled_scan_workflow_id(workflow_input)
    assert response.workspace_id == "workspace-a"
    assert response.schedule_id == "weekly"
    assert fake_client.started[0]["workflow"] == ScheduledScanWorkflow.run
    assert fake_client.started[0]["arg"] == workflow_input
    assert fake_client.started[0]["cron_schedule"] == "0 2 * * 1"


async def test_temporal_workflow_service_starts_monitor_workflow() -> None:
    fake_client = FakeTemporalClient()

    async def client_factory(settings: Settings) -> FakeTemporalClient:
        assert settings.temporal_task_queue == "test-queue"
        return fake_client

    service = TemporalWorkflowService(_settings(), client_factory=client_factory)
    request = MonitorStartRequest(
        workspace_id="workspace-a",
        project_id="project-1",
        monitor_id="weekly-monitor",
        dimensions=["pricing"],
        execution_mode="demo",
        interval_seconds=60,
        max_cycles=2,
    )

    response = await service.start_monitor(request)

    workflow_input = monitor_input_from_request(request)
    assert response.status == "started"
    assert response.workflow_id == monitor_workflow_id(workflow_input)
    assert response.workspace_id == "workspace-a"
    assert response.project_id == "project-1"
    assert response.monitor_id == "weekly-monitor"
    assert fake_client.started[0]["workflow"] == MonitorWorkflow.run
    assert fake_client.started[0]["arg"] == workflow_input


async def test_temporal_workflow_service_signals_report_approval() -> None:
    fake_client = FakeTemporalClient()

    async def client_factory(settings: Settings) -> FakeTemporalClient:
        return fake_client

    service = TemporalWorkflowService(_settings(), client_factory=client_factory)

    response = await service.approve_report(
        "report-version-1",
        ReportApprovalSignalRequest(approver_id="approver-1", note="ship it"),
    )

    handle = fake_client.get_workflow_handle(report_approval_workflow_id("report-version-1"))
    assert response.status == "signaled"
    assert response.decision == "approved"
    assert handle.signals == [
        {
            "signal": ReportApprovalWorkflow.approve,
            "args": ["approver-1", "ship it"],
        }
    ]


async def test_temporal_workflow_service_queries_workflow_state() -> None:
    fake_client = FakeTemporalClient()
    handle = fake_client.get_workflow_handle("competitive-intel-state")
    handle.state = {
        "workflow_type": "CompetitiveIntelWorkflow",
        "status": "running_langgraph",
        "run_id": "run-state",
    }

    async def client_factory(settings: Settings) -> FakeTemporalClient:
        return fake_client

    service = TemporalWorkflowService(_settings(), client_factory=client_factory)

    response = await service.get_workflow_state("competitive-intel-state")

    assert response == WorkflowStateResponse(
        workflow_id="competitive-intel-state",
        task_queue="test-queue",
        status="running_langgraph",
        state={
            "workflow_type": "CompetitiveIntelWorkflow",
            "status": "running_langgraph",
            "run_id": "run-state",
        },
    )


def test_workflow_router_returns_accepted_start_response() -> None:
    class FakeWorkflowService:
        async def start_competitive_intel(
            self,
            request: RunCreateRequest,
        ) -> WorkflowStartResponse:
            idempotency_key = request.idempotency_key or "workflow:test"
            return WorkflowStartResponse(
                workflow_id="competitive-intel-test",
                run_id=run_id_for_idempotency_key(idempotency_key),
                idempotency_key=idempotency_key,
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    run_service = _memory_run_service()
    app.dependency_overrides[get_run_service] = lambda: run_service
    client = TestClient(app)

    response = client.post(
        "/api/workflows/competitive-intel",
        json={
            "topic": "AI coding assistant workflow route",
            "competitors": ["Cursor"],
            "dimensions": ["pricing"],
            "execution_mode": "demo",
            "idempotency_key": "route-001",
        },
    )

    assert response.status_code == 202
    run_id = run_id_for_idempotency_key("route-001")
    assert response.json() == {
        "workflow_id": "competitive-intel-test",
        "workflow_type": "CompetitiveIntelWorkflow",
        "run_id": run_id,
        "idempotency_key": "route-001",
        "task_queue": "test-queue",
        "status": "started",
    }
    visible = client.get(f"/api/runs/{run_id}")
    assert visible.status_code == 200
    assert visible.json()["status"] == "queued"


def test_workflow_router_exposes_workflow_state() -> None:
    class FakeWorkflowService:
        async def get_workflow_state(self, workflow_id: str) -> WorkflowStateResponse:
            return WorkflowStateResponse(
                workflow_id=workflow_id,
                task_queue="test-queue",
                status="running",
                state={"workflow_type": "CompetitiveIntelWorkflow", "status": "running"},
            )

    app = create_app()
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    client = TestClient(app)

    response = client.get("/api/workflows/competitive-intel-state")

    assert response.status_code == 200
    assert response.json() == {
        "workflow_id": "competitive-intel-state",
        "task_queue": "test-queue",
        "status": "running",
        "state": {"workflow_type": "CompetitiveIntelWorkflow", "status": "running"},
    }


def test_runs_router_can_cut_over_to_temporal_backend() -> None:
    class FakeWorkflowService:
        async def start_competitive_intel(
            self,
            request: RunCreateRequest,
        ) -> WorkflowStartResponse:
            idempotency_key = request.idempotency_key or "workflow:cutover"
            return WorkflowStartResponse(
                workflow_id="competitive-intel-cutover",
                run_id=run_id_for_idempotency_key(idempotency_key),
                idempotency_key=idempotency_key,
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        run_orchestration_backend="temporal"
    )
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    run_service = _memory_run_service(_settings(run_orchestration_backend="temporal"))
    app.dependency_overrides[get_run_service] = lambda: run_service
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "topic": "AI coding assistant workflow cutover",
            "competitors": ["Cursor"],
            "dimensions": ["pricing"],
            "execution_mode": "demo",
            "idempotency_key": "route-cutover-001",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "workflow_id": "competitive-intel-cutover",
        "workflow_type": "CompetitiveIntelWorkflow",
        "run_id": run_id_for_idempotency_key("route-cutover-001"),
        "idempotency_key": "route-cutover-001",
        "task_queue": "test-queue",
        "status": "started",
    }
    visible = client.get(f"/api/runs/{run_id_for_idempotency_key('route-cutover-001')}")
    assert visible.status_code == 200
    assert visible.json()["status"] == "queued"


def test_runs_router_generates_visible_new_run_keys_for_temporal_cutover() -> None:
    class FakeWorkflowService:
        async def start_competitive_intel(
            self,
            request: RunCreateRequest,
        ) -> WorkflowStartResponse:
            assert request.idempotency_key is not None
            return WorkflowStartResponse(
                workflow_id=f"competitive-intel-{request.idempotency_key}",
                run_id=run_id_for_idempotency_key(request.idempotency_key),
                idempotency_key=request.idempotency_key,
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        run_orchestration_backend="temporal"
    )
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    run_service = _memory_run_service(_settings(run_orchestration_backend="temporal"))
    app.dependency_overrides[get_run_service] = lambda: run_service
    client = TestClient(app)
    payload = {
        "topic": "AI coding assistant workflow cutover",
        "competitors": ["Cursor"],
        "dimensions": ["pricing"],
        "execution_mode": "demo",
    }

    first = client.post("/api/runs", json=payload)
    second = client.post("/api/runs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.headers["X-Runtime-Command-Id"].startswith("runtime-command-")
    assert first.headers["X-Runtime-Audit-Correlation-Id"].startswith("audit-correlation-")
    assert first.headers["X-Run-Orchestration-Route"] == "temporal"
    first_body = first.json()
    second_body = second.json()
    assert first_body["idempotency_key"].startswith("ui-run:")
    assert second_body["idempotency_key"].startswith("ui-run:")
    assert first_body["run_id"] != second_body["run_id"]
    assert client.get(f"/api/runs/{first_body['run_id']}").status_code == 200
    assert client.get(f"/api/runs/{second_body['run_id']}").status_code == 200


def test_runs_router_blocks_real_temporal_cutover_when_model_policy_denies() -> None:
    class FakeWorkflowService:
        called = False

        async def start_competitive_intel(
            self,
            request: RunCreateRequest,
        ) -> WorkflowStartResponse:
            self.called = True
            return WorkflowStartResponse(
                workflow_id="should-not-start",
                run_id="run-blocked",
                idempotency_key=request.idempotency_key or "workflow:blocked",
                task_queue="test-queue",
                status="started",
            )

    fake_service = FakeWorkflowService()
    app = create_app()
    settings = _settings(
        run_orchestration_backend="temporal",
        ark_api_key=None,
        ark_model=None,
        backup_llm_api_key=None,
        backup_llm_model=None,
    )
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_temporal_workflow_service] = lambda: fake_service
    app.dependency_overrides[get_run_service] = lambda: _memory_run_service(settings)
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "topic": "AI coding assistant workflow cutover",
            "competitors": ["Cursor"],
            "dimensions": ["pricing"],
            "execution_mode": "real",
            "idempotency_key": "route-cutover-blocked",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["blocking_finding_ids"] == ["provider.no_real_provider"]
    assert fake_service.called is False


def test_workflow_router_blocks_real_run_when_model_policy_denies() -> None:
    class FakeWorkflowService:
        called = False

        async def start_competitive_intel(
            self,
            request: RunCreateRequest,
        ) -> WorkflowStartResponse:
            self.called = True
            return WorkflowStartResponse(
                workflow_id="should-not-start",
                run_id="run-blocked",
                idempotency_key=request.idempotency_key or "workflow:blocked",
                task_queue="test-queue",
                status="started",
            )

    fake_service = FakeWorkflowService()
    app = create_app()
    settings = _settings(
        ark_api_key="key",
        ark_model="model",
        compliance_redaction_enabled=False,
    )
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_temporal_workflow_service] = lambda: fake_service
    app.dependency_overrides[get_run_service] = lambda: _memory_run_service(settings)
    client = TestClient(app)

    response = client.post(
        "/api/workflows/competitive-intel",
        json={
            "topic": "AI coding assistant workflow route",
            "competitors": ["Cursor"],
            "dimensions": ["pricing"],
            "execution_mode": "real",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["blocking_finding_ids"] == [
        "compliance.redaction_disabled"
    ]
    assert fake_service.called is False


def test_workflow_router_exposes_report_approval_start_and_signal() -> None:
    class FakeWorkflowService:
        async def start_report_approval(
            self,
            request: ReportApprovalStartRequest,
        ) -> ReportApprovalStartResponse:
            return ReportApprovalStartResponse(
                workflow_id="report-approval-test",
                report_version_id=request.report_version_id,
                task_queue="test-queue",
                status="started",
            )

        async def approve_report(
            self,
            report_version_id: str,
            request: ReportApprovalSignalRequest,
        ) -> ReportApprovalSignalResponse:
            return ReportApprovalSignalResponse(
                workflow_id="report-approval-test",
                report_version_id=report_version_id,
                decision="approved",
                status="signaled",
            )

    store = EnterpriseMemoryStore()
    store.upsert_project(
        ProjectRecord(
            id="project-1",
            workspace_id="default-workspace",
            name="AI coding assistant",
            topic="AI coding assistant",
            topic_normalized="ai-coding-assistant",
            competitor_layer="L1",
            competitor_set_hash="cursor",
        )
    )
    store.upsert_report_version(
        ReportVersionRecord(
            id="report-version-1",
            workspace_id="default-workspace",
            project_id="project-1",
            run_id="run-1",
            version_number=1,
            topic_normalized="ai-coding-assistant",
            competitor_layer="L1",
            competitor_set_hash="cursor",
            report_md="Ready for review.",
        )
    )

    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    client = TestClient(app)

    start_response = client.post(
        "/api/workflows/report-approval",
        json={
            "report_version_id": "report-version-1",
            "approver_ids": ["approver-1"],
            "timeout_seconds": 60,
        },
    )
    signal_response = client.post(
        "/api/workflows/report-approval/report-version-1/approve",
        json={"approver_id": "approver-1", "note": "ship it"},
    )

    assert start_response.status_code == 202
    assert start_response.json()["workflow_type"] == "ReportApprovalWorkflow"
    assert signal_response.status_code == 202
    assert signal_response.json() == {
        "workflow_id": "report-approval-test",
        "workflow_type": "ReportApprovalWorkflow",
        "report_version_id": "report-version-1",
        "decision": "approved",
        "status": "signaled",
    }


def test_hitl_router_delegates_manual_redo_guard_to_runtime_command() -> None:
    run_service = _memory_run_service()
    detail = asyncio.run(
        run_service.create_run(
            _request(
                topic="AI coding assistant HITL",
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )
    )
    app = create_app()
    app.dependency_overrides[get_run_service] = lambda: run_service
    client = TestClient(app)

    response = client.post(f"/api/runs/{detail.id}/redo")

    assert response.status_code == 409
    assert response.json()["detail"] == "No eligible QA findings or redo limit reached."


def test_hitl_router_rejects_competitor_edits_outside_planner_review() -> None:
    run_service = _memory_run_service(
        _settings(hitl_enabled=True, ark_api_key="key", ark_model="model")
    )
    detail = asyncio.run(
        run_service.create_run(
            _request(
                topic="AI IDE",
                competitors=["Cursor"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )
    )
    app = create_app()
    app.dependency_overrides[get_run_service] = lambda: run_service
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{detail.id}/resume",
        json={
            "decision": "modify_plan",
            "competitor_edits": [{"action": "add", "name": "Windsurf"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Competitor edits require an active planner review."


def test_workflow_router_exposes_scheduled_scan_start() -> None:
    class FakeWorkflowService:
        async def start_scheduled_scan(
            self,
            request: ScheduledScanStartRequest,
        ) -> ScheduledScanStartResponse:
            return ScheduledScanStartResponse(
                workflow_id="scheduled-scan-test",
                workspace_id=request.workspace_id,
                schedule_id=request.schedule_id,
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    client = TestClient(app)

    response = client.post(
        "/api/workflows/scheduled-scan",
        json={
            "workspace_id": "workspace-a",
            "schedule_id": "weekly",
            "project_ids": ["project-1"],
            "dimensions": ["pricing"],
            "execution_mode": "demo",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "workflow_id": "scheduled-scan-test",
        "workflow_type": "ScheduledScanWorkflow",
        "workspace_id": "workspace-a",
        "schedule_id": "weekly",
        "task_queue": "test-queue",
        "status": "started",
    }


def test_workflow_router_exposes_monitor_start() -> None:
    class FakeWorkflowService:
        async def start_monitor(
            self,
            request: MonitorStartRequest,
        ) -> MonitorStartResponse:
            return MonitorStartResponse(
                workflow_id="monitor-test",
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                monitor_id=request.monitor_id,
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
    client = TestClient(app)

    response = client.post(
        "/api/workflows/monitor",
        json={
            "workspace_id": "workspace-a",
            "project_id": "project-1",
            "monitor_id": "weekly-monitor",
            "dimensions": ["pricing"],
            "execution_mode": "demo",
            "interval_seconds": 60,
            "max_cycles": 2,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "workflow_id": "monitor-test",
        "workflow_type": "MonitorWorkflow",
        "workspace_id": "workspace-a",
        "project_id": "project-1",
        "monitor_id": "weekly-monitor",
        "task_queue": "test-queue",
        "status": "started",
    }


def test_workflow_router_returns_503_when_temporal_is_unavailable() -> None:
    class FailingWorkflowService:
        async def start_competitive_intel(
            self,
            request: RunCreateRequest,
        ) -> WorkflowStartResponse:
            raise RuntimeError("connection refused")

    app = create_app()
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FailingWorkflowService()
    run_service = _memory_run_service()
    app.dependency_overrides[get_run_service] = lambda: run_service
    client = TestClient(app)

    response = client.post(
        "/api/workflows/competitive-intel",
        json={
            "topic": "AI coding assistant workflow route",
            "competitors": ["Cursor"],
            "dimensions": ["pricing"],
            "execution_mode": "demo",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Temporal workflow service is unavailable."
