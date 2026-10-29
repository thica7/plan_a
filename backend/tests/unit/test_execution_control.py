from __future__ import annotations

import asyncio
import importlib
import importlib.util
import multiprocessing
import os
import signal
import sqlite3
import threading
import time
from contextvars import Context
from dataclasses import asdict
from pathlib import Path

import pytest


def _api():
    name = "packages.infrastructure.execution_control"
    assert importlib.util.find_spec(name) is not None, "shared execution coordinator is missing"
    return importlib.import_module(name)


def _coordinator(tmp_path, **overrides):
    api = _api()
    return api.SQLiteExecutionCoordinator(tmp_path / "journal.db", api.ExecutionPolicy(**overrides))


async def _wait_until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def _pool_worker(db_path, policy, kind, number, active, peak, ready, start):
    async def work():
        api = _api()
        coordinator = api.SQLiteExecutionCoordinator(Path(db_path), api.ExecutionPolicy(**policy))
        ready.put(("ready", number))
        await asyncio.to_thread(start.wait, 10)
        for iteration in range(2):
            if kind == "run":
                ticket = await coordinator.admit(f"run-{number}-{iteration}", str(number), "start")
                guard = coordinator.run(ticket)
            else:
                guard = coordinator.model_slot()
            async with guard:
                with active.get_lock():
                    active.value += 1
                    peak.value = max(peak.value, active.value)
                await asyncio.sleep(0.04)
                with active.get_lock():
                    active.value -= 1
        ready.put(("done", number))

    asyncio.run(work())


def _crash_worker(db_path, policy, ready):
    async def work():
        api = _api()
        coordinator = api.SQLiteExecutionCoordinator(Path(db_path), api.ExecutionPolicy(**policy))
        ticket = await coordinator.admit("crash-run", "a", "original")
        async with coordinator.run(ticket) as lease, coordinator.model_slot():
            ready.put((lease.token, lease.generation))
            await asyncio.Event().wait()

    asyncio.run(work())


def test_policy_defaults_and_validation():
    api = _api()
    policy = api.ExecutionPolicy()
    assert asdict(policy) == {
        "global_running_limit": 2,
        "workspace_running_limit": 1,
        "global_queue_limit": 32,
        "workspace_queue_limit": 8,
        "queue_wait_seconds": 60,
        "model_concurrency": 4,
        "model_wait_seconds": 30,
    }
    for key, value in [
        ("global_running_limit", 0),
        ("model_concurrency", True),
        ("queue_wait_seconds", float("nan")),
        ("model_wait_seconds", -1),
    ]:
        with pytest.raises(ValueError):
            api.ExecutionPolicy(**{key: value})
    with pytest.raises(api.ExecutionUnavailableError):
        api.SQLiteExecutionCoordinator(Path(":memory:"), policy)


@pytest.mark.asyncio
async def test_atomic_admission_is_bounded_and_idempotent_across_instances(tmp_path):
    api = _api()
    one = _coordinator(tmp_path, global_queue_limit=2, workspace_queue_limit=1)
    two = _coordinator(tmp_path, global_queue_limit=2, workspace_queue_limit=1)
    tickets = await asyncio.gather(*(one.admit("r", "a", "start") for _ in range(12)))
    assert len({ticket.id for ticket in tickets}) == 1
    assert (await two.admit("r", "a", "start")) == tickets[0]
    with pytest.raises(api.ExecutionCapacityError) as error:
        await two.admit("second", "a", "start")
    assert error.value.status_code == 429
    assert error.value.retry_after_seconds >= 1
    await two.admit("second", "b", "start")
    with pytest.raises(api.ExecutionCapacityError):
        await one.admit("third", "c", "start")
    assert (await one.snapshot())["queued"] == 2


@pytest.mark.asyncio
async def test_same_run_conflicts_and_workspace_cannot_change_on_replay(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")
    with pytest.raises(api.ExecutionConflictError):
        await coordinator.admit("r", "b", "start")
    with pytest.raises(api.ExecutionConflictError):
        await coordinator.admit("r", "a", "resume")

    async def competitor():
        with pytest.raises(api.ExecutionConflictError):
            async with _coordinator(tmp_path).run(ticket):
                pytest.fail("same operation executed concurrently")

    async with coordinator.run(ticket):
        await asyncio.create_task(competitor(), context=Context())
    replay = await coordinator.admit("r", "a", "start")
    assert replay.id == ticket.id
    assert replay.state == "finished"
    with pytest.raises(api.ExecutionConflictError):
        async with coordinator.run(replay):
            pytest.fail("completed operation executed twice")


@pytest.mark.asyncio
async def test_workspace_fifo_does_not_block_other_runnable_workspaces(tmp_path):
    coordinator = _coordinator(tmp_path)
    first = await coordinator.admit("a0", "a", "start")
    older = await coordinator.admit("a1", "a", "start")
    newer = await coordinator.admit("a2", "a", "start")
    other = await coordinator.admit("b0", "b", "start")
    order = []

    async def execute(ticket):
        async with coordinator.run(ticket):
            order.append(ticket.run_id)

    async with coordinator.run(first):
        new_task = asyncio.create_task(execute(newer))
        old_task = asyncio.create_task(execute(older))
        await asyncio.wait_for(execute(other), 1)
        assert order == ["b0"]
    await asyncio.wait_for(asyncio.gather(new_task, old_task), 2)
    assert order == ["b0", "a1", "a2"]


@pytest.mark.asyncio
async def test_queued_ticket_expires_and_replay_cannot_reset_deadline(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path, queue_wait_seconds=0.05)
    ticket = await coordinator.admit("r", "a", "start")
    await asyncio.sleep(0.07)
    with pytest.raises(api.ExecutionTimeoutError):
        async with coordinator.run(ticket):
            pytest.fail("expired ticket ran")
    with sqlite3.connect(coordinator.db_path) as conn:
        assert (
            conn.execute(
                "select state from execution_control_tickets where id=?", (ticket.id,)
            ).fetchone()[0]
            == "timedout"
        )
    replay = await coordinator.admit("r", "a", "start")
    assert replay.id == ticket.id
    assert replay.deadline == ticket.deadline
    assert replay.state == "timedout"
    assert (await coordinator.snapshot())["queued"] == 0


@pytest.mark.asyncio
async def test_run_lock_acquired_after_queue_deadline_times_out_without_entering(
    tmp_path, monkeypatch
):
    api = _api()
    coordinator = _coordinator(tmp_path, queue_wait_seconds=0.05)
    ticket = await coordinator.admit("r", "a", "start")
    original = coordinator._run_lock

    def slow_run_lock(run_id):
        lock = original(run_id)
        time.sleep(0.08)
        return lock

    with monkeypatch.context() as patch:
        patch.setattr(coordinator, "_run_lock", slow_run_lock)
        with pytest.raises(api.ExecutionTimeoutError):
            async with coordinator.run(ticket):
                pytest.fail("execution entered after its queue deadline")
    with sqlite3.connect(coordinator.db_path) as conn:
        state, started_at = conn.execute(
            "select state, started_at from execution_control_tickets where id=?", (ticket.id,)
        ).fetchone()
    assert state == "timedout"
    assert started_at is None
    lock = original("r")
    assert lock is not None
    lock.close()
    snapshot = await coordinator.snapshot()
    assert snapshot["running"] == snapshot["queued"] == 0


@pytest.mark.asyncio
async def test_cancel_waiter_and_running_exception_return_capacity(tmp_path):
    coordinator = _coordinator(tmp_path, global_running_limit=1)
    first = await coordinator.admit("r1", "a", "start")
    waiting = await coordinator.admit("r2", "b", "start")

    async def wait():
        async with coordinator.run(waiting):
            pytest.fail("blocked waiter ran")

    with pytest.raises(ValueError):
        async with coordinator.run(first):
            waiter = asyncio.create_task(wait())
            await asyncio.sleep(0.03)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            raise ValueError("synthetic graph failure")
    snapshot = await coordinator.snapshot()
    assert snapshot["queued"] == snapshot["running"] == 0
    assert {item["state"] for item in snapshot["tickets"]} == {"cancelled", "finished"}


@pytest.mark.asyncio
async def test_public_cancel_cleans_failed_startup_without_revoking_running_owner(tmp_path):
    coordinator = _coordinator(tmp_path)
    abandoned = await coordinator.admit("abandoned", "a", "start")
    assert await coordinator.cancel(abandoned) is True
    assert await coordinator.cancel(abandoned) is False
    running = await coordinator.admit("running", "a", "start")
    async with coordinator.run(running):
        assert await coordinator.cancel(running) is False
        assert (await coordinator.snapshot())["running"] == 1


@pytest.mark.asyncio
async def test_fence_generation_heartbeat_and_old_context_are_invalid_after_release(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")
    async with coordinator.run(ticket) as lease:
        assert lease.ticket.state == "running"
        assert coordinator.current_lease("r") is lease
        async with _coordinator(tmp_path).run(ticket) as nested:
            assert nested is lease
        await lease.heartbeat()
        with sqlite3.connect(coordinator.db_path) as conn:
            coordinator.assert_fence(conn, "r", lease.token, lease.generation)
            with pytest.raises(api.ExecutionConflictError):
                coordinator.assert_fence(conn, "r", "wrong", lease.generation)
        await lease.release()
        with pytest.raises(api.ExecutionConflictError):
            async with coordinator.run(ticket):
                pytest.fail("released ContextVar was reused")
    second = await coordinator.admit("r", "a", "resume")
    async with coordinator.run(second) as newer:
        assert newer.generation == lease.generation + 1
        await lease.release()  # A repeated old release must not clear the newer owner.
        with sqlite3.connect(coordinator.db_path) as conn:
            coordinator.assert_fence(conn, "r", newer.token, newer.generation)
            with pytest.raises(api.ExecutionConflictError):
                coordinator.assert_fence(conn, "r", lease.token, lease.generation)
    with sqlite3.connect(coordinator.db_path) as conn:
        with pytest.raises(api.ExecutionConflictError):
            coordinator.assert_fence(conn, "r", newer.token, newer.generation)


@pytest.mark.asyncio
async def test_released_lock_invalidates_fence_even_if_release_storage_failed(
    tmp_path, monkeypatch
):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")

    def unavailable():
        raise api.ExecutionUnavailableError("synthetic release storage outage")

    with pytest.raises(api.ExecutionUnavailableError):
        async with coordinator.run(ticket) as lease:
            with monkeypatch.context() as patch:
                patch.setattr(coordinator, "_transaction", unavailable)
                await lease.release()
    with sqlite3.connect(coordinator.db_path) as conn:
        conn.execute("begin immediate")
        with pytest.raises(api.ExecutionConflictError):
            coordinator.assert_fence(conn, "r", lease.token, lease.generation)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "error", "cancel"])
async def test_explicit_handoff_keeps_background_owner_until_task_exits(tmp_path, outcome):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "resume")
    entered = asyncio.Event()
    leave = asyncio.Event()

    async def background():
        async with coordinator.run(ticket) as nested:
            assert nested is lease
            entered.set()
            await leave.wait()
            if outcome == "error":
                raise ValueError("synthetic background failure")

    async with coordinator.run(ticket) as lease:
        with pytest.raises(TypeError):
            lease.handoff(None)
        task = asyncio.create_task(background())
        lease.handoff(task)
        with pytest.raises(api.ExecutionConflictError):
            lease.handoff(task)
        await entered.wait()
        with pytest.raises(api.ExecutionConflictError):
            await lease.release()
        with pytest.raises(api.ExecutionConflictError):
            await lease.heartbeat()
        assert coordinator.current_lease("r") is lease
        with pytest.raises(api.ExecutionConflictError):
            await coordinator.admit("r", "a", "another-operation")
    assert (await coordinator.snapshot())["running"] == 1
    if outcome == "cancel":
        task.cancel()
    else:
        leave.set()
    result = await asyncio.gather(task, return_exceptions=True)
    if outcome == "error":
        assert isinstance(result[0], ValueError)
    await lease.wait_closed()
    assert (await coordinator.snapshot())["running"] == 0
    with sqlite3.connect(coordinator.db_path) as conn:
        with pytest.raises(api.ExecutionConflictError):
            coordinator.assert_fence(conn, "r", lease.token, lease.generation)


@pytest.mark.asyncio
async def test_inherited_context_does_not_implicitly_authorize_another_task(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")

    async def unauthorized_child():
        with pytest.raises(api.ExecutionConflictError):
            async with coordinator.run(ticket):
                pytest.fail("child inherited execution authority without handoff")

    async with coordinator.run(ticket):
        await asyncio.create_task(unauthorized_child())


@pytest.mark.asyncio
async def test_inherited_child_can_read_fence_but_cannot_change_lease_lifecycle(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")

    async def graph_node():
        inherited = coordinator.current_lease("r")
        assert inherited is lease
        assert coordinator.current_lease("another-run") is None
        assert _coordinator(tmp_path / "other-db").current_lease("r") is None
        with sqlite3.connect(coordinator.db_path) as conn:
            conn.execute("begin immediate")
            coordinator.assert_fence(conn, "r", inherited.token, inherited.generation)
        with pytest.raises(api.ExecutionConflictError):
            await inherited.release()
        with pytest.raises(api.ExecutionConflictError):
            await inherited.heartbeat()
        with pytest.raises(api.ExecutionConflictError):
            async with coordinator.run(ticket):
                pytest.fail("graph child acquired lifecycle ownership")

    async with coordinator.run(ticket) as lease:
        await asyncio.create_task(graph_node())
        with pytest.raises(api.ExecutionConflictError):
            await coordinator.admit("r", "a", "second")
        assert (await coordinator.snapshot())["running"] == 1
        await lease.heartbeat()
        await lease.release()
        await lease.release()


@pytest.mark.asyncio
async def test_inherited_child_cannot_release_parent_even_without_reading_context(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")

    async def graph_node():
        with pytest.raises(api.ExecutionConflictError):
            await lease.release()

    async with coordinator.run(ticket) as lease:
        await asyncio.create_task(graph_node())
        with pytest.raises(api.ExecutionConflictError):
            await coordinator.admit("r", "a", "second")
        assert (await coordinator.snapshot())["running"] == 1


@pytest.mark.asyncio
async def test_released_context_remains_invalid_in_an_inherited_child(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")
    leave = asyncio.Event()

    async def late_graph_node():
        await leave.wait()
        with pytest.raises(api.ExecutionConflictError):
            coordinator.current_lease("r")
        with pytest.raises(api.ExecutionConflictError):
            async with coordinator.run(ticket):
                pytest.fail("released inherited context was reused")

    async with coordinator.run(ticket):
        child = asyncio.create_task(late_graph_node())
    leave.set()
    await child


@pytest.mark.asyncio
async def test_pool_configuration_mismatch_fails_closed_at_every_entry(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")
    incompatible = _coordinator(tmp_path, model_concurrency=1)
    with pytest.raises(api.ExecutionConflictError):
        await incompatible.admit("r2", "b", "start")
    with pytest.raises(api.ExecutionConflictError):
        async with incompatible.run(ticket):
            pytest.fail("mismatched pool ran")
    with pytest.raises(api.ExecutionConflictError):
        async with incompatible.model_slot():
            pytest.fail("mismatched pool sent model request")


@pytest.mark.asyncio
async def test_snapshot_filters_tickets_by_workspace(tmp_path):
    coordinator = _coordinator(tmp_path)
    await coordinator.admit("secret-a", "a", "start")
    await coordinator.admit("secret-b", "b", "start")
    snapshot = await coordinator.snapshot(workspace_id="a")
    assert [row["run_id"] for row in snapshot["tickets"]] == ["secret-a"]
    assert snapshot["workspace_queued"] == 1


@pytest.mark.asyncio
async def test_unavailable_storage_is_typed_and_never_falls_back(tmp_path):
    api = _api()
    coordinator = api.SQLiteExecutionCoordinator(tmp_path, api.ExecutionPolicy())
    with pytest.raises(api.ExecutionUnavailableError) as error:
        await coordinator.admit("r", "a", "start")
    assert error.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["admit", "launcher", "claim", "model"])
async def test_cancellation_after_thread_commits_or_acquires_cleans_up(
    tmp_path, monkeypatch, phase
):
    coordinator = _coordinator(tmp_path)
    ticket = None if phase == "admit" else await coordinator.admit("r", "a", "start")
    reached = threading.Event()
    unblock = threading.Event()
    method = {"admit": "_admit_sync", "launcher": "_try_launcher_sync",
              "claim": "_claim_sync", "model": "_try_model_slot_sync"}[
        phase
    ]
    original = getattr(coordinator, method)

    def committed(*args, **kwargs):
        result = original(*args, **kwargs)
        reached.set()
        assert unblock.wait(3)
        return result

    monkeypatch.setattr(coordinator, method, committed)

    async def request():
        if phase == "admit":
            await coordinator.admit("r", "a", "start")
        elif phase in {"launcher", "claim"}:
            async with coordinator.run(ticket):
                pytest.fail("cancelled claim entered")
        else:
            async with coordinator.model_slot():
                pytest.fail("cancelled model claim entered")

    task = asyncio.create_task(request())
    await _wait_until(reached.is_set)
    task.cancel()
    await asyncio.sleep(0)
    unblock.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    snapshot = await coordinator.snapshot()
    assert snapshot["running"] == snapshot["model_active"] == 0
    assert snapshot["queued"] == (1 if phase == "model" else 0)


@pytest.mark.asyncio
async def test_cancelled_duplicate_admission_does_not_cancel_original(tmp_path, monkeypatch):
    coordinator = _coordinator(tmp_path)
    ticket = await coordinator.admit("r", "a", "start")
    reached = threading.Event()
    unblock = threading.Event()
    original = coordinator._admit_sync

    def replay(*args):
        result = original(*args)
        reached.set()
        assert unblock.wait(3)
        return result

    monkeypatch.setattr(coordinator, "_admit_sync", replay)
    task = asyncio.create_task(coordinator.admit("r", "a", "start"))
    await _wait_until(reached.is_set)
    task.cancel()
    unblock.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with coordinator.run(ticket):
        assert (await coordinator.snapshot())["running"] == 1


@pytest.mark.asyncio
async def test_model_deadline_exception_and_cancel_release_slots(tmp_path):
    api = _api()
    coordinator = _coordinator(tmp_path, model_concurrency=1, model_wait_seconds=0.05)
    async with coordinator.model_slot():
        with pytest.raises(api.ExecutionTimeoutError):
            async with _coordinator(
                tmp_path, model_concurrency=1, model_wait_seconds=0.05
            ).model_slot():
                pytest.fail("model pool exceeded capacity")
    with pytest.raises(ValueError):
        async with coordinator.model_slot():
            raise ValueError("synthetic transport failure")
    entered = asyncio.Event()

    async def transport():
        async with coordinator.model_slot():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(transport())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await coordinator.snapshot())["model_active"] == 0


@pytest.mark.asyncio
async def test_model_acquired_after_deadline_is_released_without_transport(tmp_path, monkeypatch):
    api = _api()
    coordinator = _coordinator(tmp_path, model_wait_seconds=0.03)
    original = coordinator._try_model_slot_sync

    def slow_acquire():
        lock = original()
        time.sleep(0.05)
        return lock

    monkeypatch.setattr(coordinator, "_try_model_slot_sync", slow_acquire)
    with pytest.raises(api.ExecutionTimeoutError):
        async with coordinator.model_slot():
            pytest.fail("transport started after its acquisition deadline")
    assert (await coordinator.snapshot())["model_active"] == 0


@pytest.mark.asyncio
async def test_completed_operations_and_snapshots_do_not_leak_lock_descriptors(tmp_path):
    coordinator = _coordinator(tmp_path)
    await coordinator.snapshot()
    baseline = len(os.listdir("/dev/fd"))
    for index in range(12):
        ticket = await coordinator.admit(f"r-{index}", "a", "start")
        async with coordinator.run(ticket), coordinator.model_slot():
            assert (await coordinator.snapshot())["running"] == 1
    assert len(os.listdir("/dev/fd")) <= baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,limit", [("run", 2), ("model", 2)])
async def test_real_spawned_processes_share_fixed_capacity(tmp_path, kind, limit):
    api = _api()
    policy = api.ExecutionPolicy(model_concurrency=limit)
    coordinator = api.SQLiteExecutionCoordinator(tmp_path / "journal.db", policy)
    await coordinator.snapshot()
    ctx = multiprocessing.get_context("spawn")
    active, peak = ctx.Value("i", 0), ctx.Value("i", 0)
    ready, start = ctx.Queue(), ctx.Event()
    processes = [
        ctx.Process(
            target=_pool_worker,
            args=(
                str(coordinator.db_path),
                asdict(policy),
                kind,
                index,
                active,
                peak,
                ready,
                start,
            ),
        )
        for index in range(4)
    ]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            assert (await asyncio.to_thread(ready.get, True, 10))[0] == "ready"
        start.set()
        for _ in processes:
            assert (await asyncio.to_thread(ready.get, True, 10))[0] == "done"
        for process in processes:
            await asyncio.to_thread(process.join, 3)
            assert process.exitcode == 0
        assert peak.value == limit
        snapshot = await coordinator.snapshot()
        assert snapshot["running"] == snapshot["model_active"] == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
            process.join(3)
        ready.close()


@pytest.mark.asyncio
async def test_paused_owner_is_not_stolen_and_process_exit_recovers_generation(tmp_path):
    api = _api()
    policy = api.ExecutionPolicy(
        global_running_limit=1,
        model_concurrency=1,
        model_wait_seconds=0.05,
        queue_wait_seconds=0.15,
    )
    coordinator = api.SQLiteExecutionCoordinator(tmp_path / "journal.db", policy)
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    process = ctx.Process(
        target=_crash_worker, args=(str(coordinator.db_path), asdict(policy), ready)
    )
    process.start()
    try:
        token, generation = await asyncio.to_thread(ready.get, True, 10)
        os.kill(process.pid, signal.SIGSTOP)
        waiting = await coordinator.admit("waiting", "b", "start")
        with pytest.raises(api.ExecutionTimeoutError):
            async with coordinator.run(waiting):
                pytest.fail("live paused execution was stolen")
        with pytest.raises(api.ExecutionTimeoutError):
            async with coordinator.model_slot():
                pytest.fail("live paused model slot was stolen")
        assert (await coordinator.snapshot())["running"] == 1
        process.kill()
        await asyncio.to_thread(process.join, 3)
        recovery = await coordinator.admit("crash-run", "a", "recover")
        async with coordinator.run(recovery) as lease, coordinator.model_slot():
            assert lease.generation == generation + 1
            with sqlite3.connect(coordinator.db_path) as conn:
                with pytest.raises(api.ExecutionConflictError):
                    coordinator.assert_fence(conn, "crash-run", token, generation)
        assert (await coordinator.snapshot())["running"] == 0
    finally:
        if process.is_alive():
            process.kill()
        process.join(3)
        ready.close()
