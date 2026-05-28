from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from app.deps import get_app_settings, get_run_service
from packages.orchestrator.service import RunService
from packages.workflows.activities import CompetitiveIntelActivities
from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.models import (
    CREATE_RUN_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
)


@dataclass(frozen=True)
class TemporalWorkerComponents:
    workflows: list[type]
    activities: list[Callable[..., Any]]
    activity_names: list[str]


def build_competitive_intel_worker_components(
    service: RunService,
) -> TemporalWorkerComponents:
    activities = CompetitiveIntelActivities(service)
    return TemporalWorkerComponents(
        workflows=[CompetitiveIntelWorkflow],
        activities=[
            activities.create_run,
            activities.run_langgraph_pipeline,
            activities.load_projection,
        ],
        activity_names=[
            CREATE_RUN_ACTIVITY,
            RUN_LANGGRAPH_ACTIVITY,
            LOAD_PROJECTION_ACTIVITY,
        ],
    )


async def run_worker() -> None:
    settings = get_app_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    components = build_competitive_intel_worker_components(get_run_service())
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
