from __future__ import annotations

from fastapi.testclient import TestClient

from app.deps import get_temporal_workflow_service
from app.main import create_app
from packages.config import Settings
from packages.schema.api_dto import RunCreateRequest, WorkflowStartResponse
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.service import (
    TemporalWorkflowService,
    competitive_intel_input_from_run_request,
    run_id_for_idempotency_key,
    workflow_idempotency_key,
)


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
        enterprise_store_backend="memory",
        enterprise_database_url=None,
        temporal_task_queue="test-queue",
    )


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


class FakeTemporalClient:
    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []

    async def start_workflow(
        self,
        workflow: object,
        arg: object,
        *,
        id: str,
        task_queue: str,
    ) -> FakeTemporalHandle:
        self.started.append(
            {
                "workflow": workflow,
                "arg": arg,
                "id": id,
                "task_queue": task_queue,
            }
        )
        return FakeTemporalHandle(id)


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
