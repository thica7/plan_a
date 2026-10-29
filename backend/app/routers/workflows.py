from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import (
    get_app_settings,
    get_enterprise_store,
    get_enterprise_user_context,
    get_run_service,
    get_runtime_command_service,
    get_temporal_workflow_service,
)
from app.governance import ensure_model_policy_allows_execution_mode
from packages.auth import EnterpriseUserContext, can_access_workspace
from packages.config import Settings
from packages.enterprise import EnterpriseStore, WorkspaceQuotaExceededError
from packages.identity import new_ui_run_idempotency_key
from packages.infrastructure.execution_control import ExecutionControlError
from packages.orchestrator.service import RunService
from packages.runtime import (
    ApproveReportCommand,
    RejectReportCommand,
    RequestApprovalCommand,
    RuntimeCommandError,
    RuntimeCommandService,
)
from packages.schema.api_dto import (
    MonitorStartRequest,
    MonitorStartResponse,
    ReportApprovalSignalRequest,
    ReportApprovalSignalResponse,
    ReportApprovalStartRequest,
    ReportApprovalStartResponse,
    RunCreateRequest,
    ScheduledScanStartRequest,
    ScheduledScanStartResponse,
    WorkflowStartResponse,
    WorkflowStateResponse,
)
from packages.task_center.errors import TaskCenterError
from packages.workflows.service import TemporalWorkflowService

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService,
    Depends(get_temporal_workflow_service),
]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RuntimeCommandServiceDep = Annotated[RuntimeCommandService, Depends(get_runtime_command_service)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]
EnterpriseStoreDep = Annotated[EnterpriseStore, Depends(get_enterprise_store)]


@router.post(
    "/workflows/competitive-intel",
    response_model=WorkflowStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_competitive_intel_workflow(
    request: RunCreateRequest,
    workflow_service: TemporalWorkflowServiceDep,
    run_service: RunServiceDep,
    settings: SettingsDep,
    user: EnterpriseUserDep,
    store: EnterpriseStoreDep,
) -> WorkflowStartResponse:
    _require_creation_scope(
        store, user, request.workspace_id, [request.project_id] if request.project_id else [],
    )
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    if settings.task_center_enabled:
        try:
            return await workflow_service.start_competitive_intel(request, actor=user)
        except WorkspaceQuotaExceededError as exc:
            raise HTTPException(
                status_code=429, detail=exc.decision.model_dump(mode="json"),
            ) from exc
        except TaskCenterError as exc:
            raise HTTPException(
                status_code=getattr(exc, "status_code", 503), detail=str(exc),
            ) from exc
    _ensure_workspace_quota(run_service, request.workspace_id)
    if settings.execution_control_enabled:
        request = request.model_copy(update={
            "idempotency_key": request.idempotency_key or new_ui_run_idempotency_key(),
        })
        await run_service.create_run(request, runtime_orchestration_backend="temporal")
    try:
        result = await workflow_service.start_competitive_intel(request)
    except ExecutionControlError:
        raise
    except TaskCenterError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 503), detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc
    try:
        await _ensure_workflow_run_visible(result, request, run_service)
    except WorkspaceQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.decision.model_dump(mode="json"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - explain post-start visibility failures.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Temporal workflow started but run visibility sync failed.",
        ) from exc
    return result


async def _ensure_workflow_run_visible(
    result: WorkflowStartResponse,
    request: RunCreateRequest,
    run_service: RunService,
) -> None:
    visible_request = request.model_copy(update={"idempotency_key": result.idempotency_key})
    detail = await run_service.ensure_run_visible(
        visible_request, runtime_orchestration_backend="temporal",
    )
    if detail.id != result.run_id:
        raise RuntimeError(
            f"Temporal returned run_id={result.run_id}, but local visibility "
            f"created run_id={detail.id}."
        )


def _ensure_workspace_quota(service: RunService, workspace_id: str) -> None:
    try:
        service.ensure_workspace_quota_allows_run(workspace_id)
    except WorkspaceQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.decision.model_dump(mode="json"),
        ) from exc


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowStateResponse,
)
async def get_workflow_state(
    workflow_id: str,
    service: TemporalWorkflowServiceDep,
) -> WorkflowStateResponse:
    try:
        return await service.get_workflow_state(workflow_id)
    except TaskCenterError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 503), detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc


@router.post(
    "/workflows/scheduled-scan",
    response_model=ScheduledScanStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_scheduled_scan_workflow(
    request: ScheduledScanStartRequest,
    service: TemporalWorkflowServiceDep,
    settings: SettingsDep,
    user: EnterpriseUserDep,
    store: EnterpriseStoreDep,
) -> ScheduledScanStartResponse:
    _require_creation_scope(store, user, request.workspace_id, request.project_ids)
    request = request.model_copy(update={"requested_by": user.user_id})
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    try:
        return await service.start_scheduled_scan(request)
    except TaskCenterError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 503), detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc


@router.post(
    "/workflows/monitor",
    response_model=MonitorStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_monitor_workflow(
    request: MonitorStartRequest,
    service: TemporalWorkflowServiceDep,
    settings: SettingsDep,
    user: EnterpriseUserDep,
    store: EnterpriseStoreDep,
) -> MonitorStartResponse:
    _require_creation_scope(store, user, request.workspace_id, [request.project_id])
    request = request.model_copy(update={"requested_by": user.user_id})
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    try:
        return await service.start_monitor(request)
    except TaskCenterError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 503), detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc


@router.post(
    "/workflows/report-approval",
    response_model=ReportApprovalStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_report_approval_workflow(
    request: ReportApprovalStartRequest,
    runtime: RuntimeCommandServiceDep,
    user: EnterpriseUserDep,
) -> ReportApprovalStartResponse:
    try:
        result = await runtime.request_approval(
            RequestApprovalCommand(request=request),
            actor=user,
        )
    except RuntimeCommandError as exc:
        _raise_runtime_command_error(exc)
    return result.payload


@router.post(
    "/workflows/report-approval/{report_version_id}/approve",
    response_model=ReportApprovalSignalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_report_approval_workflow(
    report_version_id: str,
    request: ReportApprovalSignalRequest,
    runtime: RuntimeCommandServiceDep,
    user: EnterpriseUserDep,
) -> ReportApprovalSignalResponse:
    try:
        result = await runtime.approve_report(
            ApproveReportCommand(report_version_id=report_version_id, request=request),
            actor=user,
        )
    except RuntimeCommandError as exc:
        _raise_runtime_command_error(exc)
    return result.payload


@router.post(
    "/workflows/report-approval/{report_version_id}/reject",
    response_model=ReportApprovalSignalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reject_report_approval_workflow(
    report_version_id: str,
    request: ReportApprovalSignalRequest,
    runtime: RuntimeCommandServiceDep,
    user: EnterpriseUserDep,
) -> ReportApprovalSignalResponse:
    try:
        result = await runtime.reject_report(
            RejectReportCommand(report_version_id=report_version_id, request=request),
            actor=user,
        )
    except RuntimeCommandError as exc:
        _raise_runtime_command_error(exc)
    return result.payload


def _raise_runtime_command_error(error: RuntimeCommandError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail)


def _require_creation_scope(store, user, workspace_id, project_ids):
    if not can_access_workspace(user, workspace_id, "project:write"):
        raise HTTPException(status_code=403, detail="Insufficient workspace permission")
    if not any(item.id == workspace_id for item in store.list_workspaces()):
        raise HTTPException(status_code=404, detail="Workspace not found")
    for project_id in project_ids:
        project = store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=403, detail="Project is outside workspace scope")
