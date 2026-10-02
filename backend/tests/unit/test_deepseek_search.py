import json

import httpx
import pytest

from packages.config import Settings, get_settings
from packages.search import SearchFilters, WebSearchError


def _settings(**overrides):
    return Settings(
        **{
            "web_search_provider": "deepseek",
            "llm_provider_name": "deepseek",
            "ark_api_key": "test-deepseek-key",
            "ark_model": "deepseek-flash",
            "ark_base_url": "https://api.deepseek.com",
            **overrides,
        }
    )


def _client(settings=None):
    from packages.search.client import create_search_client

    return create_search_client(settings or _settings())


def install_response(monkeypatch, payload, *, status=200, handler=None):
    import packages.search.deepseek_client as module

    requests = []

    async def respond(request):
        requests.append(request)
        if handler:
            return await handler(request)
        return httpx.Response(status, json=payload)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    return requests


def native_response():
    return {
        "content": [
            {"type": "server_tool_use", "name": "web_search", "id": "search-1"},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "search-1",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "产品规格",
                        "url": "https://example.com/specs",
                        "page_age": "2026-09-01",
                    },
                    {
                        "type": "web_search_result",
                        "title": "重复",
                        "url": "https://example.com/specs",
                    },
                    {"type": "web_search_result", "url": "javascript:alert(1)"},
                    {"type": "web_search_result", "url": "https://example.com.evil/pricing"},
                    {
                        "type": "web_search_result",
                        "url": "https://user:password@example.com/private",
                    },
                ],
            },
            {
                "type": "text",
                "text": "不要从 https://invented.example.com 提取候选",
                "citations": [
                    {"url": "https://example.com/specs", "cited_text": "256 GB 存储"},
                ],
            },
        ],
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 10,
            "output_tokens": 30,
            "server_tool_use": {"web_search_requests": 1},
        },
    }


def test_deepseek_can_reuse_official_primary_credentials_without_perplexity():
    assert _settings().has_web_search_credentials
    assert _settings().resolved_deepseek_api_key == "test-deepseek-key"
    assert _client().is_enabled


def test_deepseek_does_not_send_other_provider_credentials_to_official_api():
    settings = _settings(llm_provider_name="doubao", ark_base_url="https://ark.example.com")
    assert not settings.has_web_search_credentials
    assert not settings.resolved_deepseek_api_key


def test_deepseek_explicit_credentials_are_independent_of_report_provider():
    settings = _settings(llm_provider_name="other", deepseek_api_key="search-key")
    assert settings.has_web_search_credentials
    assert settings.resolved_deepseek_api_key == "search-key"


def test_deepseek_env_settings_are_bounded(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "explicit-key")
    monkeypatch.setenv("DEEPSEEK_SEARCH_MAX_TOKENS", "999999")
    monkeypatch.setenv("DEEPSEEK_SEARCH_MAX_USES", "999")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.has_web_search_credentials
        assert settings.deepseek_search_max_tokens == 4096
        assert settings.deepseek_search_max_uses == 3
    finally:
        get_settings.cache_clear()


def test_startup_warning_uses_selected_search_provider(monkeypatch, caplog):
    from packages.config.settings import validate_env_vars

    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "search-key")
    get_settings.cache_clear()
    try:
        validate_env_vars()
        assert "online search will be disabled" not in caplog.text
        assert "PPLX_API_KEY not set" not in caplog.text
    finally:
        get_settings.cache_clear()


async def test_native_search_uses_official_messages_and_only_structured_results(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    client = _client()
    results = await client.search("产品技术规格", max_results=3)
    assert len(results) == 2
    assert results[0].snippet == "256 GB 存储"
    assert results[0].date == "2026-09-01"
    assert results[0].provider == "deepseek"
    assert all("invented" not in result.url for result in results)
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.deepseek.com/anthropic/v1/messages"
    assert requests[0].headers["x-api-key"] == "test-deepseek-key"
    assert body["model"] == "deepseek-flash"
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    assert body["max_tokens"] == 1024


async def test_native_usage_counts_cached_input_and_exposes_search_requests(monkeypatch):
    install_response(monkeypatch, native_response())
    client = _client()
    await client.search("规格")
    usage = client.consume_last_usage()
    assert usage.prompt_tokens == 130
    assert usage.prompt_cache_hit_tokens == 20
    assert usage.completion_tokens == 30
    assert client.consume_last_usage() is None
    metadata = client.consume_last_metadata()
    assert metadata["native_search_requests"] == 1
    assert metadata["filter_mode"] == "prompt_preferences_and_domain_postfilter"


@pytest.mark.parametrize(
    "payload",
    [
        {"content": [{"type": "text", "text": "https://plausible.example.com"}]},
        {
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": {
                        "type": "web_search_tool_result_error",
                        "error_code": "unavailable",
                    },
                }
            ]
        },
        {"content": "invalid"},
    ],
)
async def test_native_search_missing_or_failed_result_blocks_are_errors(monkeypatch, payload):
    install_response(monkeypatch, payload)
    with pytest.raises(WebSearchError):
        await _client().search("测试")


async def test_valid_empty_search_results_are_not_fabricated(monkeypatch):
    install_response(monkeypatch, {"content": [{"type": "web_search_tool_result", "content": []}]})
    assert await _client().search("空结果") == []


async def test_domain_filters_enforced_without_substring_host_bypass(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    filters = SearchFilters(
        search_domain_filter=["example.com"], country="CN", search_recency_filter="year"
    )
    results = await _client().search("官方规格", filters=filters)
    assert [result.url for result in results] == ["https://example.com/specs"]
    prompt = json.loads(requests[0].content)["messages"][0]["content"][0]["text"]
    assert "CN" in prompt and "year" in prompt


async def test_excluded_domains_are_removed(monkeypatch):
    install_response(monkeypatch, native_response())
    results = await _client().search(
        "官方规格", filters=SearchFilters(search_domain_filter=["-example.com"])
    )
    assert [result.url for result in results] == ["https://example.com.evil/pricing"]


@pytest.mark.parametrize("status", [301, 401, 429, 503])
async def test_native_errors_do_not_echo_secrets_or_retry(monkeypatch, status):
    requests = install_response(
        monkeypatch, {"error": {"message": "test-deepseek-key secret request"}}, status=status
    )
    with pytest.raises(WebSearchError) as caught:
        await _client().search("查询")
    assert "test-deepseek-key" not in str(caught.value)
    assert f"HTTP {status}" in str(caught.value)
    assert len(requests) == 1


async def test_native_timeout_is_reported_without_request_details(monkeypatch):
    async def fail(request):
        raise httpx.ReadTimeout("test-deepseek-key", request=request)

    install_response(monkeypatch, {}, handler=fail)
    with pytest.raises(WebSearchError) as caught:
        await _client().search("查询")
    assert "test-deepseek-key" not in str(caught.value)
    assert "超时" in str(caught.value)


async def test_search_disabled_never_sends_request(monkeypatch):
    requests = install_response(monkeypatch, {})
    assert await _client(_settings(ark_api_key=None)).search("查询") == []
    assert requests == []


async def test_standalone_search_budget_blocks_paid_requests_before_dispatch(monkeypatch):
    from packages.llm.errors import LLMExecutionLimitError

    requests = install_response(monkeypatch, native_response())
    with pytest.raises(LLMExecutionLimitError):
        await _client(_settings(run_llm_max_tokens=100)).search("独立搜索")
    assert requests == []


async def test_standalone_client_accounts_multiple_searches_against_same_budget(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    client = _client(_settings(run_llm_max_calls=1))
    await client.search("第一个查询")
    metadata = client.consume_last_metadata()
    assert metadata["llm_tokens_charged"] == 160
    from packages.llm.errors import LLMExecutionLimitError

    with pytest.raises(LLMExecutionLimitError):
        await client.search("第二个查询")
    assert len(requests) == 1
