import asyncio
import time
from datetime import datetime

import pytest

from packages.business_intel.homepage import HomepageVerification
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore
from packages.observability import build_decision_replay
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest, RunDetail
from packages.schema.enterprise import ModelRouteCandidate, ModelRouteDecision, UserFeedbackRecord
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorKB,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    RevisionRecord,
)
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.fetch_page import FetchPageResult


def _test_graph_checkpointer() -> GraphCheckpointer:
    return GraphCheckpointer.in_memory()


def _now() -> datetime:
    return datetime.utcnow()


def _collector_issue(issue_id: str, subagent: str, competitor: str) -> QCIssue:
    return QCIssue(
        id=issue_id,
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        target_subagent=subagent,
        target_competitor=competitor,
        field_path=f"raw_sources[{issue_id}]",
        problem=f"{competitor} needs verified {subagent} evidence.",
        redo_scope=RedoScope(
            kind="collector",
            target_subagent=subagent,
            target_competitor=competitor,
            rationale=f"Collect verified {subagent} evidence for {competitor}.",
        ),
    )


@pytest.mark.asyncio
async def test_real_mode_requires_ark_credentials() -> None:
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=settings)

    with pytest.raises(ValueError, match="provider.no_real_provider"):
        await service.create_run(
            RunCreateRequest(
                topic="AI research assistant competitive analysis",
                competitors=["Perplexity"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )


@pytest.mark.asyncio
async def test_real_mode_accepts_backup_provider_when_model_policy_allows() -> None:
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        backup_llm_api_key="backup-key",
        backup_llm_model="backup-model",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=settings)

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI research assistant competitive analysis",
            competitors=["Perplexity"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )

    assert detail.execution_mode == "real"


@pytest.mark.asyncio
async def test_real_mode_blocks_disabled_redaction_policy() -> None:
    settings = Settings(
        demo_mode=True,
        ark_api_key="key",
        ark_model="model",
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
        compliance_redaction_enabled=False,
    )
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=settings)

    with pytest.raises(ValueError, match="compliance.redaction_disabled"):
        await service.create_run(
            RunCreateRequest(
                topic="AI research assistant competitive analysis",
                competitors=["Perplexity"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )


@pytest.mark.asyncio
async def test_auto_mode_falls_back_to_demo_when_model_policy_blocks_real() -> None:
    settings = Settings(
        demo_mode=False,
        ark_api_key="key",
        ark_model="model",
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
        compliance_redaction_enabled=False,
    )
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=settings)

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI research assistant competitive analysis",
            competitors=["Perplexity"],
            dimensions=["pricing"],
            execution_mode="auto",
        )
    )

    assert detail.execution_mode == "demo"


def test_llm_route_metadata_explains_selected_fallback_and_blockers() -> None:
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
    )

    class FakeLLM:
        def last_route_decision(self) -> ModelRouteDecision:
            return ModelRouteDecision(
                status="fallback",
                selected=ModelRouteCandidate(
                    provider_kind="backup",
                    provider_name="openrouter",
                    model_name="deepseek/deepseek-v4-pro",
                    configured=True,
                    quality_score=82,
                    cost_score=78,
                    compliance_score=100,
                ),
                fallback=ModelRouteCandidate(
                    provider_kind="demo",
                    provider_name="deterministic",
                    model_name="demo-fixture",
                    configured=True,
                    quality_score=58,
                    cost_score=100,
                    compliance_score=100,
                ),
                candidates=[],
                blocked_reasons=["Primary provider credentials are missing."],
            )

    service._llm = FakeLLM()  # type: ignore[assignment]

    metadata = service._llm_usage_metadata(None)

    assert metadata["model_route_status"] == "fallback"
    assert metadata["model_route_selected"] == "backup"
    assert metadata["model_route_selected_provider"] == "openrouter"
    assert metadata["model_route_selected_model"] == "deepseek/deepseek-v4-pro"
    assert metadata["model_route_fallback"] == "demo"
    assert metadata["model_route_fallback_model"] == "demo-fixture"
    assert "Primary provider credentials" in metadata["model_route_blocked_reasons"]


@pytest.mark.asyncio
async def test_run_request_can_enable_hitl_per_run() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            hitl_enabled=False,
        ),
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="demo",
            hitl_enabled=True,
        )
    )

    assert detail.hitl_enabled is True


@pytest.mark.asyncio
async def test_topic_only_run_discovers_competitors_in_planner() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "scoping agent" in system:
            return {
                "candidates": [
                    {"name": "Alpha", "rationale": "Direct AI sales product.", "confidence": 0.8},
                    {"name": "Beta", "rationale": "Direct replacement.", "confidence": 0.7},
                ],
                "selected_competitors": ["Alpha", "Beta", "Alpha"],
                "rationale": "Direct products.",
            }
        return {"complexity": "medium", "homepage_hints": {"Alpha": "https://alpha.example"}}

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI sales assistant comparison",
            competitors=[],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_planner_step(record)

    assert record.detail.plan.competitors == ["Alpha", "Beta"]
    assert record.detail.plan.homepage_hints["Alpha"] == "https://alpha.example"
    assert record.detail.competitor_discovery is not None
    assert record.detail.competitor_discovery.rationale == "Direct products."
    assert record.detail.competitor_discovery.candidates[0].selected is True
    assert record.detail.competitor_discovery.candidates[0].confidence == 0.8
    assert record.detail.metrics.llm_calls == 2
    llm_span_names = [span.name for span in record.detail.trace_spans if span.kind == "llm"]
    assert llm_span_names == ["competitor_discovery", "planner_scope"]
    assert record.detail.agent_messages[-1].trace_span_ids
    assert record.detail.trace_spans[0].agent == "planner"


@pytest.mark.asyncio
async def test_create_run_builds_adaptive_task_decomposition() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            collector_react_max_turns=3,
            analyst_react_max_turns=3,
        ),
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="Cursor buyer research",
            competitors=["Cursor"],
            dimensions=["pricing", "persona"],
            execution_mode="real",
        )
    )

    tasks = detail.plan.task_decomposition
    pricing_collector = next(
        task
        for task in tasks
        if task.stage == "collector" and task.dimension == "pricing"
    )
    persona_collector = next(
        task
        for task in tasks
        if task.stage == "collector" and task.dimension == "persona"
    )
    persona_survey = next(
        task
        for task in tasks
        if task.stage == "survey_interview" and task.dimension == "persona"
    )

    assert {task.stage for task in tasks} >= {"collector", "analyst", "survey_interview"}
    assert pricing_collector.priority == "high"
    assert pricing_collector.max_turns == 3
    assert persona_collector.priority == "medium"
    assert persona_collector.max_turns == 2
    assert persona_survey.depends_on == [persona_collector.id]


@pytest.mark.asyncio
async def test_survey_interview_enrichment_emits_research_evidence_payload() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            collector_react_max_turns=3,
            analyst_react_max_turns=3,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Cursor persona adoption research",
            competitors=["Cursor"],
            dimensions=["persona"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._run_survey_interview_enrichment(record, ["persona"], ["Cursor"])

    source_types = {source.source_type for source in record.detail.raw_sources}
    assert source_types == {"interview_record"}
    assert len(record.detail.raw_sources) == 1
    assert "Simulated survey and interview research" in record.detail.raw_sources[0].snippet
    assert record.detail.competitor_knowledge["Cursor"].user_personas.summary_claims
    completed = next(
        event
        for event in service.get_trace(detail.id) or []
        if event.type == "node_completed" and event.agent == "survey_interview"
    )
    assert completed.payload["source_types"] == ["interview_record"]
    assert completed.payload["bundle_count"] == 1
    assert completed.payload["question_count"] == 2
    assert completed.payload["response_count"] == 1
    assert completed.payload["interview_count"] >= 1
    assert completed.payload["redaction_count"] >= 0

    replay = build_decision_replay(record.detail, service.get_trace(detail.id) or [])
    replay_event = next(
        event
        for event in replay.events
        if event.event_type == "agent.finished" and event.agent == "survey_interview"
    )
    assert replay_event.payload["source_types"] == ["interview_record"]
    assert replay_event.payload["question_count"] == 2
    assert replay_event.payload["response_count"] == 1
    assert replay_event.payload["interview_count"] >= 1


@pytest.mark.asyncio
async def test_planner_complexity_refreshes_task_decomposition_budget() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            collector_react_max_turns=3,
            analyst_react_max_turns=3,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        return {"complexity": "low", "homepage_hints": {"Cursor": "https://cursor.com"}}

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Cursor feature check",
            competitors=["Cursor"],
            dimensions=["feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_planner_step(record)

    task = record.detail.plan.task_decomposition[0]
    message = record.detail.agent_messages[-1]
    plan_payload = message.payload["plan"]

    assert record.detail.plan.complexity == "low"
    assert task.stage == "collector"
    assert task.max_turns == 1
    assert service._collector_task_max_turns(record.detail.plan, "feature", "Cursor") == 1
    assert service._analyst_task_max_turns(record.detail.plan, "feature", "Cursor") == 1
    assert plan_payload["task_decomposition"][0]["max_turns"] == 1


@pytest.mark.asyncio
async def test_memory_policy_drives_collector_and_strict_source_qa() -> None:
    memory = PreferenceMemoryStore.in_memory()
    feedback = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id="default-workspace",
            project_id="project-memory-policy",
            user_id="analyst-1",
            feedback_type="preference",
            target_type="project",
            target_id="project-memory-policy",
            message=(
                "Prefer official verified sources before search-only leads. "
                "Apply QA policy and treat repeated blockers as a failure pattern; "
                "enforce explicit evidence before publish."
            ),
        )
    )
    for candidate in memory.extract_candidates(feedback, auto_confirm=True):
        memory.upsert_candidate(candidate)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        preference_memory=memory,
    )
    official_calls: list[tuple[str, str]] = []

    async def fake_official_sources(  # noqa: ANN001
        record,
        detail,
        dimension,
        competitor,
        context,
    ) -> list[RawSource]:
        official_calls.append((dimension, competitor))
        return [
            RawSource(
                id="source-feature-official",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="Cursor official feature docs",
                url="https://cursor.com/features",
                snippet="Cursor documents feature evidence.",
                content_hash="hash-feature-official",
                confidence=0.93,
            )
        ]

    service._collect_official_sources = fake_official_sources  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant feature review",
            competitors=["Cursor"],
            dimensions=["feature"],
            execution_mode="real",
            project_id="project-memory-policy",
        )
    )
    record = service._runs[detail.id]

    await service._real_collector_branch_step(record, "feature", "Cursor")
    collector_done = next(
        event
        for event in service.get_trace(detail.id) or []
        if event.type == "node_completed" and event.agent == "collector"
    )
    record.detail.raw_sources = [
        RawSource(
            id="source-feature-search",
            competitor="Cursor",
            dimension="feature",
            source_type="web_search_result",
            title="Cursor feature search lead",
            url="https://example.com/cursor-feature",
            snippet="Search-only feature evidence.",
            content_hash="hash-feature-search",
            confidence=0.62,
        )
    ]
    issues = service._build_collect_qa_issues(record.detail)

    assert service._memory_prefers_official_sources(record.detail.plan) is True
    assert service._memory_enforces_strict_source_qa(record.detail.plan) is True
    assert official_calls == [("feature", "Cursor")]
    assert collector_done.payload["collect"]["memory_official_first"] is True
    assert collector_done.payload["source_ids"] == ["source-feature-official"]
    assert issues[0].severity == "blocker"
    assert "MemoryAgent QA policy" in issues[0].problem


def test_feature_collection_uses_known_official_source_registry() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="AI coding",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding",
            competitors=["Cursor", "GitHub Copilot", "Claude Code", "Windsurf"],
            dimensions=["feature"],
        ),
    )

    cursor = service._official_source_candidates(detail, "Cursor", "feature")
    copilot = service._official_source_candidates(detail, "GitHub Copilot", "feature")
    claude = service._official_source_candidates(detail, "Claude Code", "feature")
    windsurf = service._official_source_candidates(detail, "Windsurf", "feature")

    assert service._should_collect_official_first("feature") is True
    assert cursor[0].url == "https://www.cursor.com/features"
    assert copilot[0].url == "https://docs.github.com/en/copilot/get-started/features"
    assert claude[0].url == "https://www.anthropic.com/product/claude-code"
    assert windsurf[0].url == "https://windsurf.com/features"


@pytest.mark.asyncio
async def test_topic_only_planner_filters_phantom_discovery_with_homepage_gate() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "scoping agent" in system:
            return {
                "candidates": [
                    {"name": "Cursor", "rationale": "Direct coding assistant.", "confidence": 0.9},
                    {
                        "name": "FAKE_PRODUCT_NOT_EXISTS",
                        "rationale": "Hallucinated competitor.",
                        "confidence": 0.6,
                    },
                    {
                        "name": "Windsurf",
                        "rationale": "Direct coding assistant.",
                        "confidence": 0.8,
                    },
                ],
                "selected_competitors": ["Cursor", "FAKE_PRODUCT_NOT_EXISTS", "Windsurf"],
                "rationale": "Mixed candidate set.",
            }
        return {
            "complexity": "medium",
            "homepage_hints": {
                "Cursor": "https://cursor.com",
                "FAKE_PRODUCT_NOT_EXISTS": "https://fake.invalid",
            },
        }

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=[],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_planner_step(record)

    assert record.detail.plan.competitors == ["Cursor", "Windsurf"]
    assert record.detail.plan.homepage_verified == {"Cursor": True, "Windsurf": True}
    assert record.detail.plan.homepage_hints["Cursor"].startswith("https://")
    assert "FAKE_PRODUCT_NOT_EXISTS" not in record.detail.plan.homepage_hints
    assert record.detail.competitor_discovery is not None
    candidates = {
        candidate.name: candidate.selected
        for candidate in record.detail.competitor_discovery.candidates
    }
    assert candidates["Cursor"] is True
    assert candidates["Windsurf"] is True
    assert candidates["FAKE_PRODUCT_NOT_EXISTS"] is False


@pytest.mark.asyncio
async def test_create_run_filters_phantom_competitors_with_homepage_gate() -> None:
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
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=["Cursor", "FAKE_PRODUCT_NOT_EXISTS", "Windsurf"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )

    assert detail.plan.competitors == ["Cursor", "Windsurf"]
    assert detail.plan.homepage_verified == {"Cursor": True, "Windsurf": True}
    assert "FAKE_PRODUCT_NOT_EXISTS" not in detail.plan.homepage_hints


@pytest.mark.asyncio
async def test_l3_market_dimension_survives_run_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _verified_homepages(competitors: list[str]) -> dict[str, HomepageVerification]:
        return {
            competitor: HomepageVerification(
                competitor=competitor,
                homepage_url=f"https://{competitor.casefold()}.example.com",
                verified=True,
                reason="test_verified",
            )
            for competitor in competitors
        }

    monkeypatch.setattr(
        "packages.orchestrator.service.verify_homepages",
        _verified_homepages,
    )
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
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant market landscape",
            competitors=["Cursor", "Copilot", "Windsurf", "Tabnine"],
            dimensions=["market", "persona"],
            competitor_layer="L3",
            scenario_id="l3_market_landscape",
            execution_mode="demo",
        )
    )

    assert detail.plan.competitor_layer == "L3"
    assert detail.plan.scenario_id == "l3_market_landscape"
    assert "market" in detail.plan.dimensions
    assert any(
        task.stage == "collector" and task.dimension == "market"
        for task in detail.plan.task_decomposition
    )
    assert any(
        task.stage == "analyst" and task.dimension == "market"
        for task in detail.plan.task_decomposition
    )


@pytest.mark.asyncio
async def test_create_run_uses_scenario_seed_competitors_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _verified_homepages(competitors: list[str]) -> dict[str, HomepageVerification]:
        return {
            competitor: HomepageVerification(
                competitor=competitor,
                homepage_url=f"https://{competitor.casefold().replace(' ', '-')}.example.com",
                verified=True,
                reason="test_verified",
            )
            for competitor in competitors
        }

    monkeypatch.setattr(
        "packages.orchestrator.service.verify_homepages",
        _verified_homepages,
    )
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
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant market landscape",
            competitors=[],
            dimensions=["market", "persona"],
            competitor_layer="L3",
            scenario_id="l3_market_landscape",
            execution_mode="demo",
        )
    )

    assert detail.plan.competitors == [
        "Cursor",
        "GitHub Copilot",
        "Windsurf",
        "Tabnine",
        "Codeium",
    ]
    assert detail.plan.competitor_layer == "L3"
    assert "market" in detail.plan.dimensions
    assert any(
        task.stage == "collector" and task.dimension == "market"
        for task in detail.plan.task_decomposition
    )


@pytest.mark.asyncio
async def test_create_run_merges_requested_scenario_required_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _verified_homepages(competitors: list[str]) -> dict[str, HomepageVerification]:
        return {
            competitor: HomepageVerification(
                competitor=competitor,
                homepage_url=f"https://{competitor.casefold()}.example.com",
                verified=True,
                reason="test_verified",
            )
            for competitor in competitors
        }

    monkeypatch.setattr(
        "packages.orchestrator.service.verify_homepages",
        _verified_homepages,
    )
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
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant market landscape",
            competitors=["Cursor", "Copilot", "Windsurf", "Tabnine"],
            dimensions=["pricing"],
            competitor_layer="L3",
            scenario_id="l3_market_landscape",
            execution_mode="demo",
        )
    )

    assert detail.plan.dimensions == ["feature", "persona", "market", "pricing"]
    assert detail.plan.scenario_recommended_dimensions[:4] == [
        "pricing",
        "feature",
        "persona",
        "market",
    ]
    task_dimensions = {task.dimension for task in detail.plan.task_decomposition}
    assert {"feature", "persona", "market", "pricing"} <= task_dimensions


@pytest.mark.asyncio
async def test_create_run_generates_dynamic_scenario_from_product_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _verified_homepages(competitors: list[str]) -> dict[str, HomepageVerification]:
        return {
            competitor: HomepageVerification(
                competitor=competitor,
                homepage_url=f"https://{competitor.casefold()}.example.com",
                verified=True,
                reason="test_verified",
            )
            for competitor in competitors
        }

    monkeypatch.setattr(
        "packages.orchestrator.service.verify_homepages",
        _verified_homepages,
    )
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
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="Enterprise AI search workflow",
            competitors=["Glean", "Coveo", "Elastic"],
            dimensions=["security"],
            competitor_layer="L2",
            scenario_id="dynamic_adaptive",
            execution_mode="demo",
        )
    )

    assert detail.plan.scenario_id.startswith("dynamic_l2_enterprise_ai_search_workflow")
    assert detail.plan.competitor_layer == "L2"
    assert detail.plan.dimensions == ["security"]
    assert detail.plan.scenario_recommended_dimensions[:4] == [
        "security",
        "pricing",
        "feature",
        "persona",
    ]
    assert any(task.dimension == "security" for task in detail.plan.task_decomposition)


@pytest.mark.asyncio
async def test_trace_spans_redact_sensitive_text_before_storage() -> None:
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
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI research assistant competitive analysis",
            competitors=["Perplexity"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]

    service._append_trace_span(
        record,
        kind="tool",
        agent="collector",
        subagent="pricing",
        name="compliance_probe",
        status="ok",
        started=time.perf_counter(),
        input_text=(
            "contact alice@example.com with "
            "OPENROUTER_TEST_KEY_REDACTED"
        ),
        output_text="Bearer abcdef1234567890 accepted",
    )

    span = record.detail.trace_spans[-1]
    tool_message = record.detail.tool_call_messages[-1]
    assert "alice@example.com" not in span.full_input
    assert "sk-or-v1-" not in span.full_input
    assert "abcdef1234567890" not in span.full_output
    assert "[redacted:email]" in span.full_input
    assert "[redacted:api_key]" in span.full_input
    assert "[redacted:bearer_token]" in span.full_output
    assert span.metadata["pii_redacted"] is True
    assert span.trace_id
    assert span.otel_span_id
    assert span.traceparent == f"00-{span.trace_id}-{span.otel_span_id}-01"
    assert record.detail.metrics.compliance_redaction_count == 3
    assert tool_message.arguments["input"] == span.full_input


@pytest.mark.asyncio
async def test_trace_span_compliance_policy_can_disable_redaction() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            compliance_redaction_enabled=False,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI research assistant competitive analysis",
            competitors=["Perplexity"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]

    service._append_trace_span(
        record,
        kind="tool",
        agent="collector",
        subagent="pricing",
        name="compliance_disabled_probe",
        status="ok",
        started=time.perf_counter(),
        input_text="contact alice@example.com",
        output_text="ok",
    )

    span = record.detail.trace_spans[-1]
    assert "alice@example.com" in span.full_input
    assert span.metadata["compliance_redaction_enabled"] is False
    assert record.detail.metrics.compliance_redaction_count == 0


def test_qa_marks_unverified_source_without_missing_false_positive() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="llm_public_knowledge",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="Pricing summary",
                content_hash="abc",
                confidence=0.7,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["Pricing summary"]},
                sources=["pricing-1"],
                confidence=0.7,
            )
        },
    )

    issues = service._build_qa_issues(detail)

    assert [issue.id for issue in issues] == ["unverified-pricing-a-pricing-1"]
    assert issues[0].severity == "warn"
    assert issues[0].redo_scope.target_competitor == "A"


def test_qa_marks_missing_dimension_as_blocker() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )

    issues = service._build_qa_issues(detail)

    assert [issue.id for issue in issues] == ["missing-pricing"]
    assert issues[0].severity == "blocker"
    assert issues[0].redo_scope.kind == "collector"


def test_final_qa_sync_replaces_stale_clean_report_claim() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        report_md=(
            "# Report\n\n"
            "**Unresolved QA Findings:** None flagged; all source claims meet minimum "
            "confidence thresholds."
        ),
        qa_findings=[
            QCIssue(
                id="missing-pricing",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                field_path="raw_sources[pricing]",
                problem="No evidence sources were collected for pricing.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="pricing",
                    rationale="Missing pricing evidence.",
                ),
            )
        ],
    )

    service._sync_report_with_final_qa(detail)

    assert "None flagged" not in detail.report_md
    assert "Final QA Gate Status" in detail.report_md
    assert "Status: blocked for review" in detail.report_md
    assert "No evidence sources were collected for pricing." in detail.report_md


def test_final_qa_sync_adds_rag_gap_fill_for_collector_warnings() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        report_md="# Report\n\nPricing evidence needs follow-up. [source:pricing-1]",
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="web_search_result",
                title="A pricing search lead",
                url="https://example.com/pricing",
                snippet="A pricing search result.",
                content_hash="abc",
                confidence=0.62,
            )
        ],
        qa_findings=[
            QCIssue(
                id="unverified-pricing-a",
                severity="warn",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                target_competitor="A",
                field_path="raw_sources[pricing]",
                problem="Pricing source needs verified webpage evidence.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="pricing",
                    target_competitor="A",
                    rationale="Verify pricing source.",
                ),
            )
        ],
    )

    service._sync_report_with_final_qa(detail)

    assert "## RAG Gap Fill" in detail.report_md
    assert "Suggested retrieval query: A pricing Pricing source needs verified" in detail.report_md
    assert "## Final QA Gate Status" in detail.report_md


def test_qa_marks_phantom_citation_as_writer_only_blocker() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        report_md="The report cites a non-existent source [source:pricing-404].",
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A has a $10 plan."]},
                sources=["pricing-1"],
                confidence=0.8,
            )
        },
    )

    issues = service._build_qa_issues(detail)

    phantom = [issue for issue in issues if issue.id == "phantom-citation-pricing-404"]
    assert len(phantom) == 1
    assert phantom[0].severity == "blocker"
    assert phantom[0].redo_scope.kind == "writer_only"


def test_qa_surfaces_latest_reflector_findings() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing", "feature"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            ),
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A feature",
                url="https://example.com/features",
                snippet="A has features.",
                content_hash="def",
                confidence=0.8,
            ),
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A costs $10."], "feature": ["A has features."]},
                sources=["pricing-1", "feature-1"],
                confidence=0.8,
            )
        },
        report_md="A has pricing and feature notes [source:pricing-1] [source:feature-1].",
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["pricing", "feature"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A costs $10. [source:pricing-1]",
                    source_ids=["pricing-1"],
                    confidence=0.8,
                ),
                ComparisonCell(
                    competitor="A",
                    dimension="feature",
                    value="A has features. [source:feature-1]",
                    source_ids=["feature-1"],
                    confidence=0.8,
                ),
            ],
            winner_by_dimension={"pricing": "A", "feature": "A"},
            summary=[],
        ),
        reflections=[
            ReflectionRecord(
                iteration=1,
                coverage_gaps=["Feature dimension needs more independent sources."],
                confidence_outliers=["Pricing confidence looks inflated."],
                cross_competitor_gaps=["No cross-competitor feature comparison."],
            )
        ],
    )

    issues = service._build_qa_issues(detail)
    reflector_issues = [issue for issue in issues if issue.detected_by == "reflector"]

    assert [issue.target_subagent for issue in reflector_issues] == [
        "feature",
        "pricing",
        "feature",
    ]
    assert [issue.redo_scope.kind for issue in reflector_issues] == [
        "collector",
        "collector",
        "comparator",
    ]
    assert all(issue.severity == "warn" for issue in reflector_issues)


def test_qa_issue_redo_scopes_are_not_placeholders() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="llm_public_knowledge",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A pricing is summarized without fetched webpage evidence.",
                content_hash="abc",
                confidence=0.7,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A pricing cites an unknown source [source:pricing-404]."]},
                sources=["pricing-1"],
                confidence=0.7,
            )
        },
        report_md="A pricing cites a missing report source [source:pricing-999].",
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A pricing cites [source:pricing-404].",
                    source_ids=["pricing-404"],
                    confidence=0.4,
                )
            ],
        ),
        reflections=[
            ReflectionRecord(
                iteration=1,
                coverage_gaps=["Pricing needs verified webpage evidence for A."],
            )
        ],
    )

    issues = service._build_qa_issues(detail)

    assert issues
    assert all(issue.redo_scope.rationale != "placeholder" for issue in issues)
    assert {
        issue.redo_scope.kind
        for issue in issues
        if issue.id
        in {
            "unverified-pricing-a-pricing-1",
            "kb-unknown-source-a-pricing-pricing-404",
            "phantom-citation-pricing-999",
            "matrix-unknown-source-pricing-404",
            "reflector-coverage-1-pricing-needs-verified-webpage-evidence-for-a",
        }
    } == {"collector", "analyst", "writer_only", "comparator"}


def test_qa_marks_empty_analyst_output_for_scoped_redo() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
    )

    issues = service._build_qa_issues(detail)

    assert [issue.id for issue in issues] == ["empty-analyst-pricing-a"]
    assert issues[0].target_agent == "analyst"
    assert issues[0].redo_scope.kind == "analyst"
    assert issues[0].redo_scope.target_subagent == "pricing"


def test_comparison_matrix_uses_kb_and_sources() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
    )
    service._merge_kb_slice(detail, "pricing", {"A": ["A has a $10 plan."]})

    matrix = service._build_comparison_matrix(
        detail,
        {"matrix_summary": ["A is cheaper."], "winner_by_dimension": {"pricing": "A"}},
    )

    assert matrix.cells[0].value == "A has a $10 plan."
    assert matrix.cells[0].source_ids == ["pricing-1"]
    assert matrix.winner_by_dimension["pricing"] == "A"


def test_comparison_matrix_maps_multi_competitor_sources() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A", "B"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="A, B",
                dimension="feature",
                source_type="webpage_verified",
                title="A and B features",
                url="https://example.com/features",
                snippet="A and B both support advanced features.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
    )
    service._merge_kb_slice(
        detail,
        "feature",
        {
            "A": ["A supports advanced features (source id: feature-1)."],
            "B": ["B supports advanced features (source id: feature-1)."],
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert all(cell.source_ids == ["feature-1"] for cell in matrix.cells)
    assert all(cell.confidence == 0.8 for cell in matrix.cells)
    assert detail.competitor_kbs["A"].sources == ["feature-1"]
    assert detail.competitor_kbs["B"].sources == ["feature-1"]


def test_comparison_matrix_majority_vote_overrides_weak_llm_winner() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A", "B"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-a-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing official",
                url="https://a.example/pricing",
                snippet="A has transparent pricing.",
                content_hash="hash-a-1",
                confidence=0.9,
            ),
            RawSource(
                id="pricing-a-2",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing docs",
                url="https://a.example/docs/pricing",
                snippet="A documents pricing gates.",
                content_hash="hash-a-2",
                confidence=0.86,
            ),
            RawSource(
                id="pricing-b-1",
                competitor="B",
                dimension="pricing",
                source_type="webpage_verified",
                title="B pricing",
                url="https://b.example/pricing",
                snippet="B pricing lead.",
                content_hash="hash-b-1",
                confidence=0.55,
            ),
        ],
    )
    service._merge_kb_slice(
        detail,
        "pricing",
        {
            "A": ["A has stronger pricing evidence."],
            "B": ["B has one pricing note."],
        },
    )

    matrix = service._build_comparison_matrix(
        detail,
        {"matrix_summary": ["LLM initially preferred B."], "winner_by_dimension": {"pricing": "B"}},
    )

    assert matrix.winner_by_dimension["pricing"] == "A"
    assert any("[majority-vote:pricing]" in item for item in matrix.summary)
    assert any("llm=B" in item and "evidence=A" in item for item in matrix.summary)


@pytest.mark.asyncio
async def test_comparator_timeout_falls_back_to_deterministic_matrix() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            comparator_timeout_seconds=0.05,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Comparator timeout budget",
            competitors=["A", "B"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-a",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://a.example/pricing",
            snippet="A publishes a $10 plan.",
            content_hash="pricing-a-hash",
            confidence=0.9,
        )
    ]
    service._merge_kb_slice(record.detail, "pricing", {"A": ["A publishes a $10 plan."]})

    async def slow_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        await asyncio.sleep(1)
        return {}

    service._llm.complete_json = slow_complete_json  # type: ignore[method-assign]

    await service._real_comparator_step(record)

    assert record.detail.comparison_matrix is not None
    assert record.detail.comparison_matrix.cells[0].source_ids == ["pricing-a"]
    events = service.get_trace(detail.id) or []
    completed = next(
        event
        for event in reversed(events)
        if event.type == "node_completed" and event.agent == "comparator"
    )
    assert completed.payload["fallback"]["reason"] == "timeout"
    assert completed.payload["fallback"]["deterministic_fallback"] is True


@pytest.mark.asyncio
async def test_collect_join_normalizes_covered_competitors_and_dedupes() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Collect join smoke",
            competitors=["A", "B"],
            dimensions=["feature"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="feature-1",
            competitor="Cross-model all 2 competitors",
            dimension="feature",
            source_type="webpage_verified",
            title="A and B features",
            url="https://example.com/features",
            snippet="A and B both support advanced features.",
            content_hash="abc",
            confidence=0.8,
        ),
        RawSource(
            id="feature-2",
            competitor="Cross-model all 2 competitors",
            dimension="feature",
            source_type="webpage_verified",
            title="A and B features",
            url="https://example.com/features",
            snippet="Duplicate evidence.",
            content_hash="abc",
            confidence=0.7,
        ),
    ]

    await service._real_collect_join_step(record, ["feature"])

    assert len(record.detail.raw_sources) == 1
    assert record.detail.raw_sources[0].covered_competitors == ["A", "B"]
    assert service.get_trace(detail.id)[-1].subagent == "collect_join"


@pytest.mark.asyncio
async def test_collect_join_skips_cross_search_when_branch_coverage_is_complete() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Collect join coverage",
            competitors=["A", "B"],
            dimensions=["feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="feature-a",
            competitor="A",
            dimension="feature",
            source_type="webpage_verified",
            title="A features",
            url="https://a.example/features",
            snippet="A feature evidence.",
            content_hash="hash-a",
            confidence=0.82,
        ),
        RawSource(
            id="feature-b",
            competitor="B",
            dimension="feature",
            source_type="webpage_verified",
            title="B features",
            url="https://b.example/features",
            snippet="B feature evidence.",
            content_hash="hash-b",
            confidence=0.81,
        ),
    ]

    async def fail_cross_search(**kwargs):  # noqa: ANN202
        raise AssertionError("cross-competitor search should be skipped")

    service._trace_search = fail_cross_search  # type: ignore[method-assign]

    await service._real_collect_join_step(record, ["feature"])

    events = service.get_trace(detail.id) or []
    skipped = next(
        event
        for event in events
        if event.agent == "collector" and event.subagent == "cross::feature"
    )
    assert skipped.payload["skipped"] is True
    assert skipped.payload["reason"] == "branch_coverage_complete"
    assert skipped.payload["covered_competitors"] == ["A", "B"]
    assert len(record.detail.raw_sources) == 2


def test_qa_marks_matrix_unknown_source_for_comparator_redo() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A has a $10 plan."]},
                sources=["pricing-1"],
                confidence=0.8,
            )
        },
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A has a $10 plan.",
                    source_ids=["pricing-404"],
                    confidence=0.8,
                )
            ],
        ),
    )

    issues = service._build_qa_issues(detail)

    matrix = [issue for issue in issues if issue.id == "matrix-unknown-source-pricing-404"]
    assert len(matrix) == 1
    assert matrix[0].severity == "blocker"
    assert matrix[0].redo_scope.kind == "comparator"


def test_qa_marks_matrix_value_citation_missing_from_source_ids() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A features",
                url="https://example.com/features",
                snippet="A supports advanced features.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"feature": ["A supports advanced features (source id: feature-1)."]},
                sources=["feature-1"],
                confidence=0.8,
            )
        },
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["feature"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="feature",
                    value="A supports advanced features (source id: feature-1).",
                    source_ids=[],
                    confidence=0.0,
                )
            ],
        ),
    )

    issues = service._build_qa_issues(detail)

    matrix = [
        issue for issue in issues if issue.id == "matrix-missing-cited-source-a-feature-feature-1"
    ]
    assert len(matrix) == 1
    assert matrix[0].severity == "blocker"
    assert matrix[0].redo_scope.kind == "comparator"


def test_qa_marks_matrix_missing_cell_for_comparator_redo() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A", "B"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            ),
            RawSource(
                id="pricing-2",
                competitor="B",
                dimension="pricing",
                source_type="webpage_verified",
                title="B pricing",
                url="https://example.com/b-pricing",
                snippet="B costs $20.",
                content_hash="def",
                confidence=0.8,
            ),
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A has a $10 plan."]},
                sources=["pricing-1"],
                confidence=0.8,
            ),
            "B": CompetitorKB(
                competitor="B",
                slices={"pricing": ["B has a $20 plan."]},
                sources=["pricing-2"],
                confidence=0.8,
            ),
        },
        comparison_matrix=ComparisonMatrix(
            competitors=["A", "B"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A has a $10 plan.",
                    source_ids=["pricing-1"],
                    confidence=0.8,
                )
            ],
        ),
    )

    issues = service._build_qa_issues(detail)

    matrix = [issue for issue in issues if issue.id == "matrix-missing-cell-b-pricing"]
    assert len(matrix) == 1
    assert matrix[0].severity == "warn"
    assert matrix[0].redo_scope.kind == "comparator"


@pytest.mark.asyncio
async def test_resume_redo_respects_max_iterations() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=1,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Test",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]
    record.detail.status = "completed"
    record.detail.qa_findings = [
        QCIssue(
            id="missing-pricing",
            severity="blocker",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="pricing",
            field_path="raw_sources[pricing]",
            problem="No evidence sources were collected for pricing.",
            redo_scope=RedoScope(
                kind="collector", target_subagent="pricing", rationale="Missing pricing."
            ),
        )
    ]
    record.detail.revisions = [
        RevisionRecord(
            id="revision-1",
            iteration=1,
            stage="collector",
            issue_count_before=1,
            issue_count_after=1,
        )
    ]

    assert service.can_start_redo(detail.id) is False
    updated = await service.resume(detail.id, HitlResumeRequest(decision="redo"))

    assert updated is not None
    assert updated.status == "completed"
    assert service._runs[detail.id].events[-1].message == "Maximum redo iterations reached (1)."


def test_convergence_ratio_tracks_remaining_issue_share() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    assert service._convergence_ratio(4, 1) == 0.25
    assert service._convergence_ratio(0, 1) == 1.0


def test_redo_issue_selection_batches_largest_competitor_gap_cluster() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-redo-cluster",
        topic="Clustered redo",
        status="completed",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(
            topic="Clustered redo",
            competitors=["A", "B", "C", "D", "E"],
            dimensions=["pricing", "feature", "integrations"],
        ),
        qa_findings=[
            _collector_issue("unverified-feature-a", "feature", "A"),
            _collector_issue("unverified-integrations-e", "integrations", "E"),
            _collector_issue("unverified-pricing-a", "pricing", "A"),
            _collector_issue("unverified-pricing-b", "pricing", "B"),
            _collector_issue("unverified-pricing-c", "pricing", "C"),
            _collector_issue("unverified-pricing-d", "pricing", "D"),
            _collector_issue("unverified-pricing-e", "pricing", "E"),
        ],
    )

    selected = service._select_redo_issues(detail)

    assert [issue.redo_scope.target_subagent for issue in selected] == [
        "pricing",
        "pricing",
        "pricing",
    ]
    assert {issue.redo_scope.target_competitor for issue in selected} == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_writer_timeout_preserves_previous_report_and_metrics() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        raise TimeoutError("LLM request timed out after 60.0 seconds.")

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer fallback",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A costs $10 per month.",
            content_hash="abc",
            confidence=0.9,
        )
    ]
    record.detail.comparison_matrix = ComparisonMatrix(
        competitors=["A"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="A",
                dimension="pricing",
                value="A costs $10 per month.",
                source_ids=["pricing-1"],
                confidence=0.9,
            )
        ],
        winner_by_dimension={"pricing": "A"},
        summary=["A has transparent pricing."],
    )
    record.detail.report_md = "Previous report. [source:pricing-1]"
    record.detail.revisions = [
        RevisionRecord(
            id="rev-1", iteration=1, stage="collector", issue_count_before=2, issue_count_after=1
        )
    ]

    await service._real_writer_step(record)

    assert record.detail.report_md == "Previous report. [source:pricing-1]"
    assert record.detail.metrics.revision_count == 1
    assert (
        record.detail.agent_messages[-1].payload["writer_mode"]
        == "preserved previous report after writer error"
    )
    assert record.detail.agent_messages[-1].trace_span_ids
    assert record.detail.trace_spans[-2].agent == "writer"
    assert record.detail.trace_spans[-2].status == "error"


@pytest.mark.asyncio
async def test_writer_budget_timeout_generates_deterministic_report() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=0.05,
        ),
    )

    async def slow_complete_text(*, system: str, user: str) -> str:
        await asyncio.sleep(1)
        return "# Slow report"

    service._llm.complete_text = slow_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer budget fallback",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A costs $10 per month.",
            content_hash="abc",
            confidence=0.9,
        )
    ]
    record.detail.comparison_matrix = ComparisonMatrix(
        competitors=["A"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="A",
                dimension="pricing",
                value="A costs $10 per month.",
                source_ids=["pricing-1"],
                confidence=0.9,
            )
        ],
        winner_by_dimension={"pricing": "A"},
        summary=["A has transparent pricing."],
    )

    await service._real_writer_step(record)

    assert "## Generation Notes" in record.detail.report_md
    assert "writer LLM exceeded 0.05s" in record.detail.report_md
    assert (
        record.detail.agent_messages[-1].payload["writer_mode"]
        == "deterministic fallback after writer error"
    )
    assert record.detail.agent_messages[-1].payload["error"] == "writer LLM exceeded 0.05s"


def test_candidate_evidence_prefers_matching_search_results() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    results = [
        SearchResult(title="Generic market map", url="https://example.com/map", snippet="A list."),
        SearchResult(
            title="Alpha product review", url="https://example.com/alpha", snippet="Alpha details."
        ),
    ]

    evidence = service._candidate_evidence("Alpha", results)

    assert [item.url for item in evidence] == ["https://example.com/alpha"]


@pytest.mark.asyncio
async def test_search_result_becomes_unverified_raw_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202 - test double mirrors async tool shape.
        return None

    monkeypatch.setattr("packages.agents.collectors.logic.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )

    source = await service._source_from_search_result(
        detail,
        "A",
        "pricing",
        SearchResult(
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A has a public pricing page.",
        ),
    )

    assert source is not None
    assert source.source_type == "web_search_result"
    assert str(source.url) == "https://example.com/pricing"


def test_collector_official_source_candidates_include_curated_enterprise_urls() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="AI coding assistant security comparison",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant security comparison",
            competitors=["GitHub Copilot"],
            dimensions=["security"],
        ),
    )

    candidates = service._official_source_candidates(detail, "GitHub Copilot", "security")

    assert any("docs.github.com" in item.url for item in candidates)
    assert any("github.blog/changelog" in item.url for item in candidates)


def test_collector_official_source_candidates_include_persona_product_pages() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="AI coding assistant buyer persona comparison",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant buyer persona comparison",
            competitors=["Cursor", "Claude Code"],
            dimensions=["persona"],
        ),
    )

    cursor_candidates = service._official_source_candidates(detail, "Cursor", "persona")
    claude_candidates = service._official_source_candidates(detail, "Claude Code", "persona")

    assert service._should_collect_official_first("persona") is True
    assert any(item.url == "https://cursor.com" for item in cursor_candidates)
    assert any("anthropic.com/product/claude-code" in item.url for item in claude_candidates)


def test_collector_official_source_candidates_use_current_windsurf_urls() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Windsurf AI coding assistant comparison",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="Windsurf AI coding assistant comparison",
            competitors=["Windsurf"],
            dimensions=["pricing", "feature", "persona"],
        ),
    )

    pricing_candidates = service._official_source_candidates(detail, "Windsurf", "pricing")
    feature_candidates = service._official_source_candidates(detail, "Windsurf", "feature")
    persona_candidates = service._official_source_candidates(detail, "Windsurf", "persona")

    assert pricing_candidates[0].url == "https://windsurf.com/plans"
    assert feature_candidates[0].url == "https://windsurf.com/features"
    assert persona_candidates[0].url == "https://windsurf.com/customers"
    assert not any(item.url == "https://windsurf.com/pricing" for item in pricing_candidates[:2])


def test_collector_search_query_adds_product_qualifier_for_ambiguous_names() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="AI coding assistant feature comparison",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant feature comparison",
            competitors=["Cursor"],
            dimensions=["feature"],
        ),
    )

    query = service._web_search_query(detail, "Cursor", "feature")

    assert "AI code editor" in query
    assert "official source" in query


def test_collector_rejects_product_identity_confusion_sources() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    windsurf_source = RawSource(
        id="pricing-windsurf-confused",
        competitor="Windsurf",
        dimension="pricing",
        source_type="webpage_verified",
        title="Devin pricing",
        url="https://devin.ai/pricing",
        snippet="Devin Desktop pricing includes a Team plan and Enterprise plan.",
        content_hash="hash-windsurf",
        confidence=0.96,
    )
    cursor_source = RawSource(
        id="feature-cursor-confused",
        competitor="Cursor",
        dimension="feature",
        source_type="webpage_verified",
        title="Cursor Extractor",
        url="https://example.com/cursor-extractor",
        snippet="Cursor Extractor is a database pagination utility with cursor-based pages.",
        content_hash="hash-cursor",
        confidence=0.96,
    )

    assert "rather than Windsurf" in (service._source_quality_problem(windsurf_source) or "")
    assert "rather than Cursor" in (service._source_quality_problem(cursor_source) or "")


@pytest.mark.asyncio
async def test_verified_source_uses_dimension_specific_snippet_and_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str) -> FetchPageResult:
        return FetchPageResult(
            url=url,
            ok=True,
            title="Cursor Pricing",
            text=(
                "Skip to main content Open menu Sign in Cookie settings "
                "Cursor pricing includes a Free plan and a Pro plan at $20 per month. "
                "Teams can contact sales for Enterprise pricing and annual billing."
            ),
            content_hash="pricing-hash",
            status_code=200,
        )

    monkeypatch.setattr("packages.agents.collectors.logic.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Cursor pricing comparison",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="Cursor pricing comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
            homepage_hints={"Cursor": "https://cursor.com"},
        ),
    )

    source = await service._source_from_search_result(
        detail,
        "Cursor",
        "pricing",
        SearchResult(
            title="Cursor official pricing",
            url="https://cursor.com/pricing",
            snippet="Official pricing page",
        ),
    )

    assert source is not None
    assert source.source_type == "webpage_verified"
    assert "$20 per month" in source.snippet
    assert source.confidence >= 0.95


@pytest.mark.asyncio
async def test_real_pipeline_runs_through_langgraph() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    order: list[str] = []

    async def fake_planner(record):  # noqa: ANN001, ANN202 - test double for bound service method.
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"collector:{competitor}:{dimension}")

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"analyst:{competitor}:{dimension}")

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        order.append(f"qa:{phase}")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Graph smoke",
                competitors=["A"],
                dimensions=["pricing", "feature"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert order[0] == "planner", [
            event.message for event in service.get_trace(detail.id) or []
        ]
        assert set(order[1:3]) == {"collector:A:pricing", "collector:A:feature"}
        assert order[3] == "qa:collect"
        assert set(order[4:6]) == {"analyst:A:pricing", "analyst:A:feature"}
        assert order[6:] == ["qa:analyst", "comparator", "reflector", "writer", "qa"]
        assert service.get_run(detail.id).status == "completed"  # type: ignore[union-attr]
        assert service._graph_checkpointer.saver is not None
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_real_collector_replay_links_rag_event_to_source_ids() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_official_sources(  # noqa: ANN001
        record,
        detail,
        dimension,
        competitor,
        context,
    ) -> list[RawSource]:
        return [
            RawSource(
                id="source-pricing-1",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="Cursor official pricing",
                url="https://cursor.com/pricing",
                snippet="Cursor publishes pricing plans.",
                content_hash="hash-pricing-1",
                confidence=0.94,
            )
        ]

    service._collect_official_sources = fake_official_sources  # type: ignore[method-assign]

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_collector_branch_step(record, "pricing", "Cursor")

    events = service.get_trace(detail.id) or []
    collector_done = next(
        event
        for event in events
        if event.type == "node_completed" and event.agent == "collector"
    )
    assert collector_done.payload["source_ids"] == ["source-pricing-1"]
    assert collector_done.payload["source_count"] == 1
    assert collector_done.payload["retrieval_stage"] == "collector_branch_finish"

    updated = service.get_run(detail.id)
    assert updated is not None
    replay = build_decision_replay(updated, events)
    rag_event = next(
        event
        for event in replay.events
        if event.event_type == "rag.retrieved" and event.source_event_id == collector_done.id
    )

    assert rag_event.evidence_ids == ["source-pricing-1"]
    assert rag_event.payload["source_ids"] == ["source-pricing-1"]


@pytest.mark.asyncio
async def test_collector_and_analyst_dimensions_run_concurrently() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    timeline: list[tuple[str, str, float]] = []

    async def fake_planner(record):  # noqa: ANN001, ANN202
        timeline.append(("planner", "done", asyncio.get_running_loop().time()))

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        timeline.append(
            (f"collector:{competitor}:{dimension}", "start", asyncio.get_running_loop().time())
        )
        await asyncio.sleep(0.05)
        timeline.append(
            (f"collector:{competitor}:{dimension}", "end", asyncio.get_running_loop().time())
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        timeline.append(
            (f"analyst:{competitor}:{dimension}", "start", asyncio.get_running_loop().time())
        )
        await asyncio.sleep(0.05)
        timeline.append(
            (f"analyst:{competitor}:{dimension}", "end", asyncio.get_running_loop().time())
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        timeline.append(("comparator", "done", asyncio.get_running_loop().time()))

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        timeline.append(("reflector", "done", asyncio.get_running_loop().time()))

    async def fake_writer(record):  # noqa: ANN001, ANN202
        timeline.append(("writer", "done", asyncio.get_running_loop().time()))

    async def fake_qa(record):  # noqa: ANN001, ANN202
        timeline.append(("qa", "done", asyncio.get_running_loop().time()))

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        timeline.append((f"qa:{phase}", "done", asyncio.get_running_loop().time()))

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Parallel smoke",
                competitors=["A"],
                dimensions=["pricing", "feature"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert _overlaps(timeline, "collector:A:pricing", "collector:A:feature")
        assert _overlaps(timeline, "analyst:A:pricing", "analyst:A:feature")
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_collect_qa_blocks_and_retries_collector_before_analyst() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    order: list[str] = []
    collector_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        nonlocal collector_calls
        collector_calls += 1
        order.append(f"collector:{collector_calls}")
        if collector_calls == 1:
            return
        record.detail.raw_sources.append(
            RawSource(
                id="pricing-1",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append("analyst")
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, ["A costs $10. [source:pricing-1]"]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")
        record.detail.comparison_matrix = service._build_comparison_matrix(record.detail, {})

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")
        record.detail.report_md = "A costs $10. [source:pricing-1]"

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Collect gate",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert order == [
            "planner",
            "collector:1",
            "collector:2",
            "analyst",
            "comparator",
            "reflector",
            "writer",
            "qa",
        ]
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_real_pipeline_auto_runs_scoped_redo_for_qa_findings() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    qa_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.plan.competitors = ["A"]

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        record.detail.raw_sources.append(
            RawSource(
                id=f"{dimension}-{len(record.detail.raw_sources) + 1}",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title=f"A {dimension}",
                url=f"https://example.com/{dimension}",
                snippet=f"A {dimension} evidence.",
                content_hash=f"{dimension}-hash",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, [f"A {dimension} finding."]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        record.detail.comparison_matrix = service._build_comparison_matrix(
            record.detail, {"matrix_summary": []}
        )

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        return None

    async def fake_writer(record):  # noqa: ANN001, ANN202
        record.detail.report_md = f"Report pass {qa_calls}."

    async def fake_qa(record):  # noqa: ANN001, ANN202
        nonlocal qa_calls
        qa_calls += 1
        if qa_calls == 1:
            record.detail.qa_findings = [
                QCIssue(
                    id="missing-pricing",
                    severity="blocker",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent="pricing",
                    field_path="raw_sources[pricing]",
                    problem="Redo pricing evidence.",
                    redo_scope=RedoScope(
                        kind="collector", target_subagent="pricing", rationale="Redo pricing."
                    ),
                )
            ]
        else:
            record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Auto redo smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
        assert len(updated.revisions) == 1
        assert updated.revisions[0].stage == "collector"
        assert qa_calls == 2
        assert any(
            event.subagent == "auto_redo" and event.type == "node_started"
            for event in service.get_trace(detail.id) or []
        )
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_real_pipeline_does_not_auto_redo_warn_only_findings() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    qa_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.plan.competitors = ["A"]

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        record.detail.raw_sources.append(
            RawSource(
                id="pricing-1",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A pricing evidence.",
                content_hash="pricing-hash",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, ["A pricing finding. [source:pricing-1]"]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        record.detail.comparison_matrix = service._build_comparison_matrix(
            record.detail, {"matrix_summary": []}
        )

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        return None

    async def fake_writer(record):  # noqa: ANN001, ANN202
        record.detail.report_md = "Report with a warning only. [source:pricing-1]"

    async def fake_qa(record):  # noqa: ANN001, ANN202
        nonlocal qa_calls
        qa_calls += 1
        record.detail.qa_findings = [
            QCIssue(
                id="unverified-pricing",
                severity="warn",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                field_path="raw_sources[pricing].source_type",
                problem="Pricing source is not independently verified.",
                redo_scope=RedoScope(
                    kind="collector", target_subagent="pricing", rationale="Retry pricing."
                ),
            )
        ]

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Warn only auto redo",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                auto_redo_warn_enabled=False,
            )
        )

        await service.run_pipeline(detail.id)

        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert [issue.id for issue in updated.qa_findings] == ["unverified-pricing"]
        assert updated.revisions == []
        assert qa_calls == 1
        assert not any(
            event.subagent == "auto_redo" and event.type == "node_started"
            for event in service.get_trace(detail.id) or []
        )
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_real_pipeline_auto_redoes_warn_when_run_option_enabled() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    qa_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.plan.competitors = ["A"]

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        record.detail.raw_sources.append(
            RawSource(
                id=f"pricing-{len(record.detail.raw_sources) + 1}",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A pricing evidence.",
                content_hash=f"pricing-hash-{len(record.detail.raw_sources) + 1}",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, ["A pricing finding."]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        record.detail.comparison_matrix = service._build_comparison_matrix(
            record.detail, {"matrix_summary": []}
        )

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        return None

    async def fake_writer(record):  # noqa: ANN001, ANN202
        record.detail.report_md = f"Report pass {qa_calls}."

    async def fake_qa(record):  # noqa: ANN001, ANN202
        nonlocal qa_calls
        qa_calls += 1
        if qa_calls == 1:
            record.detail.qa_findings = [
                QCIssue(
                    id="unverified-pricing",
                    severity="warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent="pricing",
                    field_path="raw_sources[pricing].source_type",
                    problem="Pricing source is not independently verified.",
                    redo_scope=RedoScope(
                        kind="collector", target_subagent="pricing", rationale="Retry pricing."
                    ),
                )
            ]
        else:
            record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Warn auto redo enabled",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                auto_redo_warn_enabled=True,
            )
        )

        await service.run_pipeline(detail.id)

        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
        assert len(updated.revisions) == 1
        assert qa_calls == 2
        auto_redo_events = [
            event
            for event in service.get_trace(detail.id) or []
            if event.subagent == "auto_redo" and event.type == "node_started"
        ]
        assert len(auto_redo_events) == 1
        assert auto_redo_events[0].payload["include_warn"] is True
    finally:
        await service._graph_checkpointer.aclose()


def _overlaps(timeline: list[tuple[str, str, float]], left: str, right: str) -> bool:
    points = {(name, phase): timestamp for name, phase, timestamp in timeline}
    return (
        points[(left, "start")] < points[(right, "end")]
        and points[(right, "start")] < points[(left, "end")]
    )


@pytest.mark.asyncio
async def test_collector_and_analyst_trace_spans_have_independent_contexts() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            analyst_react_enabled=False,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "collector subagent" in system:
            dimension = "pricing" if "Dimension: pricing" in user else "feature"
            return {
                "sources": [
                    {
                        "competitor": "A",
                        "title": f"A {dimension}",
                        "url": None,
                        "summary": f"A {dimension} summary.",
                        "confidence": 0.7,
                    }
                ]
            }
        return {"competitor_findings": {"A": ["A finding."]}, "caveats": []}

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Context smoke",
            competitors=["A"],
            dimensions=["pricing", "feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await asyncio.gather(
        service._real_collector_step(record, "pricing"),
        service._real_collector_step(record, "feature"),
    )
    await asyncio.gather(
        service._real_analyst_step(record, "pricing"),
        service._real_analyst_step(record, "feature"),
    )

    context_ids = {
        span.metadata["context_id"]
        for span in record.detail.trace_spans
        if span.kind == "llm" and span.agent in {"collector", "analyst"}
    }
    assert len(context_ids) == 4
    assert all(str(context_id).startswith(f"{detail.id}:") for context_id in context_ids)
    assert all(
        span.metadata["message_count"] == 3
        for span in record.detail.trace_spans
        if span.kind == "llm" and span.agent in {"collector", "analyst"}
    )
    assert len({source.id for source in record.detail.raw_sources}) == len(
        record.detail.raw_sources
    )


@pytest.mark.asyncio
async def test_collector_react_runner_searches_fetches_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202
        return FetchPageResult(
            url=url,
            ok=True,
            title="A pricing page",
            text="A pricing starts at $10 per seat.",
            content_hash="reacthash",
            status_code=200,
        )

    monkeypatch.setattr("packages.orchestrator.service.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    actions = [
        {
            "action": "web_search",
            "query": "A pricing official",
            "rationale": "Find official pricing.",
        },
        {
            "action": "fetch_page",
            "url": "https://example.com/pricing",
            "rationale": "Inspect pricing page.",
        },
        {
            "action": "finish",
            "rationale": "Evidence is sufficient.",
            "sources": [
                {
                    "competitor": "A",
                    "title": "A pricing page",
                    "url": "https://example.com/pricing",
                    "summary": "A pricing starts at $10 per seat.",
                    "confidence": 0.86,
                }
            ],
        },
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded collector ReAct runner" in system:
            return actions.pop(0)
        raise AssertionError("Fallback collector LLM should not be called when ReAct finishes.")

    async def fake_search(query: str, max_results: int = 3) -> list[SearchResult]:
        return [
            SearchResult(
                title="A pricing page",
                url="https://example.com/pricing",
                snippet="Official pricing information.",
            )
        ]

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    service._search.search = fake_search  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="React smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_collector_step(record, "pricing")

    assert len(record.detail.raw_sources) == 1
    assert record.detail.raw_sources[0].source_type == "webpage_verified"
    assert record.detail.raw_sources[0].snippet == "A pricing starts at $10 per seat."
    traced_action_spans = [
        span for span in record.detail.trace_spans if not span.name.startswith("agent_message:")
    ]
    span_names = [span.name for span in traced_action_spans]
    assert span_names == [
        "pricing_react_turn_1",
        "web_search",
        "pricing_react_turn_2",
        "robots_check",
        "fetch_page",
        "pricing_react_turn_3",
        "extract_facts",
    ]
    finish_span = next(span for span in traced_action_spans if span.name == "pricing_react_turn_3")
    assert finish_span.metadata["tool_call_count"] == 3
    assert finish_span.metadata["message_count"] == 12
    assert "context_id" in finish_span.metadata
    events = service.get_trace(detail.id) or []
    search_rag = next(event for event in events if event.type == "rag.retrieved")
    assert search_rag.payload["candidate_urls"] == ["https://example.com/pricing"]
    assert "source_ids" not in search_rag.payload
    replay = build_decision_replay(record.detail, events)
    search_replay = next(
        event
        for event in replay.events
        if event.event_type == "rag.retrieved" and event.source_event_id == search_rag.id
    )
    collector_replay = next(
        event
        for event in replay.events
        if event.event_type == "rag.retrieved"
        and event.evidence_ids == [record.detail.raw_sources[0].id]
    )
    assert search_replay.evidence_ids == []
    assert search_replay.payload["candidate_urls"] == ["https://example.com/pricing"]
    assert collector_replay.payload["retrieval_stage"] == "collector_react_finish"


@pytest.mark.asyncio
async def test_collector_react_finish_fetches_uninspected_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202
        return FetchPageResult(
            url=url,
            ok=True,
            title="A pricing page",
            text="A pricing starts at $10 per seat.",
            content_hash="finishhash",
            status_code=200,
        )

    monkeypatch.setattr("packages.orchestrator.service.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    actions = [
        {
            "action": "finish",
            "sources": [
                {
                    "competitor": "A",
                    "title": "A pricing",
                    "url": "https://example.com/pricing",
                    "summary": "A has public pricing.",
                    "confidence": 0.8,
                }
            ],
        }
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded collector ReAct runner" in system:
            return actions.pop(0)
        raise AssertionError("Fallback collector LLM should not be called when ReAct finishes.")

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="React finish fetch smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_collector_step(record, "pricing")

    assert record.detail.raw_sources[0].source_type == "webpage_verified"
    assert record.detail.raw_sources[0].content_hash == "finishhash"
    assert [
        span.name
        for span in record.detail.trace_spans
        if not span.name.startswith("agent_message:")
    ] == [
        "pricing_react_turn_1",
        "robots_check",
        "fetch_page",
        "extract_facts",
    ]


@pytest.mark.asyncio
async def test_analyst_react_runner_inspects_validates_and_finishes() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    actions = [
        {"action": "inspect_sources", "rationale": "Review available pricing evidence."},
        {
            "action": "validate_citations",
            "source_ids": ["pricing-1"],
            "rationale": "Check cited source IDs.",
        },
        {
            "action": "finish",
            "competitor_findings": {"A": ["A has a $10 plan [source:pricing-1]."]},
            "source_ids_used": ["pricing-1"],
            "caveats": [],
            "rationale": "Pricing evidence is ready.",
        },
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded analyst ReAct runner" in system:
            return actions.pop(0)
        raise AssertionError("Fallback analyst LLM should not be called when ReAct finishes.")

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Analyst ReAct smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A pricing starts at $10 per seat.",
            content_hash="reacthash",
            confidence=0.86,
        )
    ]

    await service._real_analyst_step(record, "pricing")

    assert record.detail.competitor_kbs["A"].slices["pricing"] == [
        "A has a $10 plan [source:pricing-1]."
    ]
    span_names = [span.name for span in record.detail.trace_spans]
    assert span_names == [
        "pricing_analyst_react_turn_1",
        "inspect_sources",
        "pricing_analyst_react_turn_2",
        "validate_citations",
        "pricing_analyst_react_turn_3",
    ]
    finish_span = record.detail.trace_spans[-1]
    assert finish_span.metadata["tool_call_count"] == 2
    assert finish_span.metadata["message_count"] == 11
    assert "context_id" in finish_span.metadata


@pytest.mark.asyncio
async def test_analyst_branch_skips_react_when_fanout_budget_is_exceeded() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            analyst_react_enabled=True,
            analyst_react_fanout_threshold=2,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Fanout analyst budget",
            competitors=["A", "B", "C"],
            dimensions=["feature", "pricing", "persona"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="feature-a",
            competitor="A",
            dimension="feature",
            source_type="webpage_verified",
            title="A feature",
            url="https://a.example/features",
            snippet="A supports the key workflow.",
            content_hash="feature-a-hash",
            confidence=0.84,
        )
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded analyst ReAct runner" in system:
            raise AssertionError("large fanout should skip analyst ReAct")
        return {
            "feature_tree": {
                "nodes": [
                    {
                        "name": "Workflow feature",
                        "description": "A supports the key workflow.",
                        "claims": [
                            {
                                "claim": "A supports the key workflow.",
                                "source_ids": ["feature-a"],
                                "confidence": 0.84,
                            }
                        ],
                        "children": [],
                    }
                ],
                "summary_claims": [
                    {
                        "claim": "A supports the key workflow.",
                        "source_ids": ["feature-a"],
                        "confidence": 0.84,
                    }
                ],
            }
        }

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]

    await service._real_analyst_branch_step(record, "feature", "A")

    events = service.get_trace(detail.id) or []
    completed = next(
        event
        for event in reversed(events)
        if event.type == "node_completed" and event.agent == "analyst"
    )
    assert completed.payload["react"]["react_skipped"] == "fanout_budget"
    assert completed.payload["react"]["fanout_branch_count"] == 9
    assert completed.payload["react"]["fanout_threshold"] == 2
    assert record.detail.competitor_knowledge["A"].feature_tree.summary_claims


@pytest.mark.asyncio
async def test_analyst_branch_timeout_falls_back_to_deterministic_knowledge() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            analyst_react_enabled=True,
            analyst_react_fanout_threshold=1,
            analyst_branch_timeout_seconds=0.05,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Analyst timeout budget",
            competitors=["A", "B"],
            dimensions=["feature", "pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="feature-a",
            competitor="A",
            dimension="feature",
            source_type="webpage_verified",
            title="A feature",
            url="https://a.example/features",
            snippet="A supports a documented workflow.",
            content_hash="feature-a-hash",
            confidence=0.83,
        )
    ]

    async def slow_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        await asyncio.sleep(1)
        return {}

    service._llm.complete_json = slow_complete_json  # type: ignore[method-assign]

    await service._real_analyst_branch_step(record, "feature", "A")

    knowledge = record.detail.competitor_knowledge["A"]
    events = service.get_trace(detail.id) or []
    completed = next(
        event
        for event in reversed(events)
        if event.type == "node_completed" and event.agent == "analyst"
    )
    assert completed.payload["react"]["analysis_timeout"] == "one-shot analyst exceeded 0.05s"
    assert completed.payload["react"]["deterministic_fallback"] is True
    assert knowledge.feature_tree.summary_claims[0].source_ids == ["feature-a"]
    assert "documented workflow" in knowledge.feature_tree.summary_claims[0].claim


def test_deterministic_structured_knowledge_payload_matches_schema_shape() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    sources = [
        {
            "id": "pricing-a",
            "title": "A pricing",
            "snippet": "A publishes a $10 per month plan.",
            "confidence": 0.87,
        }
    ]

    pricing = service._deterministic_structured_knowledge_payload(
        competitor="A",
        dimension="pricing",
        dimension_sources=sources,
    )
    persona = service._deterministic_structured_knowledge_payload(
        competitor="A",
        dimension="persona",
        dimension_sources=sources,
    )

    assert pricing["pricing_model"]["tiers"][0]["claims"][0]["source_ids"] == ["pricing-a"]
    assert pricing["pricing_model"]["tiers"][0]["price"] == "$10"
    assert persona["user_personas"]["segments"][0]["claims"][0]["source_ids"] == ["pricing-a"]
    assert persona["user_personas"]["segments"][0]["use_cases"]


@pytest.mark.asyncio
async def test_analyst_empty_structured_payload_falls_back_to_source_claims() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            analyst_react_enabled=True,
            analyst_react_fanout_threshold=1,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Empty analyst payload fallback",
            competitors=["A", "B"],
            dimensions=["pricing", "feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-a",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://a.example/pricing",
            snippet="A publishes a $10 per month plan.",
            content_hash="pricing-a-hash",
            confidence=0.88,
        )
    ]

    async def empty_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        return {"pricing_model": {"tiers": [], "notes": []}}

    service._llm.complete_json = empty_complete_json  # type: ignore[method-assign]

    await service._real_analyst_branch_step(record, "pricing", "A")

    kb = record.detail.competitor_kbs["A"]
    knowledge = record.detail.competitor_knowledge["A"]
    events = service.get_trace(detail.id) or []
    completed = next(
        event
        for event in reversed(events)
        if event.type == "node_completed" and event.agent == "analyst"
    )
    assert kb.slices["pricing"]
    assert knowledge.pricing_model.tiers[0].claims[0].source_ids == ["pricing-a"]
    assert completed.payload["react"]["fallback_reason"] == "empty_structured_payload"


@pytest.mark.asyncio
async def test_analyst_fanout_branch_timeout_uses_short_budget() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            analyst_react_enabled=True,
            analyst_react_fanout_threshold=1,
            analyst_branch_timeout_seconds=10,
            analyst_fanout_branch_timeout_seconds=0.05,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Fanout analyst timeout budget",
            competitors=["A", "B"],
            dimensions=["feature", "pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="feature-a",
            competitor="A",
            dimension="feature",
            source_type="webpage_verified",
            title="A feature",
            url="https://a.example/features",
            snippet="A supports a budgeted analyst fallback workflow.",
            content_hash="feature-a-hash",
            confidence=0.81,
        )
    ]

    async def slow_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        await asyncio.sleep(1)
        return {}

    service._llm.complete_json = slow_complete_json  # type: ignore[method-assign]

    await service._real_analyst_branch_step(record, "feature", "A")

    events = service.get_trace(detail.id) or []
    completed = next(
        event
        for event in reversed(events)
        if event.type == "node_completed" and event.agent == "analyst"
    )
    assert completed.payload["react"]["react_skipped"] == "fanout_budget"
    assert completed.payload["react"]["analysis_timeout"] == "one-shot analyst exceeded 0.05s"
    assert completed.payload["react"]["deterministic_fallback"] is True


@pytest.mark.asyncio
async def test_analyst_react_runner_auto_validates_finish() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded analyst ReAct runner" in system:
            return {
                "action": "finish",
                "competitor_findings": {"A": ["A has a $10 plan."]},
                "source_ids_used": ["pricing-1"],
                "caveats": [],
                "rationale": "Evidence is sufficient.",
            }
        raise AssertionError("Fallback analyst LLM should not be called when ReAct finishes.")

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Analyst auto validation smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A pricing starts at $10 per seat.",
            content_hash="reacthash",
            confidence=0.86,
        )
    ]

    await service._real_analyst_step(record, "pricing")

    assert record.detail.competitor_kbs["A"].slices["pricing"] == [
        "A has a $10 plan. [source:pricing-1]"
    ]
    assert [span.name for span in record.detail.trace_spans] == [
        "pricing_analyst_react_turn_1",
        "inspect_sources",
        "validate_citations",
    ]
    assert record.detail.trace_spans[-1].metadata["valid_count"] == 1


@pytest.mark.asyncio
async def test_real_scoped_redo_runs_through_langgraph() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )
    order: list[str] = []

    async def fake_planner(record):  # noqa: ANN001, ANN202
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"collector:{competitor}:{dimension}")

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"analyst:{competitor}:{dimension}")

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        order.append(f"qa:{phase}")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Scoped redo smoke",
                competitors=["A"],
                dimensions=["pricing", "feature"],
                execution_mode="real",
            )
        )
        record = service._runs[detail.id]
        record.detail.status = "completed"
        record.detail.report_md = "Before redo"
        record.detail.raw_sources = [
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            ),
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A feature",
                url="https://example.com/features",
                snippet="A has features.",
                content_hash="def",
                confidence=0.8,
            ),
        ]
        record.detail.qa_findings = [
            QCIssue(
                id="missing-pricing",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                field_path="raw_sources[pricing]",
                problem="Redo pricing evidence.",
                redo_scope=RedoScope(
                    kind="collector", target_subagent="pricing", rationale="Redo pricing."
                ),
            )
        ]

        await service.run_scoped_redo(detail.id)

        assert order == [
            "collector:A:pricing",
            "qa:collect",
            "analyst:A:pricing",
            "qa:analyst",
            "comparator",
            "reflector",
            "writer",
            "qa",
        ], [event.message for event in service.get_trace(detail.id) or []]
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.revisions[0].stage == "collector"
        assert all(source.dimension != "pricing" for source in updated.raw_sources)
        assert any(source.dimension == "feature" for source in updated.raw_sources)
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_demo_pipeline_uses_same_langgraph_fanout_shape() -> None:
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
        graph_checkpointer=_test_graph_checkpointer(),
    )
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Demo graph smoke",
                competitors=["A", "B"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )

        await service.run_pipeline(detail.id)
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"

        events = service.get_trace(detail.id) or []
        collector_subagents = sorted(
            event.subagent
            for event in events
            if event.type == "node_completed" and event.agent == "collector"
        )
        assert collector_subagents == ["pricing::A", "pricing::B"]
        assert any(event.agent == "collector_dispatch" for event in events)
        assert any(event.agent == "analyst_dispatch" for event in events)
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_hitl_uses_langgraph_command_resume_and_updates_plan() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            hitl_enabled=True,
            hitl_timeout_seconds=5,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.current_node = "planner"

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        record.detail.qa_findings = []

    async def fake_node(record):  # noqa: ANN001, ANN202
        return None

    async def fake_qa_hitl(record):  # noqa: ANN001, ANN202
        return {"redo_kind": "end"}

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_comparator_step = fake_node  # type: ignore[method-assign]
    service._real_reflector_step = fake_node  # type: ignore[method-assign]
    service._real_writer_step = fake_node  # type: ignore[method-assign]
    service._real_qa_step = fake_node  # type: ignore[method-assign]
    service._real_qa_hitl_step = fake_qa_hitl  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="HITL smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )
        record = service._runs[detail.id]
        await service.run_pipeline(detail.id)

        assert record.detail.status == "interrupted"
        assert service.has_pending_interrupt(detail.id) is True
        assert record.active_graph_kind == "real"

        updated = await service.resume(
            detail.id,
            HitlResumeRequest(decision="modify_plan", dimensions=["feature"]),
        )

        assert updated is not None
        for _ in range(300):
            if record.detail.status == "completed":
                break
            await asyncio.sleep(0.01)

        assert record.detail.plan.dimensions == ["feature"]
        assert record.detail.status == "completed"
        assert service.has_pending_interrupt(detail.id) is False
        assert any(event.type == "interrupt" for event in service.get_trace(detail.id) or [])
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_hitl_resume_creates_reviewable_memory_candidate() -> None:
    memory = PreferenceMemoryStore.in_memory()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            hitl_enabled=True,
        ),
        enterprise_store=EnterpriseMemoryStore(),
        preference_memory=memory,
        graph_checkpointer=_test_graph_checkpointer(),
    )

    async def fake_resume_graph(run_id, request):  # noqa: ANN001, ANN202
        return None

    service._resume_interrupted_graph = fake_resume_graph  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="HITL memory smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                project_id="project-hitl-memory",
            )
        )
        record = service._runs[detail.id]
        record.pending_interrupts["planner"] = {
            "stage": "planner",
            "graph_kind": "real",
            "thread_id": "thread-hitl-memory",
            "interrupt_node": "planner_hitl",
        }

        updated = await service.resume(
            detail.id,
            HitlResumeRequest(
                decision="modify_plan",
                note="Prefer official feature sources before writing recommendations.",
                dimensions=["feature"],
            ),
        )

        assert updated is not None
        feedback = memory.list_feedback(project_id=updated.project_id or "")
        recall = memory.recall(
            workspace_id="default-workspace",
            project_id=updated.project_id or "",
            query="feature official source",
            include_unconfirmed=True,
        )

        assert updated.plan.dimensions == ["feature"]
        assert updated.metrics.human_override_rate == 1.0
        assert feedback[0].target_type == "dimension"
        assert feedback[0].run_id == detail.id
        assert feedback[0].metadata["source"] == "hitl_resume"
        assert recall.candidates
        assert all(candidate.status == "candidate" for candidate in recall.candidates)
        assert {candidate.kind for candidate in recall.candidates} & {
            "preferred_dimension",
            "source_preference",
            "correction",
        }
        memory_events = [
            event
            for event in service.get_trace(detail.id) or []
            if event.type == "memory.feedback_captured"
        ]
        assert memory_events
        assert memory_events[0].payload["feedback_id"] == feedback[0].id
        assert set(memory_events[0].payload["candidate_ids"]) == {
            candidate.id for candidate in recall.candidates
        }
        hitl_messages = [
            message
            for message in updated.agent_messages
            if message.message_type == "hitl_memory_feedback_captured"
        ]
        assert hitl_messages
        assert hitl_messages[0].payload["has_note"] is True
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_hitl_timeout_auto_accepts_interrupt() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            hitl_enabled=True,
            hitl_timeout_seconds=0.05,
        ),
        graph_checkpointer=_test_graph_checkpointer(),
    )

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.current_node = "planner"

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        record.detail.qa_findings = []

    async def fake_node(record):  # noqa: ANN001, ANN202
        return None

    async def fake_qa_hitl(record):  # noqa: ANN001, ANN202
        return {"redo_kind": "end"}

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_comparator_step = fake_node  # type: ignore[method-assign]
    service._real_reflector_step = fake_node  # type: ignore[method-assign]
    service._real_writer_step = fake_node  # type: ignore[method-assign]
    service._real_qa_step = fake_node  # type: ignore[method-assign]
    service._real_qa_hitl_step = fake_qa_hitl  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="HITL timeout smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )
        record = service._runs[detail.id]
        await service.run_pipeline(detail.id)

        assert record.detail.status == "interrupted"
        for _ in range(300):
            if record.detail.status == "completed":
                break
            await asyncio.sleep(0.01)

        assert record.detail.status == "completed"
        assert service.has_pending_interrupt(detail.id) is False
        assert any("auto-accepted" in event.message for event in service.get_trace(detail.id) or [])
    finally:
        await service._graph_checkpointer.aclose()
