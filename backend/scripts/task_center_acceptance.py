"""Owned local acceptance machinery, not a production dispatcher or Temporal emulator.

Only verify_task_center --execute is the public entry point. Child startup requires
an unpredictable capability in a private OwnedPostgres directory. All application
imports happen after installing the synthetic child environment.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
ARTIFACTS = REPO / "data/artifacts/task-center-2026-10-29"
WORKSPACES = {
    "one-remaining": 1,
    "same-key": 1,
    "load": 10000,
    "rollback": 100,
    "cancel": 100,
    "crash": 100,
    "unknown": 100,
    "tenant-b": 100,
    "graph": 1,
    "explain": 10000,
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def synthetic_environment(root, dsn):
    return {
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": str(root),
        "PYTHONPATH": str(BACKEND),
        "PYTHONDONTWRITEBYTECODE": "1",
        "COMPETISCOPE_LOAD_ENV_FILES": "0",
        "DEMO_MODE": "true",
        "ENTERPRISE_STORE_BACKEND": "memory",
        "TASK_CENTER_ENABLED": "true",
        "TASK_CENTER_DATABASE_URL": dsn,
        "TASK_CENTER_POOL_MIN_SIZE": "1",
        "TASK_CENTER_POOL_MAX_SIZE": "4",
        "TASK_CENTER_POOL_MAX_WAITING": "128",
        "TASK_CENTER_POOL_TIMEOUT_SECONDS": "1.0",
        "TASK_CENTER_LOCK_TIMEOUT_MS": "700",
        "TASK_CENTER_STATEMENT_TIMEOUT_MS": "1500",
        "EXECUTION_CONTROL_ENABLED": "true",
        "EXECUTION_CONTROL_JOURNAL_PATH": str(root / "runs.db"),
        "RUN_ORCHESTRATION_BACKEND": "langgraph",
        "HITL_ENABLED": "false",
        "AUTH_ENABLED": "true",
        "AUTH_TOKEN_SUBJECTS": json.dumps(
            {
                f"acceptance-{ws}": {
                    "user_id": "acceptance-owner",
                    "role": "owner",
                    "workspace_id": ws,
                }
                for ws in WORKSPACES
            }
            | {"acceptance-viewer": {"user_id": "viewer", "role": "viewer", "workspace_id": "load"}}
        ),
    }


def child_config(filename, token):
    path = Path(filename)
    root = path.parent
    if (
        root.parent != Path("/private/tmp")
        or not root.name.startswith("task-center-pg-")
        or root.is_symlink()
        or path.is_symlink()
        or root.stat().st_uid != os.getuid()
        or root.stat().st_mode & 0o077
        or not (root / ".owned-postgres").is_file()
    ):
        raise RuntimeError("refusing unowned child configuration")
    config = json.loads(path.read_text())
    if (
        not secrets.compare_digest(config["token"], token)
        or config["root"] != str(root)
        or not secrets.compare_digest((root / ".owned-postgres").read_text(), token)
        or config["filename"] != str(path)
    ):
        raise RuntimeError("invalid child capability")
    validate_child_dsn(root, config["dsn"])
    os.environ.clear()
    os.environ.update(synthetic_environment(root, config["dsn"]))
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    os.chdir(runtime)
    return config


def validate_child_dsn(root, dsn):
    from psycopg.conninfo import conninfo_to_dict

    try:
        values = conninfo_to_dict(dsn)
    except Exception:
        raise RuntimeError("invalid acceptance database target") from None
    expected = {
        "host": str(root / "socket"),
        "port": "5432",
        "dbname": "postgres",
        "user": "task_center_app",
        "connect_timeout": "3",
    }
    if values != expected:
        raise RuntimeError("refusing foreign acceptance database target")


def settings(dsn):
    from packages.config import Settings

    return Settings(
        task_center_enabled=True,
        task_center_database_url=dsn,
        task_center_pool_max_size=4,
        task_center_pool_timeout_seconds=1,
        task_center_lock_timeout_ms=700,
        task_center_statement_timeout_ms=1500,
        enterprise_store_backend="memory",
        demo_mode=True,
    )


def metadata_store():
    from packages.enterprise import EnterpriseMemoryStore
    from packages.schema.enterprise import WorkspaceRecord

    store = EnterpriseMemoryStore()
    for ws, limit in WORKSPACES.items():
        store.workspaces[ws] = WorkspaceRecord(id=ws, name=ws, monthly_run_quota=limit)
    return store


def run_api(config, fd):
    import uvicorn

    from app import deps
    from app.main import create_app
    from packages.task_center.factory import get_task_service

    store = metadata_store()
    # Install a cached synthetic metadata store before the actual startup handler.
    original_store = deps.get_enterprise_store()
    original_store.workspaces.update(store.workspaces)
    app = create_app()
    active_services = []

    @app.on_event("startup")
    async def track_service():
        active_services.append(
            get_task_service(
                deps.get_app_settings(), store=original_store, journal=deps.get_run_journal()
            )
        )

    @app.on_event("shutdown")
    async def assert_closed():
        proof = {
            "pool_closed": all(
                service.repository.database.pool is None for service in active_services
            ),
            "run_services_closed": not deps._RUN_SERVICE_CACHE,
        }
        write_json(Path(config["root"]) / f"api-{os.getpid()}-closed.json", proof)
        assert all(proof.values())

    @app.get("/api/_acceptance/stats")
    async def stats():
        service = get_task_service(
            deps.get_app_settings(), store=original_store, journal=deps.get_run_journal()
        )
        return {"pid": os.getpid(), "pool": service.repository.database.stats()}

    uvicorn.run(app, fd=fd, log_level="warning", access_log=False)


def run_receiver(config, fd):
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    filename = Path(config["root"]) / "receiver.db"
    with sqlite3.connect(filename) as conn:
        conn.execute("CREATE TABLE identities (id TEXT PRIMARY KEY, sends INTEGER NOT NULL)")
        conn.execute("CREATE TABLE sends (id TEXT, sender_pid INTEGER, generation INTEGER)")
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"pid": os.getpid()}

    @app.post("/accept")
    async def accept(request: Request):
        body = await request.json()
        if request.headers.get("X-Acceptance-Capability") != config["token"]:
            return JSONResponse({"error": "unauthorized"}, status_code=403)
        # The commit happens before the HTTP receipt, across a real process boundary.
        with sqlite3.connect(filename) as conn:
            conn.execute(
                "INSERT INTO identities VALUES (?,1) ON CONFLICT(id) DO UPDATE SET sends=sends+1",
                (body["run_id"],),
            )
            conn.execute(
                "INSERT INTO sends VALUES (?,?,?)",
                (body["run_id"], body["sender_pid"], body["generation"]),
            )
        if body["topic"] == "unknown":
            return JSONResponse({"error": "acceptance unknown"}, status_code=503)
        return {"run_id": body["run_id"]}

    uvicorn.run(app, fd=fd, log_level="warning", access_log=False)


async def run_relay(config, name):
    import httpx

    from packages.task_center.database import TaskCenterDatabase
    from packages.task_center.dispatch import DispatchReceipt
    from packages.task_center.relay import OutboxRelay
    from packages.task_center.repository import SubmissionRepository
    from scripts.run_submission_relay import serve

    root = Path(config["root"])
    database = TaskCenterDatabase(settings(config["dsn"]))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        await database.open()
        repo = SubmissionRepository(database)
        async with httpx.AsyncClient(timeout=0.8, trust_env=False) as client:

            async def dispatch(claim):
                response = await client.post(
                    config["receiver"] + "/accept",
                    json={
                        "run_id": claim.expected_run_id,
                        "topic": claim.request.topic,
                        "sender_pid": os.getpid(),
                        "generation": claim.generation,
                    },
                    headers={"X-Acceptance-Capability": config["token"]},
                )
                response.raise_for_status()
                if claim.request.topic == "crash" and claim.generation == 1:
                    saved_claim = asdict(claim)
                    saved_claim["request"] = claim.request.model_dump(mode="json")
                    write_json(root / "crashed-claim.json", saved_claim)
                    # Deliberate hard death after durable acceptance, before acknowledge.
                    os._exit(73)
                return DispatchReceipt(response.json()["run_id"])

            relay = OutboxRelay(
                repo,
                dispatch,
                lease_seconds=1.5,
                dispatch_timeout_seconds=1,
                retry_base_seconds=0,
                concurrency=4,
            )
            write_json(root / f"{name}-ready.json", {"pid": os.getpid()})
            # Both real workers become ready before either starts competing for the queue.
            other = "relay-2" if name == "relay-1" else "relay-1"
            while not (root / f"{other}-ready.json").exists():
                if stop.is_set():
                    return
                await asyncio.sleep(0.02)
            await serve(relay, stop, poll_seconds=0.03)
    finally:
        await database.close()
        write_json(root / f"{name}-closed.json", {"pool_closed": database.pool is None})


async def run_graph(config):
    from dataclasses import replace as replace_settings

    from packages.auth import EnterpriseUserContext
    from packages.identity import compute_graph_thread_id
    from packages.memory import RunJournal
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunService
    from packages.schema.api_dto import RunCreateRequest
    from packages.skills.registry import SkillRegistry
    from packages.task_center.database import TaskCenterDatabase
    from packages.task_center.models import SubmissionCreateRequest
    from packages.task_center.relay import OutboxRelay
    from packages.task_center.repository import SubmissionRepository
    from packages.task_center.service import TaskCenterService

    root = Path(config["root"])
    config_settings = replace_settings(
        settings(config["dsn"]),
        execution_control_enabled=True,
        execution_control_journal_path=str(root / "graph-runs.db"),
        hitl_enabled=False,
        hitl_timeout_seconds=0,
        run_orchestration_backend="langgraph",
    )
    database = TaskCenterDatabase(config_settings)
    journal = RunJournal(root / "graph-runs.db")
    checkpoint = GraphCheckpointer(root / "graph-checkpoints.db")
    task_service = TaskCenterService(
        SubmissionRepository(database),
        settings=config_settings,
        store=metadata_store(),
        journal=journal,
    )
    service = RunService(
        SkillRegistry.from_default_path(),
        config_settings,
        journal=journal,
        enterprise_store=task_service.store,
        graph_checkpointer=checkpoint,
        submission_service=task_service,
    )
    try:
        await task_service.open()
        view = await task_service.submit(
            SubmissionCreateRequest(
                idempotency_key="graph",
                request=RunCreateRequest(
                    workspace_id="graph",
                    topic="Task center demo",
                    competitors=["Cursor"],
                    dimensions=["pricing"],
                    execution_mode="demo",
                    hitl_enabled=False,
                ),
            ),
            actor=EnterpriseUserContext("acceptance-owner", "owner", "graph"),
        )

        async def dispatch(claim):
            return await task_service.dispatch(claim, run_service=service)

        outcome = await OutboxRelay(task_service.repository, dispatch).run_once(
            submission_id=view.id
        )
        await asyncio.gather(*list(service._background_tasks.values()))
        persisted = RunJournal(journal.db_path).load_run(view.expected_run_id)
        saver = await checkpoint.open()
        checkpoints = [item async for item in saver.alist(None)]
        checkpoint_thread_ids = sorted(
            {item.config["configurable"]["thread_id"] for item in checkpoints}
        )
        events = journal.load_events(view.expected_run_id)
        assert outcome.status == "dispatched"
        assert persisted.id == view.expected_run_id
        assert persisted.status in {"completed", "completed_with_blockers"}
        assert checkpoints and any(item.type == "run_completed" for item in events)
        assert checkpoint_thread_ids == [compute_graph_thread_id(view.expected_run_id, "demo")]
        write_json(
            root / "graph-result.json",
            {
                "run_id": persisted.id,
                "expected_run_id": view.expected_run_id,
                "submission_id": view.id,
                "run_status": persisted.status,
                "checkpoints": len(checkpoints),
                "checkpoint_thread_ids": checkpoint_thread_ids,
                "events": len(events),
                "adapter": "TaskCenterService.dispatch/RunService/LangGraph",
                "external_models": False,
                "real_temporal_server": False,
            },
        )
    finally:
        tasks = list(service._background_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await checkpoint.aclose()
        await task_service.close()


class OwnedChildren:
    def __init__(self, config, evidence):
        self.config = config
        self.evidence = evidence
        self.children = []
        self.sockets = []
        self.logs = []
        self.exit_records = {}
        self.expected_sender_pid = None

    def listener(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(256)
        port = listener.getsockname()[1]
        assert port not in {5173, 8000, 5432}
        self.sockets.append(listener)
        return listener, f"http://127.0.0.1:{port}"

    def start(self, role, listener=None):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--role",
            role,
            "--config",
            self.config["filename"],
            "--token",
            self.config["token"],
        ]
        if listener is not None:
            command += ["--fd", str(listener.fileno())]
        log = (self.evidence / f"{role}-{len(self.children)}.log").open("x")
        self.logs.append(log)
        child = subprocess.Popen(
            command,
            env=synthetic_environment(Path(self.config["root"]), self.config["dsn"]),
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=self.config["root"],
            pass_fds=(listener.fileno(),) if listener else (),
        )
        self.children.append((role, child))
        if listener is not None:
            listener.close()
        return child

    def stop(self, child):
        role = next((role for role, owned in self.children if owned is child), None)
        if role is None:
            raise RuntimeError("refusing to stop an unowned child")
        record = self.exit_records.setdefault(
            child.pid,
            {
                "role": role,
                "pid": child.pid,
                "returncode": None,
                "controller_stop_requested": False,
                "stop_requested_at_utc": None,
                "forced_kill": False,
                "expected_reason": None,
                "accepted": False,
            },
        )
        if child.poll() is None:
            command = subprocess.run(
                ["/bin/ps", "-p", str(child.pid), "-o", "args="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if (
                command.returncode != 0
                or self.config["token"] not in command.stdout
                or str(Path(__file__).resolve()) not in command.stdout
            ):
                raise RuntimeError("refusing to signal an unverified child PID")
            record["controller_stop_requested"] = True
            record["stop_requested_at_utc"] = datetime.now(UTC).isoformat()
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                record["forced_kill"] = True
                child.kill()
                child.wait(timeout=5)
        else:
            child.wait(timeout=5)
        record["returncode"] = child.returncode
        if record["forced_kill"]:
            record["expected_reason"] = "shutdown_timeout_forced_kill"
        elif record["controller_stop_requested"] and child.returncode in (0, -signal.SIGTERM):
            record.update(accepted=True, expected_reason="controller_requested_sigterm")
        elif (
            child.pid == self.expected_sender_pid
            and role in ("relay-1", "relay-2")
            and child.returncode == 73
        ):
            record.update(accepted=True, expected_reason="durable_acceptance_before_ack")
        elif role == "graph" and child.returncode == 0:
            record.update(accepted=True, expected_reason="graph_completed")
        else:
            record["expected_reason"] = "unexpected_exit"
        if not record["accepted"]:
            raise RuntimeError(
                f"unexpected owned child exit: {role} pid={child.pid} returncode={child.returncode}"
            )

    def close(self):
        failures = []
        for _, child in reversed(self.children):
            try:
                self.stop(child)
            except Exception as exc:
                failures.append(exc)
        for listener in self.sockets:
            listener.close()
        for log in self.logs:
            log.close()
        if failures:
            raise RuntimeError("owned child cleanup failed") from failures[0]
        assert all(child.poll() is not None for _, child in self.children)
        assert all(listener.fileno() == -1 for listener in self.sockets)


async def eventually(check, *, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("owned acceptance condition did not become ready")


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


class Acceptance:
    def __init__(self, postgres, children, config, evidence, report):
        self.pg, self.children, self.config = postgres, children, config
        self.evidence, self.report = evidence, report
        self.serial = 0

    def owner_sql(self, sql, args=()):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.pg.owner_dsn, row_factory=dict_row) as conn:
            cursor = conn.execute(sql, args)
            return cursor.fetchall() if cursor.description else []

    def tally(self, ws):
        result = {}
        for table in ("submissions", "quota_entries", "outbox", "dispatch_attempts"):
            result[table] = self.owner_sql(
                f"SELECT count(*) AS n FROM task_center.{table} WHERE workspace_id=%s", (ws,)
            )[0]["n"]
        return result

    async def request(
        self,
        method="POST",
        path="/api/task-submissions",
        *,
        ws="load",
        key=None,
        topic="acceptance",
        data=None,
        headers=None,
        index=None,
    ):
        self.serial += 1
        index = self.serial % 2 if index is None else index
        body = (
            {
                "idempotency_key": key or f"seed4242-{self.serial}",
                "request": {
                    "workspace_id": ws,
                    "topic": topic,
                    "dimensions": ["pricing"],
                    "execution_mode": "demo",
                    "hitl_enabled": False,
                },
            }
            if data is None and method == "POST" and path == "/api/task-submissions"
            else data
        )
        start = time.perf_counter()
        response = await self.client.request(
            method,
            self.config["apis"][index] + path,
            json=body,
            headers={"Authorization": f"Bearer acceptance-{ws}", **(headers or {})},
        )
        self.raw.write(
            json.dumps(
                {
                    "method": method,
                    "path": path,
                    "process": index,
                    "input": body,
                    "status": response.status_code,
                    "elapsed_ms": (time.perf_counter() - start) * 1000,
                    "response": response.json(),
                    "retry_after": response.headers.get("Retry-After"),
                }
            )
            + "\n"
        )
        self.raw.flush()
        return response

    async def batch(self, n, *, ws="load", key=None, topic="acceptance"):
        began = time.perf_counter()
        responses = await asyncio.gather(
            *(self.request(ws=ws, key=key, topic=topic, index=i % 2) for i in range(n))
        )
        elapsed = time.perf_counter() - began
        latencies = [item.elapsed.total_seconds() * 1000 for item in responses]
        metric = {
            "concurrency": n,
            "requests": n,
            "elapsed_seconds": elapsed,
            "submission_requests_per_second": n / elapsed,
            "p50_ms": percentile(latencies, 0.50),
            "p95_ms": percentile(latencies, 0.95),
            "p99_ms": percentile(latencies, 0.99),
            "status_distribution": dict(Counter(str(item.status_code) for item in responses)),
            "error_codes": dict(
                Counter(
                    item.json().get("code", "none") for item in responses if item.status_code >= 400
                )
            ),
        }
        return responses, metric

    async def view_ready(self, ws, submission, status):
        response = await self.request("GET", f"/api/task-submissions/{submission}", ws=ws)
        return (
            response.json()
            if response.status_code == 200 and response.json()["status"] == status
            else None
        )

    async def pool_stats(self):
        return [
            (await self.request("GET", "/api/_acceptance/stats", index=i)).json() for i in range(2)
        ]

    async def run(self):
        import httpx

        from packages.task_center.database import TaskCenterDatabase
        from packages.task_center.repository import SubmissionRepository

        database = TaskCenterDatabase(settings(self.pg.app_dsn))
        self.database = database
        await database.open()
        self.repo = SubmissionRepository(database)
        try:
            with (self.evidence / "http.jsonl").open("x") as self.raw:
                async with httpx.AsyncClient(
                    timeout=15,
                    trust_env=False,
                    limits=httpx.Limits(max_connections=120, max_keepalive_connections=120),
                ) as self.client:
                    for i in range(2):

                        async def ready(i=i):
                            try:
                                return (
                                    await self.client.get(self.config["apis"][i] + "/api/health")
                                ).status_code == 200
                            except httpx.HTTPError:
                                return False

                        await eventually(ready)
                    await self.scenarios()
        finally:
            await database.close()
            self.report["cleanup"]["controller_pool_closed"] = database.pool is None

    async def scenarios(self):
        from packages.auth import EnterpriseUserContext
        from packages.schema.api_dto import RunCreateRequest
        from packages.task_center.dispatch import DispatchReceipt
        from packages.task_center.errors import DispatchConflict
        from packages.task_center.models import DispatchClaim

        scenarios = self.report["scenarios"]
        responses, metric = await self.batch(100, ws="one-remaining")
        assert Counter(item.status_code for item in responses) == {202: 1, 429: 99}
        assert self.tally("one-remaining") == dict(
            submissions=1, quota_entries=1, outbox=1, dispatch_attempts=0
        )
        scenarios["one_remaining"] = {"metrics": metric, "rows": self.tally("one-remaining")}
        responses, metric = await self.batch(100, ws="same-key", key="same-key")
        assert all(item.status_code == 202 for item in responses)
        assert len({item.json()["id"] for item in responses}) == 1
        assert len({item.json()["expected_run_id"] for item in responses}) == 1
        assert self.tally("same-key") == dict(
            submissions=1, quota_entries=1, outbox=1, dispatch_attempts=0
        )
        scenarios["same_key"] = {
            "metrics": metric,
            "rows": self.tally("same-key"),
            "submission": responses[0].json(),
        }
        response = await self.request(ws="same-key", key="same-key", topic="changed")
        assert response.status_code == 409
        scenarios["payload_conflict"] = response.json()
        for table in ("submissions", "quota_entries", "outbox"):
            self.owner_sql(
                "CREATE OR REPLACE FUNCTION task_center.acceptance_failure() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'acceptance injected' "
                "USING ERRCODE='P0001'; END $$"
            )
            self.owner_sql(
                f"CREATE TRIGGER acceptance_failure BEFORE INSERT ON task_center.{table} "
                "FOR EACH ROW EXECUTE FUNCTION task_center.acceptance_failure()"
            )
            try:
                response = await self.request(ws="rollback")
                assert response.status_code == 503 and response.headers["Retry-After"] == "1"
                assert not any(self.tally("rollback").values())
                assert not self.owner_sql(
                    "SELECT * FROM task_center.workspace_policies WHERE workspace_id='rollback'"
                )
            finally:
                self.owner_sql(f"DROP TRIGGER acceptance_failure ON task_center.{table}")
        scenarios["sql_rollback"] = {
            "injected_tables": ["submissions", "quota_entries", "outbox"],
            "rows": self.tally("rollback"),
        }

        race_results = []
        for n in range(12):
            view = (await self.request(ws="cancel", key=f"cancel-{n}")).json()

            async def cancel(view=view):
                return await self.request(
                    "POST", f"/api/task-submissions/{view['id']}/cancel", ws="cancel"
                )

            cancel_response, claim = await asyncio.gather(
                cancel(), self.repo.claim(submission_id=view["id"]), return_exceptions=True
            )
            if cancel_response.status_code == 200:
                assert cancel_response.json()["status"] == "cancelled" and isinstance(
                    claim, DispatchConflict
                )
            else:
                assert cancel_response.status_code == 409 and not isinstance(claim, BaseException)
                assert await self.repo.mark_sending(claim)
                assert await self.repo.acknowledge(claim, DispatchReceipt(claim.expected_run_id))
            # Repeated cancellation must never return a second reservation.
            repeated = await cancel()
            assert repeated.status_code == cancel_response.status_code
            race_results.append(cancel_response.status_code)
        intent = (await self.request(ws="cancel", key="intent")).json()
        claim = await self.repo.claim(submission_id=intent["id"])
        assert await self.repo.mark_sending(claim)
        response = await self.request(
            "POST", f"/api/task-submissions/{intent['id']}/cancel", ws="cancel"
        )
        assert response.status_code == 409
        assert await self.repo.fail(
            claim, error_code="unknown", unknown=True, retry_delay_seconds=0
        )
        scenarios["cancel_races"] = {
            "outcomes": dict(Counter(map(str, race_results))),
            "intent_cancel": 409,
        }

        self.report["metrics"]["idle"] = []
        for n in (10, 50, 100):
            responses, metric = await self.batch(n)
            assert all(item.status_code == 202 for item in responses)
            self.report["metrics"]["idle"].append(metric)
        self.report["metrics"]["pools_before_saturation"] = await self.pool_stats()
        await self.saturation()

        # Real RLS reuses a single connection for alternating tenant and service scopes.
        from packages.task_center.database import TaskCenterDatabase

        tenant_database = TaskCenterDatabase(
            replace(settings(self.pg.app_dsn), task_center_pool_max_size=1)
        )
        reused_pids = []
        await tenant_database.open()
        try:
            for _ in range(3):
                for ws in ("same-key", "tenant-b"):
                    async with tenant_database.transaction(ws) as conn:
                        reused_pids.append(conn.info.backend_pid)
                        rows = await (
                            await conn.execute(
                                "SELECT DISTINCT workspace_id FROM task_center.submissions"
                            )
                        ).fetchall()
                        assert [row["workspace_id"] for row in rows] == (
                            ["same-key"] if ws == "same-key" else []
                        )
                async with tenant_database.transaction("", service_role=True) as conn:
                    assert await (
                        await conn.execute("SELECT id FROM task_center.submissions LIMIT 1")
                    ).fetchone()
            assert len(set(reused_pids)) == 1
        finally:
            await tenant_database.close()
            self.report["cleanup"]["tenant_pool_closed"] = tenant_database.pool is None
        response = await self.request(
            ws="load",
            headers={
                "Authorization": "Bearer acceptance-viewer",
                "X-User-Role": "owner",
                "X-User-Id": "acceptance-owner",
                "X-Workspace-Id": "same-key",
            },
        )
        assert response.status_code == 403
        response = await self.request(
            ws="same-key",
            headers={"Authorization": "Bearer acceptance-tenant-b", "X-Workspace-Id": "same-key"},
        )
        assert response.status_code == 403
        hidden = await self.request(
            "GET",
            f"/api/task-submissions/{scenarios['same_key']['submission']['id']}",
            ws="tenant-b",
        )
        assert hidden.status_code == 404
        scenarios["tenant_auth"] = {
            "spoofed_role": 403,
            "spoofed_workspace": 403,
            "hidden_id": 404,
            "pool_stats": self.database.stats(),
            "reused_backend_pids": reused_pids,
        }
        old = await self.request(
            path="/api/runs",
            ws="one-remaining",
            data={
                "workspace_id": "one-remaining",
                "topic": "old-entry",
                "dimensions": ["pricing"],
                "execution_mode": "demo",
                "idempotency_key": "old-entry",
            },
        )
        assert old.status_code == 429
        assert self.tally("one-remaining")["submissions"] == 1
        scenarios["old_http"] = {"status": old.status_code, "rows": self.tally("one-remaining")}

        # Terminate only backend connections belonging to our private restricted role.
        # The controller is not the fault target; close it through its real lifecycle.
        await self.database.close()
        terminated = self.owner_sql(
            "SELECT pg_terminate_backend(pid) AS stopped FROM pg_stat_activity "
            "WHERE usename='task_center_app' AND pid<>pg_backend_pid()"
        )
        loss = [await self.request(ws="load") for _ in range(2)]
        assert any(
            item.status_code == 503 and item.headers.get("Retry-After") == "1" for item in loss
        )

        async def recovered():
            response = await self.request(ws="load", key="after-connection-loss")
            return response if response.status_code == 202 else None

        await eventually(recovered)
        await self.database.open()
        scenarios["connection_loss"] = {
            "terminated": len(terminated),
            "statuses": [r.status_code for r in loss],
            "recovered": 202,
        }

        # A dedicated durable receiver and exactly two real relay workers.
        listener, receiver_url = self.children.listener()
        self.config["receiver"] = receiver_url
        write_json(Path(self.config["filename"]), self.config)
        self.children.start("receiver", listener)

        async def receiver_ready():
            try:
                return (await self.client.get(receiver_url + "/health")).status_code == 200
            except Exception:
                return False

        await eventually(receiver_ready)
        crash = (await self.request(ws="crash", topic="crash", key="crash")).json()
        relay1 = self.children.start("relay-1")
        relay2 = self.children.start("relay-2")
        self.report["processes"]["relay"] = [relay1.pid, relay2.pid]

        async def crashed():
            return relay1.poll() == 73 or relay2.poll() == 73

        await eventually(crashed)
        dead = relay1 if relay1.poll() == 73 else relay2
        survivor = relay2 if dead is relay1 else relay1
        saved = json.loads((Path(self.config["root"]) / "crashed-claim.json").read_text())
        saved["request"] = RunCreateRequest(**saved["request"])
        saved["actor"] = EnterpriseUserContext(**{k: v for k, v in saved["actor"].items()})
        saved["lease_until"] = datetime.fromisoformat(saved["lease_until"])
        old_claim = DispatchClaim(**saved)
        await eventually(lambda: self.view_ready("crash", crash["id"], "dispatched"))
        assert not await self.repo.acknowledge(
            old_claim, DispatchReceipt(old_claim.expected_run_id)
        )
        assert not await self.repo.fail(old_claim, error_code="stale", unknown=True)
        assert not await self.repo.mark_sending(
            replace(old_claim, generation=old_claim.generation + 1)
        )
        with sqlite3.connect(Path(self.config["root"]) / "receiver.db") as conn:
            sends = conn.execute(
                "SELECT sends FROM identities WHERE id=?", (crash["expected_run_id"],)
            ).fetchone()[0]
            senders = dict(
                conn.execute("SELECT sender_pid,count(*) FROM sends GROUP BY sender_pid")
            )
            crash_deliveries = conn.execute(
                "SELECT sender_pid,generation FROM sends WHERE id=? ORDER BY rowid",
                (crash["expected_run_id"],),
            ).fetchall()
        assert set(senders) == {relay1.pid, relay2.pid}, "both real relays must dispatch"
        assert sends == 2 and self.tally("crash")["quota_entries"] == 1
        # The parent identifies the one injected sender death from independently read
        # receiver/SQL evidence. A child's saved claim is not an expected-exit assertion.
        assert crash_deliveries == [(dead.pid, 1), (survivor.pid, 2)]
        attempt = self.owner_sql(
            "SELECT owner_token,sent_intent_at FROM task_center.dispatch_attempts "
            "WHERE submission_id=%s AND generation=1",
            (crash["id"],),
        )[0]
        assert old_claim.submission_id == crash["id"] and old_claim.generation == 1
        assert old_claim.expected_run_id == crash["expected_run_id"]
        assert str(attempt["owner_token"]) == old_claim.owner_token
        assert attempt["sent_intent_at"] is not None
        assert self.children.expected_sender_pid is None and dead.returncode == 73
        self.children.expected_sender_pid = dead.pid
        scenarios["sender_crash"] = {
            "sends": sends,
            "durable_business_identities": 1,
            "rows": self.tally("crash"),
            "dead_sender_exit": dead.returncode,
            "confirmed_expected_sender_pid": dead.pid,
            "sender_pid_counts": senders,
            "stale_ack": False,
            "stale_fail": False,
            "forged_generation": False,
        }
        unknown = (await self.request(ws="unknown", topic="unknown", key="unknown")).json()
        first = await eventually(
            lambda: self.view_ready("unknown", unknown["id"], "dispatch_failed")
        )
        assert first["dispatch_attempt_count"] == 3
        retried = await self.request(
            "POST", f"/api/task-submissions/{unknown['id']}/retry-dispatch", ws="unknown"
        )
        assert (
            retried.status_code == 202
            and retried.json()["expected_run_id"] == unknown["expected_run_id"]
        )
        second = await eventually(
            lambda: self.view_ready("unknown", unknown["id"], "dispatch_failed")
        )
        assert second["dispatch_attempt_count"] == 3
        assert self.tally("unknown")["quota_entries"] == 1
        assert self.tally("unknown")["dispatch_attempts"] == 6
        scenarios["retry_budget"] = {
            "automatic_attempts": 3,
            "after_manual_retry": 3,
            "rows": self.tally("unknown"),
            "refunds": 0,
        }
        # Recovery includes actual delivery, not just accepting another submission.
        await eventually(
            lambda: self.view_ready(
                "load",
                (
                    self.owner_sql(
                        "SELECT id FROM task_center.submissions WHERE workspace_id='load' "
                        "AND idempotency_key='after-connection-loss'"
                    )[0]["id"]
                ),
                "dispatched",
            )
        )
        self.report["metrics"]["pools_after_recovery"] = await self.pool_stats()
        self.report["metrics"]["resources"] = self.resources()
        self.report["processes"]["relay"] = [relay1.pid, relay2.pid]
        self.children.stop(survivor)
        survivor_name = "relay-2" if survivor is relay2 else "relay-1"
        assert json.loads((Path(self.config["root"]) / f"{survivor_name}-closed.json").read_text())[
            "pool_closed"
        ]

        graph = self.children.start("graph")

        async def graph_done():
            if graph.poll() is not None:
                assert graph.returncode == 0, "real Graph child failed; see graph log"
                return True
            return False

        await eventually(graph_done, seconds=45)
        scenarios["demo_graph"] = json.loads(
            (Path(self.config["root"]) / "graph-result.json").read_text()
        )
        await self.explain()
        scenarios["sql_integrity"] = self.integrity()
        for table in (
            "workspace_policies",
            "quota_buckets",
            "submissions",
            "quota_entries",
            "outbox",
            "dispatch_attempts",
            "audit_events",
        ):
            write_json(
                self.evidence / f"sql-{table}.json",
                self.owner_sql(f"SELECT * FROM task_center.{table}"),
            )
        self.report["metrics"]["connections"] = self.owner_sql(
            "SELECT application_name,usename,state,count(*) AS n FROM pg_stat_activity "
            "GROUP BY application_name,usename,state"
        )
        # Complete database loss is last: no unsafe default-parameter restart.
        assert self.pg._server_pid() == self.pg.pid
        self.pg._run("pg_ctl", "-D", str(self.pg.data_dir), "-m", "fast", "-w", "-t", "15", "stop")
        responses, metric = await self.batch(10)
        assert all(
            item.status_code == 503 and item.headers.get("Retry-After") == "1" for item in responses
        )
        scenarios["database_stop"] = {"metrics": metric, "retry_after": "1", "restarted": False}

    async def saturation(self):
        import psycopg

        self.report["metrics"]["saturated"] = []
        for n in (10, 50, 100):
            with psycopg.connect(self.pg.owner_dsn) as blocker:
                blocker.execute("LOCK task_center.quota_buckets IN ACCESS EXCLUSIVE MODE")
                responses, metric = await self.batch(n)
                assert all(
                    r.status_code == 503 and r.headers.get("Retry-After") == "1" for r in responses
                )
                self.report["metrics"]["saturated"].append(metric)
        self.report["metrics"]["pools_after_saturation"] = await self.pool_stats()
        assert (await self.request(ws="load", key="after-saturation")).status_code == 202
        self.report["scenarios"]["pool_saturation"] = {
            "recovered": 202,
            "errors": [m["status_distribution"] for m in self.report["metrics"]["saturated"]],
        }

    def resources(self):
        rows = []
        for role, child in self.children.children:
            if child.poll() is None:
                measured = subprocess.run(
                    ["/bin/ps", "-p", str(child.pid), "-o", "pid=,rss=,%cpu=,etime="],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                values = measured.stdout.split()
                rows.append(
                    {
                        "role": role,
                        "pid": int(values[0]),
                        "rss_kib": int(values[1]),
                        "cpu_percent_snapshot": float(values[2]),
                        "elapsed": values[3],
                    }
                )
        return rows

    async def explain(self):
        from packages.auth import EnterpriseUserContext
        from packages.schema.api_dto import RunCreateRequest
        from packages.task_center.models import QuotaSeed

        for offset in range(0, 1200, 20):
            await asyncio.gather(
                *(
                    self.repo.submit(
                        RunCreateRequest(
                            workspace_id="explain",
                            topic="index sample",
                            dimensions=["pricing"],
                            idempotency_key=f"index-{i}",
                        ),
                        actor=EnterpriseUserContext("acceptance-owner", "owner", "explain"),
                        seed=QuotaSeed(10000, "block"),
                    )
                    for i in range(offset, offset + 20)
                )
            )
        self.owner_sql("ANALYZE task_center.submissions")
        self.owner_sql("ANALYZE task_center.outbox")
        plans = {}
        async with self.database.transaction("explain") as conn:
            for name, sql, args in [
                (
                    "list",
                    "SELECT id,status,created_at FROM task_center.submissions "
                    "WHERE workspace_id=%s "
                    "ORDER BY created_at DESC,id DESC LIMIT 20",
                    ("explain",),
                ),
                (
                    "idempotency",
                    "SELECT id FROM task_center.submissions "
                    "WHERE workspace_id=%s AND idempotency_key=%s",
                    ("explain", "index-899"),
                ),
            ]:
                rows = await (
                    await conn.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + sql, args)
                ).fetchone()
                plans[name] = rows["QUERY PLAN"]
        write_json(self.evidence / "explain.json", plans)
        self.report["scenarios"]["explain"] = {
            "sample_submissions": 1200,
            "fixture_workspace": "explain",
            "fixture_purpose": (
                "synthetic pending fixtures for planning; excluded from HTTP metrics"
            ),
            "enable_seqscan": self.owner_sql("SHOW enable_seqscan")[0]["enable_seqscan"],
            "plans": plans,
        }

    def integrity(self):
        mismatches = self.owner_sql(
            "SELECT b.workspace_id,b.reserved_count,COALESCE(sum(CASE e.action "
            "WHEN 'reserve' THEN 1 ELSE -1 END),0) AS net "
            "FROM task_center.quota_buckets b LEFT JOIN "
            "task_center.quota_entries e USING(workspace_id,period_start) "
            "GROUP BY b.workspace_id,b.period_start "
            "HAVING b.reserved_count<>COALESCE(sum(CASE e.action "
            "WHEN 'reserve' THEN 1 ELSE -1 END),0)"
        )
        illegal = self.owner_sql(
            "SELECT s.id FROM task_center.submissions s LEFT JOIN task_center.outbox o "
            "ON s.id=o.submission_id WHERE o.id IS NULL "
            "OR (s.run_id IS NOT NULL AND s.run_id<>s.expected_run_id) "
            "OR (s.status='cancelled' AND o.state<>'cancelled')"
        )
        duplicates = self.owner_sql(
            "SELECT submission_id,action FROM task_center.quota_entries GROUP BY "
            "submission_id,action HAVING count(*)<>1"
        )
        assert not mismatches and not illegal and not duplicates
        return {
            "ledger_mismatches": mismatches,
            "illegal_or_orphan_rows": illegal,
            "duplicates": duplicates,
            "statuses": self.owner_sql(
                "SELECT status,count(*) AS n FROM task_center.submissions GROUP BY status"
            ),
            "rows_by_workspace": self.owner_sql(
                "SELECT workspace_id,status,count(*) AS n FROM task_center.submissions "
                "GROUP BY workspace_id,status ORDER BY workspace_id,status"
            ),
            "ledger": self.owner_sql(
                "SELECT action,count(*) AS n FROM task_center.quota_entries GROUP BY action"
            ),
            "note": "pending, dispatched and unknown/failed reservations are valid business state",
        }


def source_hashes():
    paths = [
        *sorted((BACKEND / "packages").rglob("*.py")),
        *sorted((BACKEND / "app").rglob("*.py")),
        *sorted((BACKEND / "packages/task_center/migrations").glob("*.sql")),
        BACKEND / "scripts/verify_task_center.py",
        BACKEND / "scripts/task_center_acceptance.py",
        BACKEND / "scripts/local_postgres.py",
        BACKEND / "scripts/run_submission_relay.py",
        BACKEND / "tests/integration/test_task_center_acceptance.py",
    ]
    return {
        str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def execute():
    from packages.task_center.migrations import apply_migrations
    from scripts.local_postgres import OwnedPostgres

    random.seed(4242)
    evidence = ARTIFACTS / (
        "impl-task6-fix1-run-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    )
    evidence.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "failed",
        "seed": 4242,
        "scenarios": {},
        "metrics": {},
        "cleanup": {},
        "processes": {"api": [], "relay": []},
        "configuration": {
            "api_pool_max_each": 4,
            "relay_pool_max_each": 4,
            "controller_pool_max": 4,
            "application_pool_budget": 20,
            "temporary_tenant_pool_max": 1,
            "tenant_pool_closed_before_relays_start": True,
            "postgres_max_connections": 32,
            "metadata": "memory",
            "submission_http_only_throughput": True,
            "full_llm_agent_latency_measured": False,
            "platform": sys.platform,
            "real_temporal_server": False,
            "external_models": False,
        },
        "source_sha256": source_hashes(),
    }
    for relative in report["source_sha256"]:
        snapshot = evidence / "source" / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes((REPO / relative).read_bytes())
    write_json(
        evidence / "inputs.json",
        {
            "seed": 4242,
            "workspaces": WORKSPACES,
            "concurrency": [10, 50, 100],
            "configuration": report["configuration"],
            "environment_template": synthetic_environment(
                Path("<owned-root>"), "<owned-private-app-dsn>"
            ),
        },
    )
    postgres = OwnedPostgres()
    children = None
    root = None
    try:
        postgres.start()
        root = postgres.root
        report["configuration"]["postgres_version"] = postgres._run(
            "postgres", "--version"
        ).stdout.strip()
        apply_migrations(postgres.owner_dsn)
        postgres.grant_app_access()
        config = {
            "root": str(root),
            "dsn": postgres.app_dsn,
            "token": postgres._marker,
            "filename": str(root / "acceptance.json"),
            "apis": [],
        }
        children = OwnedChildren(config, evidence)
        listeners = [children.listener() for _ in range(2)]
        config["apis"] = [url for _, url in listeners]
        write_json(Path(config["filename"]), config)
        report["configuration"]["loopback_urls"] = config["apis"]
        report["configuration"]["owned_configuration_sha256"] = hashlib.sha256(
            Path(config["filename"]).read_bytes()
        ).hexdigest()
        report["processes"]["api"] = [
            children.start("api", listener).pid for listener, _ in listeners
        ]
        asyncio.run(Acceptance(postgres, children, config, evidence, report).run())
        assert report["source_sha256"] == source_hashes(), "source changed during acceptance"
        report["status"] = "passed"
    except BaseException as exc:
        write_json(
            evidence / "first-failure.json",
            {"type": type(exc).__name__, "traceback": traceback.format_exc()},
        )
    finally:
        cleanup_failures = []
        try:
            if children:
                try:
                    children.close()
                except Exception:
                    cleanup_failures.append(traceback.format_exc())
                report["processes"]["exit_results"] = list(children.exit_records.values())
                report["processes"]["exit_validation_passed"] = len(children.exit_records) == len(
                    children.children
                ) and all(row["accepted"] for row in children.exit_records.values())
                report["cleanup"]["children_joined"] = all(
                    p.poll() is not None for _, p in children.children
                )
                report["cleanup"]["listeners_closed"] = all(
                    s.fileno() == -1 for s in children.sockets
                )
                for role, child in children.children:
                    if role == "api":
                        proof = json.loads((root / f"api-{child.pid}-closed.json").read_text())
                        assert all(proof.values())
                        (evidence / f"api-{child.pid}-closed.json").write_text(json.dumps(proof))
                report["cleanup"]["api_pools_closed"] = True
                urls = config["apis"] + ([config["receiver"]] if "receiver" in config else [])
                for url in urls:
                    with socket.socket() as probe:
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        probe.bind(("127.0.0.1", int(url.rsplit(":", 1)[1])))
                report["cleanup"]["ports_released"] = True
        except BaseException:
            cleanup_failures.append(traceback.format_exc())
        try:
            if root is not None and root.exists():
                for name in ("postgres.log", "graph-result.json", "crashed-claim.json"):
                    source = root / name
                    if source.exists():
                        (evidence / name).write_bytes(source.read_bytes())
                for name in ("receiver.db", "graph-runs.db", "graph-checkpoints.db"):
                    if (root / name).exists():
                        with sqlite3.connect(root / name) as source:
                            with sqlite3.connect(evidence / name) as target:
                                source.backup(target)
                report["configuration"]["final_owned_configuration_sha256"] = hashlib.sha256(
                    Path(config["filename"]).read_bytes()
                ).hexdigest()
        except BaseException:
            cleanup_failures.append(traceback.format_exc())
        try:
            # Always attempt PG cleanup, even when a child cleanup check failed.
            postgres.stop()
            report["cleanup"]["postgres_stopped"] = not postgres.is_running
            report["cleanup"]["temporary_directory_deleted"] = root is None or not root.exists()
            report["cleanup"]["sockets_removed"] = root is None or not (root / "socket").exists()
        except BaseException:
            cleanup_failures.append(traceback.format_exc())
        if cleanup_failures:
            report["status"] = "failed"
            write_json(evidence / "cleanup-failure.json", {"tracebacks": cleanup_failures})
            if not (evidence / "first-failure.json").exists():
                write_json(
                    evidence / "first-failure.json",
                    {
                        "type": "OwnedChildOrCleanupError",
                        "phase": "final_resource_validation",
                        "tracebacks": cleanup_failures,
                    },
                )
        report["evidence_sha256"] = {
            str(path.relative_to(evidence)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(evidence.rglob("*"))
            if path.is_file()
        }
        write_json(evidence / "result.json", report)
    return {"status": report["status"], "result": str(evidence / "result.json")}


def child_main():
    parser = argparse.ArgumentParser(description="private acceptance child")
    parser.add_argument(
        "--role", required=True, choices=["api", "receiver", "relay-1", "relay-2", "graph"]
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--fd", type=int)
    args = parser.parse_args()
    config = child_config(args.config, args.token)
    if args.role == "api":
        run_api(config, args.fd)
    elif args.role == "receiver":
        run_receiver(config, args.fd)
    elif args.role == "graph":
        asyncio.run(run_graph(config))
    else:
        asyncio.run(run_relay(config, args.role))


if __name__ == "__main__":
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    child_main()
