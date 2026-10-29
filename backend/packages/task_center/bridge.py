"""Private, revalidated dispatch grants; public DTOs never carry admission flags."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from uuid import uuid4

from packages.auth import EnterpriseUserContext

from .errors import DispatchConflict
from .factory import get_task_service

_authorization = ContextVar("task_center_dispatch_authorization", default=None)


@contextmanager
def dispatch_authorization(claim):
    token = _authorization.set(("claim", claim))
    try:
        yield
    finally:
        _authorization.reset(token)


def execution_context():
    context = copy_context()
    context.run(_authorization.set, None)
    return context


class SubmissionBridge:
    def __init__(self, settings, *, store, journal, run_service, task_service=None):
        self.settings = settings
        self.store = store
        self.journal = journal
        self.run_service = run_service
        self._service = task_service

    @property
    def enabled(self):
        return self.settings.task_center_enabled

    def service(self):
        if self._service is not None:
            return self._service
        return get_task_service(self.settings, store=self.store, journal=self.journal)

    async def verified(self, request):
        grant = _authorization.get()
        if grant is None:
            return False
        service = self.service()
        await service.open()
        kind, value = grant
        valid = (
            await service.repository.validate_claim(value, request)
            if kind == "claim"
            else await service.repository.validate_activity(request)
        )
        if not valid:
            raise DispatchConflict("private submission authorization is invalid or expired")
        return True

    async def execute(self, request, *, intent, backend, actor=None, workflow_service=None):
        request = request.model_copy(
            update={"idempotency_key": request.idempotency_key or f"entry:{uuid4()}"}
        )
        actor = actor or EnterpriseUserContext(
            user_id="system-user", role="owner", workspace_id=request.workspace_id
        )
        return await self.service().execute(
            request,
            actor=actor,
            intent=intent,
            backend=backend,
            run_service=self.run_service,
            workflow_service=workflow_service,
        )

    async def create_activity(self, request):
        if not self.enabled:
            return await self.run_service.create_run(
                request, runtime_orchestration_backend="temporal"
            )
        if (request.idempotency_key or "").startswith("task-submission:"):
            service = self.service()
            await service.open()
            if not await service.repository.validate_activity(request):
                raise DispatchConflict("Temporal activity submission identity is invalid")
            token = _authorization.set(("activity", request))
            try:
                return await self.run_service.create_run(
                    request, runtime_orchestration_backend="temporal"
                )
            finally:
                _authorization.reset(token)
        result = await self.execute(request, intent="activity", backend="temporal")
        return result.payload

    async def create_monitor_activity(self, request):
        if self.enabled:
            service = self.service()
            await service.open()
            # These fields come from mutable project metadata. The workflow's
            # workspace/project/dimensions/mode still have to match exactly.
            request = await service.repository.activity_request(
                request,
                dynamic_fields={"topic", "competitors", "competitor_layer", "scenario_id"},
            )
        return await self.create_activity(request)
