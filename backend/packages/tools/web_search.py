from __future__ import annotations

from dataclasses import dataclass

from packages.search import SearchClient, SearchFilters, SearchResult


@dataclass(frozen=True)
class WebSearchRequest:
    query: str
    max_results: int = 3
    filters: SearchFilters | None = None


async def web_search(
    client: SearchClient,
    request: WebSearchRequest,
) -> list[SearchResult]:
    kwargs = {"max_results": max(1, min(request.max_results, 20))}
    if request.filters is not None:
        kwargs["filters"] = request.filters
    return await client.search(request.query, **kwargs)
