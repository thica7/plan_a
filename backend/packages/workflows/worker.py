from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from app.deps import get_app_settings, get_enterprise_store, get_run_service
from packages.enterprise import EnterpriseStore
from packages.orchestrator.service import RunService
from packages.workflows.activities import (
    CompetitiveIntelActivities,
    ReportApprovalActivities,
    ScheduledScanActivities,
)
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.models import (
    APPROVE_REPORT_VERSION_ACTIVITY,
    CREATE_RUN_ACTIVITY,
    LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
    REJECT_REPORT_VERSION_ACTIVITY,
    REQUEST_REPORT_APPROVAL_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
)
from packages.workflows.report_approval import ReportApprovalWorkflow
from packages.workflows.scheduled_scan import ScheduledScanWorkflow


@dataclass(frozen=True)
class TemporalWorkerComponents:
    workflows: list[type]
    activities: list[Callable[..., Any]]
    activity_names: list[str]


def build_competitive_intel_worker_components(
    service: RunService,
    *,
    enterprise_store: EnterpriseStore | None = None,
) -> TemporalWorkerComponents:
    competitive = CompetitiveIntelActivities(service)
    workflows: list[type] = [CompetitiveIntelWorkflow]
    activity_fns: list[Callable[..., Any]] = [
        competitive.create_run,
        competitive.run_langgraph_pipeline,
        competitive.load_projection,
    ]
    activity_names = [
        CREATE_RUN_ACTIVITY,
        RUN_LANGGRAPH_ACTIVITY,
        LOAD_PROJECTION_ACTIVITY,
    ]
    if enterprise_store is not None:
        approval = ReportApprovalActivities(enterprise_store)
        scheduled_scan = ScheduledScanActivities(service, enterprise_store)
        workflows.extend([ReportApprovalWorkflow, ScheduledScanWorkflow])
        activity_fns.extend(
            [
                approval.request_report_approval,
                approval.approve_report_version,
                approval.reject_report_version,
                scheduled_scan.list_targets,
                scheduled_scan.run_project_scan,
                scheduled_scan.record_notification,
            ]
        )
        activity_names.extend(
            [
                REQUEST_REPORT_APPROVAL_ACTIVITY,
                APPROVE_REPORT_VERSION_ACTIVITY,
                REJECT_REPORT_VERSION_ACTIVITY,
                LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY,
                RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY,
                RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY,
            ]
        )
    return TemporalWorkerComponents(
        workflows=workflows,
        activities=activity_fns,
        activity_names=activity_names,
    )


async def run_worker() -> None:
    settings = get_app_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    components = build_competitive_intel_worker_components(
        get_run_service(),
        enterprise_store=get_enterprise_store(),
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=components.workflows,
        activities=components.activities,
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
