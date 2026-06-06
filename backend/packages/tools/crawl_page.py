"""LangGraph tool for crawling one page."""

from __future__ import annotations

from langchain_core.tools import tool

from ..crawler.models import CrawlRequest
from ..crawler.parser import parse_html
from ..crawler.scheduler import CrawlerScheduler


@tool
async def crawl_page_tool(
    url: str,
    competitor: str,
    dimension: str,
) -> dict[str, object]:
    """Crawl and parse a single competitor page."""
    scheduler = CrawlerScheduler()
    try:
        result = await scheduler.crawl_sync(
            CrawlRequest(url=url, competitor=competitor, dimension=dimension)
        )
        if result.success and result.page:
            result.page = parse_html(result.page)
        return result.model_dump(mode="json")
    finally:
        await scheduler.stop()
