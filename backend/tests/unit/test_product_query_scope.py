from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.agents import SubagentContext
from packages.community.query_planner import build_community_queries
from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.discovery.planner import build_search_queries
from packages.research.models import RepairTask, ResearchBrief
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, TargetProduct
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry

TOPIC = "分析 Nintendo Switch 2 的竞品、产品功能、价格和目标用户，确定产品优化方向"
COMPETITOR = "Steam Deck OLED"


@pytest.fixture
def service() -> RunService:
    registry = SkillRegistry.from_default_path()
    feature = registry.get("feature")
    registry = SkillRegistry({
        spec.name: spec.model_copy(update={
            "description": "AI agent context window token limits GitHub developer API",
            "query_templates": ["{competitor} AI agent context window"],
        }) if spec is feature else spec
        for spec in registry.list()
    })
    return RunService(
        skill_registry=registry,
        settings=Settings(demo_mode=True),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


@pytest.fixture
def detail() -> RunDetail:
    return RunDetail(
        id="product-query-scope", topic=TOPIC, status="running", execution_mode="demo",
        created_at="2026-10-02T00:00:00", updated_at="2026-10-02T00:00:00",
        plan=AnalysisPlan(
            topic=TOPIC, competitors=[COMPETITOR], dimensions=["feature", "pricing", "persona"],
            target_product=TargetProduct(
                name="Nintendo Switch 2", category="掌上游戏机", market="CN",
                use_cases=["Nintendo Switch 2 独占游戏"],
            ),
        ),
    )


@pytest.mark.parametrize(
    ("dimension", "intent"),
    [
        ("feature", "official specifications features"),
        ("pricing", "official price pricing purchase cost"),
        ("currentprice", "official price pricing purchase cost"),
        ("persona", "target users customers use cases"),
        ("usecases", "target users customers use cases"),
    ],
)
def test_normal_product_search_starts_with_current_competitor_only(
    service: RunService, detail: RunDetail, dimension: str, intent: str,
) -> None:
    queries = build_search_queries(service._research_brief(detail, COMPETITOR, dimension))

    assert queries[0] == f"{COMPETITOR} {intent}"
    assert all(COMPETITOR in query for query in queries)
    assert all("Nintendo Switch 2" not in query and TOPIC not in query for query in queries)
    assert any("掌上游戏机" in query and "CN" in query for query in queries[1:])


def test_product_category_alone_enables_generic_queries() -> None:
    brief = ResearchBrief(
        run_id="category-only", topic=TOPIC, competitor=COMPETITOR,
        dimension="feature", product_category="掌上游戏机",
    )

    assert build_search_queries(brief)[0] == f"{COMPETITOR} official specifications features"


def test_product_repair_hints_keep_priority_over_normal_collection(
    service: RunService, detail: RunDetail,
) -> None:
    brief = service._research_brief(detail, COMPETITOR, "feature")
    hint = f"{COMPETITOR} battery life official specifications"
    repair = RepairTask(
        gap_id="missing-battery-life", competitor=COMPETITOR, dimension="feature",
        strategy="targeted_discovery", query_hints=[hint], acceptance_rule="cite battery life",
    )

    assert build_search_queries(brief, repair_tasks=[repair])[0] == hint


def test_legacy_search_still_includes_topic_and_ai_specific_intent() -> None:
    brief = ResearchBrief(
        run_id="legacy-query", topic="AI coding assistants", competitor="Cursor",
        dimension="pricing", max_search_queries=3,
    )

    queries = build_search_queries(brief)

    assert queries[0] == (
        "Cursor pricing plans billing usage limits AI coding assistants official source"
    )
    assert "API pricing token cost official docs" in queries[1]


@pytest.mark.parametrize(
    ("dimension", "intent_terms"),
    [
        ("feature", ["feature", "limitation"]),
        ("pricing", ["price", "purchase"]),
        ("persona", ["users", "use cases"]),
        ("review", ["reviews", "pros cons"]),
    ],
)
def test_product_community_queries_use_generic_intents(
    dimension: str, intent_terms: list[str],
) -> None:
    queries = build_community_queries(
        competitor=COMPETITOR, dimension=dimension, topic=TOPIC,
        product_category="掌上游戏机", limit=4,
    )
    combined = " ".join(queries).casefold()

    assert len(queries) == 4
    assert all(COMPETITOR in query and "掌上游戏机" in query for query in queries)
    assert "nintendo switch 2" not in combined
    assert all(term in combined for term in intent_terms)
    assert all(term not in combined for term in (
        "context window", "agent mode", "github", "developer", "enterprise",
        "billing quota", "usage limit", "overage", "g2", "capterra", "trustradius",
    ))


@pytest.mark.parametrize("dimension", ["feature", "pricing", "persona"])
def test_product_web_and_kb_reuse_scoped_query(
    service: RunService, detail: RunDetail, dimension: str,
) -> None:
    web_query = service._web_search_query(detail, COMPETITOR, dimension)
    kb_query = service._kb_retrieval_query(detail, COMPETITOR, dimension)
    expected = build_search_queries(service._research_brief(detail, COMPETITOR, dimension))[0]

    assert kb_query == web_query == expected
    assert "Nintendo Switch 2" not in kb_query
    assert all(term not in kb_query.casefold() for term in (
        "ai agent", "context window", "token", "github", "developer", "api",
        "billing cycles", "enterprise quote",
    ))


def test_product_without_category_still_scopes_web_and_kb(
    service: RunService, detail: RunDetail,
) -> None:
    detail.plan.target_product.category = ""

    assert service._kb_retrieval_query(detail, COMPETITOR, "feature") == (
        f"{COMPETITOR} official specifications features"
    )


def test_legacy_web_and_kb_keep_skill_description_and_topic(
    service: RunService, detail: RunDetail,
) -> None:
    detail.plan.target_product = None

    web_query = service._web_search_query(detail, COMPETITOR, "feature")
    kb_query = service._kb_retrieval_query(detail, COMPETITOR, "feature")

    assert "AI agent context window" in web_query
    assert TOPIC in web_query and "official source" in web_query
    assert "AI agent context window token limits GitHub developer API" in kb_query


@pytest.mark.asyncio
async def test_collector_passes_category_to_community_and_omits_other_product_topic(
    monkeypatch: pytest.MonkeyPatch, service: RunService, detail: RunDetail,
) -> None:
    record = RunRecord(detail=detail)
    context = SubagentContext(detail.id, "collector", f"feature::{COMPETITOR}")
    service._search = SimpleNamespace(is_enabled=True)
    queries: list[str] = []

    async def fake_trace_search(_record: RunRecord, **kwargs: object) -> list[SearchResult]:
        queries.append(str(kwargs["query"]))
        return []

    monkeypatch.setattr(service, "_trace_search", fake_trace_search)
    await service._community_source_candidates(record, detail, "feature", COMPETITOR, context)

    assert len(queries) == service._settings.collector_community_queries_per_branch
    assert all("掌上游戏机" in query and "Nintendo Switch 2" not in query for query in queries)
    assert all("context window" not in query and "agent mode" not in query for query in queries)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dimension", "intent_terms"),
    [
        ("feature", ["feature", "limitation"]),
        ("pricing", ["price", "purchase"]),
        ("persona", ["users", "use cases"]),
        ("review", ["reviews", "pros cons"]),
    ],
)
async def test_product_without_category_uses_generic_collector_community_intents(
    monkeypatch: pytest.MonkeyPatch, service: RunService, detail: RunDetail,
    dimension: str, intent_terms: list[str],
) -> None:
    detail.plan.target_product.category = ""
    record = RunRecord(detail=detail)
    context = SubagentContext(detail.id, "collector", f"{dimension}::{COMPETITOR}")
    service._search = SimpleNamespace(is_enabled=True)
    queries: list[str] = []

    async def fake_trace_search(_record: RunRecord, **kwargs: object) -> list[SearchResult]:
        queries.append(str(kwargs["query"]))
        return []

    monkeypatch.setattr(service, "_trace_search", fake_trace_search)
    await service._community_source_candidates(record, detail, dimension, COMPETITOR, context)
    combined = " ".join(queries).casefold()

    assert len(queries) == service._settings.collector_community_queries_per_branch
    assert all(COMPETITOR in query and "Nintendo Switch 2" not in query for query in queries)
    assert all(term not in combined for term in (
        "context window", "agent mode", "github", "developer", "enterprise",
        "billing quota", "usage limit", "overage", "g2", "capterra", "trustradius",
    ))
    assert all(term in combined for term in intent_terms)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dimension", "market", "country", "recency"),
    [("pricing", "CN", "CN", "year"), ("feature", "", None, None)],
)
async def test_product_search_passes_language_preference_to_trace(
    monkeypatch: pytest.MonkeyPatch, service: RunService, detail: RunDetail,
    dimension: str, market: str, country: str | None, recency: str | None,
) -> None:
    detail.plan.target_product.market = market
    record = RunRecord(detail=detail)
    calls: list[dict[str, object]] = []
    result = SearchResult(title="Steam Deck OLED", url="https://example.com/deck", snippet="specs")

    async def fake_trace_search(_record: RunRecord, **kwargs: object) -> list[SearchResult]:
        calls.append(kwargs)
        return [result]

    monkeypatch.setattr(service, "_trace_search", fake_trace_search)
    results = await service._search_research_candidates(record, detail, dimension, None, "query", 5)

    assert results == [result] and len(calls) == 1
    filters = calls[0]["filters"]
    assert filters.search_language_filter == ["en", "zh"]
    assert filters.country == country
    assert filters.search_recency_filter == recency


@pytest.mark.asyncio
async def test_product_language_preference_keeps_empty_result_fallback(
    monkeypatch: pytest.MonkeyPatch, service: RunService, detail: RunDetail,
) -> None:
    detail.plan.target_product.market = ""
    record = RunRecord(detail=detail)
    calls: list[dict[str, object]] = []
    result = SearchResult(title="Steam Deck OLED", url="https://example.com/deck", snippet="specs")

    async def fake_trace_search(_record: RunRecord, **kwargs: object) -> list[SearchResult]:
        calls.append(kwargs)
        return [] if kwargs.get("filters") else [result]

    monkeypatch.setattr(service, "_trace_search", fake_trace_search)
    results = await service._search_research_candidates(record, detail, "feature", None, "query", 5)

    assert results == [result] and len(calls) == 2
    assert calls[0]["filters"].search_language_filter == ["en", "zh"]
    assert "filters" not in calls[1]
    assert all(call["query"] == "query" for call in calls)


@pytest.mark.asyncio
async def test_legacy_search_has_no_product_language_filter(
    monkeypatch: pytest.MonkeyPatch, service: RunService, detail: RunDetail,
) -> None:
    detail.plan.target_product = None
    calls: list[dict[str, object]] = []

    async def fake_trace_search(_record: RunRecord, **kwargs: object) -> list[SearchResult]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(service, "_trace_search", fake_trace_search)
    await service._search_research_candidates(
        RunRecord(detail=detail), detail, "pricing", None, "query", 5
    )

    assert len(calls) == 1
    assert "filters" not in calls[0]
