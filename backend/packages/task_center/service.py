"""Trusted metadata, historical quota seeding and delivery of existing run commands."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps

from packages.auth import can_access_workspace
from packages.schema.api_dto import WorkflowStartResponse

from .dispatch import DispatchReceipt
from .errors import DispatchConflict, InvalidTaskCenterRequest, TaskCenterConfigurationError
from .models import QuotaSeed


def _managed(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        from .errors import TaskCenterUnavailable
        if self._stopping:
            raise TaskCenterUnavailable("task center is stopping")
        task = asyncio.current_task()
        self._operations[task] = self._operations.get(task, 0) + 1
        try:
            return await method(self, *args, **kwargs)
        finally:
            self._operations[task] -= 1
            if not self._operations[task]:
                self._operations.pop(task)
    return wrapped


@dataclass(frozen=True)
class DeliveryResult:
    payload: object
    backend: str


class TaskCenterService:
    def __init__(self, repository, *, settings, store, journal):
        self.repository = repository
        self.settings = settings
        self.store = store
        self.journal = journal
        self._open_lock = asyncio.Lock()
        self._opened = False
        self._stopping = False
        self._operations = {}
        from .offload import MetadataIO
        self.metadata = MetadataIO(timeout=settings.task_center_pool_timeout_seconds)

    async def open(self):
        async with self._open_lock:
            if self._stopping:
                from .errors import TaskCenterUnavailable
                raise TaskCenterUnavailable("task center is stopping")
            if not self._opened:
                await self.repository.database.open()
                self._opened = True

    def stop_intake(self):
        self._stopping = True

    async def drain(self):
        pending = [task for task in self._operations if task is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def close(self):
        self.stop_intake()
        await self.drain()
        await self.metadata.close()
        await self.repository.database.close()
        self._opened = False

    def validate_scope(self, request, actor):
        if not can_access_workspace(actor, request.workspace_id, "project:write"):
            raise InvalidTaskCenterRequest("actor is not authorized for this workspace")
        workspace = next(
            (item for item in self.store.list_workspaces() if item.id == request.workspace_id), None
        )
        if workspace is None:
            raise InvalidTaskCenterRequest("workspace does not exist")
        if request.project_id is not None:
            project = self.store.get_project(request.project_id)
            if project is None or project.workspace_id != request.workspace_id:
                raise InvalidTaskCenterRequest("project does not belong to workspace")
        return workspace

    async def quota_seed(self, workspace_id):
        seed = await self.metadata.run(self._read_quota_seed, workspace_id)
        return await self.repository.trusted_seed(workspace_id, seed)

    def _read_quota_seed(self, workspace_id):
        workspace = next(
            (item for item in self.store.list_workspaces() if item.id == workspace_id), None
        )
        if workspace is None:
            raise InvalidTaskCenterRequest("workspace does not exist")
        # This is the journal's read-only index. RunService.list_runs can repair writes.
        seed = QuotaSeed(
            workspace.monthly_run_quota,
            workspace.quota_enforcement,
            self.journal.load_run_summaries(),
        )
        return seed

    async def update_policy(self, workspace_id, request, *, actor):
        allowed = await self.metadata.run(
            can_access_workspace, actor, workspace_id, "workspace:write"
        )
        if not allowed:
            raise InvalidTaskCenterRequest("actor is not authorized to update workspace policy")
        await self.open()
        seed = await self.quota_seed(workspace_id)
        values = request.model_dump(exclude_none=True)
        seed = QuotaSeed(
            values.get("monthly_run_quota", seed.run_limit),
            values.get("quota_enforcement", seed.enforcement),
            seed.legacy_runs,
        )
        changes = {}
        if "monthly_run_quota" in values:
            changes["run_limit"] = values["monthly_run_quota"]
        if "quota_enforcement" in values:
            changes["enforcement"] = values["quota_enforcement"]
        return await self.repository.update_trusted_policy(
            workspace_id,
            seed,
            actor=actor.user_id,
            changes=changes,
        )

    @_managed
    async def submit(self, body, *, actor):
        """Persist intent only. Execution dependencies are owned by the relay."""
        from packages.runtime.commands import RuntimeCommandError
        from packages.runtime.service import (
            _resolved_execution_mode,
            ensure_model_execution_allowed,
        )
        from packages.workflows.service import decide_temporal_cutover

        from .errors import InvalidTaskCenterRequest

        await self.open()
        request = body.request.model_copy(update={"idempotency_key": body.idempotency_key})
        await self.metadata.run(self.validate_scope, request, actor)
        def resolve_execution():
            # Invoked only for a new key while holding the repository's key lock.
            # A replay uses its raw identity and its first accepted mode/route.
            mode = _resolved_execution_mode(request, self.settings)
            try:
                ensure_model_execution_allowed(self.settings, mode)
            except RuntimeCommandError:
                raise InvalidTaskCenterRequest(
                    "model policy does not allow real execution"
                ) from None
            resolved = request.model_copy(update={"execution_mode": mode})
            return mode, decide_temporal_cutover(self.settings, resolved).route

        view = await self.repository.submit(
            request, actor=actor, seed=await self.quota_seed(request.workspace_id),
            idempotency_key=body.idempotency_key, delivery_intent="runtime",
            resolve_execution=resolve_execution,
        )
        return await self.observe(view)

    async def observe(self, view):
        summaries = await self.metadata.run(self.journal.load_run_summaries)
        by_id = {item.id: item for item in summaries}
        observed = datetime.now(UTC)
        def projection(item):
            summary = by_id.get(item.expected_run_id)
            return item.model_copy(update={
                "run_status": summary.status if summary is not None else None,
                "run_status_observed_at": observed,
            })
        if hasattr(view, "items"):
            return view.model_copy(update={"items": [projection(item) for item in view.items]})
        return projection(view)

    def require_execution(self, run_service):
        if (
            not self.settings.execution_control_enabled
            or run_service is None
            or run_service._execution is None
            or str(self.journal.db_path) == ":memory:"
            or run_service._journal is None
            or run_service._journal.db_path.resolve() != self.journal.db_path.resolve()
        ):
            raise TaskCenterConfigurationError(
                "Task center startup requires shared execution control and durable journal"
            )

    @_managed
    async def execute(self, request, *, actor, intent, backend, run_service, workflow_service=None):
        await self.open()
        await self.metadata.run(self.validate_scope, request, actor)
        view = await self.repository.submit(
            request,
            actor=actor,
            seed=await self.quota_seed(request.workspace_id),
            delivery_intent=intent,
            execution_backend=backend,
        )
        if view.status != "dispatched":
            from .relay import OutboxRelay

            delivered, failures = [], []

            async def receiver(claim):
                try:
                    result, receipt = await self._deliver(claim, run_service, workflow_service)
                    delivered.append(result)
                    return receipt
                except Exception as exc:
                    failures.append(exc)
                    raise

            relay = OutboxRelay(
                self.repository,
                receiver,
                lease_seconds=self.settings.task_center_dispatch_lease_seconds,
                max_attempts=self.settings.task_center_dispatch_max_attempts,
                retry_base_seconds=self.settings.task_center_dispatch_retry_seconds,
            )
            outcome = await relay.run_once(submission_id=view.id)
            if outcome.status == "dispatched" and delivered:
                return delivered[0]
            if failures:
                raise failures[0]
            view = await self.repository.get(request.workspace_id, view.id)
            if view.status != "dispatched":
                raise DispatchConflict("submission delivery is busy or unavailable")
        route = await self.repository.delivery_route(request.workspace_id, view.id)
        return await self.metadata.run(self._replay, view, route, intent)

    @_managed
    async def dispatch(self, claim, *, run_service, workflow_service=None):
        """Relay adapter: it returns a receipt; the relay owns sending/ack transitions."""
        _, receipt = await self._deliver(claim, run_service, workflow_service)
        return receipt

    async def _deliver(self, claim, run_service, workflow_service):
        from .bridge import dispatch_authorization

        if not await self.repository.validate_claim(claim, claim.request):
            raise DispatchConflict("submission reservation is no longer valid")
        if claim.delivery_intent != "create_only":
            self.require_execution(run_service)
        with dispatch_authorization(claim):
            detail = await run_service.create_run(
                claim.request,
                runtime_orchestration_backend=claim.execution_backend,
            )
            if detail.id != claim.expected_run_id:
                raise DispatchConflict("receiver returned another run identity")
            if (
                claim.delivery_intent in {"runtime", "temporal"}
                and claim.execution_backend == "temporal"
            ):
                if workflow_service is None:
                    raise TaskCenterConfigurationError("Temporal delivery dependency is missing")
                payload = await workflow_service.start_competitive_intel(claim.request)
                receipt = DispatchReceipt(detail.id, payload.workflow_id)
            else:
                payload = detail
                if claim.delivery_intent == "runtime" and detail.status == "queued":
                    run_service.launch_pipeline(detail.id)
                receipt = DispatchReceipt(detail.id)
        return DeliveryResult(payload, claim.execution_backend), receipt

    def _replay(self, view, route, intent):
        if intent in {"runtime", "temporal"} and route["execution_backend"] == "temporal":
            payload = WorkflowStartResponse(
                workflow_id=view.workflow_id,
                run_id=view.expected_run_id,
                idempotency_key=f"task-submission:{view.id}",
                task_queue=self.settings.temporal_task_queue,
                status="already_started",
            )
        else:
            payload = self.journal.load_run(view.expected_run_id)
            if payload is None:
                raise DispatchConflict("accepted run is not yet visible")
        return DeliveryResult(payload, route["execution_backend"])
