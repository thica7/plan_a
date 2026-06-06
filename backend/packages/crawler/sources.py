"""Crawl source processors that expand source definitions into URLs."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .models import CrawlSource, CrawlSourceType
from .policy import SSRFGuard


class SourceProcessor(ABC):
    @abstractmethod
    async def expand(self, source: CrawlSource) -> list[str]:
        raise NotImplementedError


class SitemapProcessor(SourceProcessor):
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        self._client = client
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource) -> list[str]:
        sitemap_url = str(source.config.get("url") or source.config.get("sitemap_url") or "")
        max_urls = int(source.config.get("max_urls") or 1_000)
        seen: set[str] = set()
        return await self._expand_sitemap(sitemap_url, seen, max_urls=max_urls)

    async def _expand_sitemap(
        self,
        sitemap_url: str,
        seen_sitemaps: set[str],
        *,
        max_urls: int,
    ) -> list[str]:
        if not sitemap_url or sitemap_url in seen_sitemaps or len(seen_sitemaps) > 20:
            return []
        seen_sitemaps.add(sitemap_url)
        xml_text = await self._fetch_text(sitemap_url)
        root = ET.fromstring(xml_text)
        tag = _strip_namespace(root.tag)
        if tag == "sitemapindex":
            urls: list[str] = []
            for loc in _find_loc_values(root):
                urls.extend(await self._expand_sitemap(loc, seen_sitemaps, max_urls=max_urls))
                if len(urls) >= max_urls:
                    return urls[:max_urls]
            return urls
        return _find_loc_values(root)[:max_urls]

    async def _fetch_text(self, url: str) -> str:
        await self._guard.validate_url(url)
        if self._client is not None:
            response = await self._client.get(url, follow_redirects=True, timeout=15.0)
        else:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(url)
        response.raise_for_status()
        await self._guard.validate_url(str(response.url))
        return response.text


class RssProcessor(SourceProcessor):
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        self._client = client
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource) -> list[str]:
        feed_url = str(source.config.get("url") or source.config.get("feed_url") or "")
        max_urls = int(source.config.get("max_urls") or 1_000)
        await self._guard.validate_url(feed_url)
        if self._client is not None:
            response = await self._client.get(feed_url, follow_redirects=True, timeout=15.0)
        else:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(feed_url)
        response.raise_for_status()
        await self._guard.validate_url(str(response.url))
        return _parse_feed_urls(response.text)[:max_urls]


class WebSearchProcessor(SourceProcessor):
    async def expand(self, source: CrawlSource) -> list[str]:
        query = str(source.config.get("query") or "")
        if not query:
            return []
        max_urls = int(source.config.get("max_urls") or 25)
        api_key = os.getenv("PERPLEXITY_API_KEY") or os.getenv("PPLX_API_KEY")
        if not api_key:
            return []
        payload = {
            "model": source.config.get("model") or "sonar",
            "messages": [
                {
                    "role": "system",
                    "content": "Return authoritative web results with source citations.",
                },
                {"role": "user", "content": query},
            ],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        urls = data.get("citations") or []
        if not urls:
            urls = _extract_urls_from_obj(data)
        return [url for url in urls if isinstance(url, str)][:max_urls]


class ManualProcessor(SourceProcessor):
    async def expand(self, source: CrawlSource) -> list[str]:
        urls = source.config.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        return [url for url in urls if isinstance(url, str)]


def processor_for(source_type: CrawlSourceType) -> SourceProcessor:
    processors: dict[CrawlSourceType, SourceProcessor] = {
        "sitemap": SitemapProcessor(),
        "rss": RssProcessor(),
        "web_search": WebSearchProcessor(),
        "manual": ManualProcessor(),
    }
    return processors[source_type]


def _find_loc_values(root: ET.Element) -> list[str]:
    urls: list[str] = []
    for element in root.iter():
        if _strip_namespace(element.tag) == "loc" and element.text:
            value = element.text.strip()
            if value:
                urls.append(value)
    return urls


def _parse_feed_urls(xml_text: str) -> list[str]:
    try:
        import feedparser  # type: ignore[import-untyped]
    except ImportError:
        return _parse_feed_urls_with_xml(xml_text)

    parsed = feedparser.parse(xml_text)
    urls: list[str] = []
    for entry in getattr(parsed, "entries", []):
        link = entry.get("link") if hasattr(entry, "get") else None
        if link:
            urls.append(str(link))
    return urls or _parse_feed_urls_with_xml(xml_text)


def _parse_feed_urls_with_xml(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    urls: list[str] = []
    for entry in root.iter():
        entry_tag = _strip_namespace(entry.tag)
        if entry_tag not in {"item", "entry"}:
            continue
        for element in entry:
            if _strip_namespace(element.tag) != "link":
                continue
            href = element.attrib.get("href")
            if href:
                urls.append(href.strip())
            elif element.text and element.text.strip().startswith(("http://", "https://")):
                urls.append(element.text.strip())
    return urls


def _extract_urls_from_obj(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for nested in value.values():
            urls.extend(_extract_urls_from_obj(nested))
    elif isinstance(value, list):
        for nested in value:
            urls.extend(_extract_urls_from_obj(nested))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        urls.append(value)
    return urls


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
