from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime
from typing import Literal, cast

from temporalio import activity

from packages.business_intel import evaluate_report_release_gate
from packages.enterprise import EnterpriseStore, report_release_gate_scope
from packages.identity import (
    compute_monitor_anomaly_id,
    compute_notification_id,
    compute_workflow_id,
)
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import (
    NotificationRecord,
    ProjectRecord,
    ReportReleaseGate,
    ReportVersionRecord,
)
from packages.workflows.models import (
    APPROVE_REPORT_VERSION_ACTIVITY,
    CREATE_RUN_ACTIVITY,
    LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY,
    RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
    REJECT_REPORT_VERSION_ACTIVITY,
    REQUEST_REPORT_APPROVAL_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    RUN_MONITOR_CYCLE_ACTIVITY,
    RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
    CompetitiveIntelWorkflowInput,
    MonitorAnomaly,
    MonitorAnomalyNotificationInput,
    MonitorAnomalyNotificationState,
    MonitorAnomalySeverity,
    MonitorAnomalyType,
    MonitorCycleInput,
    MonitorCycleResult,
    MonitorSnapshot,
    ReportApprovalDecisionInput,
    ReportApprovalState,
    ReportApprovalWorkflowInput,
    ScheduledScanNotificationInput,
    ScheduledScanNotificationState,
    ScheduledScanProjectInput,
    ScheduledScanProjectResult,
    ScheduledScanTarget,
    ScheduledScanWorkflowInput,
    WorkflowProjectionState,
    WorkflowRunState,
)


class CompetitiveIntelActivities:
    def __init__(self, service: RunService) -> None:
        self._service = service

    @activity.defn(name=CREATE_RUN_ACTIVITY)
    async def create_run(self, request: CompetitiveIntelWorkflowInput) -> WorkflowRunState:
        detail = await self._service.create_run(
            RunCreateRequest(
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                idempotency_key=request.idempotency_key or None,
                topic=request.topic,
                competitors=request.competitors,
                dimensions=request.dimensions,
                competitor_layer=request.competitor_layer,
                scenario_id=request.scenario_id,
                execution_mode=request.execution_mode,
                auto_redo_warn_enabled=request.auto_redo_warn_enabled,
                hitl_enabled=request.hitl_enabled,
            )
        )
        return _run_state(detail)

    @activity.defn(name=RUN_LANGGRAPH_ACTIVITY)
    async def run_langgraph_pipeline(self, run_id: str) -> WorkflowRunState:
        detail = self._service.get_run(run_id)
        if detail is None:
            raise RuntimeError(f"Run not found: {run_id}")
        if detail.status not in {"completed", "completed_with_blockers", "interrupted", "failed"}:
            detail = await self._service.run_pipeline(run_id)
        if detail is None:
            raise RuntimeError(f"Run disappeared during pipeline execution: {run_id}")
        if detail.status == "failed":
            raise RuntimeError(f"Run failed during LangGraph activity: {run_id}")
        return _run_state(detail)

    @activity.defn(name=LOAD_PROJECTION_ACTIVITY)
    async def load_projection(self, run_id: str) -> WorkflowProjectionState:
        detail = self._service.get_run(run_id)
        if detail is None:
            raise RuntimeError(f"Run not found: {run_id}")
        projection = self._service.get_enterprise_projection(run_id)
        if projection is None:
            return WorkflowProjectionState(
                run_id=run_id,
                workspace_id=detail.workspace_id,
                project_id=detail.project_id,
            )
        return WorkflowProjectionState(
            run_id=run_id,
            workspace_id=projection.workspace_id,
            project_id=projection.project_id,
            report_version_id=projection.report_version.id,
            evidence_count=len(projection.evidence_records),
            claim_count=len(projection.claim_records),
        )


def _run_state(detail: RunDetail) -> WorkflowRunState:
    return WorkflowRunState(
        run_id=detail.id,
        idempotency_key=detail.idempotency_key,
        status=detail.status,
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        current_node=detail.current_node,
        report_chars=len(detail.report_md),
        qa_finding_count=len(detail.qa_findings),
    )


class ScheduledScanActivities:
    def __init__(self, service: RunService, store: EnterpriseStore) -> None:
        self._service = service
        self._store = store

    @activity.defn(name=LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY)
    async def list_targets(
        self,
        request: ScheduledScanWorkflowInput,
    ) -> list[ScheduledScanTarget]:
        projects = self._store.list_projects(workspace_id=request.workspace_id)
        project_ids = set(request.project_ids)
        if project_ids:
            projects = [item for item in projects if item.id in project_ids]
        return [
            self._target_from_project(project, request.dimensions)
            for project in projects[: max(1, request.max_projects)]
        ]

    @activity.defn(name=RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY)
    async def run_project_scan(
        self,
        scan_input: ScheduledScanProjectInput,
    ) -> ScheduledScanProjectResult:
        target = scan_input.target
        request = scan_input.request
        idempotency_key = _scheduled_scan_idempotency_key(
            request.schedule_id,
            target.project_id,
            scan_input.scan_started_at,
        )
        detail = await self._service.create_run(
            RunCreateRequest(
                workspace_id=target.workspace_id,
                project_id=target.project_id,
                idempotency_key=idempotency_key,
                topic=target.topic,
                competitors=target.competitors,
                dimensions=target.dimensions or request.dimensions,
                competitor_layer=target.competitor_layer,
                scenario_id=target.scenario_id,
                execution_mode=request.execution_mode,
            )
        )
        if detail.status not in {"completed", "completed_with_blockers", "interrupted", "failed"}:
            detail = await self._service.run_pipeline(detail.id)
        if detail is None:
            raise RuntimeError(f"Scheduled scan run disappeared: {idempotency_key}")
        projection = self._service.get_enterprise_projection(detail.id)
        return ScheduledScanProjectResult(
            project_id=target.project_id,
            run_id=detail.id,
            status=_scheduled_scan_project_status(detail.status),
            report_version_id=projection.report_version.id if projection else None,
            evidence_count=len(projection.evidence_records) if projection else 0,
            claim_count=len(projection.claim_records) if projection else 0,
            error="Run failed during scheduled scan." if detail.status == "failed" else "",
        )

    @activity.defn(name=RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY)
    async def record_notification(
        self,
        notification_input: ScheduledScanNotificationInput,
    ) -> ScheduledScanNotificationState:
        request = notification_input.request
        results = notification_input.results
        completed = sum(1 for item in results if item.status == "completed")
        failed = sum(1 for item in results if item.status == "failed")
        interrupted = sum(1 for item in results if item.status == "interrupted")
        notification = NotificationRecord(
            id=_scheduled_scan_notification_id(
                request.workspace_id,
                request.schedule_id,
                notification_input.scan_started_at,
            ),
            workspace_id=request.workspace_id,
            notification_type="scheduled_scan_summary",
            channel="in_app",
            severity="success" if failed == 0 else "warning",
            status="sent",
            title=f"Scheduled scan finished: {completed}/{len(results)} completed",
            body=(
                f"Schedule {request.schedule_id} scanned {len(results)} projects; "
                f"{failed} failed and {interrupted} interrupted."
            ),
            resource_type="scheduled_scan",
            resource_id=request.schedule_id,
            created_by=request.requested_by,
            sent_at=datetime.utcnow(),
            metadata={
                "scan_started_at": notification_input.scan_started_at,
                "completed_count": completed,
                "failed_count": failed,
                "interrupted_count": interrupted,
                "results": [asdict(item) for item in results],
            },
        )
        stored = self._store.upsert_notification(notification)
        return ScheduledScanNotificationState(notification_id=stored.id, status=stored.status)

    def _target_from_project(
        self,
        project: ProjectRecord,
        default_dimensions: list[str],
    ) -> ScheduledScanTarget:
        competitors = self._store.list_competitors(project_id=project.id)
        layer: Literal["L1", "L2", "L3"] | None = None
        if project.competitor_layer in {"L1", "L2", "L3"}:
            layer = cast(Literal["L1", "L2", "L3"], project.competitor_layer)
        return ScheduledScanTarget(
            project_id=project.id,
            workspace_id=project.workspace_id,
            topic=project.topic,
            competitors=[item.name for item in competitors],
            dimensions=default_dimensions or ["pricing", "feature", "persona"],
            competitor_layer=layer,
            scenario_id=project.scenario_id,
        )


def _scheduled_scan_idempotency_key(
    schedule_id: str,
    project_id: str,
    scan_started_at: str,
) -> str:
    return compute_workflow_id("scheduled", schedule_id, project_id, scan_started_at)


def _scheduled_scan_notification_id(
    workspace_id: str,
    schedule_id: str,
    scan_started_at: str,
) -> str:
    return compute_notification_id(workspace_id, schedule_id, scan_started_at)


def _scheduled_scan_project_status(status: str) -> str:
    if status == "interrupted":
        return "interrupted"
    if status == "failed":
        return "failed"
    return "completed"


class MonitorActivities:
    def __init__(self, service: RunService, store: EnterpriseStore) -> None:
        self._service = service
        self._store = store

    @activity.defn(name=RUN_MONITOR_CYCLE_ACTIVITY)
    async def run_cycle(
        self,
        cycle_input: MonitorCycleInput,
    ) -> MonitorCycleResult:
        request = cycle_input.request
        project = self._store.get_project(request.project_id)
        if project is None:
            raise RuntimeError(f"Project not found for monitor: {request.project_id}")
        if project.workspace_id != request.workspace_id:
            raise RuntimeError("Monitor project does not belong to the requested workspace.")
        previous = _latest_monitor_snapshot(self._store, request.project_id)
        competitors = self._store.list_competitors(project_id=project.id)
        layer: Literal["L1", "L2", "L3"] | None = None
        if project.competitor_layer in {"L1", "L2", "L3"}:
            layer = cast(Literal["L1", "L2", "L3"], project.competitor_layer)
        try:
            detail = await self._service.create_run(
                RunCreateRequest(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    idempotency_key=_monitor_cycle_idempotency_key(
                        request.monitor_id,
                        project.id,
                        cycle_input.cycle_index,
                        cycle_input.monitor_started_at,
                    ),
                    topic=project.topic,
                    competitors=[item.name for item in competitors],
                    dimensions=request.dimensions,
                    competitor_layer=layer,
                    scenario_id=project.scenario_id,
                    execution_mode=request.execution_mode,
                )
            )
            if detail.status not in {
                "completed",
                "completed_with_blockers",
                "interrupted",
                "failed",
            }:
                detail = await self._service.run_pipeline(detail.id)
            if detail is None:
                raise RuntimeError("Monitor run disappeared during execution.")
        except Exception as exc:  # noqa: BLE001 - monitor failures should become alerts.
            error = str(exc)[:1000]
            anomalies = _detect_monitor_anomalies(
                previous,
                None,
                status="failed",
                error=error,
                cycle_index=cycle_input.cycle_index,
            )
            return MonitorCycleResult(
                cycle_index=cycle_input.cycle_index,
                project_id=project.id,
                status="failed",
                previous=previous,
                current=None,
                anomalies=anomalies,
                error=error,
            )

        projection = self._service.get_enterprise_projection(detail.id)
        current = (
            _monitor_snapshot_from_report(projection.report_version)
            if projection is not None
            else _latest_monitor_snapshot(self._store, project.id)
        )
        status = _monitor_cycle_status(detail.status)
        anomalies = _detect_monitor_anomalies(
            previous,
            current,
            status=status,
            error="Run failed during monitor cycle." if detail.status == "failed" else "",
            cycle_index=cycle_input.cycle_index,
        )
        return MonitorCycleResult(
            cycle_index=cycle_input.cycle_index,
            project_id=project.id,
            status=status,
            previous=previous,
            current=current,
            run_id=detail.id,
            report_version_id=current.report_version_id if current else None,
            anomalies=anomalies,
            error="Run failed during monitor cycle." if detail.status == "failed" else "",
        )

    @activity.defn(name=RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY)
    async def record_anomaly_notification(
        self,
        notification_input: MonitorAnomalyNotificationInput,
    ) -> MonitorAnomalyNotificationState:
        request = notification_input.request
        result = notification_input.cycle_result
        severity = _notification_severity(result.anomalies)
        notification = NotificationRecord(
            id=_monitor_notification_id(
                request.workspace_id,
                request.project_id,
                request.monitor_id,
                result.cycle_index,
                notification_input.monitor_started_at,
            ),
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            notification_type="anomaly_alert",
            channel="in_app",
            severity=severity,
            status="sent",
            title=f"Monitor alert: {len(result.anomalies)} anomaly signals",
            body="; ".join(item.message for item in result.anomalies[:3]),
            resource_type="monitor",
            resource_id=request.monitor_id,
            created_by=request.requested_by,
            sent_at=datetime.utcnow(),
            metadata={
                "monitor_id": request.monitor_id,
                "cycle_index": result.cycle_index,
                "run_id": result.run_id,
                "report_version_id": result.report_version_id,
                "monitor_started_at": notification_input.monitor_started_at,
                "anomalies": [asdict(item) for item in result.anomalies],
            },
        )
        stored = self._store.upsert_notification(notification)
        return MonitorAnomalyNotificationState(
            notification_id=stored.id,
            status=stored.status,
            anomaly_count=len(result.anomalies),
        )


def _latest_monitor_snapshot(
    store: EnterpriseStore,
    project_id: str,
) -> MonitorSnapshot | None:
    versions = store.list_report_versions(project_id=project_id)
    if not versions:
        return None
    return _monitor_snapshot_from_report(versions[0])


def _monitor_snapshot_from_report(report: ReportVersionRecord) -> MonitorSnapshot:
    return MonitorSnapshot(
        project_id=report.project_id,
        report_version_id=report.id,
        run_id=report.run_id,
        evidence_count=len(report.evidence_ids),
        claim_count=len(report.claim_ids),
        report_chars=len(report.report_md),
        report_hash=hashlib.sha256(report.report_md.encode("utf-8")).hexdigest()[:32],
    )


def _detect_monitor_anomalies(
    previous: MonitorSnapshot | None,
    current: MonitorSnapshot | None,
    *,
    status: str,
    error: str = "",
    cycle_index: int = 0,
) -> list[MonitorAnomaly]:
    anomalies: list[MonitorAnomaly] = []
    if status == "failed":
        anomalies.append(
            _monitor_anomaly(
                cycle_index,
                "scan_failed",
                "critical",
                f"Monitor cycle failed: {error or 'unknown error'}",
            )
        )
    if current is None:
        anomalies.append(
            _monitor_anomaly(
                cycle_index,
                "report_missing",
                "critical",
                "Monitor cycle did not produce a report version.",
            )
        )
        return anomalies
    if previous is None:
        return anomalies
    if current.report_hash != previous.report_hash:
        anomalies.append(
            _monitor_anomaly(
                cycle_index,
                "report_changed",
                "info",
                "Monitor detected a changed report body.",
                previous=previous.report_version_id or "",
                current=current.report_version_id or "",
            )
        )
    if current.evidence_count < previous.evidence_count:
        anomalies.append(
            _monitor_anomaly(
                cycle_index,
                "evidence_drop",
                "warning",
                "Evidence count dropped compared with the previous monitor baseline.",
                previous=previous.evidence_count,
                current=current.evidence_count,
            )
        )
    if current.claim_count < previous.claim_count:
        anomalies.append(
            _monitor_anomaly(
                cycle_index,
                "claim_drop",
                "warning",
                "Claim count dropped compared with the previous monitor baseline.",
                previous=previous.claim_count,
                current=current.claim_count,
            )
        )
    return anomalies


def _monitor_anomaly(
    cycle_index: int,
    anomaly_type: MonitorAnomalyType,
    severity: MonitorAnomalySeverity,
    message: str,
    **metadata: str | int,
) -> MonitorAnomaly:
    return MonitorAnomaly(
        id=compute_monitor_anomaly_id(cycle_index, anomaly_type, message, metadata),
        severity=severity,
        anomaly_type=anomaly_type,
        message=message,
        metadata={"cycle_index": cycle_index, **metadata},
    )


def _monitor_cycle_idempotency_key(
    monitor_id: str,
    project_id: str,
    cycle_index: int,
    monitor_started_at: str,
) -> str:
    return compute_workflow_id(
        "monitor",
        monitor_id,
        project_id,
        cycle_index,
        monitor_started_at,
    )


def _monitor_notification_id(
    workspace_id: str,
    project_id: str,
    monitor_id: str,
    cycle_index: int,
    monitor_started_at: str,
) -> str:
    return compute_notification_id(
        workspace_id,
        project_id,
        monitor_id,
        cycle_index,
        monitor_started_at,
    )


def _notification_severity(anomalies: list[MonitorAnomaly]) -> str:
    severities = {item.severity for item in anomalies}
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "info"


def _monitor_cycle_status(status: str) -> str:
    if status == "interrupted":
        return "interrupted"
    if status == "failed":
        return "failed"
    return "completed"


class ReportApprovalActivities:
    def __init__(self, store: EnterpriseStore) -> None:
        self._store = store

    @activity.defn(name=REQUEST_REPORT_APPROVAL_ACTIVITY)
    async def request_report_approval(
        self,
        request: ReportApprovalWorkflowInput,
    ) -> ReportApprovalState:
        version = self._require_report_version(request.report_version_id)
        updated = version.model_copy(update={"status": "in_review"})
        return _approval_state(self._store.upsert_report_version(updated))

    @activity.defn(name=APPROVE_REPORT_VERSION_ACTIVITY)
    async def approve_report_version(
        self,
        decision: ReportApprovalDecisionInput,
    ) -> ReportApprovalState:
        version = self._require_report_version(decision.report_version_id)
        self._enforce_release_gate(version)
        updated = version.model_copy(update={"status": "approved"})
        return _approval_state(
            self._store.upsert_report_version(updated),
            approver_id=decision.approver_id,
            note=decision.note,
        )

    @activity.defn(name=REJECT_REPORT_VERSION_ACTIVITY)
    async def reject_report_version(
        self,
        decision: ReportApprovalDecisionInput,
    ) -> ReportApprovalState:
        version = self._require_report_version(decision.report_version_id)
        updated = version.model_copy(update={"status": "rejected"})
        return _approval_state(
            self._store.upsert_report_version(updated),
            approver_id=decision.approver_id,
            note=decision.note,
        )

    def _require_report_version(self, report_version_id: str) -> ReportVersionRecord:
        version = self._store.get_report_version(report_version_id)
        if version is None:
            raise RuntimeError(f"Report version not found: {report_version_id}")
        return version

    def _enforce_release_gate(self, version: ReportVersionRecord) -> None:
        gate = self._release_gate(version)
        if gate.allowed:
            return
        reasons = "; ".join(item.message for item in gate.issues[:3])
        raise RuntimeError(f"Report release gate blocked approval: {reasons}")

    def _release_gate(self, version: ReportVersionRecord) -> ReportReleaseGate:
        project = self._store.get_project(version.project_id)
        if project is None:
            raise RuntimeError(f"Project not found for report version: {version.project_id}")
        competitors, evidence, claims = report_release_gate_scope(
            version,
            project=project,
            store=self._store,
        )
        return evaluate_report_release_gate(
            project=project,
            report_version=version,
            competitors=competitors,
            evidence=evidence,
            claims=claims,
            source_registry=self._store.list_source_registry(workspace_id=project.workspace_id),
        )


def _approval_state(
    version: ReportVersionRecord,
    *,
    approver_id: str | None = None,
    note: str = "",
) -> ReportApprovalState:
    return ReportApprovalState(
        report_version_id=version.id,
        workspace_id=version.workspace_id,
        project_id=version.project_id,
        status=version.status,
        approver_id=approver_id,
        note=note,
    )
