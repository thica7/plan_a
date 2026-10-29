"""Existing entrypoints with real PostgreSQL, journal, execution fences and demo Graph."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from packages.auth import EnterpriseUserContext
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.runtime import CreateRunCommand, RuntimeCommandError, RuntimeCommandService
from packages.schema.api_dto import RunCreateRequest
from packages.schema.enterprise import ProjectRecord, WorkspaceQuotaUpdateRequest
from packages.skills.registry import SkillRegistry
from packages.task_center.bridge import dispatch_authorization
from packages.task_center.database import TaskCenterDatabase
from packages.task_center.errors import (
    DispatchConflict,
    IdempotencyConflict,
    QuotaExceeded,
)
from packages.task_center.models import QuotaSeed
from packages.task_center.repository import SubmissionRepository
from packages.task_center.service import TaskCenterService
from packages.workflows.activities import (
    CompetitiveIntelActivities,
    MonitorActivities,
    ScheduledScanActivities,
)
from packages.workflows.models import (
    MonitorCycleInput,
    MonitorWorkflowInput,
    ScheduledScanProjectInput,
    ScheduledScanTarget,
    ScheduledScanWorkflowInput,
)
from packages.workflows.service import (
    TemporalWorkflowService,
    competitive_intel_input_from_run_request,
)

pytest_plugins = ("postgres_support",)
ACTOR = EnterpriseUserContext(
    user_id="server-actor", role="owner", workspace_id="default-workspace"
)


def request(key="entry", **updates):
    values = dict(
        topic="Task center demo",
        competitors=["Cursor"],
        dimensions=["pricing"],
        execution_mode="demo",
        hitl_enabled=False,
        idempotency_key=key,
    )
    values.update(updates)
    return RunCreateRequest(**values)


class ControlledTemporalClient:
    """Records the actual RPC contract without claiming a live Temporal service."""

    def __init__(self):
        self.inputs = []

    async def start_workflow(self, workflow, arg, **options):
        self.inputs.append((arg, options))
        return SimpleNamespace(id=options["id"])


@pytest.fixture
async def environment(task_postgres, tmp_path):
    settings = Settings(
        task_center_enabled=True,
        task_center_database_url=task_postgres.app_dsn,
        task_center_pool_max_size=4,
        enterprise_store_backend="memory",
        execution_control_enabled=True,
        execution_control_journal_path=str(tmp_path / "runs.db"),
        execution_global_running_limit=2,
        execution_workspace_running_limit=2,
        execution_global_queue_limit=10,
        execution_workspace_queue_limit=10,
        hitl_enabled=False,
        hitl_timeout_seconds=0,
        run_orchestration_backend="langgraph",
    )
    database = TaskCenterDatabase(settings)
    await database.open()
    repo = SubmissionRepository(database)
    store = EnterpriseMemoryStore()
    store.update_workspace_quota(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=1)
    )
    store.projects["project-test"] = ProjectRecord(
        id="project-test",
        workspace_id="default-workspace",
        name="Demo",
        topic="Task center demo",
        topic_normalized="task center demo",
    )
    journal = RunJournal(tmp_path / "runs.db")
    task_service = TaskCenterService(repo, settings=settings, store=store, journal=journal)
    service = RunService(
        SkillRegistry.from_default_path(),
        settings,
        journal=journal,
        enterprise_store=store,
        graph_checkpointer=GraphCheckpointer(tmp_path / "graph.db"),
        submission_service=task_service,
    )
    client = ControlledTemporalClient()

    async def connect(settings):
        return client

    temporal = TemporalWorkflowService(
        settings,
        client_factory=connect,
        run_service=service,
        enterprise_store=store,
        journal=journal,
        submission_service=task_service,
    )
    runtime = RuntimeCommandService(
        settings=settings,
        run_service=service,
        workflow_service=temporal,
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    env = SimpleNamespace(
        settings=settings,
        repo=repo,
        store=store,
        journal=journal,
        task_service=task_service,
        service=service,
        temporal=temporal,
        runtime=runtime,
        client=client,
    )
    yield env
    tasks = list(service._background_tasks.values())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await service._graph_checkpointer.aclose()
    await database.close()


async def assert_single_reservation(env, run_id):
    snapshot = await env.repo.quota_snapshot("default-workspace")
    assert snapshot.reserved_count == 1 and snapshot.available == 0
    async with env.repo.database.transaction("default-workspace") as conn:
        rows = await (await conn.execute("SELECT * FROM task_center.submissions")).fetchall()
        entries = await (
            await conn.execute("SELECT action FROM task_center.quota_entries")
        ).fetchall()
    assert len(rows) == 1 and rows[0]["status"] == "dispatched"
    assert rows[0]["expected_run_id"] == run_id == rows[0]["run_id"]
    assert [entry["action"] for entry in entries] == ["reserve"]
    assert env.journal.load_run(run_id).id == run_id


@pytest.mark.parametrize(
    "entry",
    [
        "run_service",
        "runtime",
        "temporal",
        "competitive_activity",
        "scheduled_activity",
        "monitor_activity",
    ],
)
async def test_real_entry_reserves_once_and_replays_when_available_zero(environment, entry):
    env = environment
    if entry == "run_service":

        async def invoke():
            return (await env.service.create_run(request())).id
    elif entry == "runtime":

        async def invoke():
            return (
                await env.runtime.create_run(CreateRunCommand(request=request()), actor=ACTOR)
            ).run_id
    elif entry == "temporal":

        async def invoke():
            return (await env.temporal.start_competitive_intel(request(), actor=ACTOR)).run_id
    elif entry == "competitive_activity":

        async def invoke():
            return (
                await CompetitiveIntelActivities(env.service).create_run(
                    competitive_intel_input_from_run_request(request())
                )
            ).run_id
    elif entry == "scheduled_activity":
        scan = ScheduledScanProjectInput(
            request=ScheduledScanWorkflowInput(
                workspace_id="default-workspace", execution_mode="demo", dimensions=["pricing"]
            ),
            target=ScheduledScanTarget(
                project_id="project-test",
                workspace_id="default-workspace",
                topic="Task center demo",
                competitors=["Cursor"],
                dimensions=["pricing"],
            ),
            scan_started_at="2026-10-29T00:00:00Z",
        )

        async def invoke():
            return (
                await ScheduledScanActivities(env.service, env.store).run_project_scan(scan)
            ).run_id
    else:
        cycle = MonitorCycleInput(
            request=MonitorWorkflowInput(
                workspace_id="default-workspace",
                project_id="project-test",
                execution_mode="demo",
                dimensions=["pricing"],
            ),
            cycle_index=0,
            monitor_started_at="2026-10-29T00:00:00Z",
        )

        async def invoke():
            return (await MonitorActivities(env.service, env.store).run_cycle(cycle)).run_id

    first = await invoke()
    assert first is not None
    assert await invoke() == first
    await assert_single_reservation(env, first)


async def test_runtime_real_demo_graph_has_durable_checkpoint_and_clears_dispatch_grant(
    environment, monkeypatch
):
    env = environment
    original = env.service._demo_planner_step
    child_results = []

    async def planner(state):
        # A graph child must make an ordinary submission; quota=1 rejects it.
        async def nested():
            with pytest.raises(QuotaExceeded):
                await env.service.create_run(request("graph-child", topic="child request"))
            child_results.append("ordinary-reservation")

        await asyncio.create_task(nested())
        return await original(state)

    monkeypatch.setattr(env.service, "_demo_planner_step", planner)
    result = await env.runtime.create_run(CreateRunCommand(request=request()), actor=ACTOR)
    tasks = list(env.service._background_tasks.values())
    await asyncio.gather(*tasks)
    persisted = RunJournal(env.journal.db_path).load_run(result.run_id)
    assert persisted.status in {"completed", "completed_with_blockers"}
    assert child_results == ["ordinary-reservation"]
    assert any(event.type == "run_completed" for event in env.journal.load_events(result.run_id))
    saver = await env.service._graph_checkpointer.open()
    assert [item async for item in saver.alist(None)]
    await assert_single_reservation(env, result.run_id)


async def test_delivery_intent_conflict_and_original_backend_survive_configuration_change(
    environment,
):
    env = environment
    first = await env.temporal.start_competitive_intel(request(), actor=ACTOR)
    with pytest.raises(IdempotencyConflict):
        await env.service.create_run(request())
    assert len(env.client.inputs) == 1
    # Runtime's route can be replayed after configuration changes without using the new backend.
    await env.task_service.update_policy(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=2), actor=ACTOR
    )
    env.runtime._settings = replace(
        env.settings, run_orchestration_backend="temporal", temporal_traffic_percent=100
    )
    runtime = await env.runtime.create_run(
        CreateRunCommand(request=request("runtime-route")), actor=ACTOR
    )
    env.runtime._settings = replace(env.settings, run_orchestration_backend="langgraph")
    replay = await env.runtime.create_run(
        CreateRunCommand(request=request("runtime-route")), actor=ACTOR
    )
    assert replay.route == runtime.route == "temporal" and replay.run_id == runtime.run_id
    assert len(env.client.inputs) == 2 and first.run_id != runtime.run_id


async def test_only_create_is_never_started_by_relay_replay(environment):
    env = environment
    view = await env.repo.submit(
        request(), actor=ACTOR, seed=QuotaSeed(1, "block"), delivery_intent="create_only"
    )
    claim = await env.repo.claim(submission_id=view.id)
    assert await env.repo.mark_sending(claim)
    receipt = await env.task_service.dispatch(
        claim, run_service=env.service, workflow_service=env.temporal
    )
    assert receipt.run_id == view.expected_run_id
    assert not env.service._background_tasks and not env.client.inputs
    assert await env.repo.acknowledge(claim, receipt)


async def test_private_grant_rechecks_payload_owner_generation_and_lease(environment):
    env = environment
    view = await env.repo.submit(
        request(), actor=ACTOR, seed=QuotaSeed(1, "block"), delivery_intent="create_only"
    )
    claim = await env.repo.claim(submission_id=view.id)
    assert await env.repo.mark_sending(claim)
    for forged in (
        replace(claim, owner_token="00000000-0000-0000-0000-000000000000"),
        replace(claim, generation=claim.generation + 1),
    ):
        with dispatch_authorization(forged), pytest.raises(DispatchConflict):
            await env.service.create_run(claim.request)
    with dispatch_authorization(claim), pytest.raises(DispatchConflict):
        await env.service.create_run(claim.request.model_copy(update={"topic": "forged payload"}))
    async with env.repo.database.transaction("default-workspace") as conn:
        await conn.execute(
            "UPDATE task_center.outbox SET lease_until=clock_timestamp()-interval '1 second' "
            "WHERE submission_id=%s",
            (view.id,),
        )
    with dispatch_authorization(claim), pytest.raises(DispatchConflict):
        await env.service.create_run(claim.request)
    assert env.journal.load_run(view.expected_run_id) is None


async def test_public_internal_key_is_not_an_authorization(environment):
    env = environment
    first = await env.service.create_run(request())
    with pytest.raises(QuotaExceeded):
        await env.service.create_run(request(first.idempotency_key))
    await assert_single_reservation(env, first.id)


async def test_temporal_activity_revalidates_persisted_identity_without_context(environment):
    env = environment
    first = await env.temporal.start_competitive_intel(request(), actor=ACTOR)
    workflow_input = env.client.inputs[0][0]
    activity = CompetitiveIntelActivities(env.service)
    assert (await activity.create_run(workflow_input)).run_id == first.run_id
    with pytest.raises(DispatchConflict):
        await activity.create_run(replace(workflow_input, topic="altered"))
    await assert_single_reservation(env, first.run_id)


async def test_memory_restart_cannot_replace_persistent_quota_policy(environment):
    env = environment
    await env.service.create_run(request())
    await env.task_service.update_policy(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=0), actor=ACTOR
    )
    restarted = EnterpriseMemoryStore()
    env.task_service.store = restarted
    seed = await env.task_service.quota_seed("default-workspace")
    assert seed.run_limit == 0 and seed.policy_version == 2
    with pytest.raises(QuotaExceeded):
        await env.service.create_run(request("restart"))


async def test_actual_start_requires_execution_control_before_receiver(environment):
    env = environment
    env.task_service.settings = replace(env.settings, execution_control_enabled=False)
    with pytest.raises(RuntimeCommandError) as failure:
        await env.runtime.create_run(CreateRunCommand(request=request()), actor=ACTOR)
    assert failure.value.status_code == 503
    assert not env.journal.load_run_summaries() and not env.client.inputs


async def test_active_fingerprint_cannot_replace_expected_run_id(environment):
    env = environment
    await env.task_service.update_policy(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=2), actor=ACTOR
    )
    first = await env.service.create_run(request())
    second = await env.service.create_run(request("second"))
    assert first.id != second.id
    snapshot = await env.repo.quota_snapshot("default-workspace")
    assert snapshot.reserved_count == 2


async def test_competing_claim_returns_busy_without_another_run(environment):
    env = environment
    view = await env.repo.submit(
        request(), actor=ACTOR, seed=QuotaSeed(1, "block"), delivery_intent="create_only"
    )
    assert await env.repo.claim(submission_id=view.id) is not None
    with pytest.raises(DispatchConflict):
        await env.service.create_run(request())
    assert not env.journal.load_run_summaries()


async def test_inline_cancel_preserves_cancellation_when_cleanup_storage_fails(
    environment, monkeypatch
):
    from packages.task_center.errors import TaskCenterStorageError

    env = environment
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    async def failed_cleanup(*args, **kwargs):
        raise TaskCenterStorageError()

    monkeypatch.setattr(env.task_service, "_deliver", blocked)
    monkeypatch.setattr(env.repo, "fail", failed_cleanup)
    pending = asyncio.create_task(env.service.create_run(request()))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    snapshot = await env.repo.quota_snapshot("default-workspace")
    assert snapshot.reserved_count == 1


async def test_history_import_reads_real_journal_without_list_runs_repair(environment, monkeypatch):
    env = environment
    legacy = RunService(
        SkillRegistry.from_default_path(),
        replace(env.settings, task_center_enabled=False),
        journal=env.journal,
        enterprise_store=env.store,
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    await legacy.create_run(request("legacy"))

    def forbidden():
        raise AssertionError("history import must not repair runs")

    monkeypatch.setattr(env.service, "list_runs", forbidden)
    try:
        with pytest.raises(QuotaExceeded):
            await env.service.create_run(request())
        # The rejected first transaction rolls back bootstrap; query the trusted
        # read path to durably initialize the same historical quota bucket.
        snapshot = await env.repo.quota_snapshot(
            "default-workspace", seed=await env.task_service.quota_seed("default-workspace")
        )
        assert snapshot.imported_count == 1 and snapshot.reserved_count == 0
    finally:
        await legacy._graph_checkpointer.aclose()


async def test_new_period_import_excludes_all_task_center_expected_ids(environment):
    env = environment
    created = await env.service.create_run(request())
    now = datetime.now(UTC)
    next_month = (
        now.replace(year=now.year + 1, month=1, day=1)
        if now.month == 12
        else now.replace(month=now.month + 1, day=1)
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    persisted, revision = env.journal.load_run_snapshot(created.id)
    env.journal.save_run(
        persisted.model_copy(update={"created_at": next_month.replace(tzinfo=None)}),
        expected_revision=revision,
    )
    env.journal.save_run(
        persisted.model_copy(
            update={
                "id": "legacy-next-month",
                "idempotency_key": "legacy-next",
                "created_at": next_month.replace(tzinfo=None),
            }
        ),
        expected_revision=0,
    )
    env.repo._clock = lambda: next_month
    seed = await env.task_service.quota_seed("default-workspace")
    snapshot = await env.repo.quota_snapshot("default-workspace", seed=seed)
    assert snapshot.imported_count == 1 and snapshot.reserved_count == 0


async def test_quota_patch_reports_committed_pg_policy_when_metadata_sync_fails(
    environment, monkeypatch
):
    from fastapi import HTTPException

    from app.routers.enterprise import update_workspace_quota

    env = environment

    def broken_metadata(*args, **kwargs):
        raise RuntimeError("private metadata storage failure")

    monkeypatch.setattr(env.store, "update_workspace_quota", broken_metadata)
    with pytest.raises(HTTPException) as failure:
        await update_workspace_quota(
            "default-workspace",
            WorkspaceQuotaUpdateRequest(monthly_run_quota=0),
            env.store,
            ACTOR,
            env.settings,
            env.task_service,
        )
    assert failure.value.status_code == 503
    assert failure.value.detail == "Task-count policy committed; metadata synchronization failed"
    snapshot = await env.repo.quota_snapshot("default-workspace")
    assert snapshot.limit == 0
    assert env.store.list_workspaces()[0].monthly_run_quota == 1
    with pytest.raises(QuotaExceeded):
        await env.service.create_run(request())


async def test_verified_reservation_preserves_token_and_cost_limits(environment):
    from packages.enterprise import WorkspaceQuotaExceededError

    env = environment
    env.store.update_workspace_quota(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_token_quota=0)
    )
    with pytest.raises(WorkspaceQuotaExceededError) as failure:
        await env.service.create_run(request())
    assert failure.value.decision.usage.token_usage_ratio >= 1
    assert not env.journal.load_run_summaries()


async def test_scheduled_control_workflow_does_not_reserve_cycles(environment):
    from packages.schema.api_dto import MonitorStartRequest, ScheduledScanStartRequest

    env = environment
    await env.temporal.start_scheduled_scan(
        ScheduledScanStartRequest(workspace_id="default-workspace", execution_mode="demo")
    )
    await env.temporal.start_monitor(
        MonitorStartRequest(
            workspace_id="default-workspace", project_id="project-test", execution_mode="demo"
        )
    )
    async with env.repo.database.transaction("default-workspace") as conn:
        assert (
            await (
                await conn.execute("SELECT count(*) AS n FROM task_center.submissions")
            ).fetchone()
        )["n"] == 0
    assert len(env.client.inputs) == 2


async def test_inline_sending_timeout_is_bounded_and_keeps_reservation(environment, monkeypatch):
    env = environment
    env.task_service.settings = replace(env.settings, task_center_dispatch_lease_seconds=0.2)

    async def slow(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(env.task_service, "_deliver", slow)
    started = asyncio.get_running_loop().time()
    with pytest.raises(DispatchConflict):
        await env.service.create_run(request())
    assert asyncio.get_running_loop().time() - started < 0.5
    snapshot = await env.repo.quota_snapshot("default-workspace")
    assert snapshot.reserved_count == 1
    page = await env.repo.list("default-workspace")
    assert page.items[0].last_error_code == "dispatch_timeout"


async def test_monitor_new_cycle_reserves_again_but_retry_keeps_original_metadata(environment):
    env = environment
    activity = MonitorActivities(env.service, env.store)
    cycle = MonitorCycleInput(
        request=MonitorWorkflowInput(
            workspace_id="default-workspace",
            project_id="project-test",
            execution_mode="demo",
            dimensions=["pricing"],
        ),
        cycle_index=0,
        monitor_started_at="2026-10-29T00:00:00Z",
    )
    first = await activity.run_cycle(cycle)
    assert first.run_id
    assert (await activity.run_cycle(cycle)).run_id == first.run_id
    changed = replace(cycle, request=replace(cycle.request, dimensions=["feature"]))
    rejected = await activity.run_cycle(changed)
    assert rejected.status == "failed" and rejected.run_id is None
    next_cycle = await activity.run_cycle(replace(cycle, cycle_index=1))
    assert next_cycle.status == "failed" and next_cycle.run_id is None
    await assert_single_reservation(env, first.run_id)


async def test_runtime_preserves_token_quota_rejection_as_429(environment):
    env = environment
    env.store.update_workspace_quota(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_token_quota=0)
    )
    with pytest.raises(RuntimeCommandError) as failure:
        await env.runtime.create_run(CreateRunCommand(request=request()), actor=ACTOR)
    assert failure.value.status_code == 429


@pytest.mark.parametrize("attempt_limit, status", [(3, "pending"), (1, "dispatch_failed")])
async def test_temporal_activity_can_follow_unknown_rpc_after_lease_has_ended(
    environment, attempt_limit, status
):
    from packages.task_center.dispatch import DispatchReceipt

    env = environment
    view = await env.repo.submit(
        request(),
        actor=ACTOR,
        seed=QuotaSeed(1, "block"),
        delivery_intent="temporal",
        execution_backend="temporal",
    )
    claim = await env.repo.claim(submission_id=view.id)
    assert await env.repo.mark_sending(claim)
    receipt = await env.task_service.dispatch(
        claim, run_service=env.service, workflow_service=env.temporal
    )
    assert isinstance(receipt, DispatchReceipt)
    assert await env.repo.fail(claim, unknown=True, max_attempts=attempt_limit)
    assert (await env.repo.get("default-workspace", view.id)).status == status
    workflow_input = env.client.inputs[0][0]
    activity = CompetitiveIntelActivities(env.service)
    result = await activity.create_run(workflow_input)
    assert result.run_id == view.expected_run_id
    # An activity validates its admission. It cannot acknowledge the sender's outbox.
    assert (await env.repo.get("default-workspace", view.id)).status == status
    assert (await env.repo.quota_snapshot("default-workspace")).reserved_count == 1
    with pytest.raises(DispatchConflict):
        await activity.create_run(replace(workflow_input, topic="changed after unknown RPC"))


async def test_direct_graph_start_fails_closed_without_shared_execution(environment):
    from packages.task_center.errors import TaskCenterConfigurationError

    env = environment
    created = await env.service.create_run(request())
    env.task_service.settings = replace(env.settings, execution_control_enabled=False)
    with pytest.raises(TaskCenterConfigurationError):
        await env.service.run_pipeline(created.id)
    with pytest.raises(TaskCenterConfigurationError):
        env.service.launch_pipeline(created.id)


@pytest.mark.parametrize(
    "second_patch", [{"quota_enforcement": "monitor"}, {"monthly_token_quota": 1234}]
)
async def test_concurrent_partial_policy_patches_merge_under_the_policy_lock(
    environment, monkeypatch, second_patch
):
    env = environment
    await env.repo.quota_snapshot("default-workspace", seed=QuotaSeed(1, "block"))
    original = env.repo.update_trusted_policy
    reached, release = 0, asyncio.Event()

    async def gate(*args, **kwargs):
        nonlocal reached
        reached += 1
        if reached == 2:
            release.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(env.repo, "update_trusted_policy", gate)
    await asyncio.gather(
        env.task_service.update_policy(
            "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=5), actor=ACTOR
        ),
        env.task_service.update_policy(
            "default-workspace", WorkspaceQuotaUpdateRequest(**second_patch), actor=ACTOR
        ),
    )
    snapshot = await env.repo.quota_snapshot("default-workspace")
    assert snapshot.limit == 5
    assert snapshot.enforcement == second_patch.get("quota_enforcement", "block")


@asynccontextmanager
async def legacy_execution_restart(task_database, tmp_path, *, stage, shared):
    """Persist an actual old demo graph, then enable TC at an exhausted quota."""
    from packages.schema.models import QCIssue, RedoScope

    settings = replace(
        task_database.settings,
        execution_control_enabled=shared,
        execution_control_journal_path=str(tmp_path / "legacy-runs.db"),
        hitl_enabled=False,
        hitl_timeout_seconds=0,
        run_orchestration_backend="langgraph",
    )
    store = EnterpriseMemoryStore()
    journal = RunJournal(tmp_path / "legacy-runs.db")
    original = RunService(
        SkillRegistry.from_default_path(),
        replace(settings, task_center_enabled=False),
        journal=journal,
        enterprise_store=store,
        graph_checkpointer=GraphCheckpointer(tmp_path / "legacy-graph.db"),
    )
    current = None
    try:
        created = await original.create_run(
            request("legacy-execution", hitl_enabled=stage == "resume")
        )
        if stage == "recover":
            entered = asyncio.Event()

            async def paused_join(*args):
                entered.set()
                await asyncio.Event().wait()

            original._demo_collect_join_step = paused_join
            running = asyncio.create_task(original.run_pipeline(created.id))
            await asyncio.wait_for(entered.wait(), 3)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            await original.run_pipeline(created.id)
            if stage == "redo":
                persisted = original.get_run(created.id)
                persisted.qa_findings = [
                    QCIssue(
                        id="qa-legacy-execution",
                        severity="blocker",
                        detected_by="coverage",
                        target_agent="writer",
                        field_path="report_md",
                        problem="Missing evidence",
                        redo_scope=RedoScope(kind="writer_only", rationale="Fix gap"),
                    )
                ]
                original._persist_run(created.id)
        store.update_workspace_quota(
            "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=0)
        )
        repo = SubmissionRepository(task_database)
        task_service = TaskCenterService(repo, settings=settings, store=store, journal=journal)
        current = RunService(
            SkillRegistry.from_default_path(),
            settings,
            journal=RunJournal(journal.db_path),
            enterprise_store=store,
            graph_checkpointer=GraphCheckpointer(tmp_path / "legacy-graph.db"),
            submission_service=task_service,
        )
        runtime = RuntimeCommandService(
            settings=settings,
            run_service=current,
            workflow_service=object(),
            enterprise_store=store,
            preference_memory=PreferenceMemoryStore.in_memory(),
        )
        current.get_run(created.id)
        snapshot = await repo.quota_snapshot(
            "default-workspace",
            seed=QuotaSeed(0, "block", journal.load_run_summaries()),
        )
        assert snapshot.available == 0 and snapshot.reserved_count == 0
        yield SimpleNamespace(
            service=current,
            runtime=runtime,
            repo=repo,
            journal=journal,
            run_id=created.id,
        )
    finally:
        if current is not None:
            tasks = set(current._background_tasks.values())
            for record in current._runs.values():
                tasks.update(
                    task for task in (record.pipeline_task, record.resume_task) if task is not None
                )
            if tasks:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
            await current._graph_checkpointer.aclose()
        await original._graph_checkpointer.aclose()


@pytest.mark.parametrize(
    "entry", ["runtime_redo", "start_redo", "run_redo", "resume", "recover", "execution_guard"]
)
async def test_legacy_execution_requires_shared_control_before_mutation(
    task_database, tmp_path, entry
):
    from packages.runtime import RequestRedoCommand, ResumeReviewCommand
    from packages.schema.api_dto import HitlResumeRequest
    from packages.task_center.errors import TaskCenterConfigurationError

    stage = entry if entry in {"resume", "recover"} else "redo"
    async with legacy_execution_restart(task_database, tmp_path, stage=stage, shared=False) as env:
        assert env.service._execution is None
        entered = []
        actual = env.service._invoke_graph

        async def observed(*args, **kwargs):
            entered.append("graph")
            return await actual(*args, **kwargs)

        env.service._invoke_graph = observed
        before, revision = env.journal.load_run_snapshot(env.run_id)
        events = env.journal.load_events(env.run_id)
        try:
            with pytest.raises(TaskCenterConfigurationError):
                if entry == "runtime_redo":
                    await env.runtime.request_redo(
                        RequestRedoCommand(run_id=env.run_id), actor=ACTOR
                    )
                elif entry == "start_redo":
                    await env.service.start_scoped_redo(env.run_id)
                elif entry == "run_redo":
                    await env.service.run_scoped_redo(env.run_id)
                elif entry == "resume":
                    await env.runtime.resume_review(
                        ResumeReviewCommand(
                            run_id=env.run_id,
                            request=HitlResumeRequest(decision="accept"),
                        ),
                        actor=ACTOR,
                    )
                elif entry == "recover":
                    await env.service.recover_run(env.run_id)
                else:
                    async with env.service._execution_guard(env.run_id, "forbidden"):
                        entered.append("guard-body")
        finally:
            tasks = list(env.service._background_tasks.values())
            for record in env.service._runs.values():
                tasks.extend(
                    task for task in (record.pipeline_task, record.resume_task) if task is not None
                )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            after, after_revision = env.journal.load_run_snapshot(env.run_id)
            counts = await env.repo.list("default-workspace")
            evidence = {
                "entry": entry,
                "graph_entered": len(entered),
                "before_revision": revision,
                "after_revision": after_revision,
                "new_submissions": len(counts.items),
            }
            import json

            print("TASK4_FIX1_GATE " + json.dumps(evidence, sort_keys=True))
        assert not entered
        assert not env.service._background_tasks
        assert all(
            record.pipeline_task is None and record.resume_task is None
            for record in env.service._runs.values()
        )
        assert after_revision == revision and after.model_dump() == before.model_dump()
        assert env.journal.load_events(env.run_id) == events
        assert not counts.items


@pytest.mark.parametrize("stage", ["redo", "resume", "recover"])
async def test_legacy_execution_with_shared_control_keeps_exhausted_quota_unchanged(
    task_database, tmp_path, stage
):
    from packages.runtime import RequestRedoCommand, ResumeReviewCommand
    from packages.schema.api_dto import HitlResumeRequest

    async with legacy_execution_restart(task_database, tmp_path, stage=stage, shared=True) as env:
        entered = []
        actual = env.service._invoke_graph

        async def observed(*args, **kwargs):
            entered.append("graph")
            return await actual(*args, **kwargs)

        env.service._invoke_graph = observed
        if stage == "redo":
            result = await env.runtime.request_redo(
                RequestRedoCommand(run_id=env.run_id), actor=ACTOR
            )
            assert result.status == "accepted"
            await asyncio.gather(*list(env.service._background_tasks.values()))
        elif stage == "resume":
            await env.runtime.resume_review(
                ResumeReviewCommand(
                    run_id=env.run_id,
                    request=HitlResumeRequest(decision="accept"),
                ),
                actor=ACTOR,
            )
            await env.service._runs[env.run_id].resume_task
        else:
            await env.service.recover_run(env.run_id)
            await env.service._runs[env.run_id].pipeline_task
        assert entered
        if stage == "redo":
            assert env.journal.load_run(env.run_id).revisions
        snapshot = await env.repo.quota_snapshot("default-workspace")
        assert snapshot.reserved_count == 0 and snapshot.available == 0
        assert not (await env.repo.list("default-workspace")).items


async def test_submission_initialization_keeps_control_write_and_sql_on_same_worker(
    environment, monkeypatch,
):
    import threading
    service, task_service = environment.service, environment.task_service
    original = service._initialize_created_run
    owner = threading.get_ident()
    seen = []
    def initialize(*args):
        seen.append(threading.get_ident())
        assert threading.get_ident() != owner
        assert service._journal._control_conn.get() is not None
        return original(*args)
    monkeypatch.setattr(service, "_initialize_created_run", initialize)
    result = await task_service.execute(
        request("worker-init"), actor=ACTOR, intent="create_only",
        backend="langgraph", run_service=service,
    )
    assert result.payload.id and len(seen) == 1
    assert service._journal._control_conn.get() is None


async def test_initialization_worker_keeps_loop_free_and_durable_stream_uses_no_queue(
    environment, monkeypatch,
):
    import threading
    env = environment
    entered, release = threading.Event(), threading.Event()
    start = env.store.start_run
    def blocked_start(detail, **kwargs):
        entered.set()
        assert release.wait(3)
        return start(detail, **kwargs)
    monkeypatch.setattr(env.store, "start_run", blocked_start)
    sending = asyncio.create_task(env.task_service.execute(
        request("initialization-stream"), actor=ACTOR, intent="create_only",
        backend="langgraph", run_service=env.service,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        run_id = next(iter(env.service._runs))
        stream = env.service.stream_events(run_id)
        event = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.01)
        assert env.service._runs[run_id].subscribers == []
        assert not event.done()
        release.set()
        result = await sending
        first = await asyncio.wait_for(event, 2)
        assert first.run_id == result.payload.id and first.type == "run_created"
        assert env.service._runs[run_id].subscribers == []
        await stream.aclose()
    finally:
        release.set()
        await sending


async def test_reserved_dispatch_checks_token_cost_policy_on_metadata_worker(
    environment, monkeypatch,
):
    import threading
    env = environment
    owner = threading.get_ident()
    check = env.store.check_workspace_quota
    threads = []
    def verify(workspace_id):
        threads.append(threading.get_ident())
        assert threading.get_ident() != owner
        return check(workspace_id)
    monkeypatch.setattr(env.store, "check_workspace_quota", verify)
    result = await env.task_service.execute(
        request("worker-token-cost"), actor=ACTOR, intent="create_only",
        backend="langgraph", run_service=env.service,
    )
    assert result.payload.id and threads


async def test_policy_metadata_mirror_uses_bounded_worker(environment, monkeypatch):
    import threading

    from app.routers.enterprise import update_workspace_quota
    env = environment
    owner = threading.get_ident()
    update = env.store.update_workspace_quota
    def verify(*args, **kwargs):
        assert threading.get_ident() != owner
        return update(*args, **kwargs)
    monkeypatch.setattr(env.store, "update_workspace_quota", verify)
    workspace = await update_workspace_quota(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=4),
        store=env.store, user=ACTOR, settings=env.settings, task_service=env.task_service,
    )
    assert workspace.monthly_run_quota == 4


async def test_run_service_close_cancels_and_joins_graph_cleanup_before_return(environment):
    env = environment
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def graph():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    task = asyncio.create_task(graph())
    env.service._background_tasks[("shutdown-test", 0)] = task
    await entered.wait()
    closing = asyncio.create_task(env.service.aclose())
    await cleaning.wait()
    assert not closing.done() and env.repo.database.pool is not None
    release.set()
    await closing
    assert task.cancelled()
    env.service._background_tasks.clear()
