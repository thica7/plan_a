from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_enterprise_user_context, get_run_service
from app.events import RunEvent
from app.routers import runs as runs_router
from app.routers import stream as stream_router
from packages.auth import EnterpriseUserContext
from packages.config import Settings
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry
from packages.tools.evidence_fetch import EvidenceFetchResult


def recovery_service(
    journal=None, checkpoint_path: Path | None = None, *, real=False,
) -> RunService:
    return RunService(
        SkillRegistry.from_default_path(),
        Settings(demo_mode=not real, ark_api_key="offline-key" if real else None,
                 ark_model="offline-model" if real else None, hitl_timeout_seconds=0,
                 run_orchestration_backend="langgraph"),
        journal=journal,
        graph_checkpointer=(GraphCheckpointer(checkpoint_path) if checkpoint_path
                            else GraphCheckpointer.in_memory()),
    )


async def create_recovery_run(service, **overrides):
    request = dict(topic="Offline persisted recovery", competitors=["Cursor"],
                   dimensions=["pricing"], execution_mode="demo")
    request.update(overrides)
    return await service.create_run(RunCreateRequest(**request))


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted", [False, True])
async def test_stream_cursor_replays_only_later_events_and_delivers_new_events(tmp_path, persisted):
    journal_path = tmp_path / "journal.db"
    service = recovery_service(RunJournal(journal_path) if persisted else None)
    detail = await create_recovery_run(service)
    for message in ("already received", "replay after reconnect"):
        await service.emit(detail.id, "node_started", "planner", None, message)
    if persisted:
        service = recovery_service(RunJournal(journal_path))
    stream = service.stream_events(detail.id, after_event_id=2)
    try:
        assert (await anext(stream)).id == 3
        next_event = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await service.emit(detail.id, "node_completed", "planner", None, "live event")
        assert (await asyncio.wait_for(next_event, 2)).id == 4
    finally:
        await stream.aclose()
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_stream_subscription_during_history_does_not_lose_or_repeat_live_event():
    service = recovery_service()
    detail = await create_recovery_run(service)
    await service.emit(detail.id, "node_started", "planner", None, "history")
    stream = service.stream_events(detail.id, after_event_id=0)
    try:
        assert (await anext(stream)).id == 1
        await service.emit(detail.id, "node_completed", "planner", None, "during replay")
        assert [ (await anext(stream)).id for _ in range(2)] == [2, 3]
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        assert not pending.done()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    finally:
        await stream.aclose()


def test_stream_route_rejects_invalid_cursor_before_opening_stream():
    app = FastAPI()
    app.include_router(stream_router.router)
    app.dependency_overrides[get_run_service] = lambda: object()
    app.dependency_overrides[get_enterprise_user_context] = lambda: EnterpriseUserContext(
        "reader", "viewer", "default-workspace",
    )
    with TestClient(app) as client:
        for cursor in ("abc", "-1", "1.5"):
            response = client.get("/runs/test/stream", headers={"Last-Event-ID": cursor})
            assert response.status_code == 422


@pytest.mark.parametrize("cursor", [None, "2"])
def test_stream_route_forwards_last_event_id_and_keeps_sse_event_ids(cursor):
    received = []

    async def events(run_id, *, after_event_id):
        received.append(after_event_id)
        yield RunEvent(id=after_event_id + 1, run_id=run_id, type="run_created", message="replay")

    service = SimpleNamespace(
        peek_run_summary=lambda run_id: SimpleNamespace(workspace_id="default-workspace"),
        run_exists=lambda run_id: True,
        stream_events=events,
    )
    app = FastAPI()
    app.include_router(stream_router.router)
    app.dependency_overrides[get_run_service] = lambda: service
    app.dependency_overrides[get_enterprise_user_context] = lambda: EnterpriseUserContext(
        "reader", "viewer", "default-workspace",
    )
    with TestClient(app) as client:
        response = client.get(
            "/runs/test/stream", headers={"Last-Event-ID": cursor} if cursor else {},
        )
    expected = int(cursor or 0)
    assert response.status_code == 200
    assert received == [expected]
    assert f"id: {expected + 1}\r\n" in response.text


@pytest.mark.asyncio
async def test_run_pipeline_does_not_start_same_live_run_twice(monkeypatch):
    service = recovery_service()
    detail = await create_recovery_run(service)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service._demo_planner_step
    calls = 0

    async def planner(record):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        await original(record)

    monkeypatch.setattr(service, "_demo_planner_step", planner)
    first = asyncio.create_task(service.run_pipeline(detail.id))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(service.run_pipeline(detail.id))
        await asyncio.sleep(0.05)
        assert calls == 1
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_recovered_running_run_without_checkpoint_fails_closed(tmp_path, monkeypatch):
    journal = RunJournal(tmp_path / "journal.db")
    service = recovery_service(journal, tmp_path / "missing.db")
    detail = await create_recovery_run(service)
    detail.status = "running"
    journal.save_run(detail)
    restored = recovery_service(RunJournal(tmp_path / "journal.db"), tmp_path / "missing.db")
    planner_calls = 0

    async def planner(record):
        nonlocal planner_calls
        planner_calls += 1

    monkeypatch.setattr(restored, "_demo_planner_step", planner)
    try:
        result = await restored.run_pipeline(detail.id)
        assert planner_calls == 0
        assert result.status == "failed"
        assert "checkpoint" in restored.get_trace(detail.id)[-1].message.lower()
    finally:
        await service._graph_checkpointer.aclose()
        await restored._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_repeated_pipeline_on_human_wait_does_not_restart_or_approve(tmp_path):
    journal_path, checkpoint_path = tmp_path / "journal.db", tmp_path / "checkpoints.db"
    service = recovery_service(RunJournal(journal_path), checkpoint_path)
    detail = await create_recovery_run(service, collaboration_mode="assisted")
    try:
        await service.run_pipeline(detail.id)
        assert detail.status == "interrupted"
        events_before = [event.model_dump() for event in service.get_trace(detail.id)]
    finally:
        await service._graph_checkpointer.aclose()
    restored = recovery_service(RunJournal(journal_path), checkpoint_path)
    try:
        result = await restored.run_pipeline(detail.id)
        assert result.status == "interrupted"
        assert result.current_node == "planner_hitl"
        assert restored.has_pending_interrupt(detail.id)
        assert [event.model_dump() for event in restored.get_trace(detail.id)] == events_before
    finally:
        await restored._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "completed", "interrupted", "running", "failed"])
async def test_explicit_recovery_rejects_nonrecoverable_state_or_missing_checkpoint(status):
    service = recovery_service()
    detail = await create_recovery_run(service)
    detail.status = status
    try:
        with pytest.raises(ValueError):
            await service.recover_run(detail.id)
        assert service._runs[detail.id].pipeline_task is None
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_recovery_route_authorizes_stored_run_and_rejects_temporal_or_missing_checkpoint():
    service = recovery_service()
    detail = await create_recovery_run(service)
    detail.status = "running"
    app = FastAPI()
    app.include_router(runs_router.router)
    mode = {"backend": "langgraph"}
    actor = {"role": "owner", "workspace": "default-workspace"}
    app.dependency_overrides[get_run_service] = lambda: service
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        run_orchestration_backend=mode["backend"],
    )
    app.dependency_overrides[get_enterprise_user_context] = lambda: EnterpriseUserContext(
        "user", actor["role"], actor["workspace"],
    )
    try:
        with TestClient(app) as client:
            response = client.post(f"/runs/{detail.id}/recover")
            assert response.status_code == 409
            assert "checkpoint" in response.json()["detail"].lower()
            mode["backend"] = "temporal"
            detail.runtime_orchestration_backend = "temporal"
            response = client.post(f"/runs/{detail.id}/recover")
            assert response.status_code == 409
            assert "temporal" in response.json()["detail"].lower()
            actor["workspace"] = "other-workspace"
            assert client.post(f"/runs/{detail.id}/recover").status_code == 403
            actor["workspace"] = "default-workspace"
            actor["role"] = "viewer"
            assert client.post(f"/runs/{detail.id}/recover").status_code == 403
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_fetch_trace_keeps_cache_observation_time(monkeypatch):
    from packages.orchestrator import service as service_module

    service = recovery_service()
    detail = await create_recovery_run(service)
    observed = datetime(2026, 10, 1, 8, tzinfo=UTC)
    result = EvidenceFetchResult(
        url="https://example.invalid/specification", ok=True, title="Specification",
        text="Official product specification.", content_hash="source-hash",
        captured_at=observed, cache_hit=True,
    )

    async def fetch(*args, **kwargs):
        return result

    async def robots(*args, **kwargs):
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(service_module, "fetch_evidence_page", fetch)
    monkeypatch.setattr(service, "_trace_robots", robots)
    await service._trace_fetch(service._runs[detail.id], "collector", "feature::Cursor", result.url)
    metadata = detail.trace_spans[-1].metadata
    assert metadata["cache_hit"] is True
    assert metadata["capture_observed_at"] == observed.isoformat()


@pytest.mark.asyncio
async def test_new_local_run_persists_runtime_owner(tmp_path):
    journal = RunJournal(tmp_path / "owner.db")
    service = recovery_service(journal)
    detail = await create_recovery_run(service)
    stored = journal.load_run(detail.id).model_dump()
    assert stored.get("runtime_orchestration_backend") == "langgraph"


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, "temporal"])
async def test_explicit_recovery_rejects_unknown_or_temporal_persisted_owner_after_config_change(
    tmp_path, owner,
):
    path = tmp_path / "owner.db"
    service = recovery_service(RunJournal(path))
    detail = await create_recovery_run(service)
    stored = detail.model_copy(update={"status": "running", "runtime_orchestration_backend": owner})
    service._journal.save_run(stored)
    restored = recovery_service(RunJournal(path))
    assert restored._settings.run_orchestration_backend == "langgraph"
    try:
        with pytest.raises(ValueError, match="owner"):
            await restored.recover_run(detail.id)
    finally:
        await restored._graph_checkpointer.aclose()
