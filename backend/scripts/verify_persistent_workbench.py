"""Preview or explicitly verify an isolated persistent native PostgreSQL workbench."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data/artifacts/persistent-workbench-2026-10-30"


class VerificationFailure(RuntimeError):
    """A controlled, secret-free assertion suitable for an evidence report."""


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise VerificationFailure(message)


def validate_exit(record, snapshot, marker):
    exited = snapshot is None or (
        snapshot.get("created") == record["created"] and snapshot.get("state", "").startswith("Z")
    )
    require(
        exited
        and marker
        and all(
            marker.get(key) == value
            for key, value in {
                "pid": record["pid"],
                "created": record["created"],
                "exit_code": 0,
                "shutdown_complete": True,
            }.items()
        ),
        "service exit proof failed",
    )
    return {**record, **marker, "accepted": True}


def runtime_module():
    spec = importlib.util.spec_from_file_location(
        "persistent_acceptance_runtime", ROOT / "scripts/workbench_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Acceptance:
    def __init__(self, evidence, profile, backend_port, frontend_port):
        self.evidence, self.profile = evidence, profile
        self.runtime = runtime_module()
        self.manager = self.runtime.WorkbenchRuntime(
            ROOT,
            profile,
            backend_port=backend_port,
            frontend_port=frontend_port,
        )
        self.commands, self.exits, self.scenarios = [], [], {}
        self.stop_attempts, self.postgres_exits = [], []
        self.known_records, self.exit_proofs = {}, {}
        self.cleanup_errors = []
        self.recovery_attempt_count = 0
        self.database = {}
        self.stage = "initialization"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def cli(self, action):
        if action == "stop":
            self.capture_stop(self.records())
        command = [
            sys.executable,
            str(ROOT / "scripts/workbench_runtime.py"),
            action,
            "--execute",
            "--workspace-dir",
            str(self.profile),
            "--backend-port",
            str(self.manager.config["backend_port"]),
            "--frontend-port",
            str(self.manager.config["frontend_port"]),
        ]
        # Each lifecycle call has its own independent parent, from a foreign cwd.
        env = {
            key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR") if key in os.environ
        }
        env.update(COMPETISCOPE_LOAD_ENV_FILES="0", PYTHONDONTWRITEBYTECODE="1")
        child = subprocess.Popen(
            command,
            cwd=self.profile.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = child.communicate(timeout=100)
        except subprocess.TimeoutExpired:
            # This controller is our direct child; services retain their own ownership checks.
            child.terminate()
            stdout, stderr = child.communicate(timeout=10)
            self.commands.append(
                {"action": action, "pid": child.pid, "returncode": child.returncode}
            )
            raise RuntimeError("independent CLI timeout") from None
        row = {"action": action, "pid": child.pid, "returncode": child.returncode}
        self.commands.append(row)
        # Only controlled CLI output is retained; never serialize process environments.
        save(
            self.evidence / f"cli-{len(self.commands):02d}-{action}.json",
            {**row, "stdout": stdout, "stderr": stderr},
        )
        require(child.returncode == 0, "independent CLI failed")
        result = json.loads(stdout)
        self.remember_records(result.get("services", []))
        return result

    @staticmethod
    def record_key(record):
        return record["service"], record["pid"], record["created"]

    def remember_records(self, records):
        for record in records:
            canonical = {key: record[key] for key in ("service", "pid", "created")}
            self.known_records[self.record_key(canonical)] = canonical

    def spawn_role(self, role, env):
        try:
            record = self.manager.spawn(role, env)
        finally:
            if self.manager._pending_record is not None:
                self.remember_records([self.manager._pending_record])
        # In-memory ownership must precede the fallible persistent registry write.
        self.remember_records([record])
        return record

    def records(self):
        records = (self.manager.read_registry() or {}).get("services", [])
        self.remember_records(records)
        return records

    def capture_stop(self, records):
        self.stop_attempts.append(
            {
                "stage": self.stage,
                "records": [
                    {
                        **row,
                        "prior_exit_marker": self.manager.exit_result(row),
                        "cached_exit_proof": self.exit_proofs.get(self.record_key(row)),
                    }
                    for row in records
                ],
            }
        )
        save(self.evidence / "before-stop.json", self.stop_attempts)

    def pg_before_stop(self):
        postgres = self.manager.postgres()
        if not postgres.status()["running"]:
            return None
        return {
            "process": json.loads(postgres.process_path.read_text()),
            "log_offset": (postgres.postgres_dir / "postgres.log").stat().st_size,
        }

    def prove_pg_stopped(self, before):
        postgres = self.manager.postgres()
        require(not postgres.status()["running"], "PostgreSQL still running")
        if before is not None:
            process = before["process"]
            require(postgres._snapshot(process["pid"]) is None, "PostgreSQL actual exit unproven")
            with (postgres.postgres_dir / "postgres.log").open("rb") as stream:
                stream.seek(before["log_offset"])
                log = stream.read().decode("utf-8", errors="replace")
            require(
                "database system is shut down" in log, "PostgreSQL normal shutdown marker absent"
            )
            self.postgres_exits.append(
                {
                    "pid": process["pid"],
                    "created": process["created"],
                    "actual_exit": True,
                    "shutdown_complete": True,
                }
            )
            save(self.evidence / "postgres-exits.json", self.postgres_exits)

    def prove_exits(self, records):
        self.remember_records(records)
        for record in records:
            key = self.record_key(record)
            if key in self.exit_proofs:
                continue
            proof = validate_exit(
                record,
                self.runtime.process_snapshot(record["pid"]),
                self.manager.exit_result(record),
            )
            self.exit_proofs[key] = proof
            self.exits.append(proof)
            save(self.evidence / "exits.json", self.exits)

    def stop_role(self, record):
        if self.record_key(record) in self.exit_proofs:
            return
        self.capture_stop([record])
        self.manager.stop_record(record)
        self.prove_exits([record])

    def pause_relay(self):
        with self.manager.operation():
            record = next(row for row in self.records() if row["service"] == "relay")
            self.stop_role(record)

    def resume_relay(self):
        with self.manager.operation():
            records = [row for row in self.records() if row["service"] != "relay"]
            env = self.manager.child_environment(
                dict(os.environ), self.manager.postgres().app_environment()
            )
            record = self.spawn_role("relay", env)
            records.append(record)
            self.manager.write_registry(records, state="running")
            self.manager.wait_relay(record)

    def http(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.manager.config['backend_port']}/api{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def ok(self, method, path, payload=None, expected=200):
        status, body = self.http(method, path, payload)
        require(status == expected, f"HTTP expected {expected}, observed {status}")
        return body

    def wait_http(self, method, path, payload=None, expected=200):
        started = time.monotonic()
        observations = []
        suffix = hashlib.sha256(path.encode()).hexdigest()[:8]
        self.recovery_attempt_count += 1
        filename = f"recovery-{self.recovery_attempt_count:02d}-{method.lower()}-{suffix}.json"
        while time.monotonic() - started < 30:
            status, body = self.http(method, path, payload)
            observations.append(status)
            observation = {
                "path": path,
                "statuses": observations,
                "elapsed_seconds": time.monotonic() - started,
            }
            if path == "/readyz":
                observation["checks"] = body.get("checks", [])
            save(self.evidence / filename, observation)
            if status == expected:
                return body
            require(status == 503, f"unexpected recovery HTTP {status}")
            time.sleep(0.2)
        raise VerificationFailure("application pool recovery timeout")

    @staticmethod
    def payload(key):
        return {
            "idempotency_key": key,
            "request": {
                "topic": "持久工作台演示",
                "competitors": ["Cursor"],
                "dimensions": ["pricing"],
                "execution_mode": "demo",
                "research_depth": "quick",
                "collaboration_mode": "ai",
                "hitl_enabled": False,
                "auto_redo_warn_enabled": False,
            },
        }

    def ledger(self):
        return self.ok("GET", "/workspaces/default-workspace/quota-ledger?limit=100")

    def quota(self, limit):
        return self.ok(
            "PATCH",
            "/enterprise/workspaces/default-workspace/quota",
            {"monthly_run_quota": limit, "quota_enforcement": "block"},
        )

    def sql(self, statement, args=()):
        import psycopg
        from psycopg.rows import dict_row

        from packages.task_center.connection_logging import protected_connection_logging

        dsn = self.manager.postgres().app_environment()["ENTERPRISE_DATABASE_URL"]
        with protected_connection_logging(), psycopg.connect(dsn, row_factory=dict_row) as conn:
            conn.execute(
                "SELECT set_config('app.service_role','off',true), "
                "set_config('app.current_workspace_id','default-workspace',true)"
            )
            return conn.execute(statement, args).fetchall()

    def snapshot(self, submission_id):
        from packages.identity.stable_ids import compute_graph_thread_id

        submissions = self.sql(
            "SELECT id::text,workspace_id,project_id,status,expected_run_id,run_id "
            "FROM task_center.submissions WHERE id=%s",
            (submission_id,),
        )
        require(len(submissions) == 1, "submission missing from PostgreSQL")
        submission = submissions[0]
        run_id = submission["run_id"]
        require(run_id and run_id == submission["expected_run_id"], "run binding missing")
        runs = self.sql(
            "SELECT id,workspace_id,project_id,status,detail_json FROM runs WHERE id=%s", (run_id,)
        )
        require(len(runs) == 1, "enterprise run missing from PostgreSQL")
        run = runs[0]
        require(
            run["status"] in {"completed", "completed_with_blockers"},
            "enterprise run is not terminal",
        )
        require(
            run["project_id"] and run["workspace_id"] == submission["workspace_id"],
            "enterprise scope mismatch",
        )
        projects = self.sql(
            "SELECT id,workspace_id FROM projects WHERE id=%s", (run["project_id"],)
        )
        reports = self.sql(
            "SELECT id,version_number,workspace_id,project_id,run_id,report_md "
            "FROM report_versions "
            "WHERE run_id=%s ORDER BY version_number,id",
            (run_id,),
        )
        require(
            len(projects) == 1 and reports and all(row["report_md"] for row in reports),
            "project/report projection missing",
        )
        require(
            all(
                row["workspace_id"] == run["workspace_id"]
                and row["project_id"] == run["project_id"]
                for row in reports
            ),
            "report scope mismatch",
        )
        entries = self.sql(
            "SELECT action FROM task_center.quota_entries WHERE submission_id=%s ORDER BY action",
            (submission_id,),
        )
        require([row["action"] for row in entries] == ["reserve"], "reservation is not unique")
        with sqlite3.connect(f"file:{self.profile / 'run_journal.db'}?mode=ro", uri=True) as conn:
            journal = conn.execute(
                "SELECT id,status,detail_json FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            events = conn.execute(
                "SELECT event_id,event_json FROM events WHERE run_id=? ORDER BY event_id", (run_id,)
            ).fetchall()
        require(journal and journal[1] == run["status"] and events, "journal run/events missing")
        thread_id = compute_graph_thread_id(run_id, "demo")
        with sqlite3.connect(
            f"file:{self.profile / 'graph_checkpoints.db'}?mode=ro", uri=True
        ) as conn:
            checkpoints = conn.execute(
                "SELECT checkpoint_id,hex(checkpoint) FROM checkpoints WHERE thread_id=? "
                "ORDER BY checkpoint_id",
                (thread_id,),
            ).fetchall()
        require(checkpoints, "bound demo graph checkpoint missing")
        return {
            "submission": submission,
            "run": {key: run[key] for key in ("id", "workspace_id", "project_id", "status")},
            "project": projects[0],
            "report_versions": [row["id"] for row in reports],
            "report_version_numbers": [row["version_number"] for row in reports],
            "report_sha256": hashlib.sha256(
                json.dumps([row["report_md"] for row in reports]).encode()
            ).hexdigest(),
            "reserves": 1,
            "journal_sha256": hashlib.sha256(journal[2].encode()).hexdigest(),
            "event_count": len(events),
            "events_sha256": hashlib.sha256(json.dumps(events).encode()).hexdigest(),
            "graph_thread_id": thread_id,
            "checkpoint_count": len(checkpoints),
            "checkpoints_sha256": hashlib.sha256(json.dumps(checkpoints).encode()).hexdigest(),
            "content_qualified": False,
            "execution_mode": "demo",
        }

    def wait_completed(self, submission_id):
        deadline = time.monotonic() + 75
        last = None
        while time.monotonic() < deadline:
            view = self.ok("GET", f"/task-submissions/{submission_id}")
            if view.get("run_status") in {"completed", "completed_with_blockers", "failed"}:
                require(view["run_status"] != "failed", "demo graph failed")
                try:
                    return self.snapshot(submission_id)
                except RuntimeError as error:
                    last = error
            time.sleep(0.2)
        raise VerificationFailure("terminal graph and enterprise projection timeout") from last

    def verify_pending(self, submission):
        view = self.ok("GET", f"/task-submissions/{submission['id']}")
        require(
            view["status"] == "pending" and view["run_id"] is None and view["run_status"] is None,
            "pending submission falsely appears completed",
        )
        require(
            not self.sql("SELECT id FROM runs WHERE id=%s", (view["expected_run_id"],)),
            "pending acquired enterprise run",
        )
        return view

    def perform(self):
        self.cli("init")
        self.cli("start")
        require(self.cli("status")["state"] == "running", "CLI status is not running")
        self.database = self.sql(
            "SELECT current_setting('server_version') AS postgres_version, "
            "(SELECT extversion FROM pg_extension WHERE extname='vector') AS vector_version, "
            "current_setting('listen_addresses') AS listen_addresses"
        )[0]
        require(
            self.database["postgres_version"].startswith("15.")
            and self.database["vector_version"]
            and self.database["listen_addresses"] == "",
            "private PG15/vector contract failed",
        )
        self.quota(100)
        self.stage = "demo_graph"
        submission = self.ok("POST", "/task-submissions", self.payload("baseline"), 202)
        baseline = self.wait_completed(submission["id"])
        self.scenarios[self.stage] = baseline
        save(self.evidence / "baseline.json", baseline)

        self.stage = "api_relay_restart"
        postgres = self.manager.postgres()
        pg_before = json.loads(postgres.process_path.read_text())
        # Stop every role through the production identity gate, retaining PG. A fresh
        # public CLI process performs the start, rather than a same-parent Popen smoke.
        with self.manager.operation():
            for record in reversed(self.records()):
                self.stop_role(record)
            self.manager.write_registry([], state="stopped")
        require(postgres.status()["running"], "PostgreSQL stopped during API/Relay restart")
        self.cli("start")
        require(self.cli("status")["state"] == "running", "API/Relay restart status incorrect")
        require(
            json.loads(postgres.process_path.read_text()) == pg_before,
            "PostgreSQL identity changed",
        )
        require(
            self.snapshot(submission["id"]) == baseline, "data changed across API/Relay restart"
        )
        self.scenarios[self.stage] = {
            "baseline_unchanged": True,
            "postgres_identity_unchanged": True,
        }

        self.stage = "same_key_20"
        self.pause_relay()
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            replies = list(
                pool.map(
                    lambda _: self.http("POST", "/task-submissions", self.payload("same-key")),
                    range(20),
                )
            )
        require(all(status == 202 for status, _ in replies), "same-key concurrent HTTP failed")
        ids = {body["id"] for _, body in replies}
        require(len(ids) == 1, "same-key created multiple submissions")
        pending = self.verify_pending(replies[0][1])
        entries = self.sql(
            "SELECT action FROM task_center.quota_entries WHERE submission_id=%s", (pending["id"],)
        )
        require(entries == [{"action": "reserve"}], "same-key reserved more than once")
        self.scenarios[self.stage] = {
            "requests": 20,
            "submissions": 1,
            "reserves": 1,
            "submission_id": pending["id"],
        }

        self.stage = "cancel_once"
        before = self.ledger()["snapshot"]
        cancelled = self.ok("POST", "/task-submissions", self.payload("cancel"), 202)
        self.verify_pending(cancelled)
        self.ok("POST", f"/task-submissions/{cancelled['id']}/cancel")
        repeat, _ = self.http("POST", f"/task-submissions/{cancelled['id']}/cancel")
        require(repeat in {200, 409}, "repeat cancel response is ambiguous")
        actions = self.sql(
            "SELECT action FROM task_center.quota_entries WHERE submission_id=%s ORDER BY action",
            (cancelled["id"],),
        )
        require(
            actions == [{"action": "release"}, {"action": "reserve"}],
            "cancel did not release exactly once",
        )
        require(
            self.ledger()["snapshot"] == before, "quota snapshot did not restore after cancellation"
        )
        self.scenarios[self.stage] = {
            "submission_id": cancelled["id"],
            "release_count": 1,
            "snapshot_restored": True,
        }

        self.stage = "last_quota"
        snapshot = self.ledger()["snapshot"]
        self.quota(snapshot["imported_count"] + snapshot["reserved_count"] + 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            replies = list(
                pool.map(
                    lambda index: self.http(
                        "POST", "/task-submissions", self.payload(f"last-{index}")
                    ),
                    range(10),
                )
            )
        statuses = [status for status, _ in replies]
        require(
            statuses.count(202) == 1 and statuses.count(429) == 9,
            "last quota requires one 202 and nine explicit 429",
        )
        winner = next(body for status, body in replies if status == 202)
        self.verify_pending(winner)
        require(self.ledger()["snapshot"]["available"] == 0, "last quota snapshot incorrect")
        self.ok("POST", f"/task-submissions/{winner['id']}/cancel")
        self.scenarios[self.stage] = {
            "accepted": 1,
            "quota_rejected_429": 9,
            "submission_id": winner["id"],
        }

        self.stage = "pending_resume"
        self.verify_pending(pending)
        self.resume_relay()
        resumed = self.wait_completed(pending["id"])
        require(
            resumed["submission"]["expected_run_id"] == pending["expected_run_id"],
            "resumed another submission",
        )
        self.scenarios[self.stage] = resumed

        self.stage = "database_unavailable"
        self.pause_relay()
        fault_request = self.payload("database-down")
        quota_before = self.ledger()["snapshot"]
        self.quota(quota_before["imported_count"] + quota_before["reserved_count"] + 2)
        quota_before = self.ledger()["snapshot"]
        reserves_before = self.sql(
            "SELECT count(*) AS count FROM task_center.quota_entries WHERE action='reserve'"
        )[0]["count"]
        pg_before = self.pg_before_stop()
        postgres.stop()
        self.prove_pg_stopped(pg_before)
        status, body = self.http("POST", "/task-submissions", fault_request)
        require(status == 503, f"database unavailable requires 503, observed {status}")
        serialized = json.dumps(body).lower()
        require(
            not any(
                value in serialized
                for value in ("host=", "postgresql://", "plan_a_workspace_owner", "password")
            ),
            "unsafe 503 response",
        )
        save(self.evidence / "database-unavailable-response.json", {"status": status, "body": body})
        postgres.start()
        ready = self.wait_http("GET", "/readyz")
        required_checks = {row["name"]: row["status"] for row in ready["checks"]}
        require(
            all(required_checks.get(name) == "ok" for name in ("enterprise_store", "task_center")),
            "recovered readiness omitted required pools",
        )
        self.wait_http("GET", f"/task-submissions/{submission['id']}")
        replay = self.wait_http("POST", "/task-submissions", self.payload("baseline"), 202)
        require(
            replay["id"] == submission["id"] and self.snapshot(submission["id"]) == baseline,
            "database recovery duplicated or changed original data",
        )
        require(
            not self.sql(
                "SELECT id FROM task_center.submissions WHERE idempotency_key=%s",
                (fault_request["idempotency_key"],),
            ),
            "failed outage request left an orphan submission",
        )
        require(
            self.sql(
                "SELECT count(*) AS count FROM task_center.quota_entries WHERE action='reserve'"
            )[0]["count"]
            == reserves_before
            and self.ledger()["snapshot"] == quota_before,
            "failed outage request left a reservation",
        )
        recovered = self.wait_http("POST", "/task-submissions", fault_request, 202)
        repeated = self.wait_http("POST", "/task-submissions", fault_request, 202)
        require(
            recovered["id"] == repeated["id"]
            and recovered["expected_run_id"] == repeated["expected_run_id"],
            "original outage request replay changed submission binding",
        )
        fault_rows = self.sql(
            "SELECT id::text,expected_run_id FROM task_center.submissions WHERE idempotency_key=%s",
            (fault_request["idempotency_key"],),
        )
        require(
            fault_rows
            == [{"id": recovered["id"], "expected_run_id": recovered["expected_run_id"]}],
            "original outage request did not create exactly one bound submission",
        )
        require(
            self.sql(
                "SELECT action FROM task_center.quota_entries WHERE submission_id=%s",
                (recovered["id"],),
            )
            == [{"action": "reserve"}]
            and self.sql(
                "SELECT count(*) AS count FROM task_center.quota_entries WHERE action='reserve'"
            )[0]["count"]
            == reserves_before + 1,
            "original outage request replay did not reserve exactly once",
        )
        self.verify_pending(recovered)
        self.resume_relay()
        fault_completed = self.wait_completed(recovered["id"])
        require(
            fault_completed["submission"]["run_id"] == recovered["expected_run_id"],
            "recovered outage request completed another run",
        )
        self.scenarios[self.stage] = {
            "status": 503,
            "safe_error": True,
            "baseline_unchanged": True,
            "original_request_replayed": True,
            "outage_orphan_submissions": 0,
            "outage_extra_reserves": 0,
            "replay_count": 2,
            "original_request": fault_completed,
        }

        self.stage = "full_restart"
        records = self.records()
        pg_before = self.pg_before_stop()
        self.cli("stop")
        self.prove_exits(records)
        self.prove_pg_stopped(pg_before)
        require((postgres.data_dir / "PG_VERSION").is_file(), "stop removed persistent data")
        self.cli("start")
        require(self.cli("status")["state"] == "running", "restart status incorrect")
        require(
            self.snapshot(submission["id"]) == baseline, "full restart changed persisted baseline"
        )
        require(self.snapshot(pending["id"]) == resumed, "full restart changed resumed task")
        require(
            self.snapshot(recovered["id"]) == fault_completed,
            "full restart changed recovered outage request",
        )
        self.scenarios[self.stage] = {
            "baseline_unchanged": True,
            "resumed_unchanged": True,
            "fault_request_unchanged": True,
            "data_preserved_on_stop": True,
        }

    def cleanup(self):
        errors = []
        registry_available = True
        try:
            registered = self.records()
        except Exception:
            registered = []
            registry_available = False
            errors.append("registry unavailable")
        self.remember_records(registered)
        if self.manager._pending_record is not None:
            self.remember_records([self.manager._pending_record])
        records = list(self.known_records.values())
        try:
            pg_before = self.pg_before_stop()
        except Exception:
            pg_before = None
            errors.append("PostgreSQL identity unavailable")
        registered_keys = {self.record_key(record) for record in registered}
        # An unregistered but verified spawn must exit before the independent CLI
        # can stop PostgreSQL. Historical normal exits use their own cached proof.
        extras_proven = True
        for record in reversed(records):
            if self.record_key(record) not in registered_keys:
                try:
                    self.stop_role(record)
                except Exception:
                    extras_proven = False
                    errors.append(f"{record['service']} extra shutdown unproven")
        cli_stopped = False
        if extras_proven and registry_available:
            try:
                remaining = [
                    record
                    for record in registered
                    if self.record_key(record) not in self.exit_proofs
                ]
                if remaining != registered:
                    # A newer same-role child may have replaced the exit marker.
                    # Retire only registry records with an actual cached normal exit.
                    with self.manager.operation():
                        self.manager.write_registry(
                            remaining,
                            state="running" if remaining else "stopped",
                        )
                self.cli("stop")
                self.prove_exits(records)
                cli_stopped = True
            except Exception:
                errors.append("CLI shutdown failed")
        if not cli_stopped:
            for record in reversed(records):
                try:
                    self.stop_role(record)
                except Exception:
                    errors.append(f"{record['service']} shutdown unproven")
        services_proven = all(self.record_key(record) in self.exit_proofs for record in records)
        services_exited = True
        for record in records:
            if self.record_key(record) in self.exit_proofs:
                continue
            try:
                services_exited = services_exited and self.manager.has_exited(
                    record,
                    self.runtime.process_snapshot(record["pid"]),
                )
            except Exception:
                services_exited = False
        # An actual abnormal exit remains a failure, but no longer needs PG.
        # An active or identity-unknown process retains its dependency and data.
        if services_exited and not cli_stopped:
            try:
                self.manager.postgres().stop()
            except Exception:
                errors.append("PostgreSQL shutdown unproven")
        try:
            require(services_exited, "owned services remain active or unknown; PostgreSQL retained")
            postgres = self.manager.postgres()
            require(not postgres.status()["running"], "PostgreSQL still running")
            self.prove_pg_stopped(pg_before)
            require(services_proven, "owned service normal exits remain unproven")
            self.prove_exits(records)
        except Exception:
            errors.append("final exit verification failed")
        self.cleanup_errors = list(dict.fromkeys([*self.cleanup_errors, *errors]))
        return {
            "all_stopped": not self.cleanup_errors,
            "all_services_exited": services_exited,
            "normal_exits_proven": services_proven,
            "errors": list(self.cleanup_errors),
            "temporary_removed": False,
        }


def execute():
    backend = ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="impl-task4-run-", dir=ARTIFACTS))
    temporary = Path(tempfile.mkdtemp(prefix="persistent-workbench-test-")).resolve()
    profile = temporary / "profile"
    with socket.socket() as first, socket.socket() as second:
        first.bind(("127.0.0.1", 0))
        second.bind(("127.0.0.1", 0))
        ports = first.getsockname()[1], second.getsockname()[1]
    session = Acceptance(evidence, profile, *ports)
    failed = False
    try:
        session.perform()
    except Exception as error:
        failed = True
        save(
            evidence / "first-failure.json",
            {
                "stage": session.stage,
                "error_type": type(error).__name__,
                "message": str(error)
                if isinstance(error, VerificationFailure)
                else "operation failed; private diagnostic profile retained",
            },
        )
    finally:
        cleanup = session.cleanup()
    if not cleanup["all_stopped"] and not (evidence / "first-failure.json").exists():
        save(
            evidence / "first-failure.json",
            {
                "stage": "cleanup",
                "error_type": "ShutdownUnproven",
                "message": "owned process shutdown could not be proven",
            },
        )
    if cleanup["all_stopped"] and not failed:
        postgres = session.manager.postgres()
        # The random directory is allocated here, never accepted as a CLI target.
        require(
            temporary.name.startswith("persistent-workbench-test-") and not temporary.is_symlink(),
            "temporary ownership changed",
        )
        shutil.rmtree(temporary)
        if postgres.socket_dir.exists():
            postgres._check_socket()
            (postgres.socket_dir / ".workspace-postgres-socket").unlink()
            postgres.socket_dir.rmdir()
        cleanup["temporary_removed"] = True
    result = {
        "status": "failed" if failed or not cleanup["all_stopped"] else "passed",
        "scenarios": session.scenarios,
        "cli_commands": session.commands,
        "exits": session.exits,
        "postgres_exits": session.postgres_exits,
        "database": session.database,
        "cleanup": cleanup,
        "browser": "root_pending",
        "profile": str(profile),
        "model_calls": "demo graph; no external model capability asserted",
    }
    save(evidence / "result.json", result)
    return {"status": result["status"], "result": str(evidence / "result.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            "preview: independent CLI lifecycle; native PG15 + vector; real HTTP/Relay/demo graph; "
            "20 same-key requests, quota/cancel/outage and persistent restarts; "
            "--execute creates only a random private temporary profile and loopback ports"
        )
        return 0
    result = execute()
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
