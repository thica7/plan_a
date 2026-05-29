from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from packages.workflows.models import (
    LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
    RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
    RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
    ScheduledScanNotificationInput,
    ScheduledScanNotificationState,
    ScheduledScanProjectInput,
    ScheduledScanProjectResult,
    ScheduledScanProjectStatus,
    ScheduledScanStatus,
    ScheduledScanTarget,
    ScheduledScanWorkflowInput,
    ScheduledScanWorkflowResult,
)


@workflow.defn
class ScheduledScanWorkflow:
    """Phase 5 Temporal workflow for recurring workspace intelligence scans."""

    @workflow.run
    async def run(
        self,
        request: ScheduledScanWorkflowInput,
    ) -> ScheduledScanWorkflowResult:
        scan_started_at = workflow.now().isoformat()
        targets = _coerce_targets(
            await workflow.execute_activity(
                LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
                request,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
        results: list[ScheduledScanProjectResult] = []
        for target in targets:
            project_input = ScheduledScanProjectInput(
                request=request,
                target=target,
                scan_started_at=scan_started_at,
            )
            try:
                result = await workflow.execute_activity(
                    RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
                    project_input,
                    start_to_close_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                results.append(_coerce_project_result(result))
            except ActivityError as exc:
                results.append(
                    ScheduledScanProjectResult(
                        project_id=target.project_id,
                        run_id=None,
                        status="failed",
                        error=_activity_error_message(exc),
                    )
                )

        notification = _coerce_notification_state(
            await workflow.execute_activity(
                RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
                ScheduledScanNotificationInput(
                    request=request,
                    results=results,
                    scan_started_at=scan_started_at,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
        return _scan_result(
            request,
            results,
            notification_id=notification.notification_id,
            scan_started_at=scan_started_at,
        )


def _scan_result(
    request: ScheduledScanWorkflowInput,
    results: list[ScheduledScanProjectResult],
    *,
    notification_id: str | None,
    scan_started_at: str,
) -> ScheduledScanWorkflowResult:
    completed = sum(1 for item in results if item.status == "completed")
    failed = sum(1 for item in results if item.status == "failed")
    interrupted = sum(1 for item in results if item.status == "interrupted")
    return ScheduledScanWorkflowResult(
        workspace_id=request.workspace_id,
        schedule_id=request.schedule_id,
        status=_scan_status(len(results), completed, failed, interrupted),
        scanned_project_count=len(results),
        completed_count=completed,
        failed_count=failed,
        interrupted_count=interrupted,
        run_ids=[item.run_id for item in results if item.run_id],
        report_version_ids=[
            item.report_version_id for item in results if item.report_version_id
        ],
        notification_id=notification_id,
        scan_started_at=scan_started_at,
    )


def _scan_status(
    total: int,
    completed: int,
    failed: int,
    interrupted: int,
) -> ScheduledScanStatus:
    if total == 0:
        return "empty"
    if failed == total:
        return "failed"
    if failed or interrupted or completed < total:
        return "partial"
    return "completed"


def _coerce_targets(value: object) -> list[ScheduledScanTarget]:
    if isinstance(value, list):
        return [_coerce_target(item) for item in value]
    raise ValueError("Scheduled scan targets activity must return a list.")


def _coerce_target(value: ScheduledScanTarget | Mapping[str, object]) -> ScheduledScanTarget:
    if isinstance(value, ScheduledScanTarget):
        return value
    return ScheduledScanTarget(
        project_id=_text(value, "project_id"),
        workspace_id=_text(value, "workspace_id"),
        topic=_text(value, "topic"),
        competitors=_text_list(value.get("competitors")),
        dimensions=_text_list(value.get("dimensions")),
        competitor_layer=_optional_layer(value.get("competitor_layer")),
        scenario_id=_optional_text(value.get("scenario_id")),
    )


def _coerce_project_result(
    value: ScheduledScanProjectResult | Mapping[str, object],
) -> ScheduledScanProjectResult:
    if isinstance(value, ScheduledScanProjectResult):
        return value
    return ScheduledScanProjectResult(
        project_id=_text(value, "project_id"),
        run_id=_optional_text(value.get("run_id")),
        status=_project_status(value.get("status")),
        report_version_id=_optional_text(value.get("report_version_id")),
        evidence_count=_int(value.get("evidence_count")),
        claim_count=_int(value.get("claim_count")),
        error=_optional_text(value.get("error")) or "",
    )


def _coerce_notification_state(
    value: ScheduledScanNotificationState | Mapping[str, object],
) -> ScheduledScanNotificationState:
    if isinstance(value, ScheduledScanNotificationState):
        return value
    return ScheduledScanNotificationState(
        notification_id=_optional_text(value.get("notification_id")),
        status=_text(value, "status"),
    )


def _activity_error_message(exc: ActivityError) -> str:
    cause = exc.cause
    return str(cause or exc)[:1000]


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise ValueError(f"Scheduled scan payload field {key!r} must be a string.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError("Scheduled scan optional text field must be a string or null.")


def _text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError("Scheduled scan list field must be a list of strings.")


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("Scheduled scan integer field must not be boolean.")
    if isinstance(value, int):
        return value
    raise ValueError("Scheduled scan integer field must be an integer.")


def _optional_layer(value: object) -> str | None:
    if value is None:
        return None
    if value in {"L1", "L2", "L3"}:
        return cast(str, value)
    raise ValueError("Scheduled scan competitor layer is invalid.")


def _project_status(value: object) -> ScheduledScanProjectStatus:
    if value in {"completed", "interrupted", "failed"}:
        return cast(ScheduledScanProjectStatus, value)
    raise ValueError("Scheduled scan project result status is invalid.")
