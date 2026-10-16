from __future__ import annotations

import asyncio
import socket

import pytest
from test_run_recovery_stream import create_recovery_run, recovery_service

from packages.memory import RunJournal
from packages.workflows.activities import CompetitiveIntelActivities


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pipeline", "activity", "explicit"])
async def test_real_demo_graph_continues_sqlite_checkpoint_after_worker_cancellation(
    tmp_path, monkeypatch, route,
):
    def no_network(*args, **kwargs):
        raise AssertionError("offline recovery must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    journal_path, checkpoint_path = tmp_path / "runs.db", tmp_path / "graph.db"
    service = recovery_service(RunJournal(journal_path), checkpoint_path)
    detail = await create_recovery_run(service)
    record = service._runs[detail.id]
    budget = service._run_llm_budget(record)
    budget.reserve(is_repair=False, input_tokens=100, max_output_tokens=200)
    service._checkpoint_llm_budget(record, budget)
    entered = asyncio.Event()

    async def interrupted_join(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_demo_collect_join_step", interrupted_join)
    task = asyncio.create_task(service.run_pipeline(detail.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert RunJournal(journal_path).load_run(detail.id).status == "running"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()

    restored = recovery_service(RunJournal(journal_path), checkpoint_path)
    original_join = restored._demo_collect_join_step
    resumed = []
    resume_entered, resume_release = asyncio.Event(), asyncio.Event()

    async def must_not_restart(*args):
        raise AssertionError("completed planner/collector must not run again")

    async def resumed_join(*args):
        restored_budget = restored._run_llm_budget(restored._runs[detail.id])
        assert restored_budget.calls == 1
        assert restored_budget.tokens_used == 300
        resumed.append("collect_join")
        if route == "explicit":
            resume_entered.set()
            await resume_release.wait()
        await original_join(*args)

    monkeypatch.setattr(restored, "_demo_planner_step", must_not_restart)
    monkeypatch.setattr(restored, "_demo_collector_branch_step", must_not_restart)
    monkeypatch.setattr(restored, "_demo_collect_join_step", resumed_join)
    try:
        if route == "activity":
            result = await CompetitiveIntelActivities(restored).run_langgraph_pipeline(detail.id)
        elif route == "explicit":
            accepted = await restored.recover_run(detail.id)
            assert accepted.status == "running"
            background = restored._runs[detail.id].pipeline_task
            await asyncio.wait_for(resume_entered.wait(), 3)
            with pytest.raises(ValueError, match="already executing"):
                await restored.recover_run(detail.id)
            assert (await restored.run_pipeline(detail.id)).status == "running"
            resume_release.set()
            result = await asyncio.wait_for(background, 3)
        else:
            result = await restored.run_pipeline(detail.id)
        assert result.status in {"completed", "completed_with_blockers"}
        assert resumed == ["collect_join"]
        persisted = RunJournal(journal_path).load_run(detail.id)
        assert persisted.id == detail.id
        assert persisted.llm_budget_checkpoint["calls"] == 1
        assert persisted.llm_budget_checkpoint["tokens_charged"] == 300
    finally:
        resume_release.set()
        background = restored._runs[detail.id].pipeline_task
        if background is not None:
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
        await restored._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_real_graph_recovery_keeps_completed_planner_and_fake_model_charge(
    tmp_path, monkeypatch,
):
    def no_network(*args, **kwargs):
        raise AssertionError("offline real graph must not connect to external services")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    journal_path, checkpoint_path = tmp_path / "real-runs.db", tmp_path / "real-graph.db"
    service = recovery_service(RunJournal(journal_path), checkpoint_path, real=True)
    entered = asyncio.Event()
    model_calls = []

    async def fake_model(**kwargs):
        model_calls.append(kwargs["system"])
        return {"complexity": "low", "homepage_hints": {}}

    async def interrupted_collector(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service._llm, "complete_json", fake_model)
    monkeypatch.setattr(service, "_real_collector_branch_step", interrupted_collector)
    detail = await create_recovery_run(service, execution_mode="real", hitl_enabled=False)
    task = asyncio.create_task(service.run_pipeline(detail.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        charged = RunJournal(journal_path).load_run(detail.id).llm_budget_checkpoint
        assert charged["calls"] == len(model_calls) == 1
        assert charged["tokens_charged"] > 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()

    restored = recovery_service(RunJournal(journal_path), checkpoint_path, real=True)
    resumed = asyncio.Event()

    async def forbidden_planner(*args, **kwargs):
        raise AssertionError("real planner/model must not be replayed after its checkpoint")

    async def resumed_collector(*args):
        budget = restored._run_llm_budget(restored._runs[detail.id])
        assert budget.calls == charged["calls"]
        assert budget.tokens_used == charged["tokens_charged"]
        resumed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(restored._llm, "complete_json", forbidden_planner)
    monkeypatch.setattr(restored, "_real_planner_step", forbidden_planner)
    monkeypatch.setattr(restored, "_real_collector_branch_step", resumed_collector)
    task = asyncio.create_task(restored.run_pipeline(detail.id))
    try:
        await asyncio.wait_for(resumed.wait(), 3)
        assert restored._runs[detail.id].active_graph_kind == "real"
        assert restored._runs[detail.id].active_thread_id == detail.id
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await restored._graph_checkpointer.aclose()
