"""Task-center admission at the existing application boundaries."""

import pytest
from pydantic import ValidationError

from packages.config import Settings
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry
from packages.task_center.errors import TaskCenterConfigurationError


def run_request(key="entry", **changes):
    return RunCreateRequest(
        topic="task center entry",
        competitors=["Cursor"],
        dimensions=["pricing"],
        execution_mode="demo",
        hitl_enabled=False,
        idempotency_key=key,
        **changes,
    )


async def test_enabled_direct_create_fails_closed_without_trusted_metadata():
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(task_center_enabled=True, task_center_database_url="postgresql://invalid/task"),
        journal=RunJournal.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    try:
        with pytest.raises(TaskCenterConfigurationError):
            await service.create_run(run_request())
    finally:
        await service._graph_checkpointer.aclose()


def test_external_request_has_no_admission_bypass():
    payload = {**run_request().model_dump(), "skip_task_center": True}
    with pytest.raises(ValidationError) as failure:
        RunCreateRequest.model_validate(payload)
    assert [(item["loc"], item["type"]) for item in failure.value.errors()] == [
        (("skip_task_center",), "extra_forbidden"),
    ]


async def test_disabled_bridge_keeps_legacy_path_without_factory_or_database(monkeypatch):
    import packages.task_center.bridge as bridge_module

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "disabled bridge must not construct a service or read its database URL"
        )

    monkeypatch.setattr(bridge_module, "get_task_service", forbidden)
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(task_center_enabled=False),
        journal=RunJournal.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    try:
        assert (await service.create_run(run_request())).id
    finally:
        await service._graph_checkpointer.aclose()


@pytest.fixture
def workflow_http(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.deps import get_app_settings, get_enterprise_store, get_temporal_workflow_service
    from app.middleware import auth
    from app.routers.workflows import router
    from packages.enterprise import EnterpriseMemoryStore
    from packages.schema.api_dto import (
        MonitorStartResponse,
        ScheduledScanStartResponse,
        WorkflowStartResponse,
    )
    from packages.schema.enterprise import ProjectRecord

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        '{"test-token":{"user_id":"server-subject","role":"owner","workspace_id":"default-workspace"}}',
    )
    store = EnterpriseMemoryStore()
    store.projects["project-http"] = ProjectRecord(
        id="project-http",
        workspace_id="default-workspace",
        name="HTTP",
        topic="http",
        topic_normalized="http",
    )
    store.projects["foreign"] = ProjectRecord(
        id="foreign", workspace_id="another", name="Other", topic="http", topic_normalized="http"
    )
    calls = []

    class Receiver:
        failure = None

        async def start_competitive_intel(self, request, *, actor=None):
            if self.failure:
                raise self.failure
            calls.append((request, actor))
            return WorkflowStartResponse(
                workflow_id="workflow",
                run_id="run",
                idempotency_key="key",
                task_queue="test",
                status="started",
            )

        async def start_scheduled_scan(self, request):
            if self.failure:
                raise self.failure
            calls.append((request, None))
            return ScheduledScanStartResponse(
                workflow_id="scan",
                workspace_id=request.workspace_id,
                schedule_id=request.schedule_id,
                task_queue="test",
                status="started",
            )

        async def start_monitor(self, request):
            if self.failure:
                raise self.failure
            calls.append((request, None))
            return MonitorStartResponse(
                workflow_id="monitor",
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                monitor_id=request.monitor_id,
                task_queue="test",
                status="started",
            )

    receiver = Receiver()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        task_center_enabled=True, task_center_database_url="postgresql://unused/task"
    )
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[get_temporal_workflow_service] = lambda: receiver
    # The legacy run dependency is declared by the competitive router even when
    # task center handles delivery; no actual RunService is needed for auth QA.
    from app.deps import get_run_service

    app.dependency_overrides[get_run_service] = lambda: object()
    client = TestClient(app)
    headers = {
        "Authorization": "Bearer test-token",
        "X-User-Id": "attacker",
        "X-User-Role": "owner",
        "X-Workspace-Id": "another",
    }
    yield client, headers, calls, receiver
    client.close()


def workflow_payload(entry, **updates):
    payload = {"workspace_id": "default-workspace", "execution_mode": "demo"}
    if entry == "competitive-intel":
        payload.update(
            topic="HTTP entry",
            project_id="project-http",
            competitors=["Cursor"],
            dimensions=["pricing"],
        )
    elif entry == "scheduled-scan":
        payload.update(project_ids=["project-http"], requested_by="client-forged")
    else:
        payload.update(project_id="project-http", requested_by="client-forged")
    payload.update(updates)
    return payload


@pytest.mark.parametrize("entry", ["competitive-intel", "scheduled-scan", "monitor"])
def test_old_http_entries_validate_server_subject_and_project_scope(workflow_http, entry):
    client, headers, calls, receiver = workflow_http
    response = client.post(f"/api/workflows/{entry}", json=workflow_payload(entry), headers=headers)
    assert response.status_code == 202
    payload, actor = calls[0]
    if entry == "competitive-intel":
        assert actor.user_id == "server-subject" and actor.workspace_id == "default-workspace"
    else:
        assert payload.requested_by == "server-subject"
    calls.clear()
    response = client.post(
        f"/api/workflows/{entry}",
        json=workflow_payload(entry, workspace_id="another"),
        headers=headers,
    )
    assert response.status_code == 403 and calls == []
    project = (
        {"project_ids": ["foreign"]} if entry == "scheduled-scan" else {"project_id": "foreign"}
    )
    response = client.post(
        f"/api/workflows/{entry}", json=workflow_payload(entry, **project), headers=headers
    )
    assert response.status_code == 403 and calls == []


@pytest.mark.parametrize("entry", ["competitive-intel", "scheduled-scan", "monitor"])
@pytest.mark.parametrize("error_kind, status_code", [("quota", 429), ("conflict", 409)])
def test_old_http_entries_keep_task_center_error_status(
    workflow_http, entry, error_kind, status_code
):
    from packages.task_center.errors import IdempotencyConflict, QuotaExceeded

    client, headers, calls, receiver = workflow_http
    receiver.failure = (
        QuotaExceeded("quota exhausted")
        if error_kind == "quota"
        else IdempotencyConflict("request conflict")
    )
    response = client.post(f"/api/workflows/{entry}", json=workflow_payload(entry), headers=headers)
    assert response.status_code == status_code and not calls
