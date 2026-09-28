from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from packages.config import Settings


class WebSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    date: str | None = None
    last_updated: str | None = None


@dataclass(frozen=True)
class SearchFilters:
    country: str | None = None
    search_language_filter: list[str] | None = None
    search_domain_filter: list[str] | None = None
    search_recency_filter: Literal["hour", "day", "week", "month", "year"] | None = None
    last_updated_after_filter: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            key: value for key, value in (
                ("country", self.country),
                ("search_language_filter", self.search_language_filter),
                ("search_domain_filter", self.search_domain_filter),
                ("search_recency_filter", self.search_recency_filter),
                ("last_updated_after_filter", self.last_updated_after_filter),
            ) if value
        }


class PerplexitySearchClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def is_enabled(self) -> bool:
        return self._settings.has_web_search_credentials

    async def search(
        self, query: str, max_results: int = 3, *, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        if not self._settings.pplx_api_key:
            return []

        payload = {"query": query, "max_results": max(1, min(max_results, 20))}
        if filters is not None:
            payload.update(filters.payload())
        headers = {"Authorization": f"Bearer {self._settings.pplx_api_key}"}
        url = f"{self._settings.pplx_base_url}/search"

        async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise WebSearchError(
                f"Perplexity search failed with {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            return []

        results: list[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url_value = item.get("url")
            if not isinstance(url_value, str) or not url_value.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title") or url_value),
                    url=url_value,
                    snippet=str(item.get("snippet") or ""),
                    date=str(item["date"]) if item.get("date") else None,
                    last_updated=str(item["last_updated"]) if item.get("last_updated") else None,
                )
            )
        return results
