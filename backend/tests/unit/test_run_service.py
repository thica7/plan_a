import asyncio
import time
from datetime import datetime

import pytest

from packages.agents import SubagentContext
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
    CompetitorKnowledge,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    RevisionRecord,
)
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.evidence_fetch import EvidenceFetchResult
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


def test_refresh_quality_metrics_excludes_user_research_from_verified_rate() -> None:
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
    detail = RunDetail(
        id="run-quality-source-rate",
        topic="AI coding assistant adoption",
        status="completed",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(
            topic="AI coding assistant adoption",
            competitors=["Acme"],
            dimensions=["persona"],
        ),
        raw_sources=[
            RawSource(
                id="survey-1",
                competitor="Acme",
                dimension="persona",
                source_type="survey_simulated",
                title="Acme survey",
                snippet="Surveyed target users cite onboarding effort.",
                content_hash="surveyhash",
                confidence=0.58,
            ),
            RawSource(
                id="interview-1",
                competitor="Acme",
                dimension="persona",
                source_type="interview_record",
                title="Acme interview",
                snippet="Interviewed users discuss workflow fit and switching cost.",
                content_hash="interviewhash",
                confidence=0.62,
            ),
            RawSource(
                id="official-1",
                competitor="Acme",
                dimension="persona",
                source_type="webpage_verified",
                title="Acme official page",
                url="https://example.com/acme",
                snippet="Official Acme page describes user workflow adoption.",
                content_hash="officialhash",
                confidence=0.92,
            ),
            RawSource(
                id="docs-1",
                competitor="Acme",
                dimension="persona",
                source_type="official_docs",
                title="Acme docs",
                url="https://docs.example.com/acme",
                snippet="Official docs describe onboarding and adoption controls.",
                content_hash="docshash",
                confidence=0.94,
            ),
            RawSource(
                id="search-1",
                competitor="Acme",
                dimension="persona",
                source_type="web_search_result",
                title="Acme search result",
                url="https://search.example.com/acme",
                snippet="Search result points to user adoption commentary.",
                content_hash="searchhash",
                confidence=0.7,
            ),
        ],
    )

    service._refresh_quality_metrics(detail)

    assert detail.metrics.verified_source_rate == 0.667


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
    assert record.detail.plan.homepage_hints == {}
    assert record.detail.plan.homepage_verified == {"Alpha": False, "Beta": False}
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
        task for task in tasks if task.stage == "collector" and task.dimension == "pricing"
    )
    persona_collector = next(
        task for task in tasks if task.stage == "collector" and task.dimension == "persona"
    )
    persona_survey = next(
        task for task in tasks if task.stage == "survey_interview" and task.dimension == "persona"
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
    assert source_types == {"survey_simulated", "interview_record"}
    assert len(record.detail.raw_sources) == 2
    survey_source = next(
        source for source in record.detail.raw_sources if source.source_type == "survey_simulated"
    )
    interview_source = next(
        source for source in record.detail.raw_sources if source.source_type == "interview_record"
    )
    assert "Simulated survey and interview research" in survey_source.snippet
    assert "Synthetic interview record" in interview_source.snippet
    assert survey_source.covered_competitors == ["Cursor"]
    assert interview_source.covered_competitors == ["Cursor"]
    assert record.detail.competitor_knowledge["Cursor"].user_personas.summary_claims
    completed = next(
        event
        for event in service.get_trace(detail.id) or []
        if event.type == "node_completed" and event.agent == "survey_interview"
    )
    assert completed.payload["source_types"] == ["interview_record", "survey_simulated"]
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
    assert replay_event.payload["source_types"] == ["interview_record", "survey_simulated"]
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


def test_real_collect_qa_blocks_unverified_url_evidence_without_memory_policy() -> None:
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
        id="run-real-strict-source",
        topic="AI coding assistant feature review",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="source-feature-search",
                competitor="Cursor",
                dimension="feature",
                source_type="web_search_result",
                title="Cursor feature search lead",
                url="https://example.com/cursor-feature",
                snippet="Search-only feature evidence mentions feature and api support.",
                content_hash="hash-feature-search",
                confidence=0.62,
            )
        ],
    )

    issues = service._build_collect_qa_issues(detail)

    assert issues
    assert issues[0].severity == "blocker"
    assert "not fetched webpage evidence" in issues[0].problem


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
    assert windsurf[0].url == "https://docs.windsurf.com/plugins/cascade/cascade-overview"


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
        input_text=("contact alice@example.com with OPENROUTER_TEST_KEY_REDACTED"),
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

    assert len(issues) == 1
    assert issues[0].id.startswith("qc-issue-")
    assert issues[0].severity == "blocker"
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

    assert len(issues) == 1
    assert issues[0].id.startswith("qc-issue-")
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

    phantom = [issue for issue in issues if "pricing-404" in issue.problem]
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


@pytest.mark.asyncio
async def test_reflector_prompt_includes_comparison_matrix_digest() -> None:
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
    captured_user = ""

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        nonlocal captured_user
        captured_user = user
        return {
            "coverage_gaps": [],
            "confidence_outliers": [],
            "cross_competitor_gaps": [],
            "suggested_redo_dimension": None,
        }

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Reflector matrix digest",
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
            snippet="A publishes pricing.",
            content_hash="pricing-a-hash",
            confidence=0.9,
        ),
        RawSource(
            id="pricing-b",
            competitor="B",
            dimension="pricing",
            source_type="webpage_verified",
            title="B pricing",
            url="https://b.example/pricing",
            snippet="B publishes pricing.",
            content_hash="pricing-b-hash",
            confidence=0.9,
        ),
    ]
    record.detail.comparison_matrix = ComparisonMatrix(
        competitors=["A", "B"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="A",
                dimension="pricing",
                value="A publishes pricing.",
                source_ids=["pricing-a"],
                confidence=0.9,
            ),
            ComparisonCell(
                competitor="B",
                dimension="pricing",
                value="B publishes pricing.",
                source_ids=["pricing-b"],
                confidence=0.9,
            ),
        ],
        winner_by_dimension={"pricing": "tie"},
        summary=["[majority-vote:pricing] winner=tie; evidence=tie"],
    )

    await service._real_reflector_step(record)

    assert "Comparison Matrix JSON:" in captured_user
    assert '"source_ids": ["pricing-a"]' in captured_user
    assert record.detail.reflections[-1].cross_competitor_gaps == []


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
    assert all(issue.id.startswith("qc-issue-") for issue in issues)
    assert {"collector", "analyst", "writer_only", "comparator"}.issubset(
        {issue.redo_scope.kind for issue in issues}
    )


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

    assert len(issues) == 1
    assert issues[0].id.startswith("qc-issue-")
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

    assert "tier_name=Extracted pricing tier 1" in matrix.cells[0].value
    assert "price=$10" in matrix.cells[0].value
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
    vote_line = next(item for item in matrix.summary if item.startswith("[majority-vote:pricing]"))
    assert "confidence=A" not in vote_line
    assert "cell_confidence_winner=A" in vote_line


def test_comparison_matrix_pricing_confidence_signal_cannot_break_structural_tie() -> None:
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
                id="pricing-a",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://a.example/pricing",
                snippet="A has pricing.",
                content_hash="pricing-a",
                confidence=0.96,
            ),
            RawSource(
                id="pricing-b",
                competitor="B",
                dimension="pricing",
                source_type="webpage_verified",
                title="B pricing",
                url="https://b.example/pricing",
                snippet="B has pricing.",
                content_hash="pricing-b",
                confidence=0.8,
            ),
        ],
    )
    service._merge_kb_slice(
        detail,
        "pricing",
        {"A": ["A has pricing evidence."], "B": ["B has pricing evidence."]},
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert matrix.winner_by_dimension["pricing"] == "tie"
    vote_line = next(item for item in matrix.summary if item.startswith("[majority-vote:pricing]"))
    assert "cell_confidence_winner=A" in vote_line
    assert "evidence=tie" in vote_line
    assert "findings=tie" in vote_line


def test_comparison_matrix_adds_pricing_and_persona_standardization_summary() -> None:
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
        plan=AnalysisPlan(topic="Test", competitors=["A", "B"], dimensions=["pricing", "persona"]),
        competitor_knowledge={
            "A": CompetitorKnowledge(
                competitor="A",
                pricing_model={
                    "tiers": [
                        {
                            "name": "Free",
                            "price": "$0",
                            "billing_cycle": "monthly",
                            "claims": [
                                {
                                    "claim": "A has a free plan.",
                                    "source_ids": ["pricing-a"],
                                    "confidence": 0.9,
                                }
                            ],
                        }
                    ]
                },
                user_personas={
                    "segments": [
                        {
                            "name": "Developer",
                            "role": "engineering",
                            "company_size": "individual",
                            "use_cases": ["code generation"],
                            "pain_points": ["context switching"],
                            "claims": [
                                {
                                    "claim": "A targets developers.",
                                    "source_ids": ["persona-a"],
                                    "confidence": 0.86,
                                }
                            ],
                        }
                    ]
                },
            ),
            "B": CompetitorKnowledge(
                competitor="B",
                pricing_model={
                    "tiers": [
                        {
                            "name": "Team",
                            "price": "$10 per seat",
                            "billing_cycle": "monthly",
                            "claims": [
                                {
                                    "claim": "B has a team plan.",
                                    "source_ids": ["pricing-b"],
                                    "confidence": 0.85,
                                }
                            ],
                        }
                    ]
                },
                user_personas={
                    "segments": [
                        {
                            "name": "Enterprise buyer",
                            "role": "procurement",
                            "company_size": "enterprise",
                            "use_cases": ["vendor evaluation", "governance"],
                            "pain_points": ["risk"],
                            "claims": [
                                {
                                    "claim": "B targets enterprise buyers.",
                                    "source_ids": ["persona-b"],
                                    "confidence": 0.84,
                                }
                            ],
                        }
                    ]
                },
            ),
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert any(
        item.startswith("[pricing-standardization:pricing]")
        and "aligned_fields=tier_name,price,billing_cycle,limits" in item
        and "A tiers=Free=$0/monthly" in item
        and "B tiers=Team=$10 per seat/monthly" in item
        for item in matrix.summary
    )
    assert any(
        item.startswith("[persona-standardization:persona]")
        and "aligned_fields=segment,role,company_size,use_cases,pain_points" in item
        and "A segments=Developer(engineering/individual;use_cases=1;pain_points=1)" in item
        and "B segments=Enterprise buyer(procurement/enterprise;use_cases=2;pain_points=1)" in item
        for item in matrix.summary
    )
    pricing_cell = next(
        cell for cell in matrix.cells if cell.competitor == "A" and cell.dimension == "pricing"
    )
    persona_cell = next(
        cell for cell in matrix.cells if cell.competitor == "A" and cell.dimension == "persona"
    )
    assert "tier_name=Free; price=$0; billing_cycle=monthly" in pricing_cell.value
    b_pricing_cell = next(
        cell for cell in matrix.cells if cell.competitor == "B" and cell.dimension == "pricing"
    )
    assert "limits=not stated in collected source" in b_pricing_cell.value
    assert "segment=Developer; role=engineering; company_size=individual" in persona_cell.value
    assert "use_cases=code generation; pain_points=context switching" in persona_cell.value


def test_comparison_matrix_caps_confidence_by_structured_claims() -> None:
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
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["persona"]),
        raw_sources=[
            RawSource(
                id="persona-official",
                competitor="A",
                dimension="persona",
                source_type="webpage_verified",
                title="A customers",
                url="https://a.example/customers",
                snippet="A is used by developers and enterprise teams.",
                content_hash="persona-official-hash",
                confidence=0.96,
            ),
            RawSource(
                id="persona-survey",
                competitor="A",
                dimension="persona",
                source_type="survey_simulated",
                title="A persona survey",
                url=None,
                snippet="Surveyed developers cite context switching.",
                content_hash="persona-survey-hash",
                confidence=0.62,
            ),
        ],
        competitor_knowledge={
            "A": CompetitorKnowledge(
                competitor="A",
                user_personas={
                    "segments": [
                        {
                            "name": "Developer",
                            "role": "engineering",
                            "company_size": "team",
                            "use_cases": ["daily coding"],
                            "pain_points": ["context switching"],
                            "claims": [
                                {
                                    "claim": "A targets developers.",
                                    "source_ids": ["persona-survey"],
                                    "confidence": 0.62,
                                }
                            ],
                        }
                    ]
                },
            )
        },
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"persona": ["A targets developers. [source:persona-survey]"]},
                sources=["persona-survey"],
                confidence=0.62,
            )
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert matrix.cells[0].confidence == pytest.approx(0.62)


def test_comparison_matrix_caps_persona_confidence_by_user_research_source() -> None:
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
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["persona"]),
        raw_sources=[
            RawSource(
                id="persona-official",
                competitor="A",
                dimension="persona",
                source_type="webpage_verified",
                title="A customers",
                url="https://a.example/customers",
                snippet="A is used by developers and enterprise teams.",
                content_hash="persona-official-hash",
                confidence=0.96,
            ),
            RawSource(
                id="persona-interview",
                competitor="A",
                dimension="persona",
                source_type="interview_record",
                title="A persona interview",
                url=None,
                snippet="Interviewed developers cite context switching.",
                content_hash="persona-interview-hash",
                confidence=0.62,
            ),
        ],
        competitor_knowledge={
            "A": CompetitorKnowledge(
                competitor="A",
                user_personas={
                    "segments": [
                        {
                            "name": "Developer",
                            "role": "engineering",
                            "company_size": "team",
                            "use_cases": ["daily coding"],
                            "pain_points": ["context switching"],
                            "claims": [
                                {
                                    "claim": "A targets developers.",
                                    "source_ids": ["persona-official"],
                                    "confidence": 0.9,
                                }
                            ],
                        }
                    ]
                },
            )
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert matrix.cells[0].confidence == pytest.approx(0.62)


def test_comparison_matrix_adds_feature_standardization_summary() -> None:
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
        competitor_knowledge={
            "A": CompetitorKnowledge(
                competitor="A",
                feature_tree={
                    "nodes": [
                        {
                            "name": "Agentic coding",
                            "description": "Multi-file edits and tool use.",
                            "claims": [
                                {
                                    "claim": "A supports agentic coding.",
                                    "source_ids": ["feature-a"],
                                    "confidence": 0.88,
                                }
                            ],
                            "children": [
                                {
                                    "name": "Terminal tools",
                                    "description": "Runs terminal tasks.",
                                    "claims": [
                                        {
                                            "claim": "A can use terminal tools.",
                                            "source_ids": ["feature-a"],
                                            "confidence": 0.84,
                                        }
                                    ],
                                    "children": [],
                                }
                            ],
                        }
                    ]
                },
            ),
            "B": CompetitorKnowledge(
                competitor="B",
                feature_tree={
                    "nodes": [
                        {
                            "name": "Autocomplete",
                            "description": "Inline suggestions.",
                            "claims": [
                                {
                                    "claim": "B supports autocomplete.",
                                    "source_ids": ["feature-b"],
                                    "confidence": 0.82,
                                }
                            ],
                            "children": [],
                        }
                    ]
                },
            ),
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert any(
        item.startswith("[feature-standardization:feature]")
        and "aligned_fields=feature_name,description,claim_count,child_count" in item
        and "A features=Agentic coding(Multi-file edits and tool use.;claims=1;children=1)" in item
        and "B features=Autocomplete(Inline suggestions.;claims=1;children=0)" in item
        for item in matrix.summary
    )
    feature_cell = next(
        cell for cell in matrix.cells if cell.competitor == "A" and cell.dimension == "feature"
    )
    assert (
        "feature_name=Agentic coding; description=Multi-file edits and tool use."
        in feature_cell.value
    )
    assert "claim_count=1; child_count=1" in feature_cell.value


def test_comparison_matrix_prioritizes_taxonomy_feature_nodes() -> None:
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
        competitor_knowledge={
            "A": CompetitorKnowledge(
                competitor="A",
                feature_tree={
                    "nodes": [
                        {
                            "name": "Generic feature",
                            "description": "A model-generated generic feature node.",
                            "claims": [],
                            "children": [],
                        },
                        {
                            "name": "Repository context",
                            "description": "Codebase and repository understanding.",
                            "claims": [],
                            "children": [],
                        },
                        {
                            "name": "Code completion",
                            "description": "Inline suggestions and completion assistance.",
                            "claims": [],
                            "children": [],
                        },
                    ]
                },
            )
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})
    feature_cell = matrix.cells[0]

    assert feature_cell.value.startswith("feature_name=Code completion")
    assert feature_cell.value.index("Repository context") < feature_cell.value.index(
        "Generic feature"
    )


def test_writer_and_reflector_digests_preserve_feature_matrix_cells() -> None:
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
    long_feature_value = " | ".join(
        [
            (f"feature_name={name}; description={description}; claim_count=1; child_count=0")
            for name, description in [
                ("Code completion", "Inline suggestions and completion assistance."),
                ("Agentic coding", "Multi-file edits and refactoring workflows."),
                ("Chat and Q&A", "Conversational repository question answering."),
                ("IDE integration", "Editor extension and plugin integration."),
                ("Code review and security", "Pull request and security scanning."),
                ("Tool and terminal use", "Terminal commands and external tool actions."),
                (
                    "Enterprise administration",
                    "Team, organization, policy, and SSO administration.",
                ),
            ]
        ]
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["feature"]),
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["feature"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="feature",
                    value=long_feature_value,
                    source_ids=["feature-a"],
                    confidence=0.9,
                )
            ],
            winner_by_dimension={"feature": "A"},
            summary=[f"[feature-standardization:feature] {long_feature_value}"],
        ),
    )

    writer_digest = service._writer_matrix_digest(detail)
    reflector_digest = service._reflector_matrix_digest(detail)

    assert "Enterprise administration" in writer_digest["cells"][0]["value"]
    assert "Enterprise administration" in reflector_digest["cells"][0]["value"]
    assert "Enterprise administration" in writer_digest["summary"][0]


def test_writer_and_reflector_digests_preserve_pricing_matrix_cells() -> None:
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
    long_pricing_value = " | ".join(
        [
            (f"tier_name={name}; price={price}; billing_cycle={cycle}; limits={limits}")
            for name, price, cycle, limits in [
                ("Free", "$0", "monthly", "2,000 completions, limited chat"),
                ("Pro", "$10/user", "monthly", "higher completions and chat quota"),
                ("Business", "$19/user", "monthly", "organization controls and policy"),
                ("Team", "$40/user", "monthly", "team admin controls and pooled usage"),
                ("Enterprise", "custom", "annual", "SSO, audit, support, and governance"),
                ("Usage add-on", "metered", "usage-based", "additional premium requests"),
            ]
        ]
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value=long_pricing_value,
                    source_ids=["pricing-a"],
                    confidence=0.9,
                )
            ],
            winner_by_dimension={"pricing": "A"},
            summary=[f"[pricing-standardization:pricing] {long_pricing_value}"],
        ),
    )

    writer_digest = service._writer_matrix_digest(detail)
    reflector_digest = service._reflector_matrix_digest(detail)

    assert "Usage add-on" in writer_digest["cells"][0]["value"]
    assert "Usage add-on" in reflector_digest["cells"][0]["value"]
    assert "Usage add-on" in writer_digest["summary"][0]


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

    matrix = [issue for issue in issues if "pricing-404" in issue.problem]
    assert len(matrix) == 1
    assert matrix[0].id.startswith("qc-issue-")
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

    matrix = [issue for issue in issues if "feature-1" in issue.problem]
    assert len(matrix) == 1
    assert matrix[0].id.startswith("qc-issue-")
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

    matrix = [issue for issue in issues if "missing the pricing cell for B" in issue.problem]
    assert len(matrix) == 1
    assert matrix[0].id.startswith("qc-issue-")
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


@pytest.mark.asyncio
async def test_writer_uses_compact_context_package_for_llm_prompt() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=5,
        ),
    )
    captured_user = ""

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        nonlocal captured_user
        captured_user = user
        return "# A vs B\n\nA has stronger pricing evidence. [source:pricing-a]"

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer compact context",
            competitors=["A", "B"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    long_snippet = "A pricing is published. " + ("long-context-token " * 400)
    record.detail.raw_sources = [
        RawSource(
            id="pricing-a",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://a.example/pricing",
            snippet=long_snippet,
            content_hash="pricing-a-hash",
            confidence=0.95,
        )
    ]
    record.detail.comparison_matrix = ComparisonMatrix(
        competitors=["A", "B"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="A",
                dimension="pricing",
                value="A has stronger pricing evidence.",
                source_ids=["pricing-a"],
                confidence=0.95,
            )
        ],
        winner_by_dimension={"pricing": "A"},
        summary=["A wins the pricing evidence vote."],
    )
    service._merge_kb_slice(record.detail, "pricing", {"A": [long_snippet]})

    await service._real_writer_step(record)

    assert "Writer Context JSON:" in captured_user
    assert "under 4,500 characters" in captured_user
    assert "Competitor KB JSON:" not in captured_user
    assert "Competitor Knowledge Schema JSON:" not in captured_user
    assert len(captured_user) < 15000
    assert captured_user.count("long-context-token") < 80
    assert record.detail.agent_messages[-1].payload["writer_mode"] == "real LLM call"


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
async def test_real_search_result_fetch_failure_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202 - test double mirrors async tool shape.
        return None

    monkeypatch.setattr("packages.agents.collectors.logic.fetch_evidence_page", fake_fetch_page)
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
            snippet="A pricing starts at $10 per seat.",
        ),
    )

    assert source is None


@pytest.mark.asyncio
async def test_demo_search_result_can_remain_unverified_raw_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202 - test double mirrors async tool shape.
        return None

    monkeypatch.setattr("packages.agents.collectors.logic.fetch_evidence_page", fake_fetch_page)
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
        execution_mode="demo",
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
            snippet="A pricing starts at $10 per seat.",
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

    assert pricing_candidates[0].url == "https://docs.windsurf.com/windsurf/accounts/usage"
    assert feature_candidates[0].url == "https://docs.windsurf.com/plugins/cascade/cascade-overview"
    assert persona_candidates[0].url == "https://docs.windsurf.com/windsurf/getting-started"
    stale_windsurf_urls = {
        "https://windsurf.com/pricing",
        "https://windsurf.com/plans",
        "https://windsurf.com/customers",
        "https://windsurf.com/use-cases",
    }
    assert not any(item.url in stale_windsurf_urls for item in pricing_candidates[:2])
    assert not any(item.url in stale_windsurf_urls for item in persona_candidates[:2])
    assert not any("accounts/usage" in item.url for item in persona_candidates[:2])


def test_collector_official_source_candidates_include_llm_registry_seeds() -> None:
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
        topic="Most Powerful LLM",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(
            topic="Most Powerful LLM",
            competitors=["GPT-5.5", "Claude", "Gemini", "Llama 4"],
            dimensions=["pricing", "feature"],
        ),
    )

    gpt_pricing = service._official_source_candidates(detail, "GPT-5.5", "pricing")
    claude_features = service._official_source_candidates(detail, "Claude", "feature")
    gemini_pricing = service._official_source_candidates(detail, "Gemini", "pricing")
    llama_features = service._official_source_candidates(detail, "Llama 4", "feature")
    openai_persona = service._official_source_candidates(detail, "GPT-5.5", "persona")

    assert any("developers.openai.com" in item.url for item in gpt_pricing)
    assert any("anthropic.com" in item.url for item in claude_features)
    assert any("ai.google.dev" in item.url for item in gemini_pricing)
    assert any("ai.meta.com" in item.url or "llama.com" in item.url for item in llama_features)
    assert len(openai_persona) >= 3
    assert any("chatgpt/enterprise" in item.url for item in openai_persona)
    assert any("help.openai.com" in item.url for item in openai_persona)


@pytest.mark.asyncio
async def test_collector_official_source_collection_collects_configured_target() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            collector_target_verified_sources_per_branch=3,
            collector_search_max_results=6,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Most Powerful LLM",
            competitors=["GPT-5.5"],
            dimensions=["persona"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="persona::GPT-5.5")
    fetch_calls: list[str] = []

    async def fake_trace_fetch(  # noqa: ANN001
        record,
        agent,
        subagent,
        url,
        context=None,
    ) -> EvidenceFetchResult:
        fetch_calls.append(url)
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title=f"Official source {len(fetch_calls)}",
            text=(
                "Customer user buyer persona case study evidence for enterprise teams "
                "evaluating GPT-5.5 adoption, workflow fit, onboarding, support, "
                f"and use cases. Source URL: {url}"
            ),
            content_hash=f"hash-{len(fetch_calls)}",
            status_code=200,
            fetch_method="test_fetch",
            quality_score=0.95,
            text_length=180,
        )

    service._trace_fetch = fake_trace_fetch  # type: ignore[method-assign]

    sources = await service._collect_official_sources(
        record,
        record.detail,
        "persona",
        "GPT-5.5",
        context,
    )

    assert len(sources) == 3
    assert len(fetch_calls) == 3
    assert all(source.source_type == "webpage_verified" for source in sources)
    assert len({source.url for source in sources}) == 3
    registry_span = next(
        span for span in record.detail.trace_spans if span.name == "official_source_registry"
    )
    assert registry_span.metadata["source_count"] == 3
    assert registry_span.metadata["target_source_count"] == 3


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


def test_collector_rejects_soft_404_verified_sources() -> None:
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
    source = RawSource(
        id="persona-soft-404",
        competitor="Windsurf",
        dimension="persona",
        source_type="webpage_verified",
        title="404: This page could not be found",
        url="https://windsurf.com/customers",
        snippet=(
            "This page could not be found. Windsurf customers, developers, enterprise "
            "teams, and use cases are mentioned only in navigation."
        ),
        content_hash="soft-404-hash",
        confidence=0.96,
    )

    assert "soft 404" in (service._source_quality_problem(source) or "")


def test_collector_accepts_windsurf_docs_redirect_sources() -> None:
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
    source = RawSource(
        id="persona-windsurf-docs",
        competitor="Windsurf",
        dimension="persona",
        source_type="webpage_verified",
        title="Welcome to Windsurf - Windsurf Docs",
        url="https://docs.devin.ai/desktop/getting-started",
        snippet=(
            "Windsurf is a next-generation AI IDE built for developers, engineering "
            "teams, enterprise users, and AI-powered coding workflows."
        ),
        content_hash="windsurf-docs-hash",
        confidence=0.96,
    )

    assert service._source_quality_problem(source) is None


def test_collector_accepts_windsurf_feature_docs_redirect_sources() -> None:
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
    source = RawSource(
        id="feature-windsurf-docs",
        competitor="Windsurf",
        dimension="feature",
        source_type="webpage_verified",
        title="Windsurf - Cascade",
        url="https://docs.devin.ai/windsurf/plugins/cascade/cascade-overview",
        snippet=(
            "Windsurf Cascade brings agentic AI coding to JetBrains with Write/Chat "
            "modes, voice input, tool access, turbo mode, autocomplete, MCP, and "
            "real-time collaboration."
        ),
        content_hash="windsurf-feature-docs-hash",
        confidence=0.84,
    )

    assert service._source_quality_problem(source) is None


def test_collector_rejects_pricing_pages_as_persona_evidence() -> None:
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
    source = RawSource(
        id="persona-pricing-page",
        competitor="Windsurf",
        dimension="persona",
        source_type="webpage_verified",
        title="Plans and Usage - Devin Docs",
        url="https://docs.devin.ai/desktop/accounts/usage",
        snippet=(
            "Paid plans include Pro for individuals, Teams for organizations, and "
            "Enterprise for larger companies with usage tracking."
        ),
        content_hash="persona-pricing-page-hash",
        confidence=0.9,
    )

    assert "mismatched for persona evidence" in (service._source_quality_problem(source) or "")


def test_collector_keeps_feature_docs_when_navigation_contains_feature_facts() -> None:
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
    source = RawSource(
        id="feature-windsurf-nav-docs",
        competitor="Windsurf",
        dimension="feature",
        source_type="webpage_verified",
        title="Windsurf - Cascade",
        url="https://docs.devin.ai/windsurf/plugins/cascade/cascade-overview",
        snippet=(
            "Skip to main content Open menu Resources Docs Changelog Features "
            "Cascade (JetBrains) Overview Models Web and Docs Search Memories & Rules "
            "Model Context Protocol (MCP). Cascade brings agentic AI coding to "
            "JetBrains with Write/Chat modes and tool access."
        ),
        content_hash="windsurf-feature-nav-docs-hash",
        confidence=0.84,
    )

    assert service._source_quality_problem(source) is None


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

    monkeypatch.setattr("packages.agents.collectors.logic.fetch_evidence_page", fake_fetch_page)
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
        event for event in events if event.type == "node_completed" and event.agent == "collector"
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
                snippet=(
                    f"A {dimension} pricing plan is $20 per month for team users "
                    "and includes enterprise billing."
                ),
                content_hash=f"{dimension}-hash",
                confidence=0.96,
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
                snippet=(
                    "A pricing plan is $20 per month for team users and includes "
                    "enterprise billing."
                ),
                content_hash="pricing-hash",
                confidence=0.96,
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
                snippet=(
                    "A pricing plan is $20 per month for team users and includes "
                    "enterprise billing."
                ),
                content_hash=f"pricing-hash-{len(record.detail.raw_sources) + 1}",
                confidence=0.96,
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

    monkeypatch.setattr("packages.orchestrator.service.fetch_evidence_page", fake_fetch_page)
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

    monkeypatch.setattr("packages.orchestrator.service.fetch_evidence_page", fake_fetch_page)
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
            "snippet": "A publishes a $10 per month plan with 2,000 completions per month.",
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
    assert pricing["pricing_model"]["tiers"][0]["price"] == "$10 per month"
    assert pricing["pricing_model"]["tiers"][0]["billing_cycle"] == "monthly"
    assert pricing["pricing_model"]["tiers"][0]["limits"] == ["2,000 completions per month"]
    assert persona["user_personas"]["segments"][0]["claims"][0]["source_ids"] == ["pricing-a"]
    assert persona["user_personas"]["segments"][0]["use_cases"]


def test_deterministic_feature_payload_uses_shared_taxonomy() -> None:
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
            "id": "feature-a",
            "title": "A features",
            "snippet": (
                "A provides autocomplete, agentic multi-file edits, VS Code plugin "
                "support, terminal tool use, and repository context."
            ),
            "confidence": 0.9,
        }
    ]

    feature = service._deterministic_structured_knowledge_payload(
        competitor="A",
        dimension="feature",
        dimension_sources=sources,
    )

    node_names = [node["name"] for node in feature["feature_tree"]["nodes"]]
    assert node_names[:5] == [
        "Code completion",
        "Agentic coding",
        "IDE integration",
        "Tool and terminal use",
        "Repository context",
    ]
    assert all(node["description"] for node in feature["feature_tree"]["nodes"])
    assert feature["feature_tree"]["nodes"][0]["claims"][0]["source_ids"] == ["feature-a"]


def test_structured_feature_payload_appends_taxonomy_nodes_from_sources() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-a",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A features",
                url="https://a.example/features",
                snippet=(
                    "A supports autocomplete, pull request review, security scanning, "
                    "and enterprise admin policies."
                ),
                content_hash="feature-a-hash",
                confidence=0.9,
            )
        ],
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "feature",
        {
            "feature_tree": {
                "nodes": [
                    {
                        "name": "Generic feature",
                        "description": "A has feature evidence.",
                        "claims": [
                            {
                                "claim": "A has feature evidence.",
                                "source_ids": ["feature-a"],
                                "confidence": 0.9,
                            }
                        ],
                        "children": [],
                    }
                ],
                "summary_claims": [],
            }
        },
    )

    node_names = [node.name for node in detail.competitor_knowledge["A"].feature_tree.nodes]
    assert "Generic feature" in node_names
    assert "Code completion" in node_names
    assert "Code review and security" in node_names
    assert "Enterprise administration" in node_names


def test_structured_pricing_payload_enriches_unknown_fields_from_sources() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-a",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://a.example/pricing",
                snippet="A Pro costs $20/month and includes 500 premium requests.",
                content_hash="pricing-a-hash",
                confidence=0.9,
            )
        ],
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "pricing",
        {
            "pricing_model": {
                "tiers": [
                    {
                        "name": "Pro",
                        "price": "unknown",
                        "billing_cycle": "unknown",
                        "limits": [],
                        "claims": [
                            {
                                "claim": "A publishes Pro pricing.",
                                "source_ids": ["pricing-a"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
                "notes": [],
            }
        },
    )

    tier = detail.competitor_knowledge["A"].pricing_model.tiers[0]
    assert tier.price == "$20/month"
    assert tier.billing_cycle == "monthly"
    assert tier.limits == ["500 premium requests"]


def test_structured_pricing_payload_dedupes_free_tiers() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "pricing",
        {
            "pricing_model": {
                "tiers": [
                    {
                        "name": "Free",
                        "price": "$0",
                        "billing_cycle": "unknown",
                        "limits": ["2,000 completions per month"],
                        "claims": [
                            {
                                "claim": "A has a Free plan.",
                                "source_ids": ["pricing-a"],
                                "confidence": 0.9,
                            }
                        ],
                    },
                    {
                        "name": "Hobby",
                        "price": "Free",
                        "billing_cycle": "monthly",
                        "limits": ["limited chat messages"],
                        "claims": [
                            {
                                "claim": "A Hobby plan is free.",
                                "source_ids": ["pricing-b"],
                                "confidence": 0.8,
                            }
                        ],
                    },
                ],
                "notes": [],
            }
        },
    )

    tiers = detail.competitor_knowledge["A"].pricing_model.tiers
    assert len(tiers) == 1
    assert tiers[0].name == "Free"
    assert tiers[0].price == "$0"
    assert tiers[0].billing_cycle == "monthly"
    assert tiers[0].limits == ["2,000 completions per month", "limited chat messages"]
    assert [claim.source_ids for claim in tiers[0].claims] == [["pricing-a"], ["pricing-b"]]


def test_structured_pricing_payload_labels_duplicate_paid_tiers() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["Claude Code"], dimensions=["pricing"]),
    )

    service._merge_structured_knowledge_payload(
        detail,
        "Claude Code",
        "pricing",
        {
            "pricing_model": {
                "tiers": [
                    {
                        "name": "Enterprise",
                        "price": "$100/month",
                        "billing_cycle": "monthly",
                        "limits": ["usage tracking"],
                        "claims": [
                            {
                                "claim": "Claude Code has an enterprise cost reference.",
                                "source_ids": ["pricing-a"],
                                "confidence": 0.8,
                            }
                        ],
                    },
                    {
                        "name": "Enterprise",
                        "price": "$200/month",
                        "billing_cycle": "monthly",
                        "limits": ["expanded usage"],
                        "claims": [
                            {
                                "claim": "Claude Code has another enterprise cost reference.",
                                "source_ids": ["pricing-b"],
                                "confidence": 0.8,
                            }
                        ],
                    },
                    {
                        "name": "Enterprise",
                        "price": "custom",
                        "billing_cycle": "annual",
                        "limits": ["SSO"],
                        "claims": [
                            {
                                "claim": "Claude Code enterprise can be custom priced.",
                                "source_ids": ["pricing-c"],
                                "confidence": 0.8,
                            }
                        ],
                    },
                ],
                "notes": [],
            }
        },
    )

    tiers = detail.competitor_knowledge["Claude Code"].pricing_model.tiers
    assert [tier.name for tier in tiers] == [
        "Enterprise ($100/month)",
        "Enterprise ($200/month)",
        "Enterprise (custom)",
    ]
    assert len({tier.name for tier in tiers}) == 3
    assert all(tier.name != "Enterprise" for tier in tiers)


def test_structured_pricing_payload_standardizes_missing_paid_limit_metadata() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "pricing",
        {
            "pricing_model": {
                "tiers": [
                    {
                        "name": "Team",
                        "price": "$30 per user per month",
                        "billing_cycle": "unknown",
                        "limits": [],
                        "claims": [
                            {
                                "claim": "A publishes Team pricing.",
                                "source_ids": ["pricing-a"],
                                "confidence": 0.8,
                            }
                        ],
                    }
                ],
                "notes": [],
            }
        },
    )

    tier = detail.competitor_knowledge["A"].pricing_model.tiers[0]
    assert tier.billing_cycle == "monthly"
    assert tier.limits == ["not stated in collected source"]


def test_deterministic_pricing_payload_extracts_multiple_tiers() -> None:
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
            "snippet": (
                "Free plan includes 2,000 completions per month. "
                "Pro costs $20/month with 500 premium requests. "
                "Team costs $40 per user with unlimited completions."
            ),
            "confidence": 0.9,
        }
    ]

    pricing = service._deterministic_structured_knowledge_payload(
        competitor="A",
        dimension="pricing",
        dimension_sources=sources,
    )

    tiers = pricing["pricing_model"]["tiers"]
    assert [tier["name"] for tier in tiers[:3]] == ["Free", "Pro", "Team"]
    assert [tier["price"] for tier in tiers[:3]] == ["$0", "$20/month", "$40 per user"]
    assert tiers[0]["limits"] == ["2,000 completions per month"]
    assert tiers[1]["limits"] == ["500 premium requests"]
    assert tiers[2]["limits"] == ["unlimited completions"]


def test_deterministic_pricing_payload_maps_claude_code_max_tiers() -> None:
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
            "id": "claude-pricing",
            "title": "Claude Code pricing",
            "snippet": (
                "Claude Code is available for enterprise engineering teams. "
                "Pro costs $20/month. Max costs $100/month. "
                "Max 20x costs $200/month. Team costs $30 per user."
            ),
            "confidence": 0.9,
        }
    ]

    pricing = service._deterministic_structured_knowledge_payload(
        competitor="Claude Code",
        dimension="pricing",
        dimension_sources=sources,
    )

    tiers = pricing["pricing_model"]["tiers"]
    tier_names = [tier["name"] for tier in tiers]
    assert "Pro" in tier_names
    assert "Max" in tier_names
    assert "Team" in tier_names
    assert "Enterprise" not in tier_names
    assert [
        (tier["name"], tier["price"])
        for tier in tiers
        if tier["price"] in {"$100/month", "$200/month"}
    ] == [("Max", "$100/month"), ("Max", "$200/month")]


def test_structured_pricing_payload_appends_missing_paid_tiers_from_sources() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-a",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://a.example/pricing",
                snippet="Free plan is available. Pro costs $20/month with 500 premium requests.",
                content_hash="pricing-a-hash",
                confidence=0.9,
            )
        ],
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "pricing",
        {
            "pricing_model": {
                "tiers": [
                    {
                        "name": "Free",
                        "price": "$0",
                        "billing_cycle": "unknown",
                        "limits": [],
                        "claims": [
                            {
                                "claim": "A has a free plan.",
                                "source_ids": ["pricing-a"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
                "notes": [],
            }
        },
    )

    tiers = detail.competitor_knowledge["A"].pricing_model.tiers
    assert [(tier.name, tier.price) for tier in tiers] == [("Free", "$0"), ("Pro", "$20/month")]
    assert tiers[1].limits == ["500 premium requests"]


def test_structured_persona_payload_enriches_unknown_fields_from_sources() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["persona"]),
        raw_sources=[
            RawSource(
                id="persona-a",
                competitor="A",
                dimension="persona",
                source_type="webpage_verified",
                title="A customers",
                url="https://a.example/customers",
                snippet=(
                    "A is used by enterprise engineering teams and developers in "
                    "large codebases to reduce context switching during pull requests."
                ),
                content_hash="persona-a-hash",
                confidence=0.9,
            )
        ],
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "persona",
        {
            "user_personas": {
                "segments": [
                    {
                        "name": "unknown",
                        "role": "unknown",
                        "company_size": "unknown",
                        "pain_points": [],
                        "use_cases": [],
                        "claims": [
                            {
                                "claim": "A targets developers.",
                                "source_ids": ["persona-a"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
                "summary_claims": [],
            }
        },
    )

    segment = detail.competitor_knowledge["A"].user_personas.segments[0]
    assert segment.name == "Enterprise engineering teams"
    assert segment.role == "developer"
    assert segment.company_size == "enterprise"
    assert segment.pain_points == [
        "context switching",
        "large codebase maintenance",
        "code review throughput",
    ]
    assert segment.use_cases == ["code review"]


def test_deterministic_persona_payload_extracts_multiple_market_segments() -> None:
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
            "id": "persona-a",
            "title": "A customers",
            "snippet": (
                "A supports individual developers, SMB startup engineering teams, "
                "and enterprise organizations using IDE workflows to reduce "
                "context switching."
            ),
            "confidence": 0.9,
        }
    ]

    persona = service._deterministic_structured_knowledge_payload(
        competitor="A",
        dimension="persona",
        dimension_sources=sources,
    )

    segments = persona["user_personas"]["segments"]
    assert [segment["company_size"] for segment in segments] == [
        "individual",
        "startup",
        "enterprise",
    ]
    assert [segment["name"] for segment in segments] == [
        "Individual developers",
        "SMB and startup engineering teams",
        "Enterprise engineering teams",
    ]
    assert all("IDE workflow" in segment["use_cases"] for segment in segments)


def test_structured_persona_payload_appends_non_enterprise_segments_from_sources() -> None:
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
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["persona"]),
        raw_sources=[
            RawSource(
                id="persona-a",
                competitor="A",
                dimension="persona",
                source_type="webpage_verified",
                title="A customers",
                url="https://a.example/customers",
                snippet=(
                    "A targets individual developers, SMB startup teams, and "
                    "enterprise organizations for agentic IDE workflows."
                ),
                content_hash="persona-a-hash",
                confidence=0.9,
            )
        ],
    )

    service._merge_structured_knowledge_payload(
        detail,
        "A",
        "persona",
        {
            "user_personas": {
                "segments": [
                    {
                        "name": "Enterprise engineering teams",
                        "role": "developer",
                        "company_size": "enterprise",
                        "pain_points": [],
                        "use_cases": [],
                        "claims": [
                            {
                                "claim": "A targets enterprise teams.",
                                "source_ids": ["persona-a"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
                "summary_claims": [],
            }
        },
    )

    segments = detail.competitor_knowledge["A"].user_personas.segments
    assert [segment.company_size for segment in segments] == [
        "enterprise",
        "individual",
        "startup",
    ]
    assert segments[1].name == "Individual developers"
    assert segments[2].name == "SMB and startup engineering teams"


def test_persona_segment_names_are_competitor_specific() -> None:
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

    assert (
        service._extract_persona_segment_name("Developers use Cursor.", "Cursor")
        == "Cursor AI-native IDE developers"
    )
    assert (
        service._extract_persona_segment_name("Developers use Claude.", "Claude Code")
        == "Claude Code agentic coding teams"
    )
    assert (
        service._extract_persona_segment_name("Developers use Windsurf.", "Windsurf")
        == "Windsurf Cascade IDE developers"
    )


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
