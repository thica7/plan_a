from __future__ import annotations

from types import SimpleNamespace

import pytest

import packages.research.discovery.planner as discovery_planner
from packages.agents.planner.logic import PlannerAgentMixin
from packages.business_intel.entity_resolver import normalize_competitor_key
from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.schema.models import CompetitorDiscovery, TargetProduct
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.fetch_page import FetchPageResult


def test_unknown_competitor_survives_homepage_verification() -> None:
    planner = PlannerAgentMixin()
    discovery = CompetitorDiscovery(
        query="productivity alternatives",
        selected_competitors=["Cursor", "Notion"],
    )
    assert planner._verify_discovered_competitors(discovery).selected_competitors == [
        "Cursor", "Notion"
    ]


def test_non_latin_product_names_keep_distinct_identity_keys() -> None:
    assert normalize_competitor_key("洁净家") == "洁净家"
    assert normalize_competitor_key("示例吸尘器") == "示例吸尘器"


def test_unrelated_result_is_not_candidate_evidence() -> None:
    planner = PlannerAgentMixin()
    unrelated = SearchResult(
        title="Another product pricing", url="https://example.com/pricing",
        snippet="Plans for an unrelated product.",
    )
    assert planner._candidate_evidence("Notion", [unrelated]) == []


def test_product_profile_builds_distinct_discovery_queries() -> None:
    product = TargetProduct(
        name="示例无线吸尘器", category="家用清洁电器", market="中国",
        use_cases=["清理宠物毛发", "清洁地毯"],
    )
    queries = discovery_planner.build_competitor_queries(product, topic="家庭清洁产品调研")
    assert len(queries) >= 3
    assert any("示例无线吸尘器" in query for query in queries)
    assert any("家用清洁电器" in query for query in queries)
    assert any("清理宠物毛发" in query for query in queries)


@pytest.mark.asyncio
async def test_product_discovery_selects_only_supported_candidates(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(RunCreateRequest(
        topic="研究家用清洁电器的竞品", dimensions=["feature"],
        target_product={"name": "示例吸尘器", "category": "家用清洁电器"},
    ))
    record = service._runs[detail.id]
    service._search = SimpleNamespace(is_enabled=True)
    calls: list[str] = []

    async def search(_record, *, query, **_kwargs):
        calls.append(query)
        return [
            SearchResult(
                title="洁净家无线吸尘器选购说明",
                url="https://clean-home.example/products/vacuum",
                snippet="洁净家提供无线吸尘器用于家庭清洁。",
            ),
            SearchResult(
                title="示例吸尘器官网", url="https://example.com/vacuum",
                snippet="示例吸尘器提供家庭清洁功能。",
            ),
        ]

    async def llm(_record, **_kwargs):
        return {
            "candidates": [
                {"name": "洁净家", "rationale": "同一家庭清洁用途", "confidence": 0.8,
                 "relationship": "direct"},
                {"name": "无证品牌", "rationale": "模型猜测", "confidence": 0.8,
                 "relationship": "direct"},
                {"name": "示例吸尘器", "rationale": "目标产品本身", "confidence": 0.8,
                 "relationship": "direct"},
            ],
            "selected_competitors": ["洁净家", "无证品牌", "示例吸尘器"],
            "rationale": "同类产品",
        }

    monkeypatch.setattr(service, "_trace_search", search)
    monkeypatch.setattr(service, "_trace_llm_json", llm)
    discovery = await service._discover_competitors(record)
    assert len(calls) >= 2
    assert discovery.selected_competitors == ["洁净家"]
    assert discovery.candidates[0].relationship == "direct"
    assert discovery.candidates[0].evidence_urls == ["https://clean-home.example/products/vacuum"]
    assert discovery.candidates[1].relationship == "unverified"
    assert discovery.candidates[1].evidence_urls == []
    assert discovery.candidates[2].selected is False


@pytest.mark.asyncio
async def test_target_official_page_is_captured_before_competitor_discovery(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(RunCreateRequest(
        topic="研究示例吸尘器", dimensions=["feature"],
        target_product={
            "name": "示例吸尘器", "category": "家用清洁电器",
            "official_url": "https://example.com/vacuum",
        },
        competitors=["洁净家"],
    ))
    record = service._runs[detail.id]
    calls = []

    async def fake_fetch(_record, agent, subagent, url, context=None):
        calls.append((agent, subagent, url))
        return FetchPageResult(
            url=url, ok=True, title="示例吸尘器官网",
            text="示例吸尘器是面向家庭的无线清洁产品，可更换电池。",
            content_hash="product-content-v1", status_code=200,
        )

    monkeypatch.setattr(service, "_trace_fetch", fake_fetch)
    await service._research_target_product(record)
    evidence = record.detail.plan.target_product_evidence
    assert calls == [("planner", "target_product", "https://example.com/vacuum")]
    assert evidence is not None
    assert evidence.status == "verified"
    assert evidence.content_hash == "product-content-v1"
    assert evidence.source_url == "https://example.com/vacuum"
