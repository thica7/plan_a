from datetime import datetime

import pytest

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore, build_enterprise_projection
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import AnalysisPlan, RawSource
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_survey_interview_enrichment_adds_typed_research_evidence() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant user adoption comparison",
            competitors=["Acme"],
            dimensions=["persona"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]

    await service._run_survey_interview_enrichment(record, ["persona"], ["Acme"])

    [source] = record.detail.raw_sources
    assert source.source_type == "survey_simulated"
    assert source.competitor == "Acme"
    assert source.dimension == "persona"
    assert "target users" in source.snippet
    assert "buyer personas" in source.snippet
    assert source.confidence == 0.58
    assert record.detail.agent_messages[-1].message_type == "survey_interview_evidence_collected"
    assert record.detail.agent_messages[-1].payload["source_ids"] == [source.id]
    span = next(span for span in record.detail.trace_spans if span.name == "survey_interview_agent")
    assert span.agent == "survey_interview"
    assert span.metadata["source_type"] == "survey_simulated"
    assert span.metadata["question_count"] == 2
    assert span.metadata["interview_count"] == 1


def test_survey_evidence_projects_as_synthetic_enterprise_source() -> None:
    store = EnterpriseMemoryStore()
    detail = RunDetail(
        id="run-survey-1",
        topic="AI coding assistant user adoption comparison",
        status="completed",
        execution_mode="demo",
        created_at=datetime(2026, 6, 2, 8, 0, 0),
        updated_at=datetime(2026, 6, 2, 8, 5, 0),
        plan=AnalysisPlan(
            topic="AI coding assistant user adoption comparison",
            competitors=["Acme"],
            dimensions=["persona"],
            competitor_layer="L2",
            scenario_id="l2_workflow_overlap",
        ),
        raw_sources=[
            RawSource(
                id="persona-survey-1",
                competitor="Acme",
                dimension="persona",
                source_type="survey_simulated",
                title="Acme persona survey/interview synthesis",
                snippet=(
                    "Simulated survey and interview research: target users, customers, "
                    "enterprise teams, and buyer personas evaluate persona by adoption risk."
                ),
                content_hash="surveyhash",
                confidence=0.58,
            )
        ],
    )
    context = store.start_run(detail)
    projection = build_enterprise_projection(
        detail,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        competitor_layer="L2",
        competitor_id_map=context.competitor_id_map,
    )
    store.save_projection(projection)

    [evidence] = projection.evidence_records
    [source_registry] = store.list_source_registry(workspace_id=context.workspace_id)
    assert evidence.source_type == "survey_simulated"
    assert projection.report_version.quality_metadata["survey_source_ids"] == [
        "persona-survey-1"
    ]
    assert source_registry.domain == "survey-simulated"
    assert source_registry.trust_level == "synthetic"
