from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_run_recovery_stream import create_recovery_run, recovery_service

from app.deps import get_app_settings, get_enterprise_user_context, get_run_service
from app.routers import runs as runs_router
from app.routers.workflows import _ensure_workflow_run_visible
from packages.auth import EnterpriseUserContext
from packages.enterprise import EnterpriseMemoryStore
from packages.governance import build_model_policy_report
from packages.identity import compute_run_id_for_idempotency_key
from packages.memory import PreferenceMemoryStore, RunJournal
from packages.runtime import CreateRunCommand, RuntimeCommandService
from packages.schema.api_dto import RunCreateRequest, WorkflowStartResponse
from packages.workflows.activities import CompetitiveIntelActivities
from packages.workflows.service import competitive_intel_input_from_run_request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry", ["runtime_local", "runtime_temporal", "workflow_route", "activity"],
)
async def test_actual_internal_route_persists_owner_despite_opposite_global_backend(
    tmp_path, entry,
):
    journal = RunJournal(tmp_path / "owner.db")
    service = recovery_service(journal, tmp_path / "graph.db")
    settings = replace(
        service._settings,
        run_orchestration_backend="temporal" if entry == "runtime_local" else "langgraph",
        temporal_traffic_percent=0 if entry == "runtime_local" else 100,
    )
    service._settings = settings
    request = RunCreateRequest(
        topic="Route owner regression", competitors=["Cursor"], dimensions=["pricing"],
        execution_mode="demo", idempotency_key=f"owner:{entry}",
    )
    run_id = compute_run_id_for_idempotency_key(request.idempotency_key)
    response = WorkflowStartResponse(
        workflow_id="offline-workflow", run_id=run_id, idempotency_key=request.idempotency_key,
        task_queue="offline", status="started",
    )
    entered = asyncio.Event()

    async def hold_pipeline(*args):
        entered.set()
        await asyncio.Event().wait()

    class OfflineWorkflow:
        async def start_competitive_intel(self, request):
            return response

    runtime = RuntimeCommandService(
        settings=settings, run_service=service, workflow_service=OfflineWorkflow(),
        enterprise_store=EnterpriseMemoryStore(),
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    background = None
    try:
        if entry == "runtime_local":
            service._demo_planner_step = hold_pipeline
            result = await runtime.create_run(
                CreateRunCommand(request=request), actor=EnterpriseUserContext("owner", "owner"),
            )
            assert result.route == "langgraph"
            await asyncio.wait_for(entered.wait(), 3)
            background = service._runs[run_id].pipeline_task
        elif entry == "runtime_temporal":
            await runtime._ensure_temporal_run_visible(response, request)
        elif entry == "workflow_route":
            await _ensure_workflow_run_visible(response, request, service)
        else:
            await CompetitiveIntelActivities(service).create_run(
                competitive_intel_input_from_run_request(request),
            )
        expected_owner = "langgraph" if entry == "runtime_local" else "temporal"
        assert journal.load_run(run_id).runtime_orchestration_backend == expected_owner
    finally:
        if background is not None:
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.parametrize("policy_blocked", [False, True])
def test_recovery_api_uses_persisted_owner_and_current_model_policy(monkeypatch, policy_blocked):
    service = recovery_service(real=policy_blocked)
    detail = asyncio.run(create_recovery_run(
        service, execution_mode="real" if policy_blocked else "demo",
    ))
    detail.status = "running"
    detail.llm_budget_checkpoint = {
        "calls": 2, "repairs": 0, "tokens_charged": 1234, "cost_charged_usd": 0.01,
    }
    budget_before = dict(detail.llm_budget_checkpoint)
    settings = replace(
        service._settings, run_orchestration_backend="temporal", temporal_traffic_percent=0,
        compliance_redaction_enabled=not policy_blocked,
    )
    service._settings = settings
    executed = []

    async def checkpoint(record):
        return SimpleNamespace(values={"run_id": detail.id}, next=("planner",), tasks=())

    async def pipeline(run_id):
        executed.append(run_id)

    monkeypatch.setattr(service, "_pipeline_checkpoint", checkpoint)
    monkeypatch.setattr(service, "run_pipeline", pipeline)
    app = FastAPI()
    app.include_router(runs_router.router)
    app.dependency_overrides[get_run_service] = lambda: service
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_enterprise_user_context] = lambda: EnterpriseUserContext(
        "owner", "owner", "default-workspace",
    )
    with TestClient(app) as client:
        response = client.post(f"/runs/{detail.id}/recover")
    if policy_blocked:
        assert response.status_code == 409
        assert "redaction" in response.json()["detail"]
        assert executed == []
    else:
        assert response.status_code == 202
        assert response.json()["runtime_orchestration_backend"] == "langgraph"
        assert executed == [detail.id]
    assert detail.llm_budget_checkpoint == budget_before


def test_public_request_cannot_choose_runtime_owner():
    with pytest.raises(ValidationError):
        RunCreateRequest(
            topic="Forbidden ownership override", competitors=["Cursor"], dimensions=["pricing"],
            runtime_orchestration_backend="langgraph",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", [False, True])
@pytest.mark.parametrize("original_owner", ["langgraph", "temporal"])
async def test_internal_route_cannot_claim_duplicate_owned_by_other_runtime(
    same_key, original_owner,
):
    service = recovery_service()
    request = RunCreateRequest(
        topic="Existing run ownership", competitors=["Cursor"], dimensions=["pricing"],
        execution_mode="demo", idempotency_key="original-owner",
    )
    original = await service.create_run(request, runtime_orchestration_backend=original_owner)
    alternate = "temporal" if original_owner == "langgraph" else "langgraph"
    duplicate = (
        request if same_key else request.model_copy(update={"idempotency_key": "different-key"})
    )
    with pytest.raises(ValueError, match="owner"):
        await service.create_run(duplicate, runtime_orchestration_backend=alternate)
    assert service.get_run(original.id).runtime_orchestration_backend == original_owner


@pytest.mark.asyncio
async def test_recovery_policy_denial_keeps_budget_and_checkpoint_without_scheduling(
    tmp_path, monkeypatch,
):
    journal = RunJournal(tmp_path / "runs.db")
    service = recovery_service(journal, tmp_path / "graph.db", real=True)
    detail = await create_recovery_run(service, execution_mode="real", hitl_enabled=False)
    detail.status = "running"
    detail.llm_budget_checkpoint = {
        "calls": 2, "repairs": 0, "tokens_charged": 1234, "cost_charged_usd": 0.01,
    }
    journal.save_run(detail)
    graph = await service._get_real_graph()
    config = {"configurable": {"thread_id": detail.id}}
    await graph.aupdate_state(
        config, {"run_id": detail.id, "current_node": "planner"}, as_node="planner",
    )
    before = await graph.aget_state(config)
    calls = []

    async def forbidden_pipeline(*args, **kwargs):
        calls.append("pipeline")

    async def forbidden_model(*args, **kwargs):
        calls.append("model")

    monkeypatch.setattr(service, "run_pipeline", forbidden_pipeline)
    monkeypatch.setattr(service._llm, "complete_json", forbidden_model)
    service._settings = replace(service._settings, compliance_redaction_enabled=False)
    assert not build_model_policy_report(service._settings).real_execution_allowed
    try:
        with pytest.raises(ValueError, match="redaction"):
            await service.recover_run(detail.id)
        await asyncio.sleep(0)
        assert calls == []
        assert journal.load_run(detail.id).llm_budget_checkpoint == detail.llm_budget_checkpoint
        after = await graph.aget_state(config)
        assert after.values == before.values
        assert after.config == before.config
        assert service._runs[detail.id].pipeline_task is None
    finally:
        background = service._runs[detail.id].pipeline_task
        if background is not None:
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
        await service._graph_checkpointer.aclose()
