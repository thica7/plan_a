from datetime import datetime

import pytest

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore, build_enterprise_projection
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import AnalysisPlan, QCIssue, RawSource, RedoScope
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
    record.detail.qa_findings.append(
        QCIssue(
            id="qc-survey-redaction",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="persona",
            target_competitor="Acme",
            field_path="raw_sources.persona",
            problem=(
                "Interview coordinator jane.buyer@example.com shared "
                "OPENROUTER_TEST_KEY_REDACTED as a private note."
            ),
            redo_scope=RedoScope(
                kind="collector",
                target_subagent="persona",
                target_competitor="Acme",
                rationale="Collect user research evidence.",
            ),
        )
    )

    await service._run_survey_interview_enrichment(record, ["persona"], ["Acme"])

    assert {source.source_type for source in record.detail.raw_sources} == {
        "survey_simulated",
        "interview_record",
    }
    survey_source = next(
        source for source in record.detail.raw_sources if source.source_type == "survey_simulated"
    )
    interview_source = next(
        source for source in record.detail.raw_sources if source.source_type == "interview_record"
    )
    assert survey_source.competitor == "Acme"
    assert survey_source.dimension == "persona"
    assert "target users" in survey_source.snippet
    assert "buyer personas" in survey_source.snippet
    assert survey_source.confidence == 0.58
    assert interview_source.competitor == "Acme"
    assert interview_source.dimension == "persona"
    assert "pain points" in interview_source.snippet
    assert interview_source.confidence == 0.62
    assert "jane.buyer@example.com" not in survey_source.snippet
    assert "OPENROUTER_TEST_KEY_REDACTED" not in survey_source.snippet
    assert "jane.buyer@example.com" not in interview_source.snippet
    assert "OPENROUTER_TEST_KEY_REDACTED" not in interview_source.snippet
    assert record.detail.agent_messages[-1].message_type == "survey_interview_evidence_collected"
    assert set(record.detail.agent_messages[-1].payload["source_ids"]) == {
        survey_source.id,
        interview_source.id,
    }
    span = next(span for span in record.detail.trace_spans if span.name == "survey_interview_agent")
    assert span.agent == "survey_interview"
    assert span.metadata["source_type"] == "survey_simulated"
    assert span.metadata["question_count"] == 2
    assert span.metadata["interview_count"] == 1
    assert span.metadata["redaction_count"] >= 2
    assert span.metadata["research_redacted"] is True
    assert span.metadata["research_redaction_email_count"] >= 1
    assert "jane.buyer@example.com" not in span.full_output
    assert "OPENROUTER_TEST_KEY_REDACTED" not in span.full_output
    assert "[redacted:email]" in span.full_output
    assert "[redacted:api_key]" in span.full_output


@pytest.mark.asyncio
async def test_survey_interview_enrichment_reuses_attached_survey_response() -> None:
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
    record.detail.raw_sources.append(
        RawSource(
            id="persona-survey-response-1",
            competitor="Acme",
            dimension="persona",
            source_type="survey_response",
            title="Acme buyer survey",
            snippet="Enterprise buyer survey says onboarding effort shapes adoption.",
            content_hash="surveyresponsehash",
            confidence=0.83,
        )
    )

    await service._run_survey_interview_enrichment(record, ["persona"], ["Acme"])

    assert [source.source_type for source in record.detail.raw_sources] == ["survey_response"]
    assert record.detail.agent_messages[-1].message_type == "survey_interview_evidence_collected"
    assert record.detail.agent_messages[-1].payload["source_ids"] == []
    assert record.detail.agent_messages[-1].payload["bundles"] == []


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
                title="Acme persona survey synthesis",
                snippet=(
                    "Simulated survey and interview research: target users, customers, "
                    "enterprise teams, and buyer personas evaluate persona by adoption risk."
                ),
                content_hash="surveyhash",
                confidence=0.58,
            ),
            RawSource(
                id="persona-interview-1",
                competitor="Acme",
                dimension="persona",
                source_type="interview_record",
                title="Acme persona interview synthesis",
                snippet=(
                    "Synthetic interview record: respondents discussed onboarding effort, "
                    "switching cost, and workflow fit."
                ),
                content_hash="interviewhash",
                confidence=0.62,
            ),
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

    assert {evidence.source_type for evidence in projection.evidence_records} == {
        "survey_simulated",
        "interview_record",
    }
    source_registry = store.list_source_registry(workspace_id=context.workspace_id)
    assert projection.report_version.quality_metadata["survey_source_ids"] == [
        "persona-survey-1"
    ]
    assert projection.report_version.quality_metadata["interview_source_ids"] == [
        "persona-interview-1"
    ]
    assert {source.domain for source in source_registry} == {
        "interview-record",
        "survey-simulated",
    }
    assert {source.trust_level for source in source_registry} == {"synthetic"}
