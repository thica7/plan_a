import asyncio
import json
from datetime import UTC, datetime

import psycopg
import pytest
from pydantic import ValidationError

from packages.auth.rbac import EnterpriseUserContext
from packages.config.settings import Settings
from packages.identity import compute_run_id_for_idempotency_key
from packages.schema.api_dto import RunCreateRequest
from packages.task_center.database import TaskCenterDatabase
from packages.task_center.errors import (
    DispatchConflict,
    IdempotencyConflict,
    InvalidTaskCenterRequest,
    PolicyConflict,
    QuotaExceeded,
    SubmissionNotFound,
    TaskCenterStorageError,
)
from packages.task_center.models import QuotaSeed, SubmissionCreateRequest, SubmissionView
from packages.task_center.repository import SubmissionRepository

pytest_plugins = ("postgres_support",)
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
ACTOR = EnterpriseUserContext(
    user_id="tester", role="owner", policy_url="https://private-policy.invalid/token"
)
SEED = QuotaSeed(run_limit=10, enforcement="block")


@pytest.fixture
async def task_repository(task_postgres):
    database = TaskCenterDatabase(
        Settings(
            task_center_enabled=True,
            task_center_database_url=task_postgres.app_dsn,
            task_center_pool_min_size=1,
            task_center_pool_max_size=8,
            task_center_pool_max_waiting=128,
            task_center_pool_timeout_seconds=5,
        )
    )
    await database.open()
    yield SubmissionRepository(database, clock=lambda: NOW)
    await database.close()


def request(key="first", *, ws="default-workspace", **changes):
    return RunCreateRequest(
        topic="private research topic",
        dimensions=["product"],
        workspace_id=ws,
        idempotency_key=key,
        **changes,
    )


async def submit(repo, key="first", *, seed=SEED, ws="default-workspace", **changes):
    return await repo.submit(request(key, ws=ws, **changes), actor=ACTOR, seed=seed)


async def counts(repo, ws="default-workspace"):
    async with repo.database.transaction(ws) as conn:
        result = {}
        for table in (
            "workspace_policies",
            "quota_buckets",
            "submissions",
            "quota_entries",
            "outbox",
            "audit_events",
            "dispatch_attempts",
        ):
            row = await (
                await conn.execute(f"SELECT count(*) AS n FROM task_center.{table}")
            ).fetchone()
            result[table] = row["n"]
        return result


async def assert_ledger(repo, ws="default-workspace"):
    async with repo.database.transaction(ws) as conn:
        rows = await (
            await conn.execute(
                "SELECT b.reserved_count,COALESCE(sum(CASE e.action "
                "WHEN 'reserve' THEN 1 WHEN 'release' THEN -1 ELSE "
                "0 END),0) AS ledger "
                "FROM task_center.quota_buckets b LEFT JOIN task_center.quota_entries e "
                "USING(workspace_id,period_start) GROUP BY b.workspace_id,b.period_start"
            )
        ).fetchall()
        assert all(row["reserved_count"] == row["ledger"] for row in rows)


async def test_submission_atomically_reserves_and_creates_outbox(task_repository):
    repo = task_repository
    view = await submit(repo, seed=QuotaSeed(run_limit=1, enforcement="block"))
    assert isinstance(view, SubmissionView)
    assert view.status == "pending" and view.period_start == datetime(2026, 10, 1, tzinfo=UTC)
    assert set(view.model_dump()) == {
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
    async with repo.database.transaction("default-workspace") as conn:
        row = await (await conn.execute("SELECT * FROM task_center.submissions")).fetchone()
        assert row["expected_run_id"] == compute_run_id_for_idempotency_key(
            f"task-submission:{view.id}"
        )
        assert row["request_json"]["execution_mode"] == "auto"
        assert "idempotency_key" not in row["request_json"]
        assert json.loads(row["server_actor"]) == {
            "user_id": "tester",
            "role": "owner",
            "workspace_id": None,
        }
    tally = await counts(repo)
    assert (tally["submissions"], tally["quota_entries"], tally["outbox"]) == (1, 1, 1)
    await assert_ledger(repo)


async def test_one_remaining_quota_allows_exactly_one_of_100_distinct_requests(task_repository):
    repo = task_repository
    results = await asyncio.gather(
        *(
            submit(repo, f"key-{n}", seed=QuotaSeed(run_limit=1, enforcement="block"))
            for n in range(100)
        ),
        return_exceptions=True,
    )
    tally = await counts(repo)
    evidence = {
        "requests": 100,
        "success": sum(isinstance(item, SubmissionView) for item in results),
        "quota_exceeded": sum(isinstance(item, QuotaExceeded) for item in results),
        "unexpected_errors": [
            type(item).__name__
            for item in results
            if isinstance(item, BaseException) and not isinstance(item, QuotaExceeded)
        ],
        "rows": tally,
    }
    print("TASK_CENTER_RACE " + json.dumps(evidence))
    assert evidence["success"] == 1 and evidence["quota_exceeded"] == 99
    assert not evidence["unexpected_errors"]
    assert (tally["submissions"], tally["quota_entries"], tally["outbox"]) == (1, 1, 1)
    await assert_ledger(repo)


async def test_100_identical_requests_share_one_reservation_and_identity(task_repository):
    repo = task_repository
    results = await asyncio.gather(
        *(submit(repo, seed=QuotaSeed(run_limit=1, enforcement="block")) for _ in range(100))
    )
    tally = await counts(repo)
    evidence = {"requests": 100, "unique_ids": len({item.id for item in results}), "rows": tally}
    print("TASK_CENTER_RACE " + json.dumps(evidence))
    assert evidence["unique_ids"] == 1
    assert (tally["submissions"], tally["quota_entries"], tally["outbox"]) == (1, 1, 1)
    await assert_ledger(repo)


async def test_canonical_defaults_replay_before_zero_quota_and_payload_conflict(task_repository):
    repo = task_repository
    seed = QuotaSeed(run_limit=1, enforcement="block")
    first = await submit(repo, seed=seed)
    replay = await repo.submit(
        request(execution_mode="auto", competitors=[]), actor=ACTOR, seed=seed
    )
    assert first.id == replay.id
    with pytest.raises(IdempotencyConflict) as caught:
        await submit(repo, seed=seed, project_id="another-project")
    assert caught.value.status_code == 409
    assert "private research" not in str(caught.value)
    assert (await repo.quota_snapshot("default-workspace")).available == 0
    await assert_ledger(repo)


async def test_explicit_key_wins_and_missing_key_is_typed(task_repository):
    repo = task_repository
    one = await repo.submit(request("ignored"), actor=ACTOR, seed=SEED, idempotency_key="explicit")
    two = await repo.submit(request("other"), actor=ACTOR, seed=SEED, idempotency_key="explicit")
    assert one.id == two.id
    for key in (None, "", "x" * 201):
        with pytest.raises(InvalidTaskCenterRequest):
            await repo.submit(request(None), actor=ACTOR, seed=SEED, idempotency_key=key)
    with pytest.raises(InvalidTaskCenterRequest):
        await repo.submit(
            request(), actor=EnterpriseUserContext("u", "owner", "elsewhere"), seed=SEED
        )
    with pytest.raises(ValidationError):
        SubmissionCreateRequest(request=request(), idempotency_key="x", skip_quota=True)
    with pytest.raises(ValidationError):
        SubmissionCreateRequest(request=request(), idempotency_key="")


@pytest.mark.parametrize(
    "stage", ("quota_buckets", "submissions", "quota_entries", "outbox", "audit_events")
)
async def test_failure_at_each_sql_write_rolls_back_every_business_row(
    task_repository, task_postgres, stage
):
    repo = task_repository
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION task_center.inject_failure() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private payload in database "
            "exception' USING ERRCODE='P0001'; END $$"
        )
        conn.execute(
            f"CREATE TRIGGER injected BEFORE INSERT ON task_center.{stage} "
            "FOR EACH ROW "
            + ("WHEN (NEW.event_type='submission_created') " if stage == "audit_events" else "")
            + "EXECUTE FUNCTION task_center.inject_failure()"
        )
    try:
        with pytest.raises(TaskCenterStorageError) as caught:
            await submit(repo)
        assert caught.value.sqlstate == "P0001"
        assert "private payload" not in str(caught.value)
        assert all(value == 0 for value in (await counts(repo)).values())
    finally:
        with psycopg.connect(task_postgres.owner_dsn) as conn:
            conn.execute(f"DROP TRIGGER injected ON task_center.{stage}")


async def test_failed_reserve_update_rolls_back_existing_bucket(task_repository, task_postgres):
    repo = task_repository
    await repo.quota_snapshot("default-workspace", seed=SEED)
    before = await counts(repo)
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION task_center.inject_failure() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'quota increment failed'; END $$"
        )
        conn.execute(
            "CREATE TRIGGER injected BEFORE UPDATE ON task_center.quota_buckets FOR EACH "
            "ROW EXECUTE FUNCTION task_center.inject_failure()"
        )
    try:
        with pytest.raises(TaskCenterStorageError):
            await submit(repo)
        assert await counts(repo) == before
        assert (await repo.quota_snapshot("default-workspace")).reserved_count == 0
    finally:
        with psycopg.connect(task_postgres.owner_dsn) as conn:
            conn.execute("DROP TRIGGER injected ON task_center.quota_buckets")


async def test_history_import_is_once_scoped_deduplicated_and_excludes_owned_runs(task_repository):
    repo = task_repository
    own = await submit(repo)
    history = [
        {
            "id": "older",
            "workspace_id": "new-workspace",
            "created_at": datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
        },
        {"id": "other-ws", "workspace_id": "another", "created_at": NOW},
        {"id": "legacy", "workspace_id": "new-workspace", "created_at": NOW.replace(tzinfo=None)},
        {"id": "legacy", "workspace_id": "new-workspace", "created_at": NOW},
        {
            "id": "future",
            "workspace_id": "new-workspace",
            "created_at": datetime(2026, 11, 1, tzinfo=UTC),
        },
    ]
    seed = QuotaSeed(run_limit=10, enforcement="block", legacy_runs=history)
    snap = await repo.quota_snapshot("new-workspace", seed=seed)
    assert snap.imported_count == 1
    snap2 = await repo.quota_snapshot("new-workspace", seed=seed)
    assert snap2 == snap
    # A new month can see an existing owned run in the legacy journal; it must not count twice.
    november = SubmissionRepository(repo.database, clock=lambda: datetime(2026, 11, 2, tzinfo=UTC))
    owned_seed = QuotaSeed(
        run_limit=10,
        enforcement="block",
        legacy_runs=[
            {
                "id": own.expected_run_id,
                "workspace_id": "default-workspace",
                "created_at": datetime(2026, 11, 1, tzinfo=UTC),
            },
        ],
    )
    assert (await november.quota_snapshot("default-workspace", seed=owned_seed)).imported_count == 0
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    async with repo.database.transaction("new-workspace") as conn:
        rows = await (
            await conn.execute(
                "SELECT detail_json FROM task_center.audit_events WHERE event_type='quota_imported'"
            )
        ).fetchall()
        assert len(rows) == 1 and rows[0]["detail_json"]["imported_count"] == 1


async def test_utc_month_is_independent_of_session_timezone(task_repository):
    repo = SubmissionRepository(
        task_repository.database, clock=lambda: datetime(2026, 11, 1, tzinfo=UTC)
    )
    assert (await repo.quota_snapshot("default-workspace", seed=SEED)).period_start == datetime(
        2026, 11, 1, tzinfo=UTC
    )
    async with repo.database.transaction("default-workspace") as conn:
        await conn.execute("SET LOCAL TIME ZONE 'America/Los_Angeles'")
        row = await (
            await conn.execute(
                "SELECT period_start AT TIME ZONE 'UTC' AS period FROM task_center.quota_buckets"
            )
        ).fetchone()
        assert row["period"] == datetime(2026, 11, 1)


async def test_zero_limit_block_and_monitor_and_versioned_policy(task_repository):
    repo = task_repository
    zero = QuotaSeed(run_limit=0, enforcement="block")
    with pytest.raises(QuotaExceeded) as caught:
        await submit(repo, seed=zero)
    assert caught.value.status_code == 429
    snap = await repo.quota_snapshot("default-workspace", seed=zero)
    assert snap.limit == 0 and snap.available == 0
    monitor = QuotaSeed(run_limit=0, enforcement="monitor", policy_version=2)
    await submit(repo, seed=monitor)
    await submit(repo, "second", seed=zero)  # older policy cannot replace monitor.
    snap = await repo.quota_snapshot("default-workspace")
    assert snap.reserved_count == 2 and snap.limit == 0 and snap.enforcement == "monitor"
    with pytest.raises(PolicyConflict):
        await submit(
            repo, "third", seed=QuotaSeed(run_limit=5, enforcement="block", policy_version=2)
        )
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 2
    await assert_ledger(repo)


async def test_cancel_is_idempotent_and_releases_original_month(task_repository):
    repo = task_repository
    view = await submit(repo)
    november = SubmissionRepository(repo.database, clock=lambda: datetime(2026, 11, 2, tzinfo=UTC))
    assert (await november.cancel("default-workspace", view.id, actor=ACTOR)).status == "cancelled"
    assert (await november.cancel("default-workspace", view.id, actor=ACTOR)).status == "cancelled"
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 0
    assert (await counts(repo))["quota_entries"] == 2
    await assert_ledger(repo)


async def test_cancel_and_claim_race_has_exactly_one_winner(task_repository):
    repo = task_repository
    tally = {"cancelled": 0, "claimed": 0}
    for n in range(12):
        view = await submit(repo, f"race-{n}", seed=QuotaSeed(run_limit=100, enforcement="block"))
        cancelled, claimed = await asyncio.gather(
            repo.cancel("default-workspace", view.id, actor=ACTOR),
            repo.claim(submission_id=view.id),
            return_exceptions=True,
        )
        if isinstance(cancelled, SubmissionView):
            assert cancelled.status == "cancelled"
            assert isinstance(claimed, DispatchConflict)
            tally["cancelled"] += 1
        else:
            assert isinstance(cancelled, DispatchConflict)
            assert claimed.submission_id == view.id
            tally["claimed"] += 1
    assert sum(tally.values()) == 12
    await assert_ledger(repo)


async def test_retry_keeps_identity_reservation_attempts_and_never_refunds_sent_intent(
    task_repository, task_postgres
):
    repo = task_repository
    view = await submit(repo)
    claim = await repo.claim(submission_id=view.id)
    assert claim.generation == 1 and claim.epoch == 1
    assert claim.request.idempotency_key == f"task-submission:{view.id}"
    assert claim.actor == EnterpriseUserContext("tester", "owner", None)
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "UPDATE task_center.submissions SET status='dispatch_failed' WHERE id=%s", (view.id,)
        )
        conn.execute(
            (
                "UPDATE task_center.outbox SET "
                "state='failed',owner_token=NULL,lease_until=NULL,sent_intent_at=%s WHERE "
                "submission_id=%s"
            ),
            (NOW, view.id),
        )
        conn.execute(
            (
                "UPDATE task_center.dispatch_attempts SET outcome='unknown',sent_intent_at=%s "
                "WHERE submission_id=%s"
            ),
            (NOW, view.id),
        )
    retried = await repo.retry_dispatch("default-workspace", view.id, actor=ACTOR)
    assert (
        retried.id == view.id
        and retried.expected_run_id == view.expected_run_id
        and retried.status == "pending"
    )
    with pytest.raises(DispatchConflict):
        await repo.cancel("default-workspace", view.id, actor=ACTOR)
    second = await repo.claim(submission_id=view.id)
    assert second.generation == 2 and second.epoch == 2 and second.owner_token != claim.owner_token
    assert (await counts(repo))["dispatch_attempts"] == 2
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    with pytest.raises(DispatchConflict):
        await repo.retry_dispatch("default-workspace", view.id, actor=ACTOR)
    await assert_ledger(repo)


async def test_claim_is_exclusive_and_public_projection_remains_safe(task_repository):
    repo = task_repository
    view = await submit(repo)
    results = await asyncio.gather(
        *(repo.claim(submission_id=view.id) for _ in range(10)), return_exceptions=True
    )
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert sum(isinstance(item, DispatchConflict) for item in results) == 9
    public = await repo.get("default-workspace", view.id)
    assert public.status == "dispatching" and public.dispatch_attempt_count == 1
    assert "private research" not in public.model_dump_json()
    with pytest.raises(DispatchConflict):
        await repo.cancel("default-workspace", view.id, actor=ACTOR)
    assert await repo.claim() is None


async def test_get_list_cursor_and_ledger_are_workspace_scoped_and_stable(task_repository):
    repo = task_repository
    views = [await submit(repo, f"page-{n}") for n in range(5)]
    other = await submit(repo, ws="other")
    with pytest.raises(SubmissionNotFound):
        await repo.get("default-workspace", other.id)
    with pytest.raises(SubmissionNotFound):
        await repo.cancel("other", views[0].id, actor=ACTOR)
    expected = sorted((item.id for item in views), reverse=True)
    seen, cursor = [], None
    while True:
        page = await repo.list("default-workspace", limit=2, cursor=cursor)
        seen.extend(item.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == expected
    page = await repo.list("default-workspace", limit=2)
    for ws, status, cursor in (
        ("other", None, page.next_cursor),
        ("default-workspace", "cancelled", page.next_cursor),
        ("default-workspace", None, "bad!"),
    ):
        with pytest.raises(InvalidTaskCenterRequest):
            await repo.list(ws, status=status, cursor=cursor)
    for limit in (0, 101, True):
        with pytest.raises(InvalidTaskCenterRequest):
            await repo.list("default-workspace", limit=limit)
    ledger = await repo.quota_ledger("default-workspace", limit=2)
    assert len(ledger.items) == 2 and ledger.snapshot.reserved_count == 5
    assert ledger.next_cursor is not None
    with pytest.raises(InvalidTaskCenterRequest):
        await repo.quota_ledger("other", cursor=ledger.next_cursor)
    with pytest.raises(InvalidTaskCenterRequest):
        await repo.quota_ledger(
            "default-workspace",
            period_start=datetime(2026, 9, 1, tzinfo=UTC),
            cursor=ledger.next_cursor,
        )
    with pytest.raises(SubmissionNotFound):
        await repo.quota_snapshot("missing")


async def test_rls_pool_reuse_and_database_constraints(task_repository, task_postgres):
    repo = task_repository
    view = await submit(repo)
    await submit(repo, ws="other")
    async with repo.database.transaction("default-workspace") as conn:
        assert (
            await (
                await conn.execute("SELECT count(*) AS n FROM task_center.submissions")
            ).fetchone()
        )["n"] == 1
    async with repo.database.transaction("other") as conn:
        rows = await (
            await conn.execute("SELECT workspace_id FROM task_center.submissions")
        ).fetchall()
        assert rows == [{"workspace_id": "other"}]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with conn.transaction():
                await conn.execute("UPDATE task_center.submissions SET workspace_id='elsewhere'")
    async with repo.database.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT current_setting('app.current_workspace_id',true) AS "
                "ws,current_setting('app.service_role',true) AS service"
            )
        ).fetchone()
        assert row["ws"] in (None, "") and row["service"] in (None, "")
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        for sql, parameters in (
            ("UPDATE task_center.quota_buckets SET reserved_count=-1", ()),
            (
                (
                    "INSERT INTO "
                    "task_center.quota_entries(workspace_id,submission_id,period_start,action) "
                    "VALUES('other',%s,%s,'release')"
                ),
                (view.id, view.period_start),
            ),
        ):
            with pytest.raises(
                psycopg.errors.CheckViolation
                if not parameters
                else psycopg.errors.ForeignKeyViolation
            ):
                with conn.transaction():
                    conn.execute(sql, parameters)


async def test_public_periods_and_views_are_normalized_to_utc(task_repository):
    repo = task_repository
    view = await submit(repo)
    snapshot = await repo.quota_snapshot("default-workspace")
    ledger = await repo.quota_ledger("default-workspace")
    assert snapshot.period_start.tzinfo is UTC
    assert snapshot.period_end.tzinfo is UTC
    assert view.created_at.tzinfo is UTC
    assert view.period_start.tzinfo is UTC
    assert ledger.items[0].period_start.tzinfo is UTC


async def test_same_connection_reuse_clears_scope_between_workspaces(task_database):
    repo = SubmissionRepository(task_database, clock=lambda: NOW)
    await submit(repo)
    await submit(repo, ws="other")
    pids = []
    for ws in ("default-workspace", "other"):
        async with task_database.transaction(ws) as conn:
            row = await (
                await conn.execute(
                    "SELECT pg_backend_pid() AS pid,"
                    "current_setting('app.current_workspace_id') AS ws"
                )
            ).fetchone()
            pids.append(row["pid"])
            assert row["ws"] == ws
            rows = await (
                await conn.execute("SELECT workspace_id FROM task_center.submissions")
            ).fetchall()
            assert rows == [{"workspace_id": ws}]
    assert len(set(pids)) == 1
    async with task_database.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT current_setting('app.current_workspace_id',true) AS ws,"
                "current_setting('app.service_role',true) AS service"
            )
        ).fetchone()
        assert row["ws"] in (None, "") and row["service"] in (None, "")


async def test_cancel_audit_failure_rolls_back_release_and_all_statuses(
    task_repository, task_postgres
):
    repo = task_repository
    view = await submit(repo)
    before = await counts(repo)
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION task_center.inject_failure() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'cancel audit failed'; END $$"
        )
        conn.execute(
            "CREATE TRIGGER injected BEFORE INSERT ON task_center.audit_events "
            "FOR EACH ROW WHEN (NEW.event_type='submission_cancelled') "
            "EXECUTE FUNCTION task_center.inject_failure()"
        )
    try:
        with pytest.raises(TaskCenterStorageError):
            await repo.cancel("default-workspace", view.id, actor=ACTOR)
        assert (await repo.get("default-workspace", view.id)).status == "pending"
        assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
        assert await counts(repo) == before
        await assert_ledger(repo)
    finally:
        with psycopg.connect(task_postgres.owner_dsn) as conn:
            conn.execute("DROP TRIGGER injected ON task_center.audit_events")


async def test_dispatched_submission_cannot_release_quota(task_repository, task_postgres):
    repo = task_repository
    view = await submit(repo)
    with psycopg.connect(task_postgres.owner_dsn) as conn:
        conn.execute(
            "UPDATE task_center.submissions SET status='dispatched',"
            "run_id=expected_run_id WHERE id=%s",
            (view.id,),
        )
        conn.execute(
            "UPDATE task_center.outbox SET state='dispatched' WHERE submission_id=%s", (view.id,)
        )
    with pytest.raises(DispatchConflict):
        await repo.cancel("default-workspace", view.id, actor=ACTOR)
    assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
    assert (await counts(repo))["quota_entries"] == 1


async def test_missing_snapshot_without_seed_is_read_only(task_repository):
    repo = task_repository
    before = await counts(repo)
    with pytest.raises(SubmissionNotFound):
        await repo.quota_snapshot("default-workspace")
    assert await counts(repo) == before
    snapshot = await repo.quota_snapshot(
        "default-workspace", seed=QuotaSeed(run_limit=0, enforcement="block")
    )
    assert snapshot.limit == 0 and snapshot.reserved_count == 0 and snapshot.available == 0
    await assert_ledger(repo)


async def test_monitor_overage_is_recorded_in_submission_audit(task_repository):
    repo = task_repository
    view = await submit(repo, seed=QuotaSeed(run_limit=0, enforcement="monitor"))
    async with repo.database.transaction("default-workspace") as conn:
        row = await (
            await conn.execute(
                "SELECT detail_json FROM task_center.audit_events "
                "WHERE submission_id=%s AND event_type='submission_created'",
                (view.id,),
            )
        ).fetchone()
    assert row["detail_json"].get("quota_over_limit") is True
    assert row["detail_json"].get("enforcement") == "monitor"


async def test_cancel_release_and_new_submit_do_not_deadlock_on_policy_fk(
    task_repository, task_postgres
):
    repo = task_repository
    seed = QuotaSeed(run_limit=2, enforcement="block")
    view = await submit(repo, seed=seed)
    gate = 412987
    with psycopg.connect(task_postgres.owner_dsn, autocommit=True) as control:
        control.execute(
            "CREATE OR REPLACE FUNCTION task_center.pause_release() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(412987); "
            "RETURN NEW; END $$"
        )
        control.execute(
            "CREATE TRIGGER pause_release BEFORE INSERT ON task_center.quota_entries "
            "FOR EACH ROW WHEN (NEW.action='release') "
            "EXECUTE FUNCTION task_center.pause_release()"
        )
        control.execute("SELECT pg_advisory_lock(%s)", (gate,))
        cancelled = asyncio.create_task(repo.cancel("default-workspace", view.id, actor=ACTOR))
        submitted = None
        try:
            # The release holds its bucket before its FK check. Pause at this precise boundary.
            for _ in range(200):
                if (
                    control.execute(
                        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                        "AND objid=%s AND NOT granted",
                        (gate,),
                    ).fetchone()[0]
                    == 1
                ):
                    break
                await asyncio.sleep(0.005)
            else:
                pytest.fail("release did not reach the PostgreSQL trigger gate")
            submitted = asyncio.create_task(submit(repo, "during-cancel", seed=seed))
            for _ in range(200):
                if (
                    control.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                        "AND query LIKE 'UPDATE task_center.quota_buckets%%'"
                    ).fetchone()[0]
                    == 1
                ):
                    break
                if submitted.done():
                    break
                await asyncio.sleep(0.005)
            else:
                pytest.fail("new submit neither completed nor waited for the original bucket")
            blockers = control.execute(
                "SELECT pid,wait_event,pg_blocking_pids(pid) FROM pg_stat_activity "
                "WHERE application_name='task-center' AND wait_event_type='Lock' ORDER BY pid"
            ).fetchall()
            control.execute("SELECT pg_advisory_unlock(%s)", (gate,))
            outcomes = await asyncio.gather(cancelled, submitted, return_exceptions=True)
            assert all(isinstance(outcome, SubmissionView) for outcome in outcomes), [
                getattr(outcome, "sqlstate", type(outcome).__name__) for outcome in outcomes
            ]
            assert outcomes[0].status == "cancelled" and outcomes[1].status == "pending"
            assert (await repo.quota_snapshot("default-workspace")).reserved_count == 1
            await assert_ledger(repo)
            async with repo.database.transaction("default-workspace") as conn:
                actions = await (
                    await conn.execute(
                        "SELECT action,count(*) AS n FROM task_center.quota_entries "
                        "GROUP BY action ORDER BY action"
                    )
                ).fetchall()
            assert actions == [{"action": "release", "n": 1}, {"action": "reserve", "n": 2}]
            rows = await counts(repo)
            assert rows["submissions"] == rows["outbox"] == 2
            evidence = {
                "quota_limit": 2,
                "outcomes": [outcome.status for outcome in outcomes],
                "reserved_count": 1,
                "ledger_actions": actions,
                "rows": rows,
                "blocked_before_gate_release": [
                    {"pid": pid, "wait_event": event, "blocker_pids": pids}
                    for pid, event, pids in blockers
                ],
            }
            print("TASK_CENTER_RACE " + json.dumps(evidence))
        finally:
            control.execute("SELECT pg_advisory_unlock(%s)", (gate,))
            await asyncio.gather(
                *(task for task in (cancelled, submitted) if task is not None),
                return_exceptions=True,
            )
            control.execute("DROP TRIGGER pause_release ON task_center.quota_entries")
