"""Short PostgreSQL transactions for submissions, quota, and basic relay claims."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from packages.auth.rbac import EnterpriseUserContext
from packages.identity import compute_run_id_for_idempotency_key
from packages.schema.api_dto import RunCreateRequest

from .canonical import canonical_request
from .database import TaskCenterDatabase
from .dispatch import DispatchReceipt
from .errors import (
    DispatchConflict,
    IdempotencyConflict,
    InvalidTaskCenterRequest,
    PolicyConflict,
    QuotaExceeded,
    SubmissionNotFound,
)
from .models import (
    DispatchClaim,
    QuotaLedgerEntry,
    QuotaLedgerPage,
    QuotaSeed,
    QuotaSnapshot,
    SubmissionPage,
    SubmissionStatus,
    SubmissionView,
)

_STATUSES = {"pending", "dispatching", "dispatched", "cancelled", "dispatch_failed"}
_VIEW_SELECT = (
    "SELECT s.*,o.attempt_count AS dispatch_attempt_count FROM "
    "task_center.submissions s JOIN task_center.outbox o ON o.submission_id=s.id"
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _period(now: datetime) -> tuple[datetime, datetime]:
    start = _utc(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise InvalidTaskCenterRequest("invalid submission identifier") from None


def _view(row: Mapping[str, Any]) -> SubmissionView:
    values = {
        name: _utc(row[name]) if isinstance(row[name], datetime) else row[name]
        for name in SubmissionView.model_fields if name in row
    }
    values["id"] = str(values["id"])
    return SubmissionView.model_validate(values)


def _actor_json(actor: EnterpriseUserContext) -> str:
    return json.dumps(
        {"user_id": actor.user_id, "role": actor.role, "workspace_id": actor.workspace_id},
        separators=(",", ":"),
    )


def _check_actor(actor: EnterpriseUserContext, workspace_id: str) -> None:
    if actor.workspace_id is not None and actor.workspace_id != workspace_id:
        raise InvalidTaskCenterRequest("actor workspace does not match")


def _page_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidTaskCenterRequest("page limit must be between 1 and 100")


def _encode_cursor(scope: dict, row: Mapping[str, Any]) -> str:
    value = {"scope": scope, "created_at": row["created_at"].isoformat(), "id": str(row["id"])}
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode_cursor(cursor: str | None, scope: dict) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 2048:
            raise ValueError
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(data, dict)
            or set(data) != {"scope", "created_at", "id"}
            or data["scope"] != scope
        ):
            raise ValueError
        stamp = datetime.fromisoformat(data["created_at"])
        if stamp.tzinfo is None:
            raise ValueError
        return _utc(stamp), str(UUID(data["id"]))
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        raise InvalidTaskCenterRequest("invalid or mismatched page cursor") from None


class SubmissionRepository:
    def __init__(
        self, database: TaskCenterDatabase, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.database = database
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _audit(
        self, conn, workspace_id, event, actor, now, *, submission_id=None, detail=None
    ):
        await conn.execute(
            (
                "INSERT INTO "
                "task_center.audit_events(workspace_id,submission_id,event_type,actor"
                ",detail_json,created_at)"
                " VALUES(%s,%s,%s,%s,%s,%s)"
            ),
            (workspace_id, submission_id, event, actor, Jsonb(detail or {}), now),
        )

    async def _policy(self, conn, workspace_id: str, seed: QuotaSeed, now: datetime) -> dict:
        await conn.execute(
            (
                "INSERT INTO "
                "task_center.workspace_policies(workspace_id,run_limit,enforcement,po"
                "licy_version,updated_at)"
                " VALUES(%s,%s,%s,%s,%s) ON CONFLICT(workspace_id) DO NOTHING"
            ),
            (workspace_id, seed.run_limit, seed.enforcement, seed.policy_version, now),
        )
        # Keep policy writes serialized while allowing FK KEY SHARE checks in
        # cancel/claim, which acquire submission and bucket locks first.
        row = await (
            await conn.execute(
                "SELECT * FROM task_center.workspace_policies "
                "WHERE workspace_id=%s FOR NO KEY UPDATE",
                (workspace_id,),
            )
        ).fetchone()
        if seed.policy_version == row["policy_version"] and (seed.run_limit, seed.enforcement) != (
            row["run_limit"],
            row["enforcement"],
        ):
            raise PolicyConflict("quota policy version has conflicting values")
        if seed.policy_version > row["policy_version"]:
            row = await (
                await conn.execute(
                    (
                        "UPDATE task_center.workspace_policies SET "
                        "run_limit=%s,enforcement=%s,policy_version=%s,updated_at=%s WHERE "
                        "workspace_id=%s RETURNING *"
                    ),
                    (seed.run_limit, seed.enforcement, seed.policy_version, now, workspace_id),
                )
            ).fetchone()
        return row

    async def _bucket(
        self,
        conn,
        workspace_id: str,
        seed: QuotaSeed,
        now: datetime,
        start: datetime,
        end: datetime,
    ) -> None:
        existing = await (
            await conn.execute(
                "SELECT 1 FROM task_center.quota_buckets WHERE workspace_id=%s AND period_start=%s",
                (workspace_id, start),
            )
        ).fetchone()
        if existing is not None:
            return
        owned = {
            row["expected_run_id"]
            for row in await (
                await conn.execute(
                    "SELECT expected_run_id FROM task_center.submissions WHERE workspace_id=%s",
                    (workspace_id,),
                )
            ).fetchall()
        }
        imported = set()
        for run in seed.legacy_runs:
            value = run if isinstance(run, Mapping) else vars(run)
            if (
                value.get("workspace_id") != workspace_id
                or not value.get("id")
                or value["id"] in owned
            ):
                continue
            stamp = value.get("created_at")
            if isinstance(stamp, str):
                stamp = datetime.fromisoformat(stamp)
            if isinstance(stamp, datetime) and start <= _utc(stamp) < end:
                imported.add(value["id"])
        await conn.execute(
            (
                "INSERT INTO "
                "task_center.quota_buckets(workspace_id,period_start,period_end,impor"
                "ted_count,created_at)"
                " VALUES(%s,%s,%s,%s,%s)"
            ),
            (workspace_id, start, end, len(imported), now),
        )
        await self._audit(
            conn,
            workspace_id,
            "quota_imported",
            "task-center",
            now,
            detail={"period_start": start.isoformat(), "imported_count": len(imported)},
        )

    async def submit(
        self,
        request: RunCreateRequest,
        *,
        actor: EnterpriseUserContext,
        seed: QuotaSeed,
        idempotency_key: str | None = None,
        delivery_intent: str = "runtime",
        execution_backend: str = "langgraph",
        resolve_execution: Callable[[], tuple[str, str]] | None = None,
    ) -> SubmissionView:
        if delivery_intent not in {
            "create_only",
            "runtime",
            "temporal",
            "activity",
        } or execution_backend not in {"langgraph", "temporal"}:
            raise InvalidTaskCenterRequest("invalid delivery route")
        workspace_id = request.workspace_id
        _check_actor(actor, workspace_id)
        key = idempotency_key if idempotency_key is not None else request.idempotency_key
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise InvalidTaskCenterRequest(
                "submission requires an idempotency key of 1 to 200 characters"
            )
        payload, digest = canonical_request(request)
        now = _utc(self._clock())
        start, end = _period(now)
        async with self.database.transaction(workspace_id) as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,42))",
                (json.dumps([workspace_id, key]),),
            )
            existing = await (
                await conn.execute(
                    _VIEW_SELECT + " WHERE s.workspace_id=%s AND s.idempotency_key=%s",
                    (workspace_id, key),
                )
            ).fetchone()
            if existing is not None:
                if (
                    (existing["client_request_sha"] or existing["request_sha"]) != digest
                    or existing["delivery_intent"] != delivery_intent
                ):
                    raise IdempotencyConflict("idempotency key is already used by another request")
                return _view(existing)
            client_digest = None
            if resolve_execution is not None:
                # The key lock makes governance and server choices first-insert-only.
                # request_sha continues to bind the full actual dispatch payload.
                mode, execution_backend = resolve_execution()
                if (mode not in {"demo", "real"}
                        or execution_backend not in {"langgraph", "temporal"}):
                    raise InvalidTaskCenterRequest("invalid resolved execution route")
                client_digest = digest
                request = request.model_copy(update={"execution_mode": mode})
                payload, digest = canonical_request(request)
            policy = await self._policy(conn, workspace_id, seed, now)
            await self._bucket(conn, workspace_id, seed, now, start, end)
            reserved = await (
                await conn.execute(
                    (
                        "UPDATE task_center.quota_buckets "
                        "SET reserved_count=reserved_count+1 WHERE "
                        "workspace_id=%s AND period_start=%s AND (%s='monitor' OR "
                        "imported_count+reserved_count<%s) RETURNING imported_count,reserved_count"
                    ),
                    (workspace_id, start, policy["enforcement"], policy["run_limit"]),
                )
            ).fetchone()
            if reserved is None:
                raise QuotaExceeded("workspace monthly task quota is exhausted")
            submission_id = str(uuid4())
            expected_run_id = compute_run_id_for_idempotency_key(f"task-submission:{submission_id}")
            await conn.execute(
                (
                    "INSERT INTO "
                    "task_center.submissions(id,workspace_id,project_id,idempotency_key,r"
                    "equest_sha,request_json,server_actor,period_start,period_end,expecte"
                    "d_run_id,created_at,updated_at,delivery_intent,execution_backend,client_request_sha)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                ),
                (
                    submission_id,
                    workspace_id,
                    request.project_id,
                    key,
                    digest,
                    Jsonb(payload),
                    _actor_json(actor),
                    start,
                    end,
                    expected_run_id,
                    now,
                    now,
                    delivery_intent,
                    execution_backend,
                    client_digest,
                ),
            )
            await conn.execute(
                (
                    "INSERT INTO "
                    "task_center.quota_entries(workspace_id,submission_id,period_start,ac"
                    "tion,created_at)"
                    " VALUES(%s,%s,%s,'reserve',%s)"
                ),
                (workspace_id, submission_id, start, now),
            )
            await conn.execute(
                (
                    "INSERT INTO "
                    "task_center.outbox(workspace_id,submission_id,available_at,created_a"
                    "t,updated_at)"
                    " VALUES(%s,%s,%s,%s,%s)"
                ),
                (workspace_id, submission_id, now, now, now),
            )
            await self._audit(
                conn,
                workspace_id,
                "submission_created",
                actor.user_id,
                now,
                submission_id=submission_id,
                detail={
                    "enforcement": policy["enforcement"],
                    "quota_over_limit": (
                        reserved["imported_count"] + reserved["reserved_count"]
                        > policy["run_limit"]
                    ),
                },
            )
            return await self._get(conn, workspace_id, submission_id)

    async def _get(self, conn, workspace_id: str, submission_id: str) -> SubmissionView:
        row = await (
            await conn.execute(
                _VIEW_SELECT + " WHERE s.workspace_id=%s AND s.id=%s", (workspace_id, submission_id)
            )
        ).fetchone()
        if row is None:
            raise SubmissionNotFound("submission was not found")
        return _view(row)

    async def get(self, workspace_id: str, submission_id: str) -> SubmissionView:
        submission_id = _uuid(submission_id)
        async with self.database.transaction(workspace_id) as conn:
            return await self._get(conn, workspace_id, submission_id)

    async def list(
        self,
        workspace_id: str,
        *,
        status: SubmissionStatus | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> SubmissionPage:
        _page_limit(limit)
        if status is not None and status not in _STATUSES:
            raise InvalidTaskCenterRequest("invalid submission status")
        scope = {"kind": "submissions", "workspace_id": workspace_id, "status": status}
        boundary = _decode_cursor(cursor, scope)
        conditions, parameters = ["s.workspace_id=%s"], [workspace_id]
        if status is not None:
            conditions.append("s.status=%s")
            parameters.append(status)
        if boundary is not None:
            conditions.append("(s.created_at,s.id)<(%s,%s)")
            parameters.extend(boundary)
        parameters.append(limit + 1)
        async with self.database.transaction(workspace_id) as conn:
            rows = await (
                await conn.execute(
                    _VIEW_SELECT
                    + " WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY s.created_at DESC,s.id DESC LIMIT %s",
                    parameters,
                )
            ).fetchall()
        return SubmissionPage(
            items=[_view(row) for row in rows[:limit]],
            next_cursor=_encode_cursor(scope, rows[limit - 1]) if len(rows) > limit else None,
        )

    async def _snapshot(self, conn, workspace_id: str, start: datetime) -> QuotaSnapshot:
        row = await (
            await conn.execute(
                (
                    "SELECT b.*,p.run_limit,p.enforcement FROM task_center.quota_buckets b JOIN "
                    "task_center.workspace_policies p USING(workspace_id) WHERE b.workspace_id=%s "
                    "AND b.period_start=%s"
                ),
                (workspace_id, start),
            )
        ).fetchone()
        if row is None:
            raise SubmissionNotFound("quota bucket was not found")
        return QuotaSnapshot(
            workspace_id=workspace_id,
            period_start=_utc(row["period_start"]),
            period_end=_utc(row["period_end"]),
            limit=row["run_limit"],
            enforcement=row["enforcement"],
            imported_count=row["imported_count"],
            reserved_count=row["reserved_count"],
            available=max(0, row["run_limit"] - row["imported_count"] - row["reserved_count"]),
        )

    async def quota_snapshot(
        self, workspace_id: str, *, seed: QuotaSeed | None = None
    ) -> QuotaSnapshot:
        now = _utc(self._clock())
        start, end = _period(now)
        async with self.database.transaction(workspace_id) as conn:
            if seed is not None:
                await self._policy(conn, workspace_id, seed, now)
                await self._bucket(conn, workspace_id, seed, now, start, end)
            return await self._snapshot(conn, workspace_id, start)

    async def quota_ledger(
        self,
        workspace_id: str,
        *,
        period_start: datetime | None = None,
        limit: int = 20,
        cursor: str | None = None,
        seed: QuotaSeed | None = None,
    ) -> QuotaLedgerPage:
        _page_limit(limit)
        now = _utc(self._clock())
        start, end = _period(period_start if period_start is not None else now)
        if period_start is not None and _utc(period_start) != start:
            raise InvalidTaskCenterRequest("quota period must be a UTC month boundary")
        scope = {
            "kind": "quota_ledger",
            "workspace_id": workspace_id,
            "period_start": start.isoformat(),
        }
        boundary = _decode_cursor(cursor, scope)
        parameters: list[Any] = [workspace_id, start]
        condition = "workspace_id=%s AND period_start=%s"
        if boundary is not None:
            condition += " AND (created_at,id)<(%s,%s)"
            parameters.extend(boundary)
        parameters.append(limit + 1)
        async with self.database.transaction(workspace_id) as conn:
            if seed is not None:
                await self._policy(conn, workspace_id, seed, now)
                await self._bucket(conn, workspace_id, seed, now, start, end)
            # A single READ COMMITTED statement gives both projections the same MVCC snapshot.
            result = await (
                await conn.execute(
                    "SELECT b.*,p.run_limit,p.enforcement,e.id AS entry_id,"
                    "e.submission_id,e.action,e.amount,e.created_at FROM "
                    "task_center.quota_buckets b JOIN task_center.workspace_policies p "
                    "USING(workspace_id) LEFT JOIN LATERAL ("
                    "SELECT * FROM task_center.quota_entries WHERE " + condition +
                    " ORDER BY created_at DESC,id DESC LIMIT %s) e ON true "
                    "WHERE b.workspace_id=%s AND b.period_start=%s "
                    "ORDER BY e.created_at DESC,e.id DESC",
                    [*parameters, workspace_id, start],
                )
            ).fetchall()
            if not result:
                raise SubmissionNotFound("quota bucket was not found")
            bucket = result[0]
            snapshot = QuotaSnapshot(
                workspace_id=workspace_id, period_start=_utc(bucket["period_start"]),
                period_end=_utc(bucket["period_end"]), limit=bucket["run_limit"],
                enforcement=bucket["enforcement"], imported_count=bucket["imported_count"],
                reserved_count=bucket["reserved_count"],
                available=max(
                    0, bucket["run_limit"] - bucket["imported_count"] - bucket["reserved_count"]
                ),
            )
            rows = [{**row, "id": row["entry_id"]} for row in result if row["entry_id"] is not None]
        items = [
            QuotaLedgerEntry(
                **{
                    name: str(row[name])
                    if name in ("id", "submission_id")
                    else _utc(row[name])
                    if isinstance(row[name], datetime)
                    else row[name]
                    for name in QuotaLedgerEntry.model_fields
                }
            )
            for row in rows[:limit]
        ]
        return QuotaLedgerPage(
            items=items,
            snapshot=snapshot,
            next_cursor=_encode_cursor(scope, rows[limit - 1]) if len(rows) > limit else None,
        )

    async def _locked_submission(self, conn, workspace_id, submission_id):
        row = await (
            await conn.execute(
                "SELECT * FROM task_center.submissions WHERE workspace_id=%s AND id=%s FOR UPDATE",
                (workspace_id, submission_id),
            )
        ).fetchone()
        if row is None:
            raise SubmissionNotFound("submission was not found")
        return row

    async def cancel(
        self, workspace_id: str, submission_id: str, *, actor: EnterpriseUserContext
    ) -> SubmissionView:
        _check_actor(actor, workspace_id)
        submission_id = _uuid(submission_id)
        now = _utc(self._clock())
        async with self.database.transaction(workspace_id) as conn:
            row = await self._locked_submission(conn, workspace_id, submission_id)
            if row["status"] == "cancelled":
                return await self._get(conn, workspace_id, submission_id)
            outbox = await (
                await conn.execute(
                    "SELECT * FROM task_center.outbox WHERE submission_id=%s FOR UPDATE",
                    (submission_id,),
                )
            ).fetchone()
            history = await (
                await conn.execute(
                    (
                        "SELECT 1 FROM task_center.dispatch_attempts WHERE submission_id=%s AND "
                        "sent_intent_at IS NOT NULL LIMIT 1"
                    ),
                    (submission_id,),
                )
            ).fetchone()
            if (
                row["status"] != "pending"
                or outbox["state"] != "pending"
                or outbox["sent_intent_at"] is not None
                or history is not None
            ):
                raise DispatchConflict("submission can no longer be cancelled")
            await conn.execute(
                (
                    "UPDATE task_center.quota_buckets SET reserved_count=reserved_count-1 WHERE "
                    "workspace_id=%s AND period_start=%s"
                ),
                (workspace_id, row["period_start"]),
            )
            await conn.execute(
                (
                    "INSERT INTO "
                    "task_center.quota_entries(workspace_id,submission_id,period_start,ac"
                    "tion,created_at)"
                    " VALUES(%s,%s,%s,'release',%s)"
                ),
                (workspace_id, submission_id, row["period_start"], now),
            )
            await conn.execute(
                (
                    "UPDATE task_center.outbox SET state='cancelled',updated_at=%s WHERE "
                    "submission_id=%s"
                ),
                (now, submission_id),
            )
            await conn.execute(
                (
                    "UPDATE task_center.submissions SET "
                    "status='cancelled',cancelled_at=%s,updated_at=%s WHERE id=%s"
                ),
                (now, now, submission_id),
            )
            await self._audit(
                conn,
                workspace_id,
                "submission_cancelled",
                actor.user_id,
                now,
                submission_id=submission_id,
            )
            return await self._get(conn, workspace_id, submission_id)

    async def retry_dispatch(
        self, workspace_id: str, submission_id: str, *, actor: EnterpriseUserContext
    ) -> SubmissionView:
        _check_actor(actor, workspace_id)
        submission_id = _uuid(submission_id)
        now = _utc(self._clock())
        async with self.database.transaction(workspace_id) as conn:
            row = await self._locked_submission(conn, workspace_id, submission_id)
            if row["status"] != "dispatch_failed":
                raise DispatchConflict("only failed dispatches can be retried")
            await conn.execute(
                "SELECT 1 FROM task_center.outbox WHERE submission_id=%s FOR UPDATE",
                (submission_id,),
            )
            await conn.execute(
                (
                    "UPDATE task_center.outbox SET "
                    "state='pending',epoch=epoch+1,attempt_count=0,owner_token=NULL,lease_until=NULL,avai"
                    "lable_at=%s,updated_at=%s"
                    " WHERE submission_id=%s"
                ),
                (now, now, submission_id),
            )
            await conn.execute(
                (
                    "UPDATE task_center.submissions SET "
                    "status='pending',last_error_code=NULL,updated_at=%s WHERE id=%s"
                ),
                (now, submission_id),
            )
            await self._audit(
                conn,
                workspace_id,
                "dispatch_retried",
                actor.user_id,
                now,
                submission_id=submission_id,
            )
            return await self._get(conn, workspace_id, submission_id)

    async def _database_now(self, conn) -> datetime:
        return _utc(
            (await (await conn.execute("SELECT clock_timestamp() AS now")).fetchone())["now"]
        )

    async def claim(
        self,
        *,
        submission_id: str | None = None,
        owner: str = "relay",
        lease_seconds: float = 30,
        max_attempts: int = 3,
    ) -> DispatchClaim | None:
        if (
            not isinstance(lease_seconds, (int, float))
            or not math.isfinite(lease_seconds)
            or lease_seconds <= 0
            or type(max_attempts) is not int
            or max_attempts < 1
        ):
            raise InvalidTaskCenterRequest("invalid dispatch claim settings")
        available_now = _utc(self._clock())
        conditions = (
            "((s.status='pending' AND o.state='pending' AND o.available_at<=%s) "
            "OR (s.status='dispatching' AND o.state='leased' "
            "AND o.lease_until<=clock_timestamp()))"
        )
        parameters: list[Any] = [available_now]
        if submission_id is not None:
            submission_id = _uuid(submission_id)
            conditions += " AND s.id=%s"
            parameters.append(submission_id)
        async with self.database.transaction("", service_role=True) as conn:
            row = await (
                await conn.execute(
                    "SELECT s.* FROM task_center.submissions s JOIN task_center.outbox o "
                    "ON o.submission_id=s.id WHERE "
                    + conditions
                    + " ORDER BY o.available_at,s.created_at,s.id LIMIT 1 "
                    "FOR UPDATE OF s SKIP LOCKED",
                    parameters,
                )
            ).fetchone()
            if row is None:
                if submission_id is not None:
                    raise DispatchConflict("submission is unavailable for dispatch")
                return None
            submission_id = str(row["id"])
            outbox = await (
                await conn.execute(
                    "SELECT * FROM task_center.outbox WHERE submission_id=%s FOR UPDATE",
                    (submission_id,),
                )
            ).fetchone()
            now = await self._database_now(conn)
            expired = outbox["state"] == "leased" and outbox["lease_until"] <= now
            # The candidate JOIN is only a hint. Read the outbox under its own lock
            # after obtaining the submission lock, never trust an old JOIN snapshot.
            if not (
                (
                    row["status"] == "pending"
                    and outbox["state"] == "pending"
                    and outbox["available_at"] <= available_now
                )
                or (row["status"] == "dispatching" and expired)
            ):
                if submission_id is not None:
                    raise DispatchConflict("submission is unavailable for dispatch")
                return None
            if expired:
                await conn.execute(
                    "UPDATE task_center.dispatch_attempts SET outcome=CASE "
                    "WHEN sent_intent_at IS NULL THEN 'expired' ELSE 'unknown' END,"
                    "finished_at=%s,error_code='lease_expired' "
                    "WHERE submission_id=%s AND generation=%s",
                    (now, submission_id, outbox["generation"]),
                )
            if outbox["attempt_count"] >= max_attempts:
                await conn.execute(
                    "UPDATE task_center.outbox SET state='failed',owner_token=NULL,"
                    "lease_until=NULL,updated_at=%s WHERE submission_id=%s",
                    (now, submission_id),
                )
                await conn.execute(
                    "UPDATE task_center.submissions SET status='dispatch_failed',"
                    "last_error_code='attempts_exhausted',updated_at=%s WHERE id=%s",
                    (now, submission_id),
                )
                await self._audit(
                    conn,
                    row["workspace_id"],
                    "dispatch_exhausted",
                    "relay",
                    now,
                    submission_id=submission_id,
                    detail={"generation": outbox["generation"], "epoch": outbox["epoch"]},
                )
                return None
            token = str(uuid4())
            lease_until = now + timedelta(seconds=lease_seconds)
            generation = outbox["generation"] + 1
            await conn.execute(
                "UPDATE task_center.outbox SET state='leased',generation=%s,owner_token=%s,"
                "lease_until=%s,attempt_count=attempt_count+1,updated_at=%s "
                "WHERE submission_id=%s",
                (generation, token, lease_until, now, submission_id),
            )
            await conn.execute(
                "UPDATE task_center.submissions SET status='dispatching',updated_at=%s WHERE id=%s",
                (now, submission_id),
            )
            await conn.execute(
                "INSERT INTO task_center.dispatch_attempts(workspace_id,submission_id,generation,"
                "epoch,owner_token,started_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (row["workspace_id"], submission_id, generation, outbox["epoch"], token, now),
            )
            await self._audit(
                conn,
                row["workspace_id"],
                "dispatch_claimed",
                "relay",
                now,
                submission_id=submission_id,
                detail={"generation": generation, "epoch": outbox["epoch"]},
            )
            request = RunCreateRequest.model_validate(
                {**row["request_json"], "idempotency_key": f"task-submission:{submission_id}"}
            )
            actor = EnterpriseUserContext(**json.loads(row["server_actor"]))
            return DispatchClaim(
                submission_id=submission_id,
                workspace_id=row["workspace_id"],
                expected_run_id=row["expected_run_id"],
                epoch=outbox["epoch"],
                generation=generation,
                owner_token=token,
                lease_until=lease_until,
                attempt_count=outbox["attempt_count"] + 1,
                request=request,
                actor=actor,
                delivery_intent=row["delivery_intent"],
                execution_backend=row["execution_backend"],
            )

    async def _owned_claim(self, conn, claim: DispatchClaim):
        row = await self._locked_submission(conn, claim.workspace_id, claim.submission_id)
        outbox = await (
            await conn.execute(
                "SELECT * FROM task_center.outbox WHERE submission_id=%s FOR UPDATE",
                (claim.submission_id,),
            )
        ).fetchone()
        now = await self._database_now(conn)
        if (
            row["status"] != "dispatching"
            or outbox["state"] != "leased"
            or outbox["generation"] != claim.generation
            or outbox["epoch"] != claim.epoch
            or str(outbox["owner_token"]) != claim.owner_token
            or outbox["lease_until"] <= now
        ):
            return None
        return row, outbox, now

    async def mark_sending(self, claim: DispatchClaim) -> bool:
        """Durably record send intent only while this generation still owns a live lease."""
        async with self.database.transaction(claim.workspace_id) as conn:
            owned = await self._owned_claim(conn, claim)
            if owned is None:
                return False
            _, _, now = owned
            attempt = await (
                await conn.execute(
                    "SELECT outcome FROM task_center.dispatch_attempts "
                    "WHERE submission_id=%s AND generation=%s",
                    (claim.submission_id, claim.generation),
                )
            ).fetchone()
            if attempt["outcome"] != "claimed":
                return False
            changed = await conn.execute(
                "UPDATE task_center.outbox SET sent_intent_at=COALESCE(sent_intent_at,%s),"
                "updated_at=%s WHERE submission_id=%s AND state='leased' AND generation=%s "
                "AND owner_token=%s AND lease_until>clock_timestamp()",
                (now, now, claim.submission_id, claim.generation, claim.owner_token),
            )
            if changed.rowcount != 1:
                return False
            await conn.execute(
                "UPDATE task_center.dispatch_attempts SET outcome='sending',sent_intent_at=%s "
                "WHERE submission_id=%s AND generation=%s",
                (now, claim.submission_id, claim.generation),
            )
            await self._audit(
                conn,
                claim.workspace_id,
                "dispatch_sending",
                "relay",
                now,
                submission_id=claim.submission_id,
                detail={"generation": claim.generation},
            )
            return True

    async def acknowledge(self, claim: DispatchClaim, receipt: DispatchReceipt) -> bool:
        async with self.database.transaction(claim.workspace_id) as conn:
            owned = await self._owned_claim(conn, claim)
            if owned is None:
                return False
            row, _, now = owned
            if (
                not isinstance(receipt, DispatchReceipt)
                or receipt.run_id != row["expected_run_id"]
                or (
                    receipt.workflow_id is not None
                    and (
                        not isinstance(receipt.workflow_id, str)
                        or not receipt.workflow_id.strip()
                        or len(receipt.workflow_id) > 512
                    )
                )
            ):
                raise DispatchConflict("dispatcher receipt does not match submission identity")
            attempt = await (
                await conn.execute(
                    "SELECT outcome FROM task_center.dispatch_attempts "
                    "WHERE submission_id=%s AND generation=%s",
                    (claim.submission_id, claim.generation),
                )
            ).fetchone()
            if attempt["outcome"] != "sending":
                return False
            changed = await conn.execute(
                "UPDATE task_center.outbox SET state='dispatched',owner_token=NULL,"
                "lease_until=NULL,updated_at=%s WHERE submission_id=%s AND state='leased' "
                "AND generation=%s AND owner_token=%s AND lease_until>clock_timestamp()",
                (now, claim.submission_id, claim.generation, claim.owner_token),
            )
            if changed.rowcount != 1:
                return False
            await conn.execute(
                "UPDATE task_center.submissions SET status='dispatched',run_id=%s,workflow_id=%s,"
                "dispatched_at=%s,updated_at=%s,last_error_code=NULL WHERE id=%s",
                (receipt.run_id, receipt.workflow_id, now, now, claim.submission_id),
            )
            await conn.execute(
                "UPDATE task_center.dispatch_attempts SET outcome='succeeded',finished_at=%s "
                "WHERE submission_id=%s AND generation=%s",
                (now, claim.submission_id, claim.generation),
            )
            await self._audit(
                conn,
                claim.workspace_id,
                "dispatch_acknowledged",
                "relay",
                now,
                submission_id=claim.submission_id,
                detail={"generation": claim.generation},
            )
            return True

    async def fail(
        self,
        claim: DispatchClaim,
        *,
        error_code: str = "dispatch_error",
        unknown: bool = True,
        max_attempts: int = 3,
        retry_delay_seconds: float = 1,
    ) -> bool:
        if (
            type(max_attempts) is not int
            or max_attempts < 1
            or not isinstance(retry_delay_seconds, (int, float))
            or not math.isfinite(retry_delay_seconds)
            or retry_delay_seconds < 0
        ):
            raise InvalidTaskCenterRequest("invalid dispatch retry settings")
        # Only fixed codes and fixed text cross the persistence boundary. Never
        # persist dispatcher exception messages, reprs, tracebacks, or class names.
        safe_code = (
            error_code
            if error_code
            in {
                "dispatch_error",
                "dispatch_timeout",
                "dispatch_cancelled",
                "receipt_mismatch",
            }
            else "dispatch_error"
        )
        async with self.database.transaction(claim.workspace_id) as conn:
            owned = await self._owned_claim(conn, claim)
            if owned is None:
                return False
            _, outbox, now = owned
            exhausted = outbox["attempt_count"] >= max_attempts
            available_at = now + timedelta(seconds=min(300, retry_delay_seconds))
            changed = await conn.execute(
                "UPDATE task_center.outbox SET state=%s,owner_token=NULL,lease_until=NULL,"
                "available_at=%s,updated_at=%s WHERE submission_id=%s AND state='leased' "
                "AND generation=%s AND owner_token=%s AND lease_until>clock_timestamp()",
                (
                    "failed" if exhausted else "pending",
                    available_at,
                    now,
                    claim.submission_id,
                    claim.generation,
                    claim.owner_token,
                ),
            )
            if changed.rowcount != 1:
                return False
            await conn.execute(
                "UPDATE task_center.submissions SET status=%s,last_error_code=%s,updated_at=%s "
                "WHERE id=%s",
                (
                    "dispatch_failed" if exhausted else "pending",
                    safe_code,
                    now,
                    claim.submission_id,
                ),
            )
            await conn.execute(
                "UPDATE task_center.dispatch_attempts SET outcome=%s,finished_at=%s,error_code=%s,"
                "sanitized_error='dispatch did not receive a confirmed acceptance' "
                "WHERE submission_id=%s AND generation=%s",
                (
                    "unknown" if unknown else "failed",
                    now,
                    safe_code,
                    claim.submission_id,
                    claim.generation,
                ),
            )
            await self._audit(
                conn,
                claim.workspace_id,
                "dispatch_failed" if exhausted else "dispatch_retry_scheduled",
                "relay",
                now,
                submission_id=claim.submission_id,
                detail={
                    "generation": claim.generation,
                    "epoch": claim.epoch,
                    "error_code": safe_code,
                },
            )
            return True

    async def trusted_seed(self, workspace_id: str, seed: QuotaSeed) -> QuotaSeed:
        """Metadata bootstraps once; its restart timestamp cannot replace PG policy."""
        async with self.database.transaction(workspace_id) as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM task_center.workspace_policies WHERE workspace_id=%s",
                    (workspace_id,),
                )
            ).fetchone()
        if row is None:
            return seed
        return QuotaSeed(
            row["run_limit"], row["enforcement"], seed.legacy_runs, row["policy_version"]
        )

    async def update_trusted_policy(
        self,
        workspace_id: str,
        seed: QuotaSeed,
        *,
        actor: str,
        changes: Mapping[str, Any] | None = None,
    ) -> QuotaSnapshot:
        now = _utc(self._clock())
        start, end = _period(now)
        async with self.database.transaction(workspace_id) as conn:
            merged = await self._policy_seed(conn, workspace_id, seed, changes)
            await self._policy(conn, workspace_id, merged, now)
            await self._bucket(conn, workspace_id, seed, now, start, end)
            await self._audit(
                conn,
                workspace_id,
                "quota_policy_updated",
                actor,
                now,
                detail={"run_limit": merged.run_limit, "enforcement": merged.enforcement},
            )
            return await self._snapshot(conn, workspace_id, start)

    async def _policy_seed(self, conn, workspace_id: str, seed: QuotaSeed, changes) -> QuotaSeed:
        # Serialize initialization and PATCH through the same policy row lock.
        await conn.execute(
            "INSERT INTO task_center.workspace_policies(workspace_id,run_limit,enforcement) "
            "VALUES(%s,%s,%s) ON CONFLICT(workspace_id) DO NOTHING",
            (workspace_id, seed.run_limit, seed.enforcement),
        )
        row = await (
            await conn.execute(
                "SELECT * FROM task_center.workspace_policies "
                "WHERE workspace_id=%s FOR NO KEY UPDATE",
                (workspace_id,),
            )
        ).fetchone()
        values = (
            changes
            if changes is not None
            else {"run_limit": seed.run_limit, "enforcement": seed.enforcement}
        )
        return QuotaSeed(
            values.get("run_limit", row["run_limit"]),
            values.get("enforcement", row["enforcement"]),
            seed.legacy_runs,
            row["policy_version"] + 1,
        )

    async def validate_claim(self, claim: DispatchClaim, request: RunCreateRequest) -> bool:
        async with self.database.transaction(claim.workspace_id) as conn:
            owned = await self._owned_claim(conn, claim)
            if owned is None:
                return False
            row, _, _ = owned
            return self._request_matches(row, request) and (
                row["delivery_intent"] == claim.delivery_intent
                and row["execution_backend"] == claim.execution_backend
                and row["expected_run_id"] == claim.expected_run_id
            )

    @staticmethod
    def _request_matches(row, request: RunCreateRequest) -> bool:
        _, digest = canonical_request(request)
        return (
            request.idempotency_key == f"task-submission:{row['id']}"
            and request.workspace_id == row["workspace_id"]
            and digest == row["request_sha"]
        )

    async def validate_activity(self, request: RunCreateRequest) -> bool:
        key = request.idempotency_key or ""
        if not key.startswith("task-submission:"):
            return False
        try:
            submission_id = _uuid(key.removeprefix("task-submission:"))
        except InvalidTaskCenterRequest:
            return False
        async with self.database.transaction(request.workspace_id) as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM task_center.submissions WHERE workspace_id=%s AND id=%s",
                    (request.workspace_id, submission_id),
                )
            ).fetchone()
            if (
                row is None
                or row["execution_backend"] != "temporal"
                or row["delivery_intent"] not in {"runtime", "temporal"}
            ):
                return False
            if row["status"] == "cancelled":
                return False
            # A remote workflow may start after sender timeout, lease expiry, or
            # exhausted unknown retries. Its durable identity/reservation survives.
            authorized = await (
                await conn.execute(
                    "SELECT 1 WHERE EXISTS(SELECT 1 FROM task_center.dispatch_attempts "
                    "WHERE submission_id=%s AND sent_intent_at IS NOT NULL) "
                    "AND EXISTS(SELECT 1 FROM task_center.quota_entries "
                    "WHERE submission_id=%s AND action='reserve') "
                    "AND NOT EXISTS(SELECT 1 FROM task_center.quota_entries "
                    "WHERE submission_id=%s AND action='release')",
                    (submission_id, submission_id, submission_id),
                )
            ).fetchone()
            return authorized is not None and self._request_matches(row, request)

    async def delivery_route(self, workspace_id: str, submission_id: str) -> dict:
        async with self.database.transaction(workspace_id) as conn:
            row = await (
                await conn.execute(
                    "SELECT delivery_intent,execution_backend FROM task_center.submissions "
                    "WHERE workspace_id=%s AND id=%s",
                    (workspace_id, _uuid(submission_id)),
                )
            ).fetchone()
            if row is None:
                raise SubmissionNotFound("submission does not exist")
            return row

    async def activity_request(
        self, request: RunCreateRequest, *, dynamic_fields: set[str]
    ) -> RunCreateRequest:
        async with self.database.transaction(request.workspace_id) as conn:
            row = await (
                await conn.execute(
                    "SELECT request_json,delivery_intent FROM task_center.submissions "
                    "WHERE workspace_id=%s AND idempotency_key=%s",
                    (request.workspace_id, request.idempotency_key),
                )
            ).fetchone()
        if row is None:
            return request
        original = RunCreateRequest.model_validate(
            {**row["request_json"], "idempotency_key": request.idempotency_key}
        )
        proposed, _ = canonical_request(request)
        stored, _ = canonical_request(original)
        if row["delivery_intent"] != "activity" or any(
            proposed[key] != value for key, value in stored.items() if key not in dynamic_fields
        ):
            raise IdempotencyConflict("cycle key is already used by another request")
        return original
