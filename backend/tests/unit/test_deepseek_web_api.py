import asyncio
import json

import httpx
import pytest
from test_deepseek_search import _client, _settings, install_response
from test_deepseek_search_runtime import make_service, search

from packages.config import get_settings
from packages.search import SearchFilters, WebSearchError


def web_settings(**overrides):
    return _settings(deepseek_web_api_enabled=True, **overrides)


def response():
    return {"results": [
        {"title": "规格", "url": "https://example.com/specs", "snippet": "原文摘录", "date": "2026-10-01"},
        {"title": "duplicate", "url": "https://example.com/specs"},
        {"url": "https://example.com.evil/"},
        {"url": "https://user:secret@example.com/"},
        {"url": "javascript:alert(1)"},
        "invalid",
    ], "content": "Generated prose must never become a source"}


def test_web_flag_defaults_to_legacy_and_reads_environment(monkeypatch):
    assert _settings().deepseek_web_api_enabled is False
    monkeypatch.setenv("DEEPSEEK_WEB_API_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert get_settings().deepseek_web_api_enabled is True
    finally:
        get_settings.cache_clear()


async def test_web_search_uses_fixed_endpoint_structured_snippets_and_no_generation_budget(monkeypatch):
    requests = install_response(monkeypatch, response())
    client = _client(web_settings(run_llm_max_tokens=1, run_llm_max_calls=1, deepseek_search_model=""))
    results = await client.search("规格", max_results=50)
    assert [r.url for r in results] == ["https://example.com/specs", "https://example.com.evil/"]
    assert results[0].snippet == "原文摘录"
    assert results[0].date == "2026-10-01"
    assert results[0].provider == "deepseek"
    assert str(requests[0].url) == "https://api.deepseek.com/v1/tools/search"
    assert requests[0].headers["Authorization"] == "Bearer test-deepseek-key"
    assert json.loads(requests[0].content) == {"query": "规格", "count": 20, "need_content": False}
    assert client.consume_last_usage() is None
    metadata = client.consume_last_metadata()
    assert metadata["web_api_requests"] == metadata["web_api_successful_responses"] == 1
    assert metadata["web_api_billable_requests_estimate"] == 1
    assert metadata["billing_basis"] == "provider_success_request_estimate_not_invoice"
    assert metadata["llm_tokens_charged"] == 0
    assert client.consume_last_metadata() == {}


async def test_web_filters_use_operators_postfilter_and_disclose_unsupported_constraints(monkeypatch):
    requests = install_response(monkeypatch, response())
    client = _client(web_settings())
    results = await client.search("规格", filters=SearchFilters(
        search_domain_filter=["example.com", "-blocked.example.com"],
        search_language_filter=["zh"], country="CN", search_recency_filter="week",
        last_updated_after_filter="2026-10-01"))
    assert [r.url for r in results] == ["https://example.com/specs"]
    query = json.loads(requests[0].content)["query"]
    assert query == "规格 site:example.com -site:blocked.example.com lang:zh"
    assert client.consume_last_metadata()["unsupported_filters"] == [
        "country", "search_recency_filter", "last_updated_after_filter"]


@pytest.mark.parametrize("query,filters", [
    ("", None), (" " * 3, None), ("中" * 129, None),
    ("中" * 120, SearchFilters(search_domain_filter=["example.com"])),
])
async def test_web_query_limit_rejects_before_transport_without_truncation(monkeypatch, query, filters):
    requests = install_response(monkeypatch, response())
    with pytest.raises(WebSearchError, match="1–128"):
        await _client(web_settings()).search(query, filters=filters)
    assert requests == []


async def test_128_unicode_characters_are_accepted(monkeypatch):
    requests = install_response(monkeypatch, {"results": []})
    assert await _client(web_settings()).search("中" * 128) == []
    assert len(json.loads(requests[0].content)["query"]) == 128


@pytest.mark.parametrize("payload", [{}, [], {"results": None}, {"results": {}}, {"results": "bad"}])
async def test_web_invalid_result_schema_is_explicit_error(monkeypatch, payload):
    install_response(monkeypatch, payload)
    with pytest.raises(WebSearchError):
        await _client(web_settings()).search("规格")


@pytest.mark.parametrize("status", [301, 400, 401, 402, 403, 404, 429, 500, 503])
async def test_web_errors_are_redacted_and_never_retried(monkeypatch, status):
    requests = install_response(monkeypatch, {"error": "test-deepseek-key secret"}, status=status)
    client = _client(web_settings())
    with pytest.raises(WebSearchError, match=f"HTTP {status}") as caught:
        await client.search("规格")
    assert "test-deepseek-key" not in str(caught.value)
    assert len(requests) == 1
    metadata = client.consume_last_metadata()
    assert metadata["web_api_requests"] == 1
    assert metadata["web_api_billable_requests_estimate"] == 0


@pytest.mark.parametrize("failure", ["json", "timeout", "connect"])
async def test_web_transport_and_json_errors_are_stable(monkeypatch, failure):
    async def fail(request):
        if failure == "json":
            return httpx.Response(200, text="not json test-deepseek-key")
        error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        raise error("test-deepseek-key secret", request=request)
    requests = install_response(monkeypatch, {}, handler=fail)
    with pytest.raises(WebSearchError) as caught:
        await _client(web_settings()).search("规格")
    assert "test-deepseek-key" not in str(caught.value)
    assert len(requests) == 1


async def test_web_runtime_cache_lock_refresh_and_no_llm_reservation(monkeypatch):
    requests = install_response(monkeypatch, response())
    service, record = await make_service(deepseek_web_api_enabled=True, run_llm_max_tokens=1)
    first, second = await asyncio.gather(search(service, record), search(service, record))
    assert first == second and len(requests) == 1
    budget = service._run_llm_budget(record)
    assert budget.calls == budget.tokens_used == budget.tokens_reserved == 0
    assert record.detail.trace_spans[-1].metadata["search_cache_hit"] is True
    record.detail.evidence_refresh_active = True
    await search(service, record)
    assert len(requests) == 2
    span = record.detail.trace_spans[-1]
    assert span.input_tokens_estimate == span.output_tokens_estimate == 0
    assert span.cost_estimate_usd == 0
    assert span.metadata["web_api_requests"] == 1
    assert span.metadata["llm_tokens_charged"] == 0


async def test_web_runtime_collector_gate_counts_real_requests_and_allows_cached_reuse(monkeypatch):
    from packages.agents import SubagentContext
    requests = install_response(monkeypatch, response())
    service, record = await make_service(deepseek_web_api_enabled=True)
    context = SubagentContext(run_id=record.detail.id, agent="collector", subagent="feature::Switch")
    first = await service._search_research_candidates(record, record.detail, "feature", context, "A docs", 3)
    assert first
    assert await service._search_research_candidates(record, record.detail, "feature", context, "A docs", 3) == first
    assert await service._search_research_candidates(record, record.detail, "feature", context, "B docs", 3) == []
    assert len(requests) == 1
    assert record.detail.collector_research_usage[context.subagent].search_calls == 1


async def test_rejected_query_does_not_consume_collector_api_request_quota(monkeypatch):
    from packages.agents import SubagentContext
    requests = install_response(monkeypatch, response())
    service, record = await make_service(deepseek_web_api_enabled=True)
    context = SubagentContext(run_id=record.detail.id, agent="collector", subagent="feature::Switch")
    with pytest.raises(WebSearchError):
        await service._trace_search(record, agent="collector", subagent=context.subagent,
            query="中" * 129, max_results=3, context=context)
    assert requests == []
    assert record.detail.collector_research_usage[context.subagent].search_calls == 0


async def test_multiple_domains_and_languages_use_official_union_operators(monkeypatch):
    requests = install_response(monkeypatch, response())
    await _client(web_settings()).search("规格", filters=SearchFilters(
        search_domain_filter=["example.com", "docs.example.org", "-blocked.example.com"],
        search_language_filter=["zh", "en"]))
    assert json.loads(requests[0].content)["query"] == (
        "规格 site:example.com OR site:docs.example.org -site:blocked.example.com lang:zh,en")


@pytest.mark.parametrize("payload,filters,expected_billable", [
    ({"results": []}, None, 0),
    ({"results": [{"title": "Other", "url": "https://other.example/", "snippet": "Source"}]},
     SearchFilters(search_domain_filter=["example.com"]), 1),
])
async def test_billable_search_estimate_distinguishes_upstream_empty_from_local_filtering(
    monkeypatch, payload, filters, expected_billable
):
    install_response(monkeypatch, payload)
    client = _client(web_settings())
    assert await client.search("规格", filters=filters) == []
    metadata = client.consume_last_metadata()
    assert metadata["web_api_successful_responses"] == 1
    assert metadata["web_api_billable_requests_estimate"] == expected_billable
