"""DeepSeek's standalone search API; no model generation or token reservation."""
from __future__ import annotations

from contextvars import ContextVar

import httpx

from packages.config import Settings
from packages.search.deepseek_client import _domain_allowed, _valid_url
from packages.search.perplexity_client import SearchFilters, SearchResult, WebSearchError

DEEPSEEK_WEB_SEARCH_ENDPOINT = "https://api.deepseek.com/v1/tools/search"


class DeepSeekWebSearchClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._metadata: ContextVar[dict | None] = ContextVar(
            f"web-search-metadata-{id(self)}", default=None
        )

    @property
    def is_enabled(self) -> bool:
        return bool(self._settings.resolved_deepseek_api_key)

    def consume_last_usage(self):
        return None

    def consume_last_metadata(self) -> dict:
        metadata = self._metadata.get() or {}
        self._metadata.set(None)
        return metadata

    async def search(
        self, query: str, max_results: int = 3, *, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        unsupported = [key for key in (
            "country", "search_recency_filter", "last_updated_after_filter"
        ) if filters and getattr(filters, key)]
        metadata = {
            "web_api_requests": 0,
            "web_api_successful_responses": 0,
            "web_api_billable_requests_estimate": 0,
            "billing_basis": "provider_success_request_estimate_not_invoice",
            "llm_request_attempts": 0,
            "llm_tokens_charged": 0,
            "llm_cost_charged_usd": 0.0,
            "filter_mode": "official_operators_and_domain_postfilter",
            "unsupported_filters": unsupported,
        }
        self._metadata.set(metadata)
        if not self.is_enabled:
            return []
        transport_query = query.strip()
        operators = []
        if filters:
            domains = filters.search_domain_filter or []
            allowed = [f"site:{domain}" for domain in domains if not domain.startswith("-")]
            if allowed:
                operators.append(" OR ".join(allowed))
            operators.extend(f"-site:{domain[1:]}" for domain in domains if domain.startswith("-"))
            if filters.search_language_filter:
                operators.append("lang:" + ",".join(filters.search_language_filter))
        if operators:
            transport_query += " " + " ".join(operators)
        if not query.strip() or not 1 <= len(transport_query) <= 128:
            raise WebSearchError("DeepSeek 搜索 query（含过滤条件）必须为 1–128 个 Unicode 字符")
        payload = {"query": transport_query, "count": max(1, min(max_results, 20)), "need_content": False}
        metadata["web_api_requests"] = 1
        # A timeout can occur after a billable request: never retry automatically.
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.llm_timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.post(
                    DEEPSEEK_WEB_SEARCH_ENDPOINT, json=payload,
                    headers={"Authorization": f"Bearer {self._settings.resolved_deepseek_api_key}"},
                )
        except httpx.TimeoutException:
            raise WebSearchError("DeepSeek 搜索 API 超时") from None
        except httpx.HTTPError:
            raise WebSearchError("DeepSeek 搜索 API 连接失败") from None
        if response.status_code != 200:
            raise WebSearchError(f"DeepSeek 搜索 API 失败（HTTP {response.status_code}）")
        metadata["web_api_successful_responses"] = 1
        metadata["web_api_billable_requests_estimate"] = 1
        try:
            data = response.json()
        except ValueError:
            raise WebSearchError("DeepSeek 搜索 API 返回无效 JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise WebSearchError("DeepSeek 搜索 API 返回无效 results 结构")
        if not data["results"]:
            metadata["web_api_billable_requests_estimate"] = 0
        results, seen = [], set()
        for item in data["results"]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not _valid_url(url) or url in seen or not _domain_allowed(url, filters):
                continue
            title, snippet = item.get("title", url), item.get("snippet", "")
            if not isinstance(title, str) or not isinstance(snippet, str):
                continue
            seen.add(url)
            results.append(SearchResult(
                title=title or url, url=url, snippet=snippet,
                date=item.get("date") if isinstance(item.get("date"), str) else None,
                provider="deepseek",
            ))
        return results[:payload["count"]]
