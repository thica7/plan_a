from __future__ import annotations

from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_temporal_workflow_service
from app.main import create_app
from packages.config import Settings
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


def _request(idempotency_key: str | None = None) -> RunCreateRequest:
    return RunCreateRequest(
        topic="AI coding assistant workflow route",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key=idempotency_key,
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
            return WorkflowStartResponse(
                workflow_id="competitive-intel-test",
                run_id="run-test",
                idempotency_key=request.idempotency_key or "workflow:test",
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
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
    assert response.json() == {
        "workflow_id": "competitive-intel-test",
        "workflow_type": "CompetitiveIntelWorkflow",
        "run_id": "run-test",
        "idempotency_key": "route-001",
        "task_queue": "test-queue",
        "status": "started",
    }


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
            return WorkflowStartResponse(
                workflow_id="competitive-intel-cutover",
                run_id="run-cutover",
                idempotency_key=request.idempotency_key or "workflow:cutover",
                task_queue="test-queue",
                status="started",
            )

    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        run_orchestration_backend="temporal"
    )
    app.dependency_overrides[get_temporal_workflow_service] = lambda: FakeWorkflowService()
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
        "run_id": "run-cutover",
        "idempotency_key": "route-cutover-001",
        "task_queue": "test-queue",
        "status": "started",
    }


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
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        run_orchestration_backend="temporal",
        ark_api_key=None,
        ark_model=None,
        backup_llm_api_key=None,
        backup_llm_model=None,
    )
    app.dependency_overrides[get_temporal_workflow_service] = lambda: fake_service
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
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        ark_api_key="key",
        ark_model="model",
        compliance_redaction_enabled=False,
    )
    app.dependency_overrides[get_temporal_workflow_service] = lambda: fake_service
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

    app = create_app()
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
