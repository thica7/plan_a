from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy

from packages.workflows.models import (
    RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY,
    RUN_MONITOR_CYCLE_ACTIVITY,
    MonitorAnomaly,
    MonitorAnomalyNotificationInput,
    MonitorAnomalyNotificationState,
    MonitorAnomalySeverity,
    MonitorAnomalyType,
    MonitorCycleInput,
    MonitorCycleResult,
    MonitorCycleStatus,
    MonitorSnapshot,
    MonitorStatus,
    MonitorWorkflowInput,
    MonitorWorkflowResult,
)


@workflow.defn
class MonitorWorkflow:
    """Phase 5 long-running project monitor with anomaly notifications."""

    @workflow.run
    async def run(self, request: MonitorWorkflowInput) -> MonitorWorkflowResult:
        monitor_started_at = workflow.now().isoformat()
        results: list[MonitorCycleResult] = []
        notification_ids: list[str] = []
        cycle_count = max(1, request.max_cycles)
        for cycle_index in range(cycle_count):
            cycle_result = _coerce_cycle_result(
                await workflow.execute_activity(
                    RUN_MONITOR_CYCLE_ACTIVITY,
                    MonitorCycleInput(
                        request=request,
                        cycle_index=cycle_index,
                        monitor_started_at=monitor_started_at,
                    ),
                    start_to_close_timeout=timedelta(hours=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            )
            if cycle_result.anomalies:
                notification = _coerce_notification_state(
                    await workflow.execute_activity(
                        RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY,
                        MonitorAnomalyNotificationInput(
                            request=request,
                            cycle_result=cycle_result,
                            monitor_started_at=monitor_started_at,
                        ),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                )
                if notification.notification_id:
                    notification_ids.append(notification.notification_id)
            results.append(cycle_result)
            if cycle_index < cycle_count - 1:
                await workflow.sleep(timedelta(seconds=max(1, request.interval_seconds)))

        return _monitor_result(
            request,
            results,
            notification_ids=notification_ids,
            monitor_started_at=monitor_started_at,
        )


def _monitor_result(
    request: MonitorWorkflowInput,
    results: list[MonitorCycleResult],
    *,
    notification_ids: list[str],
    monitor_started_at: str,
) -> MonitorWorkflowResult:
    failed_count = sum(1 for item in results if item.status == "failed")
    return MonitorWorkflowResult(
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        monitor_id=request.monitor_id,
        status=_monitor_status(len(results), failed_count),
        cycle_count=len(results),
        failed_count=failed_count,
        anomaly_count=sum(len(item.anomalies) for item in results),
        run_ids=[item.run_id for item in results if item.run_id],
        notification_ids=notification_ids,
        monitor_started_at=monitor_started_at,
    )


def _monitor_status(total: int, failed_count: int) -> MonitorStatus:
    if total > 0 and failed_count == total:
        return "failed"
    if failed_count:
        return "partial"
    return "completed"


def _coerce_cycle_result(value: MonitorCycleResult | Mapping[str, object]) -> MonitorCycleResult:
    if isinstance(value, MonitorCycleResult):
        return value
    return MonitorCycleResult(
        cycle_index=_int(value.get("cycle_index")),
        project_id=_text(value, "project_id"),
        status=_cycle_status(value.get("status")),
        previous=_coerce_optional_snapshot(value.get("previous")),
        current=_coerce_optional_snapshot(value.get("current")),
        run_id=_optional_text(value.get("run_id")),
        report_version_id=_optional_text(value.get("report_version_id")),
        anomalies=_coerce_anomalies(value.get("anomalies")),
        error=_optional_text(value.get("error")) or "",
    )


def _coerce_optional_snapshot(value: object) -> MonitorSnapshot | None:
    if value is None:
        return None
    if isinstance(value, MonitorSnapshot):
        return value
    if isinstance(value, Mapping):
        return MonitorSnapshot(
            project_id=_text(value, "project_id"),
            report_version_id=_optional_text(value.get("report_version_id")),
            run_id=_optional_text(value.get("run_id")),
            evidence_count=_int(value.get("evidence_count")),
            claim_count=_int(value.get("claim_count")),
            report_chars=_int(value.get("report_chars")),
            report_hash=_optional_text(value.get("report_hash")) or "",
        )
    raise ValueError("Monitor snapshot must be an object or null.")


def _coerce_anomalies(value: object) -> list[MonitorAnomaly]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_coerce_anomaly(item) for item in value]
    raise ValueError("Monitor anomalies field must be a list.")


def _coerce_anomaly(value: MonitorAnomaly | Mapping[str, object]) -> MonitorAnomaly:
    if isinstance(value, MonitorAnomaly):
        return value
    metadata = value.get("metadata")
    return MonitorAnomaly(
        id=_text(value, "id"),
        severity=_anomaly_severity(value.get("severity")),
        anomaly_type=_anomaly_type(value.get("anomaly_type")),
        message=_text(value, "message"),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _coerce_notification_state(
    value: MonitorAnomalyNotificationState | Mapping[str, object],
) -> MonitorAnomalyNotificationState:
    if isinstance(value, MonitorAnomalyNotificationState):
        return value
    return MonitorAnomalyNotificationState(
        notification_id=_optional_text(value.get("notification_id")),
        status=_text(value, "status"),
        anomaly_count=_int(value.get("anomaly_count")),
    )


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise ValueError(f"Monitor payload field {key!r} must be a string.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError("Monitor optional text field must be a string or null.")


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("Monitor integer field must not be boolean.")
    if isinstance(value, int):
        return value
    raise ValueError("Monitor integer field must be an integer.")


def _cycle_status(value: object) -> MonitorCycleStatus:
    if value in {"completed", "interrupted", "failed"}:
        return cast(MonitorCycleStatus, value)
    raise ValueError("Monitor cycle status field is invalid.")


def _anomaly_severity(value: object) -> MonitorAnomalySeverity:
    if value in {"info", "warning", "critical"}:
        return cast(MonitorAnomalySeverity, value)
    raise ValueError("Monitor anomaly severity field is invalid.")


def _anomaly_type(value: object) -> MonitorAnomalyType:
    if value in {
        "scan_failed",
        "report_missing",
        "report_changed",
        "evidence_drop",
        "claim_drop",
    }:
        return cast(MonitorAnomalyType, value)
    raise ValueError("Monitor anomaly type field is invalid.")
