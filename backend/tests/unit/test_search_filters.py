from __future__ import annotations

import packages.search.perplexity_client as search_module
from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.web_search import WebSearchRequest, web_search


async def test_search_api_forwards_supported_date_domain_and_locale_filters(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, json, headers):
            calls.append(json)
            assert headers["Authorization"] == "Bearer test-key"
            return type("Response", (), {"status_code": 200, "json": lambda self: {"results": []}})()

    monkeypatch.setattr(search_module.httpx, "AsyncClient", FakeClient)
    filters = search_module.SearchFilters(
        country="CN", search_language_filter=["zh"],
        search_domain_filter=["example.com"], search_recency_filter="year",
    )
    client = search_module.PerplexitySearchClient(Settings(pplx_api_key="test-key"))
    await client.search("current pricing", filters=filters)
    assert calls == [{
        "query": "current pricing", "max_results": 3,
        "country": "CN", "search_language_filter": ["zh"],
        "search_domain_filter": ["example.com"], "search_recency_filter": "year",
    }]


async def test_web_search_request_preserves_filter_contract() -> None:
    received = []

    class FakeClient:
        async def search(self, query, max_results, *, filters):
            received.append((query, max_results, filters.search_recency_filter))
            return []

    filters = search_module.SearchFilters(search_recency_filter="year")
    await web_search(FakeClient(), WebSearchRequest(query="pricing", max_results=5, filters=filters))
    assert received == [("pricing", 5, "year")]


async def test_product_pricing_search_falls_back_when_recent_filter_has_no_results(monkeypatch):
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(RunCreateRequest(
        topic="产品价格调研", dimensions=["pricing"], competitors=["示例品牌"],
        target_product={"name": "目标产品", "category": "家用清洁电器", "market": "CN"},
    ))
    calls = []

    async def fake_trace_search(_record, **kwargs):
        filters = kwargs.get("filters")
        calls.append(filters.search_recency_filter if filters else None)
        if filters:
            assert filters.country == "CN"
            return []
        return [SearchResult(title="示例品牌官方价格", url="https://example.com/pricing", snippet="现价")]

    monkeypatch.setattr(service, "_trace_search", fake_trace_search)
    results = await service._search_research_candidates(
        service._runs[detail.id], detail, "pricing", None,
        "示例品牌 价格", 5,
    )
    assert calls == ["year", None]
    assert [result.title for result in results] == ["示例品牌官方价格"]
