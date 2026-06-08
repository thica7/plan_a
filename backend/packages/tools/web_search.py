from __future__ import annotations

from dataclasses import dataclass

from packages.search import PerplexitySearchClient, SearchResult


@dataclass(frozen=True)
class WebSearchRequest:
    query: str
    max_results: int = 3


async def web_search(
    client: PerplexitySearchClient,
    request: WebSearchRequest,
) -> list[SearchResult]:
    return await client.search(
        request.query,
        max_results=max(1, min(request.max_results, 20)),
    )
