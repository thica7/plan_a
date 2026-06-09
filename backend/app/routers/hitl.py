from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_enterprise_user_context, get_runtime_command_service
from packages.auth import EnterpriseUserContext
from packages.runtime import (
    RequestRedoCommand,
    ResumeReviewCommand,
    RuntimeCommandError,
    RuntimeCommandService,
)
from packages.schema.api_dto import HitlResumeRequest, RunDetail

router = APIRouter()
RuntimeCommandServiceDep = Annotated[RuntimeCommandService, Depends(get_runtime_command_service)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]


@router.post("/runs/{run_id}/resume", response_model=RunDetail)
async def resume_run(
    run_id: str,
    request: HitlResumeRequest,
    runtime: RuntimeCommandServiceDep,
    user: EnterpriseUserDep,
) -> RunDetail:
    try:
        result = await runtime.resume_review(
            ResumeReviewCommand(run_id=run_id, request=request),
            actor=user,
        )
    except RuntimeCommandError as exc:
        _raise_runtime_command_error(exc)
    return result.payload


@router.post("/runs/{run_id}/redo", response_model=RunDetail)
async def start_manual_redo(
    run_id: str,
    runtime: RuntimeCommandServiceDep,
    user: EnterpriseUserDep,
) -> RunDetail:
    try:
        result = await runtime.request_redo(
            RequestRedoCommand(run_id=run_id),
            actor=user,
        )
    except RuntimeCommandError as exc:
        _raise_runtime_command_error(exc)
    return result.payload


def _raise_runtime_command_error(error: RuntimeCommandError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail)
