from __future__ import annotations

from pathlib import Path

import pytest

from packages.auth import EnterpriseUserContext
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore
from packages.runtime import (
    CreateMonitorJobCommand,
    PauseMonitorJobCommand,
    ResumeMonitorJobCommand,
    RuntimeCommandError,
    RuntimeCommandService,
    TriggerMonitorJobCommand,
)
from packages.schema.api_dto import MonitorStartResponse
from packages.schema.enterprise import MonitorJobCreateRequest, ProjectRecord

DEFAULT_WORKSPACE_ID = "default-workspace"


@pytest.mark.asyncio
async def test_runtime_commands_manage_monitor_job_lifecycle(tmp_path: Path) -> None:
    store = _store_with_project()
    workflow = _FakeWorkflowService()
    service = _runtime_service(store, workflow, tmp_path)
    actor = _actor()

    created = await service.create_monitor_job(
        CreateMonitorJobCommand(
            request=MonitorJobCreateRequest(
                workspace_id=DEFAULT_WORKSPACE_ID,
                project_id="project-monitor",
                monitor_id="weekly-monitor",
                name="Weekly CI watch",
                dimensions=["pricing", "feature"],
                schedule="weekly:monday:09:00",
                execution_mode="demo",
            )
        ),
        actor=actor,
    )
    job = created.payload

    assert created.command_type == "create_monitor_job"
    assert created.route == "enterprise"
    assert job.id == "weekly-monitor"
    assert job.status == "active"
    assert job.dimensions == ["pricing", "feature"]
    assert job.metadata["runtime_command_boundary"] is True

    paused = await service.pause_monitor_job(
        PauseMonitorJobCommand(monitor_id=job.id),
        actor=actor,
    )
    assert paused.payload.status == "paused"

    with pytest.raises(RuntimeCommandError) as blocked:
        await service.trigger_monitor_job(
            TriggerMonitorJobCommand(monitor_id=job.id),
            actor=actor,
        )
    assert blocked.value.status_code == 409

    resumed = await service.resume_monitor_job(
        ResumeMonitorJobCommand(monitor_id=job.id),
        actor=actor,
    )
    assert resumed.payload.status == "active"

    triggered = await service.trigger_monitor_job(
        TriggerMonitorJobCommand(monitor_id=job.id),
        actor=actor,
    )

    updated = store.get_monitor_job(job.id)
    assert triggered.command_type == "trigger_monitor_job"
    assert triggered.route == "temporal"
    assert triggered.status == "accepted"
    assert triggered.payload.workflow_id == "workflow-weekly-monitor"
    assert workflow.started[0].monitor_id == "weekly-monitor"
    assert workflow.started[0].dimensions == ["pricing", "feature"]
    assert updated is not None
    assert updated.last_status == "running"
    assert updated.last_workflow_id == "workflow-weekly-monitor"
    assert updated.last_started_at is not None
    assert {log.action for log in store.list_audit_logs(DEFAULT_WORKSPACE_ID)} >= {
        "monitor_job.upserted",
        "monitor_job.updated",
        "monitor_job.run_recorded",
    }


def test_store_records_monitor_job_run_completion() -> None:
    store = _store_with_project()
    job = store.upsert_monitor_job(
        _monitor_job(),
        actor_id="system-user",
    )

    updated = store.record_monitor_job_run(
        job.id,
        status="completed",
        workflow_id="workflow-1",
        run_id="run-1",
        report_version_id="report-v1",
        actor_id="system-user",
    )

    assert updated is not None
    assert updated.last_status == "completed"
    assert updated.last_workflow_id == "workflow-1"
    assert updated.last_run_id == "run-1"
    assert updated.last_report_version_id == "report-v1"
    assert updated.last_completed_at is not None


class _FakeWorkflowService:
    def __init__(self) -> None:
        self.started = []

    async def start_monitor(self, request):
        self.started.append(request)
        return MonitorStartResponse(
            workflow_id=f"workflow-{request.monitor_id}",
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            monitor_id=request.monitor_id,
            task_queue="competitive-intel",
            status="started",
        )


def _store_with_project() -> EnterpriseMemoryStore:
    store = EnterpriseMemoryStore()
    store.upsert_project(
        ProjectRecord(
            id="project-monitor",
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Enterprise LLM watch",
            topic="Enterprise LLM watch",
            topic_normalized="enterprise-llm-watch",
            created_by="system-user",
        )
    )
    return store


def _monitor_job():
    from packages.schema.enterprise import MonitorJobRecord

    return MonitorJobRecord(
        id="weekly-monitor",
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id="project-monitor",
        name="Weekly CI watch",
        dimensions=["pricing"],
    )


def _runtime_service(
    store: EnterpriseMemoryStore,
    workflow: _FakeWorkflowService,
    tmp_path: Path,
) -> RuntimeCommandService:
    return RuntimeCommandService(
        settings=_settings(),
        run_service=object(),
        workflow_service=workflow,
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore(tmp_path / "memory.sqlite"),
    )


def _actor() -> EnterpriseUserContext:
    return EnterpriseUserContext(
        user_id="system-user",
        role="owner",
        workspace_id=DEFAULT_WORKSPACE_ID,
    )


def _settings(**overrides: object) -> Settings:
    values = {
        "demo_mode": True,
        "ark_api_key": None,
        "ark_model": None,
        "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "llm_timeout_seconds": 10,
        "llm_temperature": 0.2,
        "enterprise_store_backend": "memory",
        "enterprise_database_url": None,
    }
    values.update(overrides)
    return Settings(**values)
