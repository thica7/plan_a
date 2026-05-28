import pytest

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.orchestrator.service import RunService
from packages.skills.registry import SkillRegistry
from packages.workflows import (
    CREATE_RUN_ACTIVITY,
    LOAD_PROJECTION_ACTIVITY,
    RUN_LANGGRAPH_ACTIVITY,
    CompetitiveIntelActivities,
    CompetitiveIntelWorkflow,
    CompetitiveIntelWorkflowInput,
    build_competitive_intel_worker_components,
)
from packages.workflows.competitive_intel import _workflow_result
from packages.workflows.models import WorkflowProjectionState, WorkflowRunState


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )


@pytest.mark.asyncio
async def test_temporal_activities_are_idempotent_around_existing_langgraph() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
    )
    activities = CompetitiveIntelActivities(service)
    request = CompetitiveIntelWorkflowInput(
        topic="AI coding assistant temporal test",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key="temporal-unit-001",
    )

    created = await activities.create_run(request)
    duplicate = await activities.create_run(request)
    completed = await activities.run_langgraph_pipeline(created.run_id)
    event_count = len(service.get_trace(created.run_id) or [])
    completed_again = await activities.run_langgraph_pipeline(created.run_id)
    projection = await activities.load_projection(created.run_id)

    assert duplicate.run_id == created.run_id
    assert duplicate.idempotency_key == "temporal-unit-001"
    assert completed.status == "completed"
    assert completed_again.status == "completed"
    assert len(service.get_trace(created.run_id) or []) == event_count
    assert projection.report_version_id is not None
    assert projection.evidence_count >= 1
    assert projection.claim_count >= 1


def test_temporal_worker_registers_only_the_outer_workflow_and_activities() -> None:
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=_settings())

    components = build_competitive_intel_worker_components(service)
    registered_activity_names = [
        getattr(activity_fn, "__temporal_activity_definition").name
        for activity_fn in components.activities
    ]

    assert components.workflows == [CompetitiveIntelWorkflow]
    assert len(components.activities) == 3
    assert registered_activity_names == components.activity_names
    assert components.activity_names == [
        CREATE_RUN_ACTIVITY,
        RUN_LANGGRAPH_ACTIVITY,
        LOAD_PROJECTION_ACTIVITY,
    ]


def test_competitive_intel_workflow_result_preserves_projection_metadata() -> None:
    result = _workflow_result(
        WorkflowRunState(
            run_id="run-1",
            idempotency_key="workflow-1",
            status="completed",
            workspace_id="workspace-1",
            project_id="project-1",
            report_chars=128,
            qa_finding_count=2,
        ),
        WorkflowProjectionState(
            run_id="run-1",
            workspace_id="workspace-1",
            project_id="project-1",
            report_version_id="report-version-1",
            evidence_count=3,
            claim_count=4,
        ),
    )

    assert result.status == "completed"
    assert result.report_version_id == "report-version-1"
    assert result.evidence_count == 3
    assert result.claim_count == 4
    assert result.report_chars == 128
    assert result.qa_finding_count == 2
