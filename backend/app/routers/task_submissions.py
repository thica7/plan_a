"""Durable submission HTTP surface. Graph execution belongs to the relay."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_enterprise_user_context, get_submission_service
from packages.auth import EnterpriseUserContext, can_access_workspace
from packages.enterprise.store import DEFAULT_WORKSPACE_ID
from packages.task_center.models import (
    QuotaLedgerPage,
    SubmissionCreateRequest,
    SubmissionPage,
    SubmissionStatus,
    SubmissionView,
)

router = APIRouter()
ServiceDep = Annotated[object, Depends(get_submission_service)]
ActorDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]


async def scope(service, actor, workspace_id=None, *, action="report:read", invisible=False):
    workspace_id = workspace_id or actor.workspace_id or DEFAULT_WORKSPACE_ID
    allowed = await service.metadata.run(can_access_workspace, actor, workspace_id, action)
    if not allowed:
        raise HTTPException(
            404 if invisible else 403,
            detail="Submission not found" if invisible else "Insufficient workspace permission",
        )
    return workspace_id


@router.post("/task-submissions", response_model=SubmissionView, status_code=202)
async def create_submission(body: SubmissionCreateRequest, service: ServiceDep, actor: ActorDep):
    await scope(service, actor, body.request.workspace_id, action="project:write")
    return await service.submit(body, actor=actor)


@router.get("/task-submissions", response_model=SubmissionPage)
async def list_submissions(
    service: ServiceDep,
    actor: ActorDep,
    workspace_id: str | None = None,
    status: SubmissionStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
):
    workspace_id = await scope(service, actor, workspace_id)
    page = await service.repository.list(workspace_id, status=status, limit=limit, cursor=cursor)
    return await service.observe(page)


@router.get("/task-submissions/{submission_id}", response_model=SubmissionView)
async def get_submission(
    submission_id: str, service: ServiceDep, actor: ActorDep, workspace_id: str | None = None
):
    workspace_id = await scope(service, actor, workspace_id, invisible=True)
    return await service.observe(await service.repository.get(workspace_id, submission_id))


@router.post("/task-submissions/{submission_id}/cancel", response_model=SubmissionView)
async def cancel_submission(
    submission_id: str, service: ServiceDep, actor: ActorDep, workspace_id: str | None = None
):
    workspace_id = await scope(service, actor, workspace_id, action="project:write", invisible=True)
    return await service.observe(
        await service.repository.cancel(workspace_id, submission_id, actor=actor)
    )


@router.post(
    "/task-submissions/{submission_id}/retry-dispatch",
    response_model=SubmissionView,
    status_code=202,
)
async def retry_submission(
    submission_id: str, service: ServiceDep, actor: ActorDep, workspace_id: str | None = None
):
    workspace_id = await scope(service, actor, workspace_id, action="project:write", invisible=True)
    return await service.observe(
        await service.repository.retry_dispatch(workspace_id, submission_id, actor=actor)
    )


@router.get("/workspaces/{workspace_id}/quota-ledger", response_model=QuotaLedgerPage)
async def quota_ledger(
    workspace_id: str,
    service: ServiceDep,
    actor: ActorDep,
    period_start: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
):
    await scope(service, actor, workspace_id, action="workspace:read")
    return await service.repository.quota_ledger(
        workspace_id,
        period_start=period_start,
        limit=limit,
        cursor=cursor,
        seed=await service.quota_seed(workspace_id),
    )
