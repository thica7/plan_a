from dataclasses import asdict
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from packages.agents import SubagentContext
from packages.agents.writer.prompt_builder import WriterPromptBuilder
from packages.business_intel.homepage import HomepageVerification
from packages.config import Settings
from packages.identity import compute_workflow_idempotency_key
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService, _active_run_fingerprint
from packages.research.models import RepairTask, ResearchBrief
from packages.research.pipeline import _repair_brief
from packages.schema import models
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest, RunDetail
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.evidence_fetch import EvidenceFetchResult
from packages.workflows.activities import CompetitiveIntelActivities
from packages.workflows.models import CompetitiveIntelWorkflowInput
from packages.workflows.service import (
    competitive_intel_input_from_run_request,
    workflow_idempotency_key,
)


def _request(**overrides: object) -> RunCreateRequest:
    payload = dict(
        topic="AI coding assistant comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        execution_mode="demo",
    )
    payload.update(overrides)
    return RunCreateRequest(**payload)


def _service(*, hitl_enabled: bool = False) -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, hitl_enabled=hitl_enabled),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


def test_research_modes_contract_accepts_optional_brief_and_limits_text() -> None:
    brief_type = models.DecisionBrief
    assert brief_type().model_dump() == {
        "decision_question": "",
        "primary_job": "",
        "success_metric": "",
    }
    request = _request(
        research_depth="deep",
        collaboration_mode="assisted",
        decision_brief={
            "decision_question": "Which product should we build?",
            "primary_job": "Choose a product direction",
            "success_metric": "Decision made",
        },
    )
    assert isinstance(request.decision_brief, brief_type)
    assert request.decision_brief.decision_question == "Which product should we build?"
    with pytest.raises(ValidationError):
        brief_type(decision_question="x" * 501)
    with pytest.raises(ValidationError):
        _request(research_depth="unlimited")
    with pytest.raises(ValidationError):
        _request(collaboration_mode="manual")


@pytest.mark.parametrize(
    ("collaboration_mode", "hitl_enabled"),
    [("ai", True), ("assisted", False)],
)
def test_conflicting_explicit_collaboration_and_hitl_are_rejected(
    collaboration_mode: str,
    hitl_enabled: bool,
) -> None:
    with pytest.raises(ValidationError, match="collaboration_mode"):
        _request(collaboration_mode=collaboration_mode, hitl_enabled=hitl_enabled)


@pytest.mark.asyncio
async def test_run_persists_research_modes_and_collaboration_controls_hitl() -> None:
    service = _service(hitl_enabled=True)
    request = _request(
        research_depth="quick",
        collaboration_mode="ai",
        decision_brief={"decision_question": "Where should we invest?"},
    )
    detail = await service.create_run(request)

    assert detail.plan.research_depth == "quick"
    assert detail.plan.collaboration_mode == "ai"
    assert detail.plan.decision_brief == request.decision_brief
    assert detail.hitl_enabled is False
    assert service.get_run(detail.id).plan.decision_brief == request.decision_brief


@pytest.mark.asyncio
async def test_legacy_request_keeps_hitl_defaults_and_workflow_key() -> None:
    service = _service(hitl_enabled=True)
    request = _request()
    detail = await service.create_run(request)

    assert request.research_depth is None
    assert request.collaboration_mode is None
    assert request.decision_brief is None
    assert detail.plan.research_depth is None
    assert detail.plan.collaboration_mode is None
    assert detail.plan.decision_brief is None
    assert detail.hitl_enabled is True

    old_payload = request.model_dump(
        mode="json",
        exclude={"idempotency_key", "research_depth", "collaboration_mode", "decision_brief"},
    )
    assert workflow_idempotency_key(request) == compute_workflow_idempotency_key(old_payload)


def test_active_run_fingerprint_includes_each_explicit_research_mode_field() -> None:
    common = dict(
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        competitor_layer=None,
        scenario_id=None,
        execution_mode="demo",
        output_language="zh-CN",
        auto_redo_warn_enabled=False,
        hitl_enabled=False,
    )
    legacy = _active_run_fingerprint(**common)
    assert _active_run_fingerprint(**common, research_depth="quick") != legacy
    assert _active_run_fingerprint(**common, collaboration_mode="ai") != legacy
    assert _active_run_fingerprint(
        **common,
        decision_brief=models.DecisionBrief(decision_question="Build or buy?"),
    ) != legacy


@pytest.mark.asyncio
async def test_temporal_round_trip_preserves_research_modes_to_run_plan() -> None:
    from temporalio.converter import DataConverter

    service = _service()
    request = _request(
        idempotency_key="research-modes-temporal-roundtrip",
        research_depth="deep",
        collaboration_mode="assisted",
        decision_brief={
            "decision_question": "Which segment first?",
            "primary_job": "Choose a launch segment",
            "success_metric": "Segment approved",
        },
    )
    workflow_input = competitive_intel_input_from_run_request(request)
    payloads = await DataConverter.default.encode([workflow_input])
    [decoded] = await DataConverter.default.decode(
        payloads, [CompetitiveIntelWorkflowInput]
    )
    assert asdict(decoded)["decision_brief"] == request.decision_brief.model_dump()

    result = await CompetitiveIntelActivities(service).create_run(decoded)
    detail = service.get_run(result.run_id)
    assert detail.plan.research_depth == "deep"
    assert detail.plan.collaboration_mode == "assisted"
    assert detail.plan.decision_brief == request.decision_brief
    assert detail.hitl_enabled is True


def test_research_depth_budget_table_is_exact_and_monotonic() -> None:
    from packages.research.budget import research_depth_budget

    expected = {
        "quick": (2, 2, 1, 6, 3, 1, 0, 60, "4,000-6,000", 6, 1, 1),
        "standard": (5, 3, 2, 10, 5, 2, 1, 120, "8,000-12,000", 12, 2, 2),
        "deep": (8, 5, 3, 16, 8, 3, 2, 160, "16,000-20,000", 24, 3, 3),
    }
    fields = (
        "competitor_limit", "target_sources", "max_search_queries",
        "max_candidates", "max_fetches", "max_advanced_fetches",
        "max_repair_rounds", "llm_max_calls", "report_chars",
        "max_slices", "collector_max_turns", "analyst_max_turns",
    )
    budgets = [research_depth_budget(depth) for depth in expected]
    for depth, budget in zip(expected, budgets, strict=True):
        assert tuple(getattr(budget, field) for field in fields) == expected[depth]
    for field in fields[:8] + fields[9:]:
        assert getattr(budgets[0], field) <= getattr(budgets[1], field)
        assert getattr(budgets[1], field) <= getattr(budgets[2], field)
    assert research_depth_budget(None) is None


@pytest.mark.asyncio
async def test_quick_scope_rejects_excess_slices_and_caps_task_turns() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, collector_react_max_turns=6, analyst_react_max_turns=6),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    with pytest.raises(ValueError, match="quick.*6 slices"):
        await service.create_run(_request(
            research_depth="quick", competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona", "security"],
        ))
    with pytest.raises(ValueError, match="quick.*6 slices"):
        await service.create_run(_request(
            research_depth="quick", competitors=["Copilot", "Windsurf"],
            target_product={"name": "Cursor"},
            dimensions=["pricing", "feature", "persona"],
        ))
    detail = await service.create_run(_request(
        research_depth="quick", competitors=["Cursor", "Copilot"],
        dimensions=["pricing", "feature", "persona"],
    ))
    assert len(detail.plan.competitors) * len(detail.plan.dimensions) == 6
    assert {task.max_turns for task in detail.plan.task_decomposition if task.stage in {"collector", "analyst"}} == {1}
    assert service._run_llm_budget(service._runs[detail.id]).max_calls - 6 * 2 >= 20


@pytest.mark.asyncio
async def test_low_deployment_llm_cap_reduces_allowed_scope_for_writer_reserve() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, run_llm_max_calls=38),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    with pytest.raises(ValueError, match="quick.*slices"):
        await service.create_run(_request(
            research_depth="quick", competitors=["Cursor"],
            dimensions=["pricing", "feature", "persona", "security", "market"],
        ))
    detail = await service.create_run(_request(
        research_depth="quick", competitors=["Cursor", "Copilot"],
        dimensions=["pricing", "feature"],
    ))
    assert len(detail.plan.competitors) * len(detail.plan.dimensions) == 4
    assert {task.max_turns for task in detail.plan.task_decomposition if task.stage == "analyst"} == {1}
    assert service._run_llm_budget(service._runs[detail.id]).max_calls == 38


@pytest.mark.asyncio
async def test_slice_limit_is_contiguous_across_analyst_one_shot_transition() -> None:
    from packages.research.budget import research_depth_budget

    assert research_depth_budget("standard").analyst_one_shot_threshold(70) == 6
    assert research_depth_budget("standard").allowed_slices(70) == 10
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, run_llm_max_calls=70),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(_request(
        research_depth="standard", competitors=["Cursor", "Copilot"],
        dimensions=["pricing", "feature", "persona", "security"],
    ))
    assert len(detail.plan.competitors) * len(detail.plan.dimensions) == 8
    assert {task.max_turns for task in detail.plan.task_decomposition if task.stage == "analyst"} == {1}


@pytest.mark.asyncio
async def test_deep_low_llm_budget_admits_seven_eight_nine_slices_with_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.research.budget import research_depth_budget

    budget = research_depth_budget("deep")
    assert budget.analyst_one_shot_threshold(88) == 6
    assert budget.allowed_slices(88) == 10
    for slices in range(1, budget.allowed_slices(88) + 1):
        analyst_calls = budget.analyst_max_turns + 1 if slices <= 6 else 1
        assert slices * (budget.collector_max_turns + 1 + analyst_calls) <= 50
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]
    monkeypatch.setattr(
        "packages.orchestrator.service.verify_homepages",
        lambda competitors: {
            name: HomepageVerification(competitor=name, verified=False, reason="unknown")
            for name in competitors
        },
    )
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, run_llm_max_calls=88, analyst_react_fanout_threshold=100),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    for competitors, dimensions, expected_slices in (
        (names[:6], ["pricing"], 6),
        (names[:7], ["pricing"], 7),
        (names[:8], ["pricing"], 8),
        (names[:3], ["pricing", "feature", "persona"], 9),
    ):
        detail = await service.create_run(_request(
            research_depth="deep", competitors=competitors, dimensions=dimensions,
        ))
        assert len(detail.plan.competitors) * len(detail.plan.dimensions) == expected_slices
        analyst_turns = {task.max_turns for task in detail.plan.task_decomposition if task.stage == "analyst"}
        assert analyst_turns == ({3} if expected_slices == 6 else {1})
        assert service._should_use_analyst_react(
            detail, dimension="pricing", qa_feedback=[{"issue": "gap"}],
        ) is (expected_slices == 6)
        if expected_slices > 6:
            assert expected_slices * (budget.collector_max_turns + 1 + 1) <= 50


@pytest.mark.asyncio
async def test_auto_discovery_respects_slice_capacity_below_competitor_limit() -> None:
    service = _service()
    detail = await service.create_run(_request(
        research_depth="quick", competitors=[],
        dimensions=["pricing", "feature", "persona", "security"],
    ))
    async def fake_llm_json(*args: object, **kwargs: object) -> dict[str, object]:
        return {"selected_competitors": ["Alpha", "Beta", "Gamma"]}
    service._trace_llm_json = fake_llm_json  # type: ignore[method-assign]
    discovery = await service._discover_competitors(service._runs[detail.id])
    assert discovery.selected_competitors == ["Alpha"]


@pytest.mark.asyncio
async def test_auto_discovery_filters_target_before_slice_limit() -> None:
    service = _service()
    detail = await service.create_run(_request(
        research_depth="quick", competitors=[], target_product={"name": "Cursor"},
        dimensions=["pricing", "feature", "persona"],
    ))
    service._search = SimpleNamespace(is_enabled=True)

    async def fake_search(*args: object, **kwargs: object) -> list[SearchResult]:
        return [SearchResult(
            title="Windsurf AI coding assistant",
            url="https://windsurf.com",
            snippet="Windsurf AI coding assistant competitor",
        )]

    async def fake_llm_json(*args: object, **kwargs: object) -> dict[str, object]:
        return {"selected_competitors": ["Cursor", "Windsurf"]}

    service._trace_search = fake_search  # type: ignore[method-assign]
    service._trace_llm_json = fake_llm_json  # type: ignore[method-assign]
    discovery = await service._discover_competitors(service._runs[detail.id])
    assert discovery.selected_competitors == ["Windsurf"]


@pytest.mark.asyncio
async def test_hitl_scope_rejects_excess_slices_before_mutating_plan() -> None:
    service = _service(hitl_enabled=True)
    detail = await service.create_run(_request(research_depth="quick"))
    service._runs[detail.id].pending_interrupts["planner"] = {"stage": "planner"}
    with pytest.raises(ValueError, match="quick.*6 slices"):
        await service.resume(detail.id, HitlResumeRequest(
            decision="modify_plan",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona", "security"],
        ))
    assert detail.plan.competitors == ["Cursor"]
    assert detail.plan.dimensions == ["pricing"]


@pytest.mark.asyncio
async def test_manual_redo_cannot_expand_completed_run_beyond_slice_limit() -> None:
    service = _service()
    detail = await service.create_run(_request(
        research_depth="quick", competitors=["Cursor", "Copilot"],
    ))
    detail.status = "completed"
    detail.qa_findings = [models.QCIssue(
        id="pricing-gap", severity="blocker", detected_by="coverage",
        target_agent="collector", field_path="raw_sources[pricing]",
        problem="No pricing evidence", redo_scope=models.RedoScope(
            kind="collector", target_subagent="pricing", rationale="Missing evidence",
        ),
    )]
    with pytest.raises(ValueError, match="quick.*6 slices"):
        await service.resume(detail.id, HitlResumeRequest(
            decision="redo", dimensions=["pricing", "feature", "persona", "security"],
        ))
    assert detail.plan.dimensions == ["pricing"]


@pytest.mark.asyncio
async def test_fixed_analyst_fanout_uses_one_shot_for_explicit_depth() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, analyst_react_fanout_threshold=100),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(_request(
        research_depth="standard", competitors=["Cursor", "Copilot", "Windsurf", "Tabnine"],
        dimensions=["pricing", "feature", "persona"],
    ))
    assert len(detail.plan.competitors) * len(detail.plan.dimensions) == 12
    assert service._should_use_analyst_react(detail, dimension="pricing", qa_feedback=[{"issue": "gap"}]) is False


@pytest.mark.asyncio
async def test_deep_max_scope_leaves_writer_llm_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]
    monkeypatch.setattr(
        "packages.orchestrator.service.verify_homepages",
        lambda competitors: {
            name: HomepageVerification(competitor=name, verified=False, reason="unknown")
            for name in competitors
        },
    )
    service = _service()
    detail = await service.create_run(_request(
        research_depth="deep", competitors=names,
        dimensions=["pricing", "feature", "persona"],
    ))
    assert len(detail.plan.competitors) * len(detail.plan.dimensions) == 24
    assert {task.max_turns for task in detail.plan.task_decomposition if task.stage == "analyst"} == {1}
    budget = service._run_llm_budget(service._runs[detail.id])
    assert budget.max_calls - 24 * (3 + 1 + 1) - 2 - 4 >= 32


@pytest.mark.asyncio
async def test_auto_scope_requires_room_for_target_and_one_competitor() -> None:
    service = _service()
    with pytest.raises(ValueError, match="quick.*slices"):
        await service.create_run(_request(
            research_depth="quick", competitors=[], target_product={"name": "Cursor"},
            dimensions=["pricing", "feature", "persona", "security"],
        ))


@pytest.mark.asyncio
async def test_collector_search_budget_counts_filtered_fallback_and_community(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    detail = await service.create_run(_request(
        research_depth="standard", target_product={"name": "Cursor"},
    ))
    record = service._runs[detail.id]
    context = SubagentContext(detail.id, "collector", "pricing::Cursor")
    calls: list[str] = []
    async def fake_web_search(provider: object, request: object) -> list[object]:
        calls.append(request.query)
        return []
    monkeypatch.setattr("packages.orchestrator.service.web_search", fake_web_search)
    service._search = SimpleNamespace(is_enabled=True)
    await service._search_research_candidates(record, detail, "pricing", context, "Cursor pricing", 5)
    await service._trace_search(record, agent="collector", subagent=context.subagent,
                                query="react retry", max_results=3, context=context)
    await service._community_source_candidates(record, detail, "pricing", "Cursor", context)
    assert calls == ["Cursor pricing", "Cursor pricing"]
    assert detail.collector_research_usage[context.subagent].search_calls == 2
    assert RunDetail.model_validate(detail.model_dump()).collector_research_usage[context.subagent].search_calls == 2


@pytest.mark.asyncio
async def test_collector_fetch_and_advanced_budget_shared_with_later_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    detail = await service.create_run(_request(research_depth="quick"))
    record = service._runs[detail.id]
    context = SubagentContext(detail.id, "collector", "pricing::Cursor")
    network_calls: list[bool] = []
    async def fake_robots(*args: object) -> SimpleNamespace:
        return SimpleNamespace(allowed=True)
    async def fake_fetch(url: str, **kwargs: object) -> EvidenceFetchResult:
        allowed = bool(kwargs.get("allow_advanced", True))
        network_calls.append(allowed)
        return EvidenceFetchResult(
            url=url, ok=False, title="", text="", content_hash="weak",
            fetch_method="basic_httpx_low_quality",
            failure_reason="content_too_short",
            advanced_fetch_attempted=allowed,
        )
    async def fake_pipeline(brief: ResearchBrief, **kwargs: object) -> SimpleNamespace:
        for index in range(3):
            await kwargs["fetch"](f"https://example.com/page-{index}")
        return SimpleNamespace(
            coverage=None, gaps=[], repair_tasks=[], metrics={},
            candidate_ledger=[], candidates=[],
        )
    monkeypatch.setattr(service, "_trace_robots", fake_robots)
    monkeypatch.setattr("packages.orchestrator.service.fetch_evidence_page", fake_fetch)
    monkeypatch.setattr("packages.agents.collectors.logic.run_research_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_raw_sources_from_research_result", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_trace_local_tool", lambda *args, **kwargs: None)
    await service._trace_fetch(record, "collector", context.subagent, "https://example.com/react", context)
    await service._collect_competitor_with_research_pipeline(
        record, detail, "pricing", "Cursor", context, batch_sources=[],
        target_source_count=2, include_official=True, enable_search=False,
    )
    assert network_calls == [True, False, False]
    usage = detail.collector_research_usage[context.subagent]
    assert (usage.fetch_calls, usage.advanced_fetch_attempts) == (3, 1)
    assert RunDetail.model_validate(detail.model_dump()).collector_research_usage[context.subagent] == usage


@pytest.mark.asyncio
async def test_explicit_depth_caps_manual_competitors_and_iterations() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, max_iterations=4),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    names = ["Cursor", "Copilot", "Windsurf"]
    with pytest.raises(ValueError, match="quick.*2 competitors"):
        await service.create_run(_request(research_depth="quick", competitors=names))

    quick = await service.create_run(_request(research_depth="quick"))
    standard = await service.create_run(_request(research_depth="standard"))
    deep = await service.create_run(_request(research_depth="deep"))
    legacy = await service.create_run(_request(competitors=names))
    assert [item.max_iterations for item in (quick, standard, deep, legacy)] == [1, 2, 4, 4]
    assert legacy.plan.competitors == names


@pytest.mark.asyncio
async def test_explicit_depth_caps_scenario_seed_competitors() -> None:
    service = _service()
    detail = await service.create_run(
        _request(
            competitors=[],
            research_depth="quick",
            scenario_id="l3_market_landscape",
            dimensions=["market", "persona"],
        )
    )
    assert detail.plan.competitors == ["Cursor", "GitHub Copilot"]


@pytest.mark.asyncio
async def test_scenario_seed_is_trimmed_to_slice_capacity_before_validation() -> None:
    service = _service()
    detail = await service.create_run(_request(
        competitors=[], research_depth="quick", scenario_id="l3_market_landscape",
        dimensions=["pricing", "feature", "persona", "security"],
    ))
    assert detail.plan.competitors == ["Cursor"]
    assert len(detail.plan.competitors) * len(detail.plan.dimensions) <= 6


@pytest.mark.asyncio
async def test_scenario_seed_filters_target_before_selecting_rival() -> None:
    service = _service()
    detail = await service.create_run(_request(
        research_depth="quick", competitors=[], target_product={"name": "Cursor"},
        scenario_id="l3_market_landscape", dimensions=["feature", "persona", "market"],
    ))
    assert detail.plan.competitors == ["GitHub Copilot"]


@pytest.mark.asyncio
async def test_demo_auto_discovery_respects_quick_limit() -> None:
    service = _service()
    detail = await service.create_run(_request(competitors=[], research_depth="quick"))
    await service._demo_planner_step(service._runs[detail.id])
    assert detail.plan.competitors == ["Demo Alpha", "Demo Beta"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("depth", "expected_count"),
    [("quick", 2), ("standard", 4), ("deep", 8), (None, 5)],
)
async def test_auto_discovery_respects_depth_limit(depth: str | None, expected_count: int) -> None:
    service = _service()
    detail = await service.create_run(
        _request(competitors=[], research_depth=depth)
    )
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]

    prompts: list[str] = []

    async def fake_llm_json(*args: object, **kwargs: object) -> dict[str, object]:
        prompts.append(str(kwargs["user"]))
        return {"selected_competitors": names, "candidates": names}

    service._trace_llm_json = fake_llm_json  # type: ignore[method-assign]
    discovery = await service._discover_competitors(service._runs[detail.id])
    assert discovery.selected_competitors == names[:expected_count]
    if depth is not None:
        assert f"Select at most {expected_count} competitors" in prompts[0]


def test_hitl_competitor_edit_cannot_exceed_explicit_depth_limit() -> None:
    service = _service()
    detail = models.AnalysisPlan(
        topic="AI coding assistant comparison",
        research_depth="quick",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
    )
    run_detail = RunDetail(
        id="run-hitl-budget",
        topic=detail.topic,
        status="interrupted",
        execution_mode="demo",
        created_at="2026-09-29T00:00:00",
        updated_at="2026-09-29T00:00:00",
        plan=detail,
    )
    with pytest.raises(ValueError, match="quick.*2 competitors"):
        service._apply_planner_competitor_review(
            run_detail,
            HitlResumeRequest(
                decision="modify_plan",
                competitors=["Cursor", "Copilot", "Windsurf"],
            ),
        )
    assert run_detail.plan.competitors == ["Cursor", "Copilot"]


@pytest.mark.asyncio
async def test_hitl_over_limit_preserves_pending_review_and_other_plan_fields() -> None:
    service = _service(hitl_enabled=True)
    detail = await service.create_run(_request(research_depth="quick"))
    service._runs[detail.id].pending_interrupts["planner"] = {"stage": "planner"}
    with pytest.raises(ValueError, match="quick.*2 competitors"):
        await service.resume(
            detail.id,
            HitlResumeRequest(
                decision="modify_plan",
                dimensions=["feature"],
                competitors=["Cursor", "Copilot", "Windsurf"],
            ),
        )
    assert detail.plan.dimensions == ["pricing"]
    assert detail.plan.competitors == ["Cursor"]
    assert service._runs[detail.id].pending_interrupts["planner"] == {"stage": "planner"}


@pytest.mark.asyncio
async def test_collector_and_llm_budgets_follow_depth_with_legacy_unchanged() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            collector_target_verified_sources_per_branch=10,
            collector_search_max_results=20,
            run_llm_max_calls=200,
        ),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    expected = {
        "quick": (2, 1, 6, 3, 1, 0, 60),
        "standard": (3, 2, 10, 5, 2, 1, 120),
        "deep": (5, 3, 16, 8, 3, 2, 160),
        None: (10, 2, 20, 10, 3, 1, 200),
    }
    for depth, values in expected.items():
        detail = await service.create_run(_request(research_depth=depth))
        detail.execution_mode = "real"
        brief = service._research_brief(detail, "Cursor", "pricing")
        budget = service._run_llm_budget(service._runs[detail.id])
        assert (
            brief.target_source_count,
            brief.max_search_queries,
            brief.max_candidates,
            brief.max_fetches,
            brief.max_advanced_fetches,
            brief.max_repair_rounds,
            budget.max_calls,
        ) == values


@pytest.mark.asyncio
async def test_deployment_settings_cap_explicit_budgets() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            collector_target_verified_sources_per_branch=1,
            run_llm_max_calls=46,
            max_iterations=1,
        ),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(_request(research_depth="deep"))
    detail.execution_mode = "real"
    brief = service._research_brief(detail, "Cursor", "pricing")
    assert detail.max_iterations == 1
    assert brief.target_source_count == 1
    assert brief.max_fetches == 8
    assert brief.max_advanced_fetches <= 3
    assert service._run_llm_budget(service._runs[detail.id]).max_calls == 46


@pytest.mark.asyncio
async def test_legacy_llm_budget_keeps_minimum_one_call() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, run_llm_max_calls=0),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(_request())
    assert service._run_llm_budget(service._runs[detail.id]).max_calls == 1


@pytest.mark.asyncio
async def test_pipeline_receives_depth_repair_rounds_and_source_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    captured: list[tuple[int, int]] = []

    async def fake_pipeline(brief: object, **kwargs: object) -> SimpleNamespace:
        captured.append((brief.max_repair_rounds, brief.target_source_count))
        return SimpleNamespace(
            coverage=None,
            gaps=[],
            repair_tasks=[],
            metrics={},
            candidate_ledger=[],
            candidates=[],
        )

    monkeypatch.setattr("packages.agents.collectors.logic.run_research_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_raw_sources_from_research_result", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_trace_local_tool", lambda *args, **kwargs: None)
    for depth in ("quick", "standard", "deep", None):
        detail = await service.create_run(_request(research_depth=depth))
        detail.execution_mode = "real"
        await service._collect_competitor_with_research_pipeline(
            service._runs[detail.id],
            detail,
            "pricing",
            "Cursor",
            SimpleNamespace(subagent="pricing::Cursor"),
            batch_sources=[],
            target_source_count=9,
            include_official=True,
            enable_search=False,
        )
    assert captured == [(0, 2), (1, 3), (2, 5), (1, 9)]


def test_repair_pass_keeps_explicit_budget_caps_and_legacy_expansion() -> None:
    task = RepairTask(
        gap_id="gap-pricing",
        strategy="targeted_discovery",
        competitor="Cursor",
        dimension="pricing",
        acceptance_rule="Find current official pricing.",
    )
    common = dict(
        run_id="run-repair-budget", topic="AI IDE", competitor="Cursor",
        dimension="pricing", max_search_queries=2, max_candidates=10, max_fetches=5,
    )
    explicit = _repair_brief(
        ResearchBrief(**common, research_depth="standard"), [task], round_index=1
    )
    legacy = _repair_brief(ResearchBrief(**common), [task], round_index=1)
    assert (explicit.max_search_queries, explicit.max_candidates, explicit.max_fetches) == (2, 10, 5)
    assert (legacy.max_search_queries, legacy.max_candidates, legacy.max_fetches) == (3, 12, 6)


@pytest.mark.asyncio
async def test_clean_pipeline_search_respects_settings_result_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, collector_search_max_results=3),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(_request(research_depth="deep"))
    detail.execution_mode = "real"
    service._search = SimpleNamespace(is_enabled=True)
    requested_results: list[int] = []

    async def fake_search(*args: object) -> list[object]:
        requested_results.append(int(args[-1]))
        return []

    async def fake_pipeline(brief: object, **kwargs: object) -> SimpleNamespace:
        await kwargs["search"]("cursor pricing", brief.max_candidates)
        return SimpleNamespace(
            coverage=None, gaps=[], repair_tasks=[], metrics={},
            candidate_ledger=[], candidates=[],
        )

    monkeypatch.setattr(service, "_search_research_candidates", fake_search)
    monkeypatch.setattr("packages.agents.collectors.logic.run_research_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_raw_sources_from_research_result", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_trace_local_tool", lambda *args, **kwargs: None)
    await service._collect_competitor_with_research_pipeline(
        service._runs[detail.id], detail, "pricing", "Cursor",
        SimpleNamespace(subagent="pricing::Cursor"),
        batch_sources=[], target_source_count=5, include_official=True,
    )
    assert requested_results == [3]


@pytest.mark.asyncio
@pytest.mark.parametrize("fetch_method", ["webfetch_v2:browser", "basic_httpx_low_quality"])
async def test_clean_pipeline_counts_advanced_attempt_even_after_basic_fallback(
    monkeypatch: pytest.MonkeyPatch,
    fetch_method: str,
) -> None:
    service = _service()
    detail = await service.create_run(_request(research_depth="quick"))
    detail.execution_mode = "real"
    allow_advanced_values: list[bool] = []

    async def fake_trace_fetch(*args: object, allow_advanced: bool = True) -> SimpleNamespace:
        allow_advanced_values.append(allow_advanced)
        return SimpleNamespace(
            fetch_method=fetch_method,
            advanced_fetch_attempted=allow_advanced,
        )

    async def fake_pipeline(brief: object, **kwargs: object) -> SimpleNamespace:
        await kwargs["fetch"]("https://example.com/first")
        await kwargs["fetch"]("https://example.com/second")
        return SimpleNamespace(
            coverage=None, gaps=[], repair_tasks=[], metrics={},
            candidate_ledger=[], candidates=[],
        )

    monkeypatch.setattr(service, "_trace_fetch", fake_trace_fetch)
    monkeypatch.setattr("packages.agents.collectors.logic.run_research_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_raw_sources_from_research_result", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_trace_local_tool", lambda *args, **kwargs: None)
    await service._collect_competitor_with_research_pipeline(
        service._runs[detail.id], detail, "pricing", "Cursor",
        SimpleNamespace(subagent="pricing::Cursor"),
        batch_sources=[], target_source_count=2, include_official=True,
        enable_search=False,
    )
    assert allow_advanced_values == [True, False]


@pytest.mark.asyncio
async def test_writer_first_draft_prompt_uses_depth_target() -> None:
    service = _service()
    for depth, target in (
        ("quick", "4,000-6,000"),
        ("standard", "8,000-12,000"),
        ("deep", "16,000-20,000"),
        (None, "16,000-20,000"),
    ):
        detail = await service.create_run(_request(research_depth=depth))
        prompt = WriterPromptBuilder().first_draft_prompt(
            detail,
            language_guidance="English",
            user_research_policy="Policy",
            memory_context="none",
            layer_context="L1",
            grounding_prompt="Grounding",
            community_policy_text="Community",
            writer_context_json="{}",
            required_sections="Decision Summary",
        )
        assert f"Target {target} characters" in prompt.user
        if depth == "quick":
            assert "Core section minimums:" not in prompt.user
        else:
            assert "Core section minimums:" in prompt.user


@pytest.mark.asyncio
async def test_writer_legacy_markdown_path_uses_depth_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    captured: list[str] = []

    async def fake_grounding(*args: object) -> str:
        return "Grounding"

    async def fake_llm_text(*args: object, **kwargs: object) -> str:
        captured.append(str(kwargs["user"]))
        return "## Decision Summary\nDraft"

    monkeypatch.setattr(service, "_writer_grounding_prompt", fake_grounding)
    monkeypatch.setattr(service, "_trace_llm_text", fake_llm_text)
    evidence_pack = SimpleNamespace(
        metrics=SimpleNamespace(segmented_writer_required=False),
        to_prompt_json=lambda: "{}",
    )
    for depth in ("quick", "standard", "deep", None):
        detail = await service.create_run(_request(research_depth=depth))
        result = await service._writer_markdown_report_from_evidence_pack(
            service._runs[detail.id], evidence_pack, timeout_seconds=1
        )
        assert result.startswith("## Decision Summary")
    assert [
        "Target 4,000-6,000 characters" in captured[0],
        "Target 8,000-12,000 characters" in captured[1],
        "Target 16,000-20,000 characters" in captured[2],
        "Target 16,000-20,000 characters" in captured[3],
    ] == [True] * 4
    assert "Core section minimums:" not in captured[0]
    assert "Core section minimums:" in captured[3]


@pytest.mark.asyncio
async def test_default_segment_writer_prompt_includes_depth_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    captured: list[str] = []

    async def fake_llm_text(*args: object, **kwargs: object) -> str:
        captured.append(str(kwargs["user"]))
        return "## Decision Summary\nDraft"

    monkeypatch.setattr(service, "_trace_llm_text", fake_llm_text)
    segment = {
        "segment_name": "decision_summary",
        "section_id": "decision_summary",
        "segment_kind": "section_fragment",
        "allowed_source_ids": [],
    }
    for depth in ("quick", "standard", "deep", None):
        detail = await service.create_run(_request(research_depth=depth))
        await service._writer_segment_markdown(
            service._runs[detail.id], segment=segment, timeout_seconds=1,
            language_guidance="English", memory_context="none",
            layer_context="L1", required_sections="Decision Summary", retry_count=0,
        )
    for prompt, target in zip(captured[:3], ("4,000-6,000", "8,000-12,000", "16,000-20,000"), strict=True):
        assert f"Full report target: {target} characters" in prompt
    assert "Full report target" not in captured[3]
