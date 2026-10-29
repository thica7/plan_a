"""HTTP acceptance uses real admission transactions against private PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from app import deps
from app.main import create_app
from packages.auth import EnterpriseUserContext
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import RunJournal
from packages.schema.api_dto import RunCreateRequest
from packages.task_center.models import QuotaSeed
from packages.task_center.repository import SubmissionRepository

pytest_plugins = ("postgres_support",)


async def test_ledger_page_and_snapshot_share_one_mvcc_statement(task_database):
    repo = SubmissionRepository(task_database)
    actor = EnterpriseUserContext("tester", "owner", "default-workspace")
    view = await repo.submit(
        RunCreateRequest(topic="coherent ledger", dimensions=["product"]),
        actor=actor,
        seed=QuotaSeed(2, "block"),
        idempotency_key="ledger",
    )
    snapshot_read, resume = asyncio.Event(), asyncio.Event()
    original = task_database.transaction
    reader = None

    class ReaderConnection:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        async def execute(self, query, *args, **kwargs):
            cursor = await self.conn.execute(query, *args, **kwargs)
            if (
                asyncio.current_task() is reader
                and "task_center.quota_buckets" in str(query)
                and "SELECT" in str(query).upper()
            ):
                snapshot_read.set()
                await resume.wait()
            return cursor

    @asynccontextmanager
    async def gated(*args, **kwargs):
        async with original(*args, **kwargs) as conn:
            yield ReaderConnection(conn)

    # Cancellation must commit on another connection while the completed SELECT is paused.
    await task_database.pool.resize(1, 3)
    task_database.transaction = gated
    reader = asyncio.create_task(repo.quota_ledger("default-workspace"))
    try:
        await asyncio.wait_for(snapshot_read.wait(), 3)
        await repo.cancel("default-workspace", view.id, actor=actor)
    finally:
        resume.set()
    page = await reader
    assert page.next_cursor is None
    assert page.snapshot.reserved_count == sum(
        1 if e.action == "reserve" else -1 for e in page.items
    )
    assert page.snapshot.period_start.utcoffset().total_seconds() == 0


@pytest.fixture
async def http_client(task_postgres, tmp_path):
    settings = Settings(
        task_center_enabled=True,
        task_center_database_url=task_postgres.app_dsn,
        enterprise_store_backend="memory",
        run_orchestration_backend="langgraph",
        temporal_traffic_percent=0,
        task_center_pool_min_size=1,
        task_center_pool_max_size=4,
        task_center_pool_timeout_seconds=1,
    )
    journal = RunJournal(tmp_path / "journal.sqlite3")
    store = EnterpriseMemoryStore()
    application = create_app()
    application.dependency_overrides[deps.get_app_settings] = lambda: settings
    application.dependency_overrides[deps.get_enterprise_store] = lambda: store
    application.dependency_overrides[deps.get_run_journal] = lambda: journal
    application.dependency_overrides[deps.get_run_service] = lambda: pytest.fail(
        "pure API built Graph"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client, settings, journal, store, application
    from packages.task_center.factory import close_task_services

    await close_task_services()


def body(key="first", **updates):
    return {
        "idempotency_key": key,
        "request": {
            "topic": "private test topic",
            "dimensions": ["product"],
            "workspace_id": "default-workspace",
            **updates,
        },
    }


async def test_http_create_replay_conflict_cancel_and_projection(http_client):
    client, *_ = http_client
    response = await client.post("/api/task-submissions", json=body())
    assert response.status_code == 202, response.text
    view = response.json()
    assert view["status"] == "pending" and view["run_status"] is None
    assert view["run_status_observed_at"] is not None
    assert set(view) == {
        "id",
        "workspace_id",
        "project_id",
        "status",
        "expected_run_id",
        "run_id",
        "workflow_id",
        "created_at",
        "updated_at",
        "period_start",
        "dispatch_attempt_count",
        "last_error_code",
        "run_status",
        "run_status_observed_at",
    }
    replay = await client.post("/api/task-submissions", json=body())
    assert replay.status_code == 202 and replay.json()["id"] == view["id"]
    conflict = await client.post("/api/task-submissions", json=body(topic="changed"))
    assert conflict.status_code == 409
    for _ in range(2):
        cancelled = await client.post(f"/api/task-submissions/{view['id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    ledger = await client.get("/api/workspaces/default-workspace/quota-ledger")
    assert ledger.status_code == 200, ledger.text
    assert ledger.json()["snapshot"]["reserved_count"] == 0
    assert sorted(e["action"] for e in ledger.json()["items"]) == ["release", "reserve"]
    assert "private test topic" not in str(view) and "owner_token" not in str(view)


async def test_http_pagination_concurrent_replay_and_validation(http_client):
    client, *_ = http_client
    responses = await asyncio.gather(
        *(client.post("/api/task-submissions", json=body()) for _ in range(8))
    )
    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["id"] for r in responses}) == 1
    await client.post("/api/task-submissions", json=body("second"))
    page = await client.get("/api/task-submissions", params={"limit": 1})
    assert page.status_code == 200 and page.json()["next_cursor"]
    other = await client.get(
        "/api/task-submissions", params={"limit": 1, "cursor": page.json()["next_cursor"]}
    )
    assert (
        other.status_code == 200 and other.json()["items"][0]["id"] != page.json()["items"][0]["id"]
    )
    for params in (
        {"limit": 0},
        {"limit": 101},
        {"cursor": "bad"},
        {"cursor": page.json()["next_cursor"], "status": "cancelled"},
    ):
        invalid = await client.get("/api/task-submissions", params=params)
        assert invalid.status_code in (400, 422)
    for extra in ("execution_backend", "delivery_intent", "skip_quota"):
        invalid = await client.post("/api/task-submissions", json={**body(), extra: "x"})
        assert invalid.status_code == 422


async def test_http_scope_permissions_disabled_and_model_policy(http_client):
    client, settings, _, _, _ = http_client
    created = await client.post("/api/task-submissions", json=body())
    assert created.status_code == 202
    headers = {"X-Workspace-Id": "other", "X-User-Role": "owner"}
    assert (
        await client.get(
            "/api/task-submissions", params={"workspace_id": "default-workspace"}, headers=headers
        )
    ).status_code == 403
    assert (
        await client.get(f"/api/task-submissions/{created.json()['id']}", headers=headers)
    ).status_code == 404
    assert (
        await client.post("/api/task-submissions", json=body("project", project_id="unknown"))
    ).status_code == 400
    assert (
        await client.post(
            "/api/task-submissions", json=body("reader"), headers={"X-User-Role": "viewer"}
        )
    ).status_code == 403
    real = await client.post("/api/task-submissions", json=body("real", execution_mode="real"))
    assert real.status_code == 400
    object.__setattr__(settings, "task_center_enabled", False)
    disabled = await client.post("/api/task-submissions", json=body("off"))
    assert disabled.status_code == 503


async def test_http_auth_subject_cannot_be_spoofed_and_quota_retry_is_free(
    http_client, monkeypatch
):
    import json

    from app.middleware import auth
    from packages.schema.enterprise import WorkspaceQuotaUpdateRequest

    client, _, _, store, _ = http_client
    store.update_workspace_quota(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=1)
    )
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv(
        "AUTH_TOKEN_SUBJECTS",
        json.dumps(
            {
                "owner-token": {
                    "user_id": "owner",
                    "role": "owner",
                    "workspace_id": "default-workspace",
                },
                "viewer-token": {
                    "user_id": "viewer",
                    "role": "viewer",
                    "workspace_id": "default-workspace",
                },
                "other-token": {"user_id": "other", "role": "owner", "workspace_id": "other"},
            }
        ),
    )
    owner = {"Authorization": "Bearer owner-token"}
    first = await client.post("/api/task-submissions", json=body(), headers=owner)
    assert first.status_code == 202
    denied = await client.post(
        "/api/task-submissions",
        json=body("spoof"),
        headers={
            "Authorization": "Bearer viewer-token",
            "X-User-Role": "owner",
            "X-User-Id": "owner",
        },
    )
    assert denied.status_code == 403
    other = await client.get(
        f"/api/task-submissions/{first.json()['id']}",
        headers={"Authorization": "Bearer other-token", "X-Workspace-Id": "default-workspace"},
    )
    assert other.status_code == 404
    quota = await client.post("/api/task-submissions", json=body("full"), headers=owner)
    assert quota.status_code == 429
    # Real claim/failure leaves the original reservation; public retry preserves identity.
    from packages.task_center.factory import get_task_service

    _, settings, journal, store, _ = http_client
    service = get_task_service(settings, store=store, journal=journal)
    claim = await service.repository.claim(submission_id=first.json()["id"], max_attempts=1)
    assert await service.repository.fail(
        claim, error_code="dispatch_error", unknown=True, max_attempts=1
    )
    retried = await client.post(
        f"/api/task-submissions/{first.json()['id']}/retry-dispatch", headers=owner
    )
    assert retried.status_code == 202
    assert retried.json()["expected_run_id"] == first.json()["expected_run_id"]
    ledger = await client.get("/api/workspaces/default-workspace/quota-ledger", headers=owner)
    assert ledger.json()["snapshot"]["reserved_count"] == 1
    assert [item["action"] for item in ledger.json()["items"]] == ["reserve"]


async def test_disabled_dependency_stops_before_metadata_io(monkeypatch):
    application = create_app()
    application.dependency_overrides[deps.get_app_settings] = lambda: Settings(
        task_center_enabled=False
    )
    application.dependency_overrides[deps.get_enterprise_store] = lambda: pytest.fail(
        "disabled constructed store"
    )
    application.dependency_overrides[deps.get_run_journal] = lambda: pytest.fail(
        "disabled constructed journal"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/api/task-submissions")
    assert response.status_code == 503 and response.headers["retry-after"] == "1"


async def test_startup_readiness_and_shutdown_order_keep_graph_and_transactions_joined(
    http_client, monkeypatch
):
    from functools import lru_cache
    from types import SimpleNamespace

    from packages.task_center.factory import get_task_service

    client, settings, journal, store, application = http_client
    monkeypatch.setattr(deps, "get_app_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_run_journal", lambda: journal)

    @lru_cache
    def cached_store():
        return store

    monkeypatch.setattr(deps, "get_enterprise_store", cached_store)
    lifespan = application.router.lifespan_context(application)
    await lifespan.__aenter__()
    service = get_task_service(settings, store=store, journal=journal)
    pool = service.repository.database.pool
    ready = await client.get("/api/readyz")
    assert ready.status_code == 200, ready.text
    assert any(check == {"name": "task_center", "status": "ok"} for check in ready.json()["checks"])
    assert service.repository.database.pool is pool
    await client.post("/api/task-submissions", json=body())
    assert service.repository.database.pool is pool
    borrower_entered, borrower_release = asyncio.Event(), asyncio.Event()
    graph_closing, graph_release, graph_joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def borrower():
        async with service.repository.database.transaction("default-workspace") as conn:
            await conn.execute("SELECT 1")
            borrower_entered.set()
            await borrower_release.wait()
            await conn.execute("SELECT 2")

    async def close_graph():
        assert service.repository.database.pool is pool
        graph_closing.set()
        await graph_release.wait()
        graph_joined.set()

    deps._RUN_SERVICE_CACHE[(id(application),)] = SimpleNamespace(aclose=close_graph)
    borrowed = asyncio.create_task(borrower())
    await borrower_entered.wait()
    shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
    await graph_closing.wait()
    rejected = await client.post("/api/task-submissions", json=body("stopping"))
    assert rejected.status_code == 503
    assert not shutdown.done()
    graph_release.set()
    await graph_joined.wait()
    await asyncio.sleep(0.01)
    assert not shutdown.done(), "driver close must wait for checked-out transaction"
    borrower_release.set()
    await borrowed
    await shutdown
    assert service.repository.database.pool is None


async def test_http_validation_and_pool_errors_do_not_echo_private_payload(http_client):
    client, settings, journal, store, _ = http_client
    invalid = await client.post(
        "/api/task-submissions", json={**body(), "backend": "private-extra-payload"}
    )
    assert invalid.status_code == 422
    assert "private-extra-payload" not in invalid.text
    from packages.task_center.factory import get_task_service

    service = get_task_service(settings, store=store, journal=journal)
    async with service.repository.database._connection():
        async with service.repository.database._connection():
            async with service.repository.database._connection():
                async with service.repository.database._connection():
                    response = await client.get("/api/task-submissions")
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert response.json()["code"] == "task_center_pool_busy"
    assert settings.task_center_database_url not in response.text
    assert "private test topic" not in response.text


@pytest.mark.parametrize("initial_demo_mode", [True, False])
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_auto_identity_replays_first_mode_after_defaults_and_zero_quota_change(
    http_client, initial_demo_mode, cancel_first
):
    from packages.governance.model_policy import build_model_policy_report
    from packages.schema.enterprise import WorkspaceQuotaUpdateRequest
    from packages.task_center.factory import get_task_service

    client, settings, journal, store, _ = http_client
    object.__setattr__(settings, "ark_api_key", "dummy-local-policy-value")
    object.__setattr__(settings, "ark_model", "dummy-local-model")
    object.__setattr__(settings, "demo_mode", initial_demo_mode)
    assert build_model_policy_report(settings).real_execution_allowed
    original_mode = settings.default_execution_mode
    payload = body("auto-stable-identity")
    first = await client.post("/api/task-submissions", json=payload)
    assert first.status_code == 202, first.text
    service = get_task_service(settings, store=store, journal=journal)
    async with service.repository.database.transaction("default-workspace") as conn:
        original = await (
            await conn.execute(
                "SELECT request_json,request_sha,client_request_sha,execution_backend "
                "FROM task_center.submissions "
                "WHERE id=%s",
                (first.json()["id"],),
            )
        ).fetchone()
    assert original["request_json"]["execution_mode"] == original_mode
    from packages.task_center.canonical import canonical_request

    assert (
        original["client_request_sha"]
        == canonical_request(RunCreateRequest(**payload["request"]))[1]
    )
    assert (
        original["request_sha"]
        == canonical_request(RunCreateRequest(**original["request_json"]))[1]
    )
    assert original["client_request_sha"] != original["request_sha"]
    if cancel_first:
        assert (
            await client.post(f"/api/task-submissions/{first.json()['id']}/cancel")
        ).status_code == 200
    await service.update_policy(
        "default-workspace",
        WorkspaceQuotaUpdateRequest(monthly_run_quota=0),
        actor=EnterpriseUserContext("owner", "owner", "default-workspace"),
    )
    object.__setattr__(settings, "demo_mode", not initial_demo_mode)
    assert settings.default_execution_mode != original_mode
    replay = await client.post("/api/task-submissions", json=payload)
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["status"] == ("cancelled" if cancel_first else "pending")
    async with service.repository.database.transaction("default-workspace") as conn:
        stored = await (
            await conn.execute(
                "SELECT request_json,request_sha,client_request_sha,execution_backend "
                "FROM task_center.submissions "
                "WHERE id=%s",
                (first.json()["id"],),
            )
        ).fetchone()
        counts = await (
            await conn.execute(
                "SELECT (SELECT count(*) FROM task_center.submissions) AS submissions,"
                "(SELECT sum(reserved_count) FROM task_center.quota_buckets) AS reserved,"
                "(SELECT count(*) FROM task_center.quota_entries "
                "WHERE action='reserve') AS reserves"
            )
        ).fetchone()
    assert stored == original
    assert counts == {"submissions": 1, "reserved": 0 if cancel_first else 1, "reserves": 1}
    # A business change or an explicit mode is a different raw request, even if it
    # happens to resolve to the original execution mode.
    for changed in (
        body("auto-stable-identity", topic="other topic"),
        body("auto-stable-identity", execution_mode=original_mode),
        body("auto-stable-identity", execution_mode=settings.default_execution_mode),
    ):
        assert (await client.post("/api/task-submissions", json=changed)).status_code == 409
    assert (
        await client.post("/api/task-submissions", json=payload, headers={"X-User-Role": "viewer"})
    ).status_code == 403


async def test_accepted_auto_replay_does_not_govern_a_new_default_mode(http_client):
    from packages.governance.model_policy import build_model_policy_report

    client, settings, *_ = http_client
    object.__setattr__(settings, "ark_api_key", "dummy-local-policy-value")
    object.__setattr__(settings, "ark_model", "dummy-local-model")
    first = await client.post("/api/task-submissions", json=body("accepted-auto"))
    assert first.status_code == 202
    # Current real policy is blocked. That cannot rewrite a stored demo submission
    # or reject replay of the identical already accepted client request.
    object.__setattr__(settings, "demo_mode", False)
    object.__setattr__(settings, "compliance_redaction_enabled", False)
    assert settings.default_execution_mode == "real"
    assert not build_model_policy_report(settings).real_execution_allowed
    replay = await client.post("/api/task-submissions", json=body("accepted-auto"))
    assert replay.status_code == 202 and replay.json()["id"] == first.json()["id"]
    assert (await client.post("/api/task-submissions", json=body("new-auto"))).status_code == 400


async def test_concurrent_auto_identity_keeps_one_first_server_mode_and_reservation(http_client):
    from dataclasses import replace

    from packages.schema.enterprise import WorkspaceQuotaUpdateRequest
    from packages.task_center.factory import get_task_service

    client, settings, journal, store, _ = http_client
    object.__setattr__(settings, "ark_api_key", "dummy-local-policy-value")
    object.__setattr__(settings, "ark_model", "dummy-local-model")
    store.update_workspace_quota(
        "default-workspace", WorkspaceQuotaUpdateRequest(monthly_run_quota=1)
    )
    second_settings = replace(settings, demo_mode=False)
    application = create_app()
    application.dependency_overrides[deps.get_app_settings] = lambda: second_settings
    application.dependency_overrides[deps.get_enterprise_store] = lambda: store
    application.dependency_overrides[deps.get_run_journal] = lambda: journal
    application.dependency_overrides[deps.get_run_service] = lambda: pytest.fail(
        "pure API built Graph"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://other"
    ) as second:
        results = await asyncio.gather(
            *(
                (client if index % 2 else second).post(
                    "/api/task-submissions", json=body("concurrent-auto")
                )
                for index in range(12)
            )
        )
        assert {item.status_code for item in results} == {202}
        assert len({item.json()["id"] for item in results}) == 1
    service = get_task_service(settings, store=store, journal=journal)
    async with service.repository.database.transaction("default-workspace") as conn:
        rows = await (
            await conn.execute("SELECT request_json,execution_backend FROM task_center.submissions")
        ).fetchall()
        count = await (
            await conn.execute("SELECT reserved_count FROM task_center.quota_buckets")
        ).fetchone()
    assert len(rows) == 1 and rows[0]["request_json"]["execution_mode"] in {"demo", "real"}
    assert rows[0]["execution_backend"] == "langgraph" and count["reserved_count"] == 1


async def test_legacy_resolved_row_replays_only_its_known_stored_payload(http_client):
    from packages.task_center.factory import get_task_service

    client, settings, journal, store, _ = http_client
    service = get_task_service(settings, store=store, journal=journal)
    await service.open()
    # This models v2 storage: resolved payload is known, original raw auto/explicit
    # intent is irretrievable. Do not invent it in migration or comparison.
    original = await service.repository.submit(
        RunCreateRequest(**body("legacy-resolved", execution_mode="demo")["request"]),
        actor=EnterpriseUserContext("owner", "owner", "default-workspace"),
        seed=QuotaSeed(1, "block"),
        idempotency_key="legacy-resolved",
    )
    ambiguous = await client.post("/api/task-submissions", json=body("legacy-resolved"))
    assert ambiguous.status_code == 409
    known = await client.post(
        "/api/task-submissions", json=body("legacy-resolved", execution_mode="demo")
    )
    assert known.status_code == 202 and known.json()["id"] == original.id
