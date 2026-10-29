from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from app.events import RunEvent
from packages.config import Settings
from packages.infrastructure.execution_control import (
    ExecutionCapacityError,
    ExecutionConflictError,
    ExecutionUnavailableError,
)
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import AnalysisPlan
from packages.skills.registry import SkillRegistry


def shared_service(path, **overrides):
    options = dict(
        execution_control_enabled=True,
        execution_control_journal_path=str(path),
        execution_global_running_limit=1,
        execution_workspace_running_limit=1,
        execution_global_queue_limit=2,
        execution_workspace_queue_limit=2,
        execution_queue_wait_seconds=2,
        hitl_timeout_seconds=0,
        run_orchestration_backend="langgraph",
    )
    options.update(overrides)
    return RunService(
        SkillRegistry.from_default_path(),
        Settings(**options),
        journal=RunJournal(path),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


def request(key, workspace="default-workspace"):
    return RunCreateRequest(
        topic=key,
        competitors=["Cursor"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key=key,
        workspace_id=workspace,
        hitl_enabled=False,
    )


def detail(run_id="run-cas"):
    return RunDetail(
        id=run_id,
        topic="CAS",
        status="queued",
        execution_mode="demo",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="CAS", competitors=["Cursor"], dimensions=["pricing"]),
    )


async def close_services(*services):
    for service in services:
        await service._graph_checkpointer.aclose()


def test_shared_control_requires_matching_file_journal(tmp_path):
    settings = Settings(
        execution_control_enabled=True, execution_control_journal_path=str(tmp_path / "shared.db")
    )
    for journal in (None, RunJournal.in_memory(), RunJournal(tmp_path / "other.db")):
        with pytest.raises(ExecutionUnavailableError):
            RunService(
                SkillRegistry.from_default_path(),
                settings,
                journal=journal,
                graph_checkpointer=GraphCheckpointer.in_memory(),
            )


def test_journal_snapshot_revision_and_compare_and_swap(tmp_path):
    journal = RunJournal(tmp_path / "journal.db")
    value = detail()
    assert journal.save_run(value, expected_revision=0) == 1
    loaded, revision = journal.load_run_snapshot(value.id)
    assert revision == 1 and loaded.topic == "CAS"
    loaded.topic = "winner"
    assert journal.save_run(loaded, expected_revision=revision) == 2
    value.topic = "stale"
    with pytest.raises(ExecutionConflictError):
        journal.save_run(value, expected_revision=revision)
    assert journal.load_run(value.id).topic == "winner"


@pytest.mark.asyncio
async def test_journal_rejects_unfenced_active_and_released_owner(tmp_path):
    service = shared_service(tmp_path / "journal.db")
    created = await service.create_run(request("fence"))
    ticket = service._execution_tickets[created.id]
    try:
        async with service._execution.run(ticket) as lease:
            with pytest.raises(ExecutionConflictError):
                RunJournal(tmp_path / "journal.db").save_run(created)
            revision = service._journal.save_run(
                created,
                token=lease.token,
                generation=lease.generation,
            )
        with pytest.raises(ExecutionConflictError):
            service._journal.save_run(
                created,
                expected_revision=revision,
                token=lease.token,
                generation=lease.generation,
            )
    finally:
        await close_services(service)


def test_journal_allocates_event_ids_and_never_replaces(tmp_path):
    first = RunJournal(tmp_path / "journal.db")
    second = RunJournal(tmp_path / "journal.db")
    first.save_run(detail())
    one = first.append_event(RunEvent(id=1, run_id="run-cas", type="run_created", message="one"))
    two = second.append_event(RunEvent(id=1, run_id="run-cas", type="run_created", message="two"))
    assert (one.id, two.id) == (1, 2)
    assert [event.message for event in first.load_events("run-cas", after_event_id=1)] == ["two"]


@pytest.mark.asyncio
async def test_shared_pipeline_bounds_queue_and_duplicate_graph(tmp_path, monkeypatch):
    path = tmp_path / "journal.db"
    first, second = shared_service(path), shared_service(path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def invoke(record, **kwargs):
        calls.append(record.detail.id)
        entered.set()
        await release.wait()
        record.detail.status = "completed"
        first._persist_run(record.detail.id)
        return True

    snapshot = SimpleNamespace(values={}, tasks=(), next=())
    monkeypatch.setattr(first, "_pipeline_checkpoint", lambda record: _value(snapshot))
    monkeypatch.setattr(second, "_pipeline_checkpoint", lambda record: _value(snapshot))
    monkeypatch.setattr(first, "_invoke_graph", invoke)
    monkeypatch.setattr(first, "_finalize_demo_pipeline", lambda record: _value(None))
    tasks = []
    try:
        run = await first.create_run(request("first"))
        tasks.append(first.launch_pipeline(run.id))
        await asyncio.wait_for(entered.wait(), 1)
        same = await second.create_run(request("first"))
        assert same.id == run.id
        with pytest.raises(ExecutionConflictError):
            await second.run_pipeline(run.id)
        queued = [await second.create_run(request(f"queued-{index}")) for index in range(2)]
        with pytest.raises(ExecutionCapacityError):
            await second.create_run(request("overflow"))
        assert first.launch_pipeline(run.id) is tasks[0]
        assert calls == [run.id]
        snapshot = await first._execution.snapshot()
        assert snapshot["running"] == 1 and snapshot["queued"] == 2
        assert len(snapshot["tickets"]) == 3
        assert all(second.get_run(item.id).status == "queued" for item in queued)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_services(first, second)


async def _value(value):
    return value


@pytest.mark.asyncio
async def test_resume_handoff_survives_response_and_deduplicates_decision(tmp_path, monkeypatch):
    from packages.schema.api_dto import HitlResumeRequest

    path = tmp_path / "journal.db"
    service, observer = shared_service(path), shared_service(path)
    value = await service.create_run(request("resume"))
    await service._execution.cancel(service._execution_tickets[value.id])
    record = service._runs[value.id]
    value.status, value.current_node = "interrupted", "planner_hitl"
    value.interrupt_graph_kind, value.interrupt_thread_id = "demo", "thread-review"
    service._persist_run(value.id)
    service._hydrate_pending_interrupt_from_detail(record)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def resume_graph(run_id, decision):
        calls.append(run_id)
        entered.set()
        await release.wait()
        record.detail.status = "completed"
        service._persist_run(run_id)

    monkeypatch.setattr(service, "_resume_interrupted_graph", resume_graph)
    try:
        accepted = await service.resume(value.id, HitlResumeRequest(decision="accept"))
        assert accepted.status == "running"
        await asyncio.wait_for(entered.wait(), 1)
        assert (await service._execution.snapshot())["running"] == 1
        duplicate = await observer.resume(value.id, HitlResumeRequest(decision="accept"))
        assert duplicate.status == "running"
        with pytest.raises(ExecutionConflictError):
            await observer.resume(value.id, HitlResumeRequest(decision="redo"))
        assert calls == [value.id]
        release.set()
        await record.resume_task
        # Await the registered lease cleanup, which runs after task completion.
        for _ in range(100):
            if (await service._execution.snapshot())["running"] == 0:
                break
            await asyncio.sleep(0.001)
        assert (await service._execution.snapshot())["running"] == 0
    finally:
        release.set()
        if record.resume_task:
            await asyncio.gather(record.resume_task, return_exceptions=True)
        await close_services(service, observer)


@pytest.mark.asyncio
async def test_control_audit_and_remote_sse_do_not_overwrite_owner(tmp_path):
    path = tmp_path / "journal.db"
    owner, observer = shared_service(path), shared_service(path)
    value = await owner.create_run(request("audit"))
    ticket = owner._execution_tickets[value.id]
    try:
        async with owner._execution.run(ticket):
            value.report_md = "owner report"
            value.status = "running"
            owner._persist_run(value.id)
            await observer.append_control_event(
                value.id,
                "runtime.command",
                "runtime",
                None,
                "audit",
                {"command_id": "same-command"},
            )
            await observer.append_control_event(
                value.id,
                "runtime.command",
                "runtime",
                None,
                "audit",
                {"command_id": "same-command"},
            )
            assert owner._journal.load_run(value.id).report_md == "owner report"
            assert (
                len(
                    [e for e in owner._journal.load_events(value.id) if e.type == "runtime.command"]
                )
                == 1
            )
            stream = observer.stream_events(value.id, after_event_id=1)
            assert (await anext(stream)).message == "audit"
            await stream.aclose()
    finally:
        await close_services(owner, observer)


@pytest.mark.asyncio
async def test_import_refuses_active_owner_before_mutation(tmp_path):
    from packages.schema.survey import UserResearchImportRequest

    service = shared_service(tmp_path / "journal.db")
    value = await service.create_run(request("import"))
    ticket = service._execution_tickets[value.id]
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold():
        async with service._execution.run(ticket):
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold())
    try:
        await entered.wait()
        before = service._runs[value.id].detail.model_dump_json()
        with pytest.raises(ExecutionConflictError):
            service.import_user_research_materials(
                value.id,
                UserResearchImportRequest(
                    materials=[
                        {
                            "source_type": "manual_note",
                            "competitor": "Cursor",
                            "text": "Interview observation",
                        }
                    ]
                ),
            )
        assert service._runs[value.id].detail.model_dump_json() == before
    finally:
        release.set()
        await task
        await close_services(service)


def runtime_for(service, workflow=None):
    from packages.enterprise import EnterpriseMemoryStore
    from packages.memory import PreferenceMemoryStore
    from packages.runtime import RuntimeCommandService

    return RuntimeCommandService(
        settings=service._settings,
        run_service=service,
        workflow_service=workflow or object(),
        enterprise_store=EnterpriseMemoryStore(),
        preference_memory=PreferenceMemoryStore.in_memory(),
    )


@pytest.mark.asyncio
async def test_runtime_api_returns_execution_capacity_and_retry_after(tmp_path, monkeypatch):
    import httpx
    from app import deps
    from app.main import create_app
    from app.rate_limit import SlidingWindowRateLimiter
    from packages.auth import EnterpriseUserContext

    service = shared_service(tmp_path / "api.db", create_run_rate_limit_per_window=100)
    runtime = runtime_for(service)
    entered, release = asyncio.Event(), asyncio.Event()

    async def graph(record, **kwargs):
        entered.set()
        await release.wait()
        return False

    monkeypatch.setattr(
        service,
        "_pipeline_checkpoint",
        lambda record: _value(SimpleNamespace(values={}, tasks=(), next=())),
    )
    monkeypatch.setattr(service, "_invoke_graph", graph)
    app = create_app()
    app.dependency_overrides[deps.get_runtime_command_service] = lambda: runtime
    app.dependency_overrides[deps.get_run_service] = lambda: service
    app.dependency_overrides[deps.get_app_settings] = lambda: service._settings
    app.dependency_overrides[deps.get_create_run_rate_limiter] = SlidingWindowRateLimiter
    app.dependency_overrides[deps.get_enterprise_user_context] = lambda: EnterpriseUserContext(
        "owner", "owner", "default-workspace"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/runs", json=request("api-first").model_dump(mode="json")
            )
            assert response.status_code == 201
            await asyncio.wait_for(entered.wait(), 1)
            for index in range(2):
                response = await client.post(
                    "/api/runs", json=request(f"api-queued-{index}").model_dump(mode="json")
                )
                assert response.status_code == 201
            response = await client.post(
                "/api/runs", json=request("api-overflow").model_dump(mode="json")
            )
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "1"
            assert "admission queue" in response.text
    finally:
        release.set()
        tasks = list(service._background_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_services(service)


@pytest.mark.asyncio
async def test_temporal_route_reserves_before_workflow_start(tmp_path):
    from packages.auth import EnterpriseUserContext
    from packages.runtime import CreateRunCommand

    service = shared_service(tmp_path / "temporal.db", run_orchestration_backend="temporal")
    await service.create_run(request("occupied-1"))
    await service.create_run(request("occupied-2"))
    starts = []

    async def start(value):
        starts.append(value)
        raise AssertionError("full admission must not start a workflow")

    runtime = runtime_for(service, SimpleNamespace(start_competitive_intel=start))
    try:
        with pytest.raises(ExecutionCapacityError):
            await runtime.create_run(
                CreateRunCommand(request=request("temporal-overflow")),
                actor=EnterpriseUserContext("owner", "owner", "default-workspace"),
            )
        assert starts == []
    finally:
        await close_services(service)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["competitive", "scheduled", "monitor"])
async def test_temporal_real_activity_replay_reports_busy(tmp_path, monkeypatch, kind):
    from packages.enterprise import EnterpriseMemoryStore
    from packages.workflows.activities import (
        CompetitiveIntelActivities,
        MonitorActivities,
        ScheduledScanActivities,
        _monitor_cycle_idempotency_key,
        _scheduled_scan_idempotency_key,
    )
    from packages.workflows.models import (
        MonitorCycleInput,
        MonitorWorkflowInput,
        ScheduledScanProjectInput,
        ScheduledScanWorkflowInput,
    )

    store = EnterpriseMemoryStore()
    service = shared_service(tmp_path / "activity.db")
    service._enterprise_store = store
    seed = await service.create_run(request("seed"))
    await service._execution.cancel(service._execution_tickets[seed.id])
    started = "2026-10-28T00:00:00+00:00"
    if kind == "competitive":
        key = "competitive-busy"

        async def call(run_id):
            return await CompetitiveIntelActivities(service).run_langgraph_pipeline(run_id)
    elif kind == "scheduled":
        scan = ScheduledScanActivities(service, store)
        options = ScheduledScanWorkflowInput(
            workspace_id=seed.workspace_id,
            schedule_id="scan",
            project_ids=[seed.project_id],
            dimensions=["pricing"],
        )
        target = (await scan.list_targets(options))[0]
        key = _scheduled_scan_idempotency_key("scan", seed.project_id, started)

        async def call(run_id):
            return await scan.run_project_scan(
                ScheduledScanProjectInput(request=options, target=target, scan_started_at=started)
            )
    else:
        options = MonitorWorkflowInput(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            monitor_id="monitor",
            dimensions=["pricing"],
        )
        key = _monitor_cycle_idempotency_key("monitor", seed.project_id, 0, started)

        async def call(run_id):
            return await MonitorActivities(service, store).run_cycle(
                MonitorCycleInput(request=options, cycle_index=0, monitor_started_at=started)
            )

    created = await service.create_run(
        request(key).model_copy(update={"project_id": seed.project_id}),
        runtime_orchestration_backend="temporal",
        skip_active_duplicate_check=True,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def graph(record, **kwargs):
        entered.set()
        await release.wait()
        return False

    monkeypatch.setattr(
        service,
        "_pipeline_checkpoint",
        lambda record: _value(SimpleNamespace(values={}, tasks=(), next=())),
    )
    monkeypatch.setattr(service, "_invoke_graph", graph)
    task = asyncio.create_task(service.run_pipeline(created.id))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(ExecutionConflictError):
            await call(created.id)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await close_services(service)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["timeout", "cancel", "immediate_cancel", "launch_failure"])
async def test_admitted_background_failure_releases_ticket_and_finishes_queue(
    tmp_path, monkeypatch, outcome
):
    service = shared_service(tmp_path / "failure.db", execution_queue_wait_seconds=0.05)
    first = await service.create_run(request("holder"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold():
        async with service._execution.run(service._execution_tickets[first.id]):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    await entered.wait()
    queued = await service.create_run(request("will-fail"))
    task = None
    try:
        if outcome == "launch_failure":

            def launch(coroutine):
                raise RuntimeError("cannot launch")

            with monkeypatch.context() as patch:
                patch.setattr(asyncio, "create_task", launch)
                with pytest.raises(RuntimeError, match="cannot launch"):
                    service.launch_pipeline(queued.id)
        else:
            task = service.launch_pipeline(queued.id)
            if outcome in {"cancel", "immediate_cancel"}:
                if outcome == "cancel":
                    await asyncio.sleep(0.01)
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert (await service._execution.snapshot())["queued"] == 0
        snapshot = service._journal.load_run(queued.id)
        assert snapshot.status == "failed"
        assert any(
            "execution" in event.message.lower()
            for event in service._journal.load_events(queued.id)
        )
    finally:
        release.set()
        await asyncio.gather(holder, *([task] if task else []), return_exceptions=True)
        await close_services(service)


@pytest.mark.asyncio
async def test_real_demo_graph_children_write_with_inherited_fence(tmp_path):
    service = shared_service(tmp_path / "actual-graph.db")
    value = await service.create_run(request("actual-demo"))
    try:
        result = await service.run_pipeline(value.id)
        assert result.status == "completed"
        assert service._journal.load_run(value.id).report_md
        ids = [event.id for event in service._journal.load_events(value.id)]
        assert ids == list(range(1, len(ids) + 1))
        assert (await service._execution.snapshot())["running"] == 0
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_create_initialization_is_serialized_before_owner_claim(tmp_path):
    import sqlite3

    from packages.enterprise import EnterpriseMemoryStore

    path = tmp_path / "initialize.db"
    service = shared_service(path)
    store = EnterpriseMemoryStore()
    original = store.start_run
    calls = []

    def start(value, **kwargs):
        with sqlite3.connect(path, timeout=0) as connection:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("begin immediate")
        calls.append(value.id)
        return original(value, **kwargs)

    store.start_run = start
    service._enterprise_store = store
    try:
        first = await service.create_run(request("same-create"))
        values = [
            first,
            *(
                await asyncio.gather(
                    *(service.create_run(request("same-create")) for _ in range(7))
                )
            ),
        ]
        assert len({value.id for value in values}) == 1
        assert calls == [values[0].id]
        assert (
            len(
                [
                    event
                    for event in service._journal.load_events(values[0].id)
                    if event.type == "run_created"
                ]
            )
            == 1
        )
    finally:
        await close_services(service)


def test_dependency_uses_configured_shared_journal(tmp_path, monkeypatch):
    from app import deps

    path = tmp_path / "dependency.db"
    monkeypatch.setattr(
        deps,
        "get_app_settings",
        lambda: Settings(execution_control_enabled=True, execution_control_journal_path=str(path)),
    )
    deps.get_run_journal.cache_clear()
    try:
        assert deps.get_run_journal().db_path == path
    finally:
        deps.get_run_journal.cache_clear()


@pytest.mark.asyncio
async def test_runtime_resume_replays_same_decision_after_handoff(tmp_path, monkeypatch):
    from packages.auth import EnterpriseUserContext
    from packages.runtime import ResumeReviewCommand
    from packages.schema.api_dto import HitlResumeRequest

    service = shared_service(tmp_path / "runtime-review.db")
    value = await service.create_run(request("runtime-review"))
    await service._execution.cancel(service._execution_tickets[value.id])
    record = service._runs[value.id]
    value.status, value.current_node = "interrupted", "planner_hitl"
    value.interrupt_graph_kind, value.interrupt_thread_id = "demo", "runtime-thread"
    service._persist_run(value.id)
    service._hydrate_pending_interrupt_from_detail(record)
    entered, release = asyncio.Event(), asyncio.Event()

    async def resume_graph(*args):
        record.detail.current_node = "collector"
        service._persist_run(value.id)
        entered.set()
        await release.wait()

    monkeypatch.setattr(service, "_resume_interrupted_graph", resume_graph)
    runtime = runtime_for(service)
    command = ResumeReviewCommand(run_id=value.id, request=HitlResumeRequest(decision="accept"))
    actor = EnterpriseUserContext("owner", "owner", "default-workspace")
    try:
        await runtime.resume_review(command, actor=actor)
        await entered.wait()
        replay = await runtime.resume_review(command, actor=actor)
        assert replay.payload.status == "running"
    finally:
        release.set()
        if record.resume_task:
            await asyncio.gather(record.resume_task, return_exceptions=True)
            await record.execution_lease.wait_closed()
        await close_services(service)


def test_shared_journal_storage_failure_is_typed(tmp_path):
    import sqlite3

    path = tmp_path / "storage.db"
    journal = RunJournal(path)
    value = detail()
    journal.save_run(value)
    with sqlite3.connect(path) as conn:
        conn.execute("drop table runs")
    with pytest.raises(ExecutionUnavailableError):
        journal.save_run(value)


@pytest.mark.asyncio
async def test_hitl_timeout_uses_new_owner_after_graph_releases_slot(tmp_path):
    service = shared_service(tmp_path / "timer.db", hitl_timeout_seconds=0.03)
    value = await service.create_run(
        request("timeout-review").model_copy(
            update={
                "hitl_enabled": True,
                "collaboration_mode": "assisted",
            }
        )
    )
    try:
        result = await service.run_pipeline(value.id)
        assert result.status == "interrupted"
        for _ in range(100):
            if service.get_run(value.id).status == "completed":
                break
            await asyncio.sleep(0.02)
        assert service.get_run(value.id).status == "completed"
        assert (await service._execution.snapshot())["running"] == 0
    finally:
        record = service._runs[value.id]
        service._cancel_hitl_timeout(record)
        if record.resume_task:
            await asyncio.gather(record.resume_task, return_exceptions=True)
            if record.execution_lease:
                await record.execution_lease.wait_closed()
        await close_services(service)


@pytest.mark.asyncio
async def test_shared_services_keep_workspace_fifo_and_allow_other_workspace(tmp_path, monkeypatch):
    service = shared_service(
        tmp_path / "fifo.db",
        execution_global_running_limit=2,
        execution_global_queue_limit=4,
        execution_workspace_queue_limit=4,
    )
    started = []
    releases = {}
    tasks = []

    async def graph(record, **kwargs):
        started.append(record.detail.topic)
        await releases[record.detail.topic].wait()
        record.detail.status = "completed"
        service._persist_run(record.detail.id)
        return False

    monkeypatch.setattr(
        service,
        "_pipeline_checkpoint",
        lambda record: _value(SimpleNamespace(values={}, tasks=(), next=())),
    )
    monkeypatch.setattr(service, "_invoke_graph", graph)

    async def wait_started(topic):
        for _ in range(100):
            if topic in started:
                return
            await asyncio.sleep(0.005)
        pytest.fail(f"pipeline did not start: {topic}")

    try:
        for topic, workspace in [("a1", "A"), ("a2", "A"), ("a3", "A"), ("b1", "B")]:
            releases[topic] = asyncio.Event()
            value = await service.create_run(request(topic, workspace))
            tasks.append(service.launch_pipeline(value.id))
            if topic == "a1":
                await wait_started(topic)
        await wait_started("b1")
        assert started == ["a1", "b1"]
        releases["a1"].set()
        await wait_started("a2")
        assert "a3" not in started
        releases["a2"].set()
        await wait_started("a3")
        assert started == ["a1", "b1", "a2", "a3"]
    finally:
        for release in releases.values():
            release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_services(service)


@pytest.mark.asyncio
async def test_automatic_redo_reenters_same_owner_without_another_ticket(tmp_path, monkeypatch):
    from packages.schema.models import QCIssue, RedoScope

    service = shared_service(tmp_path / "redo.db")
    value = await service.create_run(request("auto-redo"))
    value.qa_findings = [
        QCIssue(
            id="gap",
            severity="blocker",
            detected_by="coverage",
            target_agent="writer",
            field_path="report_md",
            problem="Missing evidence",
            redo_scope=RedoScope(kind="writer_only", rationale="Fix gap"),
        )
    ]
    record = service._runs[value.id]
    observed = []

    async def redo_owned(run_id, **kwargs):
        observed.append(service._execution.current_lease(run_id))
        service._persist_run(run_id)

    monkeypatch.setattr(service, "_run_scoped_redo_owned", redo_owned)
    try:
        async with service._execution.run(service._execution_tickets[value.id]) as lease:
            assert await service._maybe_run_auto_redo(record) is True
            assert observed == [lease]
            state = await service._execution.snapshot()
            assert state["running"] == 1 and len(state["tickets"]) == 1
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_no_journal_slow_stream_bounds_queue_without_losing_cursor():
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(hitl_timeout_seconds=0),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    value = await service.create_run(request("slow-stream"))
    stream = service.stream_events(value.id)
    pending = None
    try:
        assert (await anext(stream)).id == 1
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        for index in range(200):
            await service.emit(value.id, "node_completed", "planner", None, str(index))
        queue = service._runs[value.id].subscribers[0]
        assert queue.qsize() == 64
        events = [await pending]
        for _ in range(199):
            events.append(await anext(stream))
        assert [event.id for event in events] == list(range(2, 202))
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        await close_services(service)


@pytest.mark.asyncio
async def test_duplicate_queued_launcher_cancel_keeps_original_ticket(tmp_path, monkeypatch):
    path = tmp_path / "duplicate-launch.db"
    owner, duplicate = shared_service(path), shared_service(path)
    held = await owner.create_run(request("capacity-holder"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold():
        async with owner._execution.run(owner._execution_tickets[held.id]):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    await entered.wait()
    value = await owner.create_run(request("shared-queued-launcher"))
    await duplicate.create_run(request("shared-queued-launcher"))
    calls = []

    async def checkpoint(record):
        return SimpleNamespace(values={}, tasks=(), next=())

    async def graph(record, **kwargs):
        calls.append(record.detail.id)
        record.detail.status = "completed"
        owner._persist_run(record.detail.id)
        return False

    for service in (owner, duplicate):
        monkeypatch.setattr(service, "_pipeline_checkpoint", checkpoint)
        monkeypatch.setattr(service, "_invoke_graph", graph)
    first = owner.launch_pipeline(value.id)
    second = None
    try:
        await asyncio.sleep(0.02)
        try:
            second = duplicate.launch_pipeline(value.id)
        except ExecutionConflictError:
            pass  # Immediate explicit busy is also a valid duplicate response.
        if second is not None:
            await asyncio.sleep(0.01)
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)
        states = (await owner._execution.snapshot())["tickets"]
        assert next(row for row in states if row["run_id"] == value.id)["state"] == "queued"
        release.set()
        await holder
        await first
        assert calls == [value.id]
        assert owner._journal.load_run(value.id).status == "completed"
    finally:
        release.set()
        await asyncio.gather(holder, first, *([second] if second else []), return_exceptions=True)
        await close_services(owner, duplicate)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_temporal_connection_failure_finishes_owned_queued_run(tmp_path, failure):
    from packages.workflows.service import TemporalWorkflowService

    service = shared_service(tmp_path / "connect-fail.db")
    value = await service.create_run(
        request("connect-fail"), runtime_orchestration_backend="temporal"
    )

    async def connect(settings):
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("offline connection rejected before RPC")

    workflow = TemporalWorkflowService(service._settings, client_factory=connect)
    try:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await workflow.start_competitive_intel(request("connect-fail"))
        assert (await service._execution.snapshot())["queued"] == 0
        assert service._journal.load_run(value.id).status == "failed"
        events = service._journal.load_events(value.id)
        assert any(event.type == "run_failed" and "Temporal" in event.message for event in events)
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_fresh_runtime_adopts_valid_queued_run_without_new_ticket(tmp_path, monkeypatch):
    from packages.auth import EnterpriseUserContext
    from packages.runtime import CreateRunCommand

    path = tmp_path / "adopt-queued.db"
    creator = shared_service(path)
    value = await creator.create_run(request("created-before-exit"))
    ticket_id = creator._execution_tickets[value.id].id
    fresh = shared_service(path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def checkpoint(record):
        return SimpleNamespace(values={}, tasks=(), next=())

    async def graph(record, **kwargs):
        entered.set()
        await release.wait()
        record.detail.status = "completed"
        fresh._persist_run(record.detail.id)
        return False

    monkeypatch.setattr(fresh, "_pipeline_checkpoint", checkpoint)
    monkeypatch.setattr(fresh, "_invoke_graph", graph)
    try:
        await runtime_for(fresh).create_run(
            CreateRunCommand(request=request("created-before-exit")),
            actor=EnterpriseUserContext("owner", "owner", "default-workspace"),
        )
        await asyncio.sleep(0.03)
        assert entered.is_set()
        states = (await fresh._execution.snapshot())["tickets"]
        assert len(states) == 1 and states[0]["id"] == ticket_id
    finally:
        release.set()
        await asyncio.gather(*fresh._background_tasks.values(), return_exceptions=True)
        await close_services(creator, fresh)


@pytest.mark.asyncio
async def test_duplicate_temporal_start_cannot_connect_or_cancel_original_launcher(tmp_path):
    from packages.workflows.service import TemporalWorkflowService

    service = shared_service(tmp_path / "duplicate-temporal.db")
    value = await service.create_run(
        request("duplicate-temporal"), runtime_orchestration_backend="temporal"
    )
    entered, release = asyncio.Event(), asyncio.Event()
    duplicate_connections = []

    async def start(*args, **kwargs):
        entered.set()
        await release.wait()

    async def connect(settings):
        return SimpleNamespace(start_workflow=start)

    async def duplicate_connect(settings):
        duplicate_connections.append(True)
        raise RuntimeError("duplicate connection must not happen")

    first = TemporalWorkflowService(service._settings, client_factory=connect)
    second = TemporalWorkflowService(service._settings, client_factory=duplicate_connect)
    task = asyncio.create_task(first.start_competitive_intel(request("duplicate-temporal")))
    try:
        await entered.wait()
        with pytest.raises(ExecutionConflictError):
            await second.start_competitive_intel(request("duplicate-temporal"))
        assert duplicate_connections == []
        state = await service._execution.snapshot()
        assert state["queued"] == 1
        assert service._journal.load_run(value.id).status == "queued"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await close_services(service)


@pytest.mark.asyncio
async def test_temporal_rpc_timeout_keeps_admission_and_records_uncertainty(tmp_path):
    from packages.workflows.service import TemporalWorkflowService

    service = shared_service(tmp_path / "uncertain-temporal.db")
    value = await service.create_run(
        request("uncertain-temporal"), runtime_orchestration_backend="temporal"
    )

    async def start(*args, **kwargs):
        raise TimeoutError("RPC outcome is unknown")

    async def connect(settings):
        return SimpleNamespace(start_workflow=start)

    workflow = TemporalWorkflowService(service._settings, client_factory=connect)
    try:
        with pytest.raises(TimeoutError):
            await workflow.start_competitive_intel(request("uncertain-temporal"))
        assert (await service._execution.snapshot())["queued"] == 1
        assert service._journal.load_run(value.id).status == "queued"
        assert any(
            event.type == "runtime.command" and event.payload.get("outcome") == "uncertain"
            for event in service._journal.load_events(value.id)
        )
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_same_idempotency_key_refuses_other_workspace_and_explicit_project(tmp_path):
    service = shared_service(tmp_path / "scope.db")
    value = await service.create_run(
        request("scoped-key", "workspace-a").model_copy(update={"project_id": "project-a"})
    )
    try:
        with pytest.raises(ExecutionConflictError):
            await service.create_run(request("scoped-key", "workspace-b"))
        with pytest.raises(ExecutionConflictError):
            await service.create_run(
                request("scoped-key", "workspace-a").model_copy(update={"project_id": "project-b"})
            )
        assert (await service.create_run(request("scoped-key", "workspace-a"))).id == value.id
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_fresh_runtime_refuses_expired_queued_ticket(tmp_path):
    from packages.auth import EnterpriseUserContext
    from packages.infrastructure.execution_control import ExecutionTimeoutError
    from packages.runtime import CreateRunCommand

    path = tmp_path / "expired-queued.db"
    creator = shared_service(path, execution_queue_wait_seconds=0.02)
    value = await creator.create_run(request("expired-before-launch"))
    await asyncio.sleep(0.03)
    fresh = shared_service(path, execution_queue_wait_seconds=0.02)
    try:
        with pytest.raises(ExecutionTimeoutError):
            await runtime_for(fresh).create_run(
                CreateRunCommand(request=request("expired-before-launch")),
                actor=EnterpriseUserContext("owner", "owner", "default-workspace"),
            )
        assert fresh._background_tasks == {}
        assert fresh._journal.load_run(value.id).status == "failed"
        assert len((await fresh._execution.snapshot())["tickets"]) == 1
    finally:
        await close_services(creator, fresh)


@pytest.mark.asyncio
async def test_temporal_connection_exceeding_deadline_never_starts_rpc(tmp_path):
    from packages.infrastructure.execution_control import ExecutionTimeoutError
    from packages.workflows.service import TemporalWorkflowService

    service = shared_service(tmp_path / "connect-deadline.db", execution_queue_wait_seconds=0.02)
    value = await service.create_run(
        request("connect-deadline"), runtime_orchestration_backend="temporal"
    )
    starts = []

    async def start(*args, **kwargs):
        starts.append(True)

    async def connect(settings):
        await asyncio.sleep(0.03)
        return SimpleNamespace(start_workflow=start)

    workflow = TemporalWorkflowService(service._settings, client_factory=connect)
    try:
        with pytest.raises(ExecutionTimeoutError):
            await workflow.start_competitive_intel(request("connect-deadline"))
        assert starts == []
        assert service._journal.load_run(value.id).status == "failed"
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_fresh_runtime_adopts_queued_temporal_start_with_same_ticket(tmp_path):
    from packages.auth import EnterpriseUserContext
    from packages.runtime import CreateRunCommand
    from packages.workflows.service import TemporalWorkflowService

    path = tmp_path / "fresh-temporal-start.db"
    creator = shared_service(path, run_orchestration_backend="temporal")
    value = await creator.create_run(
        request("fresh-temporal"), runtime_orchestration_backend="temporal"
    )
    fresh = shared_service(path, run_orchestration_backend="temporal")
    starts = []

    async def start(*args, **kwargs):
        starts.append(kwargs["id"])

    async def connect(settings):
        return SimpleNamespace(start_workflow=start)

    workflow = TemporalWorkflowService(fresh._settings, client_factory=connect)
    try:
        result = await runtime_for(fresh, workflow).create_run(
            CreateRunCommand(request=request("fresh-temporal")),
            actor=EnterpriseUserContext("owner", "owner", "default-workspace"),
        )
        assert result.route == "temporal"
        assert len(starts) == 1
        state = await fresh._execution.snapshot()
        assert len(state["tickets"]) == 1
        assert state["tickets"][0]["id"] == creator._execution_tickets[value.id].id
    finally:
        await close_services(creator, fresh)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_temporal_confirmed_start_survives_later_connection_failure(tmp_path, failure):
    from packages.workflows.service import TemporalWorkflowService

    service = shared_service(tmp_path / "confirmed-start.db")
    value = await service.create_run(
        request("confirmed-start"), runtime_orchestration_backend="temporal"
    )
    starts = []

    async def start(*args, **kwargs):
        starts.append(kwargs["id"])

    async def connect(settings):
        return SimpleNamespace(start_workflow=start)

    async def broken(settings):
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("later connection failed after an earlier successful RPC")

    try:
        first = await TemporalWorkflowService(
            service._settings,
            client_factory=connect,
        ).start_competitive_intel(request("confirmed-start"))
        assert first.status == "started"
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await TemporalWorkflowService(
                service._settings,
                client_factory=broken,
            ).start_competitive_intel(request("confirmed-start"))
        assert len(starts) == 1
        assert (await service._execution.snapshot())["queued"] == 1
        assert service._journal.load_run(value.id).status == "queued"
        assert not any(
            event.type == "run_failed" for event in service._journal.load_events(value.id)
        )
    finally:
        await close_services(service)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["started", "already_started"])
async def test_temporal_start_intent_is_committed_before_rpc(tmp_path, outcome):
    from packages.workflows.service import TemporalWorkflowService
    from temporalio.exceptions import WorkflowAlreadyStartedError

    service = shared_service(tmp_path / "start-intent.db")
    value = await service.create_run(
        request("start-intent"), runtime_orchestration_backend="temporal"
    )
    intent_seen = []

    async def start(*args, **kwargs):
        events = service._journal.load_events(value.id)
        intent_seen.append(
            any(
                event.type == "runtime.command"
                and event.payload.get("outcome") == "start_rpc_intent"
                and event.payload.get("workflow_id") == kwargs["id"]
                and event.payload.get("ticket_id") == service._execution_tickets[value.id].id
                for event in events
            )
        )
        if outcome == "already_started":
            raise WorkflowAlreadyStartedError(kwargs["id"], "competitive_intel")

    async def connect(settings):
        return SimpleNamespace(start_workflow=start)

    try:
        result = await TemporalWorkflowService(
            service._settings,
            client_factory=connect,
        ).start_competitive_intel(request("start-intent"))
        assert result.status == outcome
        assert intent_seen == [True]
        assert any(
            event.payload.get("outcome") == "start_rpc_confirmed"
            and event.payload.get("status") == outcome
            for event in service._journal.load_events(value.id)
        )
    finally:
        await close_services(service)


@pytest.mark.asyncio
async def test_concurrent_same_key_rechecks_explicit_project_after_admission(tmp_path, monkeypatch):
    path = tmp_path / "project-race.db"
    first, second = shared_service(path), shared_service(path)
    entered = 0
    release = asyncio.Event()
    original_first, original_second = first._execution.admit, second._execution.admit

    async def barrier(admit, *args):
        nonlocal entered
        entered += 1
        if entered == 2:
            release.set()
        await release.wait()
        return await admit(*args)

    monkeypatch.setattr(first._execution, "admit", lambda *args: barrier(original_first, *args))
    monkeypatch.setattr(second._execution, "admit", lambda *args: barrier(original_second, *args))
    try:
        results = await asyncio.gather(
            first.create_run(
                request("project-race").model_copy(update={"project_id": "project-a"})
            ),
            second.create_run(
                request("project-race").model_copy(update={"project_id": "project-b"})
            ),
            return_exceptions=True,
        )
        accepted = [result for result in results if not isinstance(result, BaseException)]
        rejected = [result for result in results if isinstance(result, BaseException)]
        assert len(accepted) == len(rejected) == 1
        assert isinstance(rejected[0], ExecutionConflictError)
        assert len((await first._execution.snapshot())["tickets"]) == 1
        assert first._journal.load_run(accepted[0].id).project_id == accepted[0].project_id
    finally:
        await close_services(first, second)


@pytest.mark.asyncio
async def test_claim_storage_busy_finishes_owned_admission_after_short_real_writer(
    tmp_path, monkeypatch
):
    import sqlite3
    import threading
    import time

    path = tmp_path / "claim-storage-busy.db"
    service = shared_service(path, execution_queue_wait_seconds=10)
    value = await service.create_run(request("claim-storage-busy"))
    original_claim = service._execution._claim_sync
    ready = threading.Event()
    writer = None

    def hold_writer():
        with sqlite3.connect(path) as connection:
            connection.execute("begin immediate")
            ready.set()
            time.sleep(1.25)

    def claim(ticket):
        nonlocal writer
        writer = threading.Thread(target=hold_writer)
        writer.start()
        assert ready.wait(3)
        return original_claim(ticket)

    monkeypatch.setattr(service._execution, "_claim_sync", claim)
    task = service.launch_pipeline(value.id)
    try:
        with pytest.raises(ExecutionUnavailableError):
            await task
        if writer is not None:
            await asyncio.to_thread(writer.join)
        state = await service._execution.snapshot()
        assert state["queued"] == state["running"] == 0
        assert service._journal.load_run(value.id).status == "failed"
        assert any(event.type == "run_failed" for event in service._journal.load_events(value.id))
        launcher = service._execution.try_launcher(service._execution_tickets[value.id])
        assert launcher is not None
        launcher.lock.close()
    finally:
        if writer is not None:
            await asyncio.to_thread(writer.join)
        await asyncio.gather(task, return_exceptions=True)
        await close_services(service)
