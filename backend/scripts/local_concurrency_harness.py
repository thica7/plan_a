"""Offline acceptance scenarios; no production routes or coordinator replacements."""

from __future__ import annotations

import asyncio
import hashlib
import multiprocessing
import os
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SEED = 20261028
ROOT = Path(__file__).resolve().parents[2]
REGRESSIONS = {
    "duplicate_single_consumer": "test_shared_pipeline_bounds_queue_and_duplicate_graph",
    "workspace_fifo_and_cross_workspace":
        "test_shared_services_keep_workspace_fifo_and_allow_other_workspace",
    "cancel_timeout_startup_failure":
        "test_admitted_background_failure_releases_ticket_and_finishes_queue",
    "stale_revision": "test_journal_snapshot_revision_and_compare_and_swap",
    "released_token": "test_journal_rejects_unfenced_active_and_released_owner",
    "durable_event_ids": "test_journal_allocates_event_ids_and_never_replaces",
    "slow_consumer_memory_bound": "test_no_journal_slow_stream_bounds_queue_without_losing_cursor",
}


def isolate_environment(directory: Path) -> None:
    """Set all environment based providers before importing application modules."""
    for key in list(os.environ):
        if key.startswith(("EXECUTION_", "LLM_", "RUN_LLM_")):
            os.environ.pop(key)
    os.environ.update({
        "COMPETISCOPE_LOAD_ENV_FILES": "0", "AUTH_ENABLED": "false",
        "REDIS_CACHE_ENABLED": "false", "REDIS_RATE_LIMIT_ENABLED": "false",
        "KB_DB_PATH": str(directory / "knowledge.db"), "KB_RETRIEVAL_MODE": "sparse",
        "KB_EMBEDDING_PROVIDER": "hash", "KB_RERANKER_PROVIDER": "none",
        "ENTERPRISE_STORE_BACKEND": "memory", "RUN_ORCHESTRATION_BACKEND": "langgraph",
        "DEMO_MODE": "true", "PYTHONDONTWRITEBYTECODE": "1",
        "EXECUTION_CONTROL_ENABLED": "false", "AUTH_POLICY_ENGINE": "internal",
    })
    for key in (
        "ARK_API_KEY", "ARK_MODEL", "PPLX_API_KEY", "DEEPSEEK_API_KEY", "BACKUP_LLM_API_KEY",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        os.environ.pop(key, None)


@contextmanager
def offline_sockets():
    """Fail closed if any scenario accidentally tries an IP connection or listener."""
    original_connect, original_bind = socket.socket.connect, socket.socket.bind

    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            raise AssertionError(f"Offline verifier refused IP connection: {address!r}")
        return original_connect(sock, address)

    def bind(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            raise AssertionError(f"Offline verifier refused IP listener: {address!r}")
        return original_bind(sock, address)

    with patch.object(socket.socket, "connect", connect), \
            patch.object(socket.socket, "connect_ex", connect), \
            patch.object(socket.socket, "bind", bind):
        yield


def settings(path: Path, **overrides):
    from packages.config import Settings

    return Settings(**{
        "demo_mode": True, "run_orchestration_backend": "langgraph",
        "enterprise_store_backend": "memory", "enterprise_database_url": None,
        "hitl_enabled": False, "hitl_timeout_seconds": 0,
        "auto_redo_enabled": False, "auto_redo_warn_enabled": False,
        "execution_control_enabled": True, "execution_control_journal_path": str(path),
        "execution_global_running_limit": 2, "execution_workspace_running_limit": 1,
        "execution_global_queue_limit": 8, "execution_workspace_queue_limit": 8,
        "execution_queue_wait_seconds": 0.5, "execution_model_wait_seconds": 5,
        "llm_max_concurrency": 2, "create_run_rate_limit_per_window": 10000,
        "ark_api_key": "synthetic-offline", "ark_model": "synthetic-model",
        "ark_base_url": "https://model.invalid", "deepseek_api_key": "synthetic-offline",
        "llm_max_retries": 0, "llm_retry_backoff_seconds": 0,
        **overrides,
    })


def service_for(directory: Path, *, checkpoint: bool = False):
    from packages.enterprise import EnterpriseMemoryStore
    from packages.memory import RunJournal
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunService
    from packages.skills.registry import SkillRegistry

    path = directory / "journal.db"
    service = RunService(
        SkillRegistry.from_default_path(), settings(path), journal=RunJournal(path),
        enterprise_store=EnterpriseMemoryStore(),
        graph_checkpointer=(GraphCheckpointer(directory / "checkpoints.db")
                            if checkpoint else GraphCheckpointer.in_memory()),
    )
    return service


def app_for(service, workspace):
    from app import deps
    from app.main import create_app
    from app.rate_limit import SlidingWindowRateLimiter
    from packages.auth import EnterpriseUserContext
    from packages.memory import PreferenceMemoryStore
    from packages.runtime import RuntimeCommandService

    runtime = RuntimeCommandService(
        settings=service._settings, run_service=service, workflow_service=object(),
        enterprise_store=service._enterprise_store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    app = create_app()
    app.dependency_overrides[deps.get_runtime_command_service] = lambda: runtime
    app.dependency_overrides[deps.get_run_service] = lambda: service
    app.dependency_overrides[deps.get_app_settings] = lambda: service._settings
    limiter = SlidingWindowRateLimiter()
    app.dependency_overrides[deps.get_create_run_rate_limiter] = lambda: limiter
    app.dependency_overrides[deps.get_enterprise_user_context] = lambda: EnterpriseUserContext(
        "offline-owner", "owner", workspace,
    )
    return app


def request(key, workspace):
    return {
        "topic": key, "competitors": ["Cursor"], "dimensions": ["pricing"],
        "execution_mode": "demo", "idempotency_key": key,
        "workspace_id": workspace, "hitl_enabled": False,
    }


def response_for(request):
    import httpx

    if request.url.path.endswith("/messages"):
        return httpx.Response(200, json={
            "content": [{"type": "web_search_tool_result", "content": []}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        })
    return httpx.Response(200, json={
        "choices": [{"message": {"content": '{"rewrites": ["alternate query"]}'}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    })


async def wait_event(event, timeout=30):
    assert await asyncio.to_thread(event.wait, timeout), "Process barrier timed out"


def burst_worker(directory, index, count, counters, counter_lock, ready, start, release, results):
    """Each spawn owns a real API, RuntimeCommandService and RunService."""
    directory = Path(directory)
    isolate_environment(directory)

    async def work():
        import httpx
        from packages.knowledge.retrieval import DefaultQueryRewriter
        from packages.llm.doubao_client import DoubaoClient
        from packages.search.deepseek_client import DeepSeekSearchClient

        service = service_for(directory)
        app = app_for(service, f"pressure-{index}")
        consumers = {}
        tasks = []

        async def checkpoint(record):
            return SimpleNamespace(values={}, tasks=(), next=())

        async def graph(record, **kwargs):
            run_id = record.detail.id
            assert service._execution.current_lease(run_id) is not None
            consumers[run_id] = consumers.get(run_id, 0) + 1
            with counter_lock:
                counters[0] += 1
                counters[1] = max(counters[1], counters[0])
                counters[4 + index] += 1
                counters[6] = max(counters[6], counters[4 + index])
            try:
                await wait_event(release)
                llm = DoubaoClient(service._settings)
                native = DeepSeekSearchClient(service._settings)
                rewritten = await asyncio.gather(
                    llm.complete_text(system="offline", user="synthetic generation"),
                    DefaultQueryRewriter(llm).rewrite("synthetic query", num_rewrites=1),
                    native.search("synthetic search"),
                )
                assert rewritten[1] == ["alternate query"]
                record.detail.status = "completed"
                service._persist_run(run_id)
                return False
            finally:
                with counter_lock:
                    counters[0] -= 1
                    counters[4 + index] -= 1

        async def transport(req):
            with counter_lock:
                counters[2] += 1
                counters[3] = max(counters[3], counters[2])
                if req.url.path.endswith("/messages"):
                    counters[9] += 1
                elif b"synthetic generation" in req.content:
                    counters[7] += 1
                else:
                    counters[8] += 1
            try:
                await asyncio.sleep(0.06)
                return response_for(req)
            finally:
                with counter_lock:
                    counters[2] -= 1

        real_client = httpx.AsyncClient

        def client(**kwargs):
            kwargs.setdefault("transport", httpx.MockTransport(transport))
            return real_client(**kwargs)

        async def post(client, number):
            before = time.monotonic()
            submitted_wall = time.time()
            result = await client.post("/api/runs", json=request(
                f"pressure-{index}-{number}", f"pressure-{index}",
            ))
            elapsed = time.monotonic() - before
            assert result.status_code in {201, 429}, result.text
            if result.status_code == 429:
                assert "admission queue" in result.text, result.text
            return {"status": result.status_code, "create_ms": elapsed * 1000,
                    "submitted_wall": submitted_wall,
                    "retry_after": result.headers.get("Retry-After"),
                    "run_id": result.json().get("id")}

        try:
            with patch.object(service, "_pipeline_checkpoint", checkpoint), \
                    patch.object(service, "_invoke_graph", graph), \
                    patch.object(httpx, "AsyncClient", client):
                async with real_client(
                    transport=httpx.ASGITransport(app=app), base_url="http://offline.invalid",
                ) as api:
                    ready.put({"kind": "ready", "pid": os.getpid()})
                    await wait_event(start)
                    order = list(range(count))
                    random.Random(SEED + index).shuffle(order)
                    responses = await asyncio.gather(*(post(api, n) for n in order))
                    tasks = list(service._background_tasks.values())
                    ready.put({"kind": "admitted", "pid": os.getpid()})
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await asyncio.sleep(0)
                state = await service._execution.snapshot()
                tickets = {ticket["run_id"]: ticket for ticket in state["tickets"]}
                for row in responses:
                    run_id = row["run_id"]
                    if run_id:
                        row["terminal_status"] = service._journal.load_run(run_id).status
                        ticket = tickets[run_id]
                        assert ticket["ended_at"] is not None
                        row["end_to_end_ms"] = (
                            ticket["ended_at"] - row["submitted_wall"]
                        ) * 1000
                report = {"responses": responses, "consumers": consumers}
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await service._graph_checkpointer.aclose()
        await asyncio.sleep(0)
        report["pending_tasks"] = len(pending_tasks())
        assert report["pending_tasks"] == 0
        results.put(report)

    try:
        with offline_sockets():
            asyncio.run(work())
    except BaseException:
        results.put({"error": traceback.format_exc()})
        raise


def percentiles(values):
    ordered = sorted(values)
    assert ordered
    result = {}
    for name, fraction in (("p50", .5), ("p95", .95)):
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        result[name] = round(ordered[lower] + (ordered[upper] - ordered[lower])
                             * (position - lower), 3)
    return result


def pending_tasks():
    return [task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()]


async def finish_scenario(coroutine):
    result = await coroutine
    await asyncio.sleep(0)
    pending = pending_tasks()
    assert not pending, [str(task) for task in pending]
    return {**result, "pending_tasks": len(pending)}


def run_burst(directory, count):
    ctx = multiprocessing.get_context("spawn")
    counters, lock = ctx.Array("i", 10, lock=False), ctx.Lock()
    ready, results, start, release = ctx.Queue(), ctx.Queue(), ctx.Event(), ctx.Event()
    processes = [ctx.Process(target=burst_worker, args=(
        str(directory), index, count // 2 + (count % 2 if index == 0 else 0),
        counters, lock, ready, start, release, results,
    )) for index in range(2)]
    try:
        for process in processes:
            process.start()
        assert all(ready.get(timeout=30)["kind"] == "ready" for _ in processes)
        start.set()
        assert all(ready.get(timeout=30)["kind"] == "admitted" for _ in processes)
        # Deliberately exceed the fixed queue deadline while holders retain real run leases.
        time.sleep(0.65)
        release.set()
        reports = [results.get(timeout=30) for _ in processes]
        assert all("error" not in report for report in reports), reports
        for process in processes:
            process.join(30)
        exitcodes = [process.exitcode for process in processes]
        assert exitcodes == [0, 0], exitcodes
        rows = [row for report in reports for row in report["responses"]]
        accepted = [row for row in rows if row["status"] == 201]
        rejected = [row for row in rows if row["status"] == 429]
        completed = [row for row in accepted if row["terminal_status"] == "completed"]
        from packages.infrastructure.execution_factory import create_execution_coordinator
        from packages.memory import RunJournal

        with RunJournal(directory / "journal.db")._connect() as connection:
            connection.row_factory = sqlite3.Row
            tickets = connection.execute("select * from execution_control_tickets").fetchall()
            expired = sum(row["state"] == "timedout" for row in tickets)
            queue_ms = [(row["started_at"] - row["enqueued_at"]) * 1000
                        for row in tickets if row["started_at"] is not None]
        assert accepted and rejected and expired
        assert len(completed) + expired == len(accepted)
        assert counters[1] == counters[3] == 2 and counters[6] == 1
        assert counters[0] == counters[2] == 0
        assert all(sum(report["consumers"].values()) == len(report["consumers"])
                   for report in reports)
        assert all(report["pending_tasks"] == 0 for report in reports)
        assert all(int(row["retry_after"]) >= 1 for row in rejected)
        state = asyncio.run(create_execution_coordinator(settings(
            directory / "journal.db",
        )).snapshot())
        final = {key: state[key] for key in ("queued", "running", "model_active")}
        assert all(value == 0 for value in final.values()), final
        return {
            "requests": count, "accepted": len(accepted), "rejected": len(rejected),
            "completed": len(completed), "expired": expired,
            "http_429": len(rejected), "retry_after_valid": len(rejected),
            "running_peak": counters[1], "model_peak": counters[3],
            "workspace_running_peak": counters[6], "generation_calls": counters[7],
            "rewrite_calls": counters[8], "native_search_calls": counters[9],
            "latency_ms": {"create": percentiles([row["create_ms"] for row in rows]),
                           "queue": percentiles(queue_ms),
                           "end_to_end": percentiles([row["end_to_end_ms"] for row in accepted]),
                           "completed_end_to_end": percentiles([
                               row["end_to_end_ms"] for row in completed
                           ])},
            "latency_samples": {"create": len(rows), "queue": len(queue_ms),
                                "end_to_end": len(accepted),
                                "completed_end_to_end": len(completed)},
            "percentile_method": "linear interpolation over sorted samples",
            "queue_latency_scope": "admitted_at to claimed_at; only started tickets",
            "end_to_end_latency_scope": "HTTP submission to ticket ended_at (accepted requests)",
            "fault_injection": {"holder_release_delay_seconds": .65,
                                "queue_deadline_seconds": .5,
                                "interpretation": "deadline/cleanup fault injection; no SLA claim"},
            "final": final,
            "process_exitcodes": exitcodes, "pending_tasks": 0,
            "entries": ["POST /api/runs", "RuntimeCommandService.create_run",
                        "RunService.launch_pipeline/run_pipeline", "SQLiteExecutionCoordinator.run",
                        "DoubaoClient.complete_text", "DefaultQueryRewriter.rewrite",
                        "DeepSeekSearchClient.search"],
            "synthetic": "Only graph body/checkpoint placeholder and provider HTTP responses",
            "responses": rows,
        }
    finally:
        start.set()
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
        ready.close()
        results.close()
        ready.join_thread()
        results.join_thread()


async def cross_instance(directory, burst):
    import httpx
    from app.routers.stream import stream_run
    from packages.auth import EnterpriseUserContext

    # A fresh service reads both processes' durable runs, without their memory stores.
    service, producer = service_for(directory), service_for(directory)
    read = 0
    try:
        for index in range(2):
            workspace = f"pressure-{index}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_for(service, workspace)),
                base_url="http://offline.invalid",
            ) as client:
                listing = await client.get("/api/runs")
                assert listing.status_code == 200, listing.text
                expected = {row["run_id"] for row in burst["responses"]
                            if row["run_id"] and service.get_run(row["run_id"]).workspace_id
                            == workspace}
                assert {row["id"] for row in listing.json()} == expected
                for run_id in expected:
                    response = await client.get(f"/api/runs/{run_id}")
                    assert response.status_code == 200 and response.json()["id"] == run_id
                    read += 1
        run_id = next(row["run_id"] for row in burst["responses"] if row["run_id"])
        # More than the in-memory subscriber bound, all read from the durable journal.
        for number in range(80):
            await producer.append_control_event(
                run_id, "runtime.command", "runtime", None, "offline cursor fixture",
                {"command_id": f"cursor-{number}"},
            )
        events = service._journal.load_events(run_id)
        cursor = events[10].id
        expected = [event.id for event in events if event.id > cursor]

        class ConnectedRequest:
            async def is_disconnected(self):
                return False

        # ASGITransport buffers never-ending SSE; consume the real route's body iterator.
        response = await stream_run(
            run_id, ConnectedRequest(), service,
            EnterpriseUserContext("offline-owner", "owner", service.get_run(run_id).workspace_id),
            last_event_id=cursor,
        )
        actual = []
        try:
            for index in range(len(expected)):
                await asyncio.sleep(.001)  # A deliberately slow consumer with a durable cursor.
                event = await asyncio.wait_for(anext(response.body_iterator), 2)
                actual.append(int(event["id"]))
                if index == 1:
                    for number in range(80, 96):
                        await producer.append_control_event(
                            run_id, "runtime.command", "runtime", None, "append during stream",
                            {"command_id": f"cursor-{number}"},
                        )
            appended = [event.id for event in service._journal.load_events(run_id)
                        if event.id > expected[-1]]
            for _ in appended:
                event = await asyncio.wait_for(anext(response.body_iterator), 2)
                actual.append(int(event["id"]))
        finally:
            await response.body_iterator.aclose()
        assert actual == expected + appended
        state = await service._execution.snapshot()
        assert state["queued"] == state["running"] == state["model_active"] == 0
        return {"get_and_list": True, "runs_read": read,
                "durable_sse_slow_cursor": True, "cursor": cursor, "event_ids": actual,
                "sse_transport": "real stream route body iterator; no socket, no ASGI buffering"}
    finally:
        await service._graph_checkpointer.aclose()
        await producer._graph_checkpointer.aclose()


def recovery_owner(directory, ready):
    directory = Path(directory)
    isolate_environment(directory)

    async def work():
        from packages.schema.api_dto import RunCreateRequest

        service = service_for(directory, checkpoint=True)
        value = await service.create_run(RunCreateRequest(**request(
            "checkpoint-recovery", "recover",
        )))
        announced = False

        async def pause(record, dimension, competitor):
            nonlocal announced
            if not announced:
                # LangGraph saves checkpoints asynchronously; entry into a graph child
                # alone is not evidence that the previous superstep reached SQLite.
                async with asyncio.timeout(5):
                    while True:
                        saved = await service._pipeline_checkpoint(record)
                        if saved.values.get("run_id") == record.detail.id and any(
                            "collect" in node for node in saved.next
                        ):
                            break
                        await asyncio.sleep(.01)
                announced = True
                lease = service._execution.current_lease(record.detail.id)
                ready.put({"run_id": record.detail.id, "token": lease.token,
                           "generation": lease.generation, "pid": os.getpid()})
            await asyncio.Event().wait()

        # Planner and the LangGraph saver execute normally before this inner collector pauses.
        with patch.object(service, "_demo_collector_branch_step", pause):
            await service.run_pipeline(value.id)

    with offline_sockets():
        asyncio.run(work())


async def run_recovery(directory):
    from packages.infrastructure.execution_control import ExecutionConflictError

    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    process = ctx.Process(target=recovery_owner, args=(str(directory), ready))
    process.start()
    service = None
    try:
        owner = await asyncio.to_thread(ready.get, True, 30)
        assert owner["pid"] == process.pid
        # Only the verifier's own child is terminated. Kernel locks perform owner release.
        process.terminate()
        await asyncio.to_thread(process.join, 5)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 5)
        assert not process.is_alive()
        service = service_for(directory, checkpoint=True)
        run_id = owner["run_id"]
        record = service._load_run_record(run_id)
        checkpoint = await service._pipeline_checkpoint(record)
        assert checkpoint.values["run_id"] == run_id and any(
            "collect" in node for node in checkpoint.next
        ), (
            checkpoint.values, checkpoint.next,
        )

        def planner_count():
            return sum(event.type == "node_completed" and event.agent == "planner"
                       for event in service._journal.load_events(run_id))

        before = planner_count()
        assert before == 1
        result = await service.recover_run(run_id)
        assert result is not None
        # The new owner is active here; old token rejection is not merely release validation.
        try:
            service._journal.save_run(
                result, token=owner["token"], generation=owner["generation"],
            )
        except ExecutionConflictError:
            old_token_active_rejected = True
        else:
            raise AssertionError("Stale token wrote while recovered owner was active")
        await asyncio.wait_for(service._runs[run_id].pipeline_task, 30)
        # Handoff release runs as an async task after the graph task finishes.
        async with asyncio.timeout(5):
            while (await service._execution.snapshot())["running"]:
                await asyncio.sleep(.01)
        snapshot = await service._execution.snapshot()
        generation = max(ticket["generation"] for ticket in snapshot["tickets"]
                         if ticket["run_id"] == run_id)
        assert generation > owner["generation"]
        detail = service._journal.load_run(run_id)
        try:
            service._journal.save_run(detail, token=owner["token"], generation=owner["generation"])
        except ExecutionConflictError:
            old_token_rejected = True
        else:
            raise AssertionError("Exited owner's token was accepted")
        assert planner_count() == before
        assert detail.status in {"completed", "completed_with_blockers"}, detail.status
        assert snapshot["queued"] == snapshot["running"] == snapshot["model_active"] == 0
        return {
            "real_langgraph_checkpoint": True, "checkpoint_pending_nodes": list(checkpoint.next),
            "owner_exitcode": process.exitcode, "owner_joined": True,
            "generation_before": owner["generation"], "generation_after": generation,
            "old_token_rejected": old_token_rejected,
            "old_token_rejected_while_new_owner_active": old_token_active_rejected,
            "planner_completions_before": before, "planner_completions_after": planner_count(),
            "terminal_status": detail.status, "content_quality_asserted": False,
            "final": {key: snapshot[key] for key in ("queued", "running", "model_active")},
            "synthetic": "demo fixture content; only first owner's inner collector paused",
        }
    finally:
        if process.is_alive():
            process.kill()
        await asyncio.to_thread(process.join, 5)
        ready.close()
        ready.join_thread()
        if service:
            await service._graph_checkpointer.aclose()


async def run_singleflight(directory):
    from packages.knowledge.retrieval import DefaultQueryRewriter, RetrievalService
    from packages.llm.doubao_client import DoubaoClient
    from packages.tools import evidence_fetch

    fetch_calls = 0

    async def fetch(url, **options):
        nonlocal fetch_calls
        fetch_calls += 1
        await asyncio.sleep(.02)
        body = "Offline public documentation."
        return evidence_fetch.EvidenceFetchResult(
            url=url, ok=True, title="Offline", text=body,
            content_hash=hashlib.sha256(body.encode()).hexdigest()[:16],
            source_material_level="full_source", status_code=200, quality_score=.8,
            capture_metadata={"nested": [[1]]},
        )

    with patch.object(evidence_fetch, "_fetch_evidence_page", fetch):
        pages = await asyncio.gather(*(evidence_fetch.fetch_evidence_page(
            "https://offline.example/docs",
        ) for _ in range(32)))
    assert fetch_calls == 1
    pages[0].capture_metadata["nested"][0].append(2)
    assert all(page.capture_metadata["nested"] == [[1]] for page in pages[1:])

    class Embedding:
        model_version = "offline-acceptance-v1"
        dimensions = 2
        calls = 0

        async def embed_query(self, query):
            self.calls += 1
            await asyncio.sleep(.02)
            return [1., 2.]

    provider = Embedding()
    retrieval = RetrievalService(
        None, None, embed_fn=lambda texts: [], embedding_provider=provider,
        query_rewriter=DefaultQueryRewriter(DoubaoClient(settings(directory / "singleflight.db"))),
    )
    vectors = await asyncio.gather(*(retrieval._embed_query("offline-same") for _ in range(32)))
    assert provider.calls == 1
    vectors[0][0] = 99.
    assert all(vector == [1., 2.] for vector in vectors[1:])
    return {"scope": "single-process", "burst": 32, "fetch_provider_calls": fetch_calls,
            "embedding_provider_calls": provider.calls, "independent_copies": True,
            "entries": ["fetch_evidence_page", "RetrievalService._embed_query"],
            "synthetic": "inner fetch and embedding provider only; Redis disabled"}


def run_regressions(directory):
    nodes = {name: "backend/tests/unit/test_shared_run_execution.py::" + test
             for name, test in REGRESSIONS.items()}
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--basetemp", str(directory / "pytest-regressions"), *nodes.values()]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"),
           "KB_DB_PATH": str(directory / "regression-knowledge.db")}
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return {"passed": True, "kind": "executed existing regression tests, separate from new burst",
            "nodeids": nodes, "command": command, "stdout": result.stdout, "stderr": result.stderr}


def execute(count: int) -> dict:
    """All persistent state is confined to this function's owned temporary directory."""
    if not 16 <= count <= 256:
        raise ValueError("requests must be between 16 and 256")
    result = {
        "schema_version": 1, "mode": "execute", "seed": SEED, "passed": False,
        "external_services": False,
        "limits": {"running": 2, "workspace_running": 1, "model": 2, "queue": 8,
                   "queue_wait_seconds": .5, "create_rate_limit": 10000},
        "scope": "same POSIX host, same journal file and policy; single local owner",
        "not_verified": ["Redis service/Lua/TTL/disconnect", "Postgres service",
                         "Qdrant HTTP service", "Temporal service", "cross-container locking",
                         "multiple hosts or external exactly-once",
                         "cross-process cache singleflight",
                         "paid model quality", "whole-chain async legacy persistence/BGE/HTTP"],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="competiscope-local-concurrency-") as temporary:
            directory = Path(temporary)
            isolate_environment(directory)
            for name in ("burst", "recovery"):
                (directory / name).mkdir()
            with offline_sockets():
                result["burst"] = run_burst(directory / "burst", count)
                result["cross_instance"] = asyncio.run(finish_scenario(cross_instance(
                    directory / "burst", result["burst"],
                )))
                result["recovery"] = asyncio.run(finish_scenario(run_recovery(
                    directory / "recovery",
                )))
                result["singleflight"] = asyncio.run(finish_scenario(run_singleflight(directory)))
                result["regressions"] = run_regressions(directory)
            result["passed"] = True
        result["cleanup"] = {"temporary_directory_removed": not Path(temporary).exists(),
                             "all_children_joined": not multiprocessing.active_children()}
        assert all(result["cleanup"].values()), result["cleanup"]
    except Exception:
        result["passed"] = False
        result["error"] = traceback.format_exc()
        result["cleanup"] = {
            "temporary_directory_removed": (
                "temporary" not in locals() or not Path(temporary).exists()
            ),
            "all_children_joined": not multiprocessing.active_children(),
        }
    return result
