from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_app_settings, get_temporal_workflow_service
from app.governance import ensure_model_policy_allows_execution_mode
from packages.config import Settings
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
from packages.workflows.service import TemporalWorkflowService

router = APIRouter()
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService,
    Depends(get_temporal_workflow_service),
]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.post(
    "/workflows/competitive-intel",
    response_model=WorkflowStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_competitive_intel_workflow(
    request: RunCreateRequest,
    service: TemporalWorkflowServiceDep,
    settings: SettingsDep,
) -> WorkflowStartResponse:
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    try:
        return await service.start_competitive_intel(request)
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
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
) -> ScheduledScanStartResponse:
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    try:
        return await service.start_scheduled_scan(request)
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
) -> MonitorStartResponse:
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    try:
        return await service.start_monitor(request)
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
    service: TemporalWorkflowServiceDep,
) -> ReportApprovalStartResponse:
    try:
        return await service.start_report_approval(request)
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc


@router.post(
    "/workflows/report-approval/{report_version_id}/approve",
    response_model=ReportApprovalSignalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_report_approval_workflow(
    report_version_id: str,
    request: ReportApprovalSignalRequest,
    service: TemporalWorkflowServiceDep,
) -> ReportApprovalSignalResponse:
    try:
        return await service.approve_report(report_version_id, request)
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc


@router.post(
    "/workflows/report-approval/{report_version_id}/reject",
    response_model=ReportApprovalSignalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reject_report_approval_workflow(
    report_version_id: str,
    request: ReportApprovalSignalRequest,
    service: TemporalWorkflowServiceDep,
) -> ReportApprovalSignalResponse:
    try:
        return await service.reject_report(report_version_id, request)
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc
