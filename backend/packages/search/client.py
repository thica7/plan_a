from __future__ import annotations

from typing import Protocol

from packages.config import Settings
from packages.search.perplexity_client import PerplexitySearchClient, SearchFilters, SearchResult


class SearchClient(Protocol):
    @property
    def is_enabled(self) -> bool: ...

    async def search(
        self, query: str, max_results: int = 3, *, filters: SearchFilters | None = None
    ) -> list[SearchResult]: ...


def create_search_client(settings: Settings) -> SearchClient:
    if settings.web_search_provider == "deepseek":
        from packages.search.deepseek_client import DeepSeekSearchClient

        return DeepSeekSearchClient(settings)
    return PerplexitySearchClient(settings)
