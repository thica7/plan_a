from __future__ import annotations

import json
from contextvars import ContextVar
from urllib.parse import urlsplit

import httpx

from packages.config import Settings
from packages.llm.doubao_client import LLMUsage
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget, current_llm_execution
from packages.search.perplexity_client import SearchFilters, SearchResult, WebSearchError

DEEPSEEK_SEARCH_ENDPOINT = "https://api.deepseek.com/anthropic/v1/messages"
# Native search injects provider-side page context that the caller cannot size.
SEARCH_INPUT_RESERVE_PER_USE = 16384


class DeepSeekSearchClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._usage: ContextVar[LLMUsage | None] = ContextVar(
            f"search-usage-{id(self)}", default=None
        )
        self._metadata: ContextVar[dict | None] = ContextVar(
            f"search-metadata-{id(self)}", default=None
        )
        # Standalone smoke / project gap fill share the budget for this client.
        # RunService supplies its existing run budget through the context instead.
        self._standalone_budget = RunLLMBudget(
            max_calls=settings.run_llm_max_calls,
            max_repairs=0,
            max_tokens=settings.run_llm_max_tokens,
            max_cost_usd=settings.run_llm_max_cost_usd,
            input_usd_per_million=settings.llm_input_usd_per_million,
            cache_usd_per_million=settings.llm_cache_usd_per_million,
            output_usd_per_million=settings.llm_output_usd_per_million,
        )

    @property
    def is_enabled(self) -> bool:
        return bool(
            self._settings.resolved_deepseek_api_key and self._settings.deepseek_search_model
        )

    def consume_last_usage(self) -> LLMUsage | None:
        usage = self._usage.get()
        self._usage.set(None)
        return usage

    def consume_last_metadata(self) -> dict:
        metadata = self._metadata.get() or {}
        self._metadata.set({})
        return metadata

    async def search(
        self,
        query: str,
        max_results: int = 3,
        *,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        self._usage.set(None)
        self._metadata.set({})
        if not self.is_enabled or not query.strip():
            return []
        if current_llm_execution.get() is not None:
            return await self._search_with_provider(query, max_results, filters=filters)
        filter_text = json.dumps(filters.payload(), ensure_ascii=False) if filters else ""
        execution = LLMCallExecution(
            self._standalone_budget,
            is_repair=False,
            input_tokens=len((query + filter_text).encode("utf-8"))
            + 512
            + SEARCH_INPUT_RESERVE_PER_USE * self._settings.deepseek_search_max_uses,
            max_output_tokens=self._settings.deepseek_search_max_tokens,
        )
        token = current_llm_execution.set(execution)
        try:
            execution.reserve()
            return await self._search_with_provider(query, max_results, filters=filters)
        finally:
            usage = self._usage.get()
            execution.settle(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
            )
            self._metadata.set({**(self._metadata.get() or {}), **execution.metadata()})
            current_llm_execution.reset(token)

    async def _search_with_provider(
        self,
        query: str,
        max_results: int,
        *,
        filters: SearchFilters | None,
    ) -> list[SearchResult]:
        prompt = f"Perform a web search for the query: {query}"
        if filters is not None and filters.payload():
            prompt += "\nSearch preferences: " + json.dumps(filters.payload(), ensure_ascii=False)
        payload = {
            "model": self._settings.deepseek_search_model,
            "max_tokens": self._settings.deepseek_search_max_tokens,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self._settings.deepseek_search_max_uses,
                }
            ],
        }
        key = self._settings.resolved_deepseek_api_key
        headers = {
            "x-api-key": key,
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2023-06-01",
        }
        execution = current_llm_execution.get()
        if execution is not None:
            execution.reserve_transport()
        # No automatic retry: a timeout can happen after a paid native search.
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.llm_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    DEEPSEEK_SEARCH_ENDPOINT, json=payload, headers=headers
                )
        except httpx.TimeoutException:
            raise WebSearchError("DeepSeek 原生搜索超时") from None
        except httpx.HTTPError:
            raise WebSearchError("DeepSeek 原生搜索连接失败") from None
        if not 200 <= response.status_code < 300:
            raise WebSearchError(f"DeepSeek 原生搜索失败（HTTP {response.status_code}）")
        try:
            data = response.json()
        except ValueError:
            raise WebSearchError("DeepSeek 原生搜索返回无效 JSON") from None
        if not isinstance(data, dict):
            raise WebSearchError("DeepSeek 原生搜索返回无效结构")
        usage = _parse_usage(data.get("usage"))
        self._usage.set(usage)
        if execution is not None and usage is not None:
            execution.settle_attempt(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cache_hit_tokens=usage.prompt_cache_hit_tokens or 0,
            )
            execution.provider_accounted = True
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise WebSearchError("DeepSeek 原生搜索返回无效内容块")
        result_blocks = [
            block
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "web_search_tool_result"
        ]
        raw_usage = data.get("usage") or {}
        server_usage = raw_usage.get("server_tool_use") if isinstance(raw_usage, dict) else None
        self._metadata.set(
            {
                "native_search_requests": _nonnegative_int(
                    server_usage.get("web_search_requests")
                    if isinstance(server_usage, dict)
                    else None
                )
                or 0,
                "structured_result_blocks": len(result_blocks),
                "filter_mode": "prompt_preferences_and_domain_postfilter",
            }
        )
        if not result_blocks:
            raise WebSearchError("DeepSeek 未返回原生搜索结果块，无法确认联网搜索")
        snippets = {}
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            citations = block.get("citations")
            for citation in citations if isinstance(citations, list) else []:
                if not isinstance(citation, dict):
                    continue
                url, excerpt = citation.get("url"), citation.get("cited_text")
                if isinstance(url, str) and isinstance(excerpt, str) and excerpt:
                    snippets.setdefault(url, excerpt)
        results, seen = [], set()
        for block in result_blocks:
            items = block.get("content")
            if not isinstance(items, list):
                raise WebSearchError("DeepSeek 原生搜索工具失败或返回无效结果")
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "web_search_result":
                    continue
                url = item.get("url")
                if not _valid_url(url) or url in seen or not _domain_allowed(url, filters):
                    continue
                seen.add(url)
                results.append(
                    SearchResult(
                        title=str(item.get("title") or url),
                        url=url,
                        snippet=snippets.get(url, ""),
                        date=item.get("page_age")
                        if isinstance(item.get("page_age"), str)
                        else None,
                        provider="deepseek",
                    )
                )
        return results[: max(1, min(max_results, 20))]


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_usage(value: object) -> LLMUsage | None:
    if not isinstance(value, dict):
        return None
    prompt = _nonnegative_int(value.get("input_tokens"))
    output = _nonnegative_int(value.get("output_tokens"))
    if prompt is None or output is None:
        return None
    cached = _nonnegative_int(value.get("cache_read_input_tokens")) or 0
    creation = _nonnegative_int(value.get("cache_creation_input_tokens")) or 0
    total_prompt = prompt + cached + creation
    return LLMUsage(
        prompt_tokens=total_prompt,
        completion_tokens=output,
        total_tokens=total_prompt + output,
        prompt_cache_hit_tokens=cached,
        prompt_cache_miss_tokens=prompt + creation,
    )


def _valid_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not (parsed.username or parsed.password)
        )
    except ValueError:
        return False


def _domain_allowed(url: str, filters: SearchFilters | None) -> bool:
    if filters is None or not filters.search_domain_filter:
        return True
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    allowed = [
        domain.lower().lstrip(".").rstrip(".")
        for domain in filters.search_domain_filter
        if not domain.startswith("-")
    ]
    blocked = [
        domain[1:].lower().lstrip(".").rstrip(".")
        for domain in filters.search_domain_filter
        if domain.startswith("-")
    ]
    def matches(domain: str) -> bool:
        return bool(domain) and (host == domain or host.endswith("." + domain))
    return not any(matches(domain) for domain in blocked) and (
        not allowed or any(matches(domain) for domain in allowed)
    )
