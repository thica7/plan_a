"""Outbox protocol against PostgreSQL and a persistent controlled receiver."""

import asyncio
import json
import multiprocessing
import os
import sqlite3
from dataclasses import replace

import psycopg
import pytest

from packages.auth.rbac import EnterpriseUserContext
from packages.config.settings import Settings
from packages.schema.api_dto import RunCreateRequest
from packages.task_center.database import TaskCenterDatabase
from packages.task_center.errors import DispatchConflict
from packages.task_center.models import QuotaSeed
from packages.task_center.repository import SubmissionRepository

pytest_plugins = ("postgres_support",)
ACTOR = EnterpriseUserContext("outbox-tester", "owner", "default-workspace")
SEED = QuotaSeed(run_limit=100, enforcement="block")


def settings(dsn):
    return Settings(
        task_center_enabled=True,
        task_center_database_url=dsn,
        task_center_pool_min_size=1,
        task_center_pool_max_size=8,
        task_center_pool_max_waiting=128,
        task_center_pool_timeout_seconds=5,
    )


@pytest.fixture
async def relay_repository(task_postgres):
    database = TaskCenterDatabase(settings(task_postgres.app_dsn))
    await database.open()
    try:
        yield SubmissionRepository(database)
    finally:
        await database.close()


async def submit(repo, key="first"):
    return await repo.submit(
        RunCreateRequest(topic="private payload", dimensions=["product"], idempotency_key=key),
        actor=ACTOR,
        seed=SEED,
    )


def expire(postgres, submission_id):
    with psycopg.connect(postgres.owner_dsn) as conn:
        conn.execute(
            "UPDATE task_center.outbox SET lease_until=clock_timestamp()-interval '1 second' "
            "WHERE submission_id=%s",
            (submission_id,),
        )


async def history(repo, submission_id):
    async with repo.database.transaction("", service_role=True) as conn:
        return await (
            await conn.execute(
                "SELECT generation,epoch,outcome,error_code,sanitized_error,sent_intent_at "
                "FROM task_center.dispatch_attempts WHERE submission_id=%s ORDER BY generation",
                (submission_id,),
            )
        ).fetchall()


async def test_expired_claim_recovers_with_a_new_generation(relay_repository, task_postgres):
    repo = relay_repository
    view = await submit(repo)
    first = await repo.claim(submission_id=view.id)
    expire(task_postgres, view.id)
    second = await repo.claim(submission_id=view.id)
    assert second.generation == 2
    assert second.owner_token != first.owner_token
    assert [row["outcome"] for row in await history(repo, view.id)] == ["expired", "claimed"]


async def test_send_ack_binds_identity_and_only_marks_dispatched(relay_repository):
    from packages.task_center.dispatch import DispatchReceipt

    repo = relay_repository
    view = await submit(repo)
    claim = await repo.claim(submission_id=view.id)
    assert await repo.mark_sending(claim)
    assert await repo.acknowledge(claim, DispatchReceipt(claim.expected_run_id, "wf-test"))
    public = await repo.get("default-workspace", view.id)
    assert public.status == "dispatched" and public.run_id == view.expected_run_id
    assert public.workflow_id == "wf-test"
    assert "completed" not in public.model_dump_json()
    assert (await history(repo, view.id))[0]["outcome"] == "succeeded"
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1


async def test_expired_third_owner_exhausts_budget_and_retry_gets_new_epoch(
    relay_repository,
    task_postgres,
):
    repo = relay_repository
    view = await submit(repo)
    claims = []
    for _ in range(3):
        claim = await repo.claim(submission_id=view.id)
        claims.append(claim)
        expire(task_postgres, view.id)
    assert await repo.claim(submission_id=view.id) is None
    assert (await repo.get("default-workspace", view.id)).status == "dispatch_failed"
    assert [r["outcome"] for r in await history(repo, view.id)] == ["expired"] * 3
    retried = await repo.retry_dispatch("default-workspace", view.id, actor=ACTOR)
    fourth = await repo.claim(submission_id=view.id)
    assert fourth.epoch == 2 and fourth.generation == 4 and fourth.attempt_count == 1
    assert fourth.expected_run_id == retried.expected_run_id == view.expected_run_id
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    assert len((await repo.quota_ledger("default-workspace")).items) == 1


async def test_failure_has_finite_backoff_and_never_refunds_after_send_intent(
    relay_repository,
    task_postgres,
):
    repo = relay_repository
    view = await submit(repo)
    claim = await repo.claim(submission_id=view.id)
    assert await repo.mark_sending(claim)
    assert await repo.fail(claim, error_code="secret postgres://password", retry_delay_seconds=2)
    assert (await repo.get("default-workspace", view.id)).status == "pending"
    assert await repo.claim() is None
    attempt = (await history(repo, view.id))[0]
    assert attempt["outcome"] == "unknown"
    assert attempt["error_code"] == "dispatch_error"
    assert "secret" not in str(attempt)
    with pytest.raises(DispatchConflict):
        await repo.cancel("default-workspace", view.id, actor=ACTOR)
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "UPDATE task_center.outbox SET available_at=clock_timestamp()-interval '1 second'"
        )
    for attempt_number in (2, 3):
        claim = await repo.claim(submission_id=view.id)
        assert claim.attempt_count == attempt_number
        assert await repo.mark_sending(claim)
        assert await repo.fail(claim, retry_delay_seconds=0)
    assert (await repo.get("default-workspace", view.id)).status == "dispatch_failed"
    assert len(await history(repo, view.id)) == 3


async def test_relay_dispatches_outside_transactions_and_rejects_wrong_identity(
    relay_repository,
    task_postgres,
):
    from packages.task_center.dispatch import DispatchReceipt
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    view = await submit(repo)
    probes = []

    async def dispatch(claim):
        with psycopg.connect(task_postgres.owner_dsn) as conn:
            probes.append(
                conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name='task-center' "
                    "AND state='idle in transaction'"
                ).fetchone()[0]
            )
            # NOWAIT also proves no submission/outbox business lock spans dispatch.
            conn.execute(
                "SELECT id FROM task_center.submissions WHERE id=%s FOR UPDATE NOWAIT", (view.id,)
            )
            conn.execute(
                "SELECT id FROM task_center.outbox WHERE submission_id=%s FOR UPDATE NOWAIT",
                (view.id,),
            )
        return DispatchReceipt("wrong-run")

    result = await OutboxRelay(repo, dispatch, retry_base_seconds=0).run_once()
    assert result.status == "retry_scheduled"
    assert probes == [0]
    public = await repo.get("default-workspace", view.id)
    assert public.status == "pending" and public.run_id is None
    assert public.last_error_code == "receipt_mismatch"


async def test_timeout_and_cancellation_release_connections_keep_quota_and_hide_errors(
    relay_repository,
):
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    view = await submit(repo)
    entered = asyncio.Event()

    async def hanging(claim):
        entered.set()
        await asyncio.Event().wait()

    relay = OutboxRelay(
        repo, hanging, lease_seconds=2, dispatch_timeout_seconds=0.02, retry_base_seconds=0
    )
    assert (await relay.run_once()).status == "retry_scheduled"
    assert (await history(repo, view.id))[0]["error_code"] == "dispatch_timeout"
    relay = OutboxRelay(
        repo, hanging, lease_seconds=2, dispatch_timeout_seconds=1, retry_base_seconds=0
    )
    entered.clear()
    task = asyncio.create_task(relay.run_once())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await history(repo, view.id))[1]["error_code"] == "dispatch_cancelled"

    async def failing(claim):
        raise RuntimeError("postgres://secret-pass raw private payload")

    assert (await OutboxRelay(repo, failing, retry_base_seconds=0).run_once()).status == "failed"
    attempts = await history(repo, view.id)
    assert all(row["outcome"] == "unknown" for row in attempts)
    assert "secret-pass" not in str(attempts) and "raw private" not in str(attempts)
    assert repo.database.stats()["pool_available"] == repo.database.stats()["pool_size"]
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1


def receiver_init(path):
    with sqlite3.connect(path, timeout=10) as conn:
        conn.executescript(
            "PRAGMA journal_mode=WAL;"
            "CREATE TABLE identities(run_id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE);"
            "CREATE TABLE sends(id INTEGER PRIMARY KEY,run_id TEXT,request_key TEXT,"
            "generation INTEGER,pid INTEGER);"
        )


def receiver_accept(path, claim):
    from packages.identity import compute_run_id_for_idempotency_key
    from packages.task_center.dispatch import DispatchReceipt

    actual_run_id = compute_run_id_for_idempotency_key(claim.request.idempotency_key)
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute(
            "INSERT INTO sends(run_id,request_key,generation,pid) VALUES(?,?,?,?)",
            (actual_run_id, claim.request.idempotency_key, claim.generation, os.getpid()),
        )
        conn.execute(
            "INSERT INTO identities VALUES(?,?) ON CONFLICT DO NOTHING",
            (actual_run_id, claim.request.idempotency_key),
        )
        stored = conn.execute(
            "SELECT run_id FROM identities WHERE request_key=?", (claim.request.idempotency_key,)
        ).fetchone()[0]
        assert stored == actual_run_id
    return DispatchReceipt(actual_run_id)


def relay_child(dsn, receiver_path, barrier, result_queue, crash_before_ack=False):
    """Spawn entry point; owns its pool and exits only its own test process."""
    from packages.task_center.relay import OutboxRelay

    async def run():
        database = TaskCenterDatabase(settings(dsn))
        await database.open()
        try:

            async def dispatch(claim):
                receipt = receiver_accept(receiver_path, claim)
                if crash_before_ack:
                    os._exit(23)
                return receipt

            relay = OutboxRelay(SubmissionRepository(database), dispatch)
            if barrier is not None:
                barrier.wait(timeout=10)
            results = []
            for _ in range(100):
                result = await relay.run_once()
                if result.status == "idle":
                    break
                results.append((result.submission_id, result.status))
            result_queue.put((os.getpid(), results))
        finally:
            await database.close()

    asyncio.run(run())


async def join_children(processes):
    try:
        await asyncio.gather(*(asyncio.to_thread(p.join, 20) for p in processes))
        assert all(not p.is_alive() for p in processes), "owned test process did not finish"
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)


async def test_two_spawn_processes_claim_same_batch_exactly_once(
    relay_repository,
    task_postgres,
    tmp_path,
):
    repo = relay_repository
    views = [await submit(repo, f"parallel-{n}") for n in range(24)]
    path = str(tmp_path / "receiver.sqlite")
    receiver_init(path)
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(2), context.Queue()
    processes = [
        context.Process(target=relay_child, args=(task_postgres.app_dsn, path, barrier, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    await join_children(processes)
    assert [p.exitcode for p in processes] == [0, 0]
    results = [queue.get(timeout=2) for _ in processes]
    assert all(rows for _, rows in results), "both real workers must dispatch"
    dispatched = [row for _, rows in results for row in rows]
    assert len(dispatched) == len({row[0] for row in dispatched}) == len(views)
    assert all(status == "dispatched" for _, status in dispatched)
    with sqlite3.connect(path) as conn:
        identities = conn.execute("SELECT count(*) FROM identities").fetchone()[0]
        sends = conn.execute("SELECT count(*) FROM sends").fetchone()[0]
        worker_pids = conn.execute("SELECT count(DISTINCT pid) FROM sends").fetchone()[0]
    assert identities == sends == 24 and worker_pids == 2
    for view in views:
        attempts = await history(repo, view.id)
        assert [(row["generation"], row["outcome"]) for row in attempts] == [(1, "succeeded")]
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 24
    print(
        "TASK3_MULTIPROCESS "
        + json.dumps(
            {
                "processes": 2,
                "attempts": 24,
                "business_identities": identities,
                "receiver_sends": sends,
                "worker_pids": worker_pids,
            }
        )
    )


async def test_child_dies_after_durable_acceptance_replay_preserves_business_identity(
    relay_repository,
    task_postgres,
    tmp_path,
):
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    view = await submit(repo)
    path = str(tmp_path / "receiver.sqlite")
    receiver_init(path)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    child = context.Process(
        target=relay_child, args=(task_postgres.app_dsn, path, None, queue, True)
    )
    child.start()
    await join_children([child])
    assert child.exitcode == 23
    assert (await repo.get("default-workspace", view.id)).status == "dispatching"
    assert (await history(repo, view.id))[0]["outcome"] == "sending"
    expire(task_postgres, view.id)

    async def dispatch(claim):
        assert claim.expected_run_id == view.expected_run_id
        return receiver_accept(path, claim)

    result = await OutboxRelay(repo, dispatch).run_once()
    assert result.status == "dispatched"
    public = await repo.get("default-workspace", view.id)
    assert public.run_id == public.expected_run_id == view.expected_run_id
    assert [(row["generation"], row["outcome"]) for row in await history(repo, view.id)] == [
        (1, "unknown"),
        (2, "succeeded"),
    ]
    with sqlite3.connect(path) as conn:
        identities = conn.execute("SELECT count(*) FROM identities").fetchone()[0]
        sends = conn.execute("SELECT count(*) FROM sends").fetchone()[0]
        generations = [row[0] for row in conn.execute("SELECT generation FROM sends ORDER BY id")]
    assert identities == 1 and sends == 2 and generations == [1, 2]
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    print(
        "TASK3_CRASH_REPLAY "
        + json.dumps(
            {
                "child_exitcode": child.exitcode,
                "business_identities": identities,
                "receiver_sends": sends,
                "generations": generations,
                "outcomes": ["unknown", "succeeded"],
                "reserved_count": 1,
            }
        )
    )


async def test_paused_old_sender_cannot_ack_or_fail_after_new_owner_dispatches(
    relay_repository,
    task_postgres,
    tmp_path,
):
    from packages.task_center.dispatch import DispatchReceipt
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    view = await submit(repo)
    path = str(tmp_path / "receiver.sqlite")
    receiver_init(path)
    entered, resume = asyncio.Event(), asyncio.Event()
    old_claims = []

    async def old_dispatch(claim):
        old_claims.append(claim)
        receipt = receiver_accept(path, claim)
        entered.set()
        await resume.wait()
        return receipt

    old_task = asyncio.create_task(OutboxRelay(repo, old_dispatch).run_once())
    await asyncio.wait_for(entered.wait(), 3)
    expire(task_postgres, view.id)

    async def new_dispatch(claim):
        return receiver_accept(path, claim)

    assert (await OutboxRelay(repo, new_dispatch).run_once()).status == "dispatched"
    resume.set()
    assert (await old_task).status == "lease_lost"
    old = old_claims[0]
    assert not await repo.acknowledge(old, DispatchReceipt(old.expected_run_id))
    assert not await repo.fail(old, retry_delay_seconds=0)
    assert not await repo.mark_sending(old)
    assert (await repo.get("default-workspace", view.id)).status == "dispatched"
    assert [r["outcome"] for r in await history(repo, view.id)] == ["unknown", "succeeded"]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM identities").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sends").fetchone()[0] == 2


async def test_pre_send_recheck_wrong_token_and_expired_lease_never_send(
    relay_repository, task_postgres
):
    from packages.task_center.dispatch import DispatchReceipt

    repo = relay_repository
    view = await submit(repo)
    old = await repo.claim(submission_id=view.id)
    forged = replace(old, owner_token="00000000-0000-0000-0000-000000000000")
    assert not await repo.mark_sending(forged)
    assert not await repo.acknowledge(forged, DispatchReceipt(old.expected_run_id))
    assert not await repo.fail(forged)
    expire(task_postgres, view.id)
    assert not await repo.mark_sending(old)
    assert not await repo.acknowledge(old, DispatchReceipt(old.expected_run_id))
    assert not await repo.fail(old)
    assert (await history(repo, view.id))[0]["sent_intent_at"] is None
    new = await repo.claim(submission_id=view.id)
    assert await repo.mark_sending(new)
    assert not await repo.mark_sending(new), "a single claim may only send once"
    with pytest.raises(DispatchConflict):
        await repo.acknowledge(new, DispatchReceipt("wrong-run"))
    assert (await repo.get("default-workspace", view.id)).status == "dispatching"


async def test_pending_without_any_send_intent_can_still_cancel(relay_repository):
    repo = relay_repository
    view = await submit(repo)
    claim = await repo.claim(submission_id=view.id)
    assert await repo.fail(claim, unknown=False, retry_delay_seconds=0)
    assert (await repo.cancel("default-workspace", view.id, actor=ACTOR)).status == "cancelled"
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 0
    assert [r["action"] for r in await raw_ledger(repo)] == ["reserve", "release"]


async def raw_ledger(repo):
    async with repo.database.transaction("default-workspace") as conn:
        return await (
            await conn.execute(
                "SELECT action FROM task_center.quota_entries ORDER BY created_at,id"
            )
        ).fetchall()


async def test_last_sending_owner_crash_exhausts_and_manual_retry_keeps_all_identity(
    relay_repository,
    task_postgres,
):
    repo = relay_repository
    view = await submit(repo)
    for _ in range(3):
        claim = await repo.claim(submission_id=view.id)
        assert await repo.mark_sending(claim)
        expire(task_postgres, view.id)
    assert await repo.claim(submission_id=view.id) is None
    assert (await repo.get("default-workspace", view.id)).status == "dispatch_failed"
    assert [r["outcome"] for r in await history(repo, view.id)] == ["unknown"] * 3
    retried = await repo.retry_dispatch("default-workspace", view.id, actor=ACTOR)
    assert retried.dispatch_attempt_count == 0
    with pytest.raises(DispatchConflict):
        await repo.cancel("default-workspace", view.id, actor=ACTOR)
    for generation in (4, 5, 6):
        claim = await repo.claim(submission_id=view.id)
        assert (claim.epoch, claim.generation, claim.attempt_count) == (
            2,
            generation,
            generation - 3,
        )
        assert claim.expected_run_id == view.expected_run_id
        assert claim.request.idempotency_key == f"task-submission:{view.id}"
        assert await repo.mark_sending(claim)
        assert await repo.fail(claim, retry_delay_seconds=0)
    assert (await repo.get("default-workspace", view.id)).status == "dispatch_failed"
    assert len(await history(repo, view.id)) == 6
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    assert len((await repo.quota_ledger("default-workspace")).items) == 1


async def test_cancel_and_relay_race_preserves_release_and_intent_exclusion(
    relay_repository,
    monkeypatch,
):
    from packages.task_center.dispatch import DispatchReceipt
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    tally = {"cancelled": 0, "dispatched": 0}

    started = asyncio.Event()
    cancel_locked, resume_cancel = asyncio.Event(), asyncio.Event()
    pause_cancel = False
    original_locked_submission = repo._locked_submission

    async def locked_submission(conn, workspace_id, submission_id):
        nonlocal pause_cancel
        row = await original_locked_submission(conn, workspace_id, submission_id)
        if pause_cancel:
            pause_cancel = False
            cancel_locked.set()
            await resume_cancel.wait()
        return row

    monkeypatch.setattr(repo, "_locked_submission", locked_submission)

    async def dispatch(claim):
        started.set()
        return DispatchReceipt(claim.expected_run_id)

    async def cancel_after_claim(view):
        await started.wait()
        return await repo.cancel("default-workspace", view.id, actor=ACTOR)

    for n in range(12):
        started.clear()
        view = await submit(repo, f"race-{n}")
        if n % 2:
            cancelled, relayed = await asyncio.gather(
                cancel_after_claim(view),
                OutboxRelay(repo, dispatch).run_once(),
                return_exceptions=True,
            )
        else:
            cancel_locked.clear()
            resume_cancel.clear()
            pause_cancel = True
            cancelling = asyncio.create_task(repo.cancel("default-workspace", view.id, actor=ACTOR))
            try:
                # Wait for the real SELECT FOR UPDATE to hold the submission
                # lock, then let Relay contend while cancellation is uncommitted.
                await asyncio.wait_for(cancel_locked.wait(), 3)
                relayed = await OutboxRelay(repo, dispatch).run_once()
                assert not cancelling.done()
            finally:
                resume_cancel.set()
                cancelled = await cancelling
        public = await repo.get("default-workspace", view.id)
        tally[public.status] += 1
        attempts = await history(repo, view.id)
        if public.status == "cancelled":
            assert cancelled.status == "cancelled" and relayed.status == "idle"
            assert not attempts
        else:
            assert isinstance(cancelled, DispatchConflict) and relayed.status == "dispatched"
            assert [r["outcome"] for r in attempts] == ["succeeded"]
    assert tally == {"cancelled": 6, "dispatched": 6}
    ledger = await raw_ledger(repo)
    assert sum(row["action"] == "reserve" for row in ledger) == 12
    assert sum(row["action"] == "release" for row in ledger) == tally["cancelled"]
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == tally["dispatched"]
    print("TASK3_CANCEL_RACE " + json.dumps(tally))


async def test_concurrent_run_once_calls_respect_relay_bound(relay_repository):
    from packages.task_center.dispatch import DispatchReceipt
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    for n in range(9):
        await submit(repo, f"bounded-{n}")
    active, maximum = 0, 0

    async def dispatch(claim):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.025)
        active -= 1
        return DispatchReceipt(claim.expected_run_id)

    relay = OutboxRelay(repo, dispatch, concurrency=3)
    results = await asyncio.gather(*(relay.run_once() for _ in range(9)))
    assert all(row.status == "dispatched" for row in results)
    assert maximum == 3 and active == 0


async def test_cancel_cleanup_storage_failure_preserves_cancellation_and_recoverable_lease(
    relay_repository,
    task_postgres,
):
    from packages.task_center.relay import OutboxRelay

    repo = relay_repository
    view = await submit(repo)
    entered = asyncio.Event()

    async def waiting(claim):
        entered.set()
        await asyncio.Event().wait()

    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION task_center.reject_retry_audit() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$"
        )
        conn.execute(
            "CREATE TRIGGER retry_audit_failure BEFORE INSERT ON task_center.audit_events "
            "FOR EACH ROW WHEN (NEW.event_type='dispatch_retry_scheduled') "
            "EXECUTE FUNCTION task_center.reject_retry_audit()"
        )
    task = asyncio.create_task(OutboxRelay(repo, waiting).run_once())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        with psycopg.connect(task_postgres.owner_dsn) as conn:
            conn.execute("DROP TRIGGER retry_audit_failure ON task_center.audit_events")
    assert (await repo.get("default-workspace", view.id)).status == "dispatching"
    assert (await history(repo, view.id))[0]["outcome"] == "sending"
    assert repo.database.stats()["pool_available"] == repo.database.stats()["pool_size"]
    expire(task_postgres, view.id)
    assert (await repo.claim(submission_id=view.id)).generation == 2
    assert (await history(repo, view.id))[0]["outcome"] == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"lease_seconds": "invalid"},
        {"lease_seconds": True},
        {"lease_seconds": float("nan")},
        {"dispatch_timeout_seconds": 30},
        {"dispatch_timeout_seconds": 0},
        {"retry_base_seconds": float("inf")},
        {"concurrency": 0},
        {"max_attempts": True},
    ],
)
async def test_relay_rejects_invalid_settings_with_safe_error(relay_repository, changes):
    from packages.task_center.errors import InvalidTaskCenterRequest
    from packages.task_center.relay import OutboxRelay

    async def dispatch(claim):
        raise AssertionError("invalid configuration must never dispatch")

    with pytest.raises(InvalidTaskCenterRequest):
        OutboxRelay(relay_repository, dispatch, **changes)


async def test_relay_deadline_does_not_depend_on_host_wall_clock(
    relay_repository,
    monkeypatch,
):
    from datetime import UTC, datetime, timedelta

    import packages.task_center.relay as relay_module
    from packages.task_center.dispatch import DispatchReceipt

    class SkewedClock(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return datetime.now(tz) + timedelta(days=1)

    # Only the process wall clock is skewed. PostgreSQL still grants a live lease.
    monkeypatch.setattr(relay_module, "datetime", SkewedClock, raising=False)
    repo = relay_repository
    view = await submit(repo)
    sent = []

    async def dispatch(claim):
        sent.append(claim.submission_id)
        return DispatchReceipt(claim.expected_run_id)

    result = await relay_module.OutboxRelay(repo, dispatch).run_once()
    assert result.status == "dispatched" and sent == [view.id]
