"""Crawl source processors that expand source definitions into URLs."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import CrawlSource, CrawlSourceType
from .policy import SSRFError, SSRFGuard

_PRICING_URL_PATTERNS = [
    r"/pricing(?:/|$)",
    r"/plans(?:/|$)",
    r"/enterprise(?:/|$)",
    r"/billing(?:/|$)",
]
_DOCS_URL_PATTERNS = [
    r"https?://docs\.",
    r"/docs(?:/|$)",
    r"/documentation(?:/|$)",
    r"/api(?:/|$)",
    r"/help(?:/|$)",
    r"/learn(?:/|$)",
]
_CHANGELOG_URL_PATTERNS = [
    r"/changelog(?:/|$)",
    r"/releases(?:/|$)",
    r"/blog/category/releases(?:/|$)",
    r"/what'?s-new(?:/|$)",
]
_REVIEW_SITE_DOMAINS = {"g2.com", "g2crowd.com", "capterra.com", "trustradius.com", "getapp.com"}


class SourceProcessor(ABC):
    @abstractmethod
    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        raise NotImplementedError


class SitemapProcessor(SourceProcessor):
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        http_client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        self._config = config or {}
        self._client = http_client or client
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, self._config)
        sitemap_url = str(config.get("url") or config.get("sitemap_url") or "")
        max_urls = int(config.get("max_urls") or 1_000)
        include_patterns = _pattern_list(config.get("include_patterns"))
        exclude_patterns = _pattern_list(config.get("exclude_patterns"))
        seen: set[str] = set()
        return await self._expand_sitemap(
            sitemap_url,
            seen,
            max_urls=max_urls,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )

    async def _expand_sitemap(
        self,
        sitemap_url: str,
        seen_sitemaps: set[str],
        *,
        max_urls: int,
        include_patterns: list[str],
        exclude_patterns: list[str],
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
                urls.extend(
                    await self._expand_sitemap(
                        loc,
                        seen_sitemaps,
                        max_urls=max_urls,
                        include_patterns=include_patterns,
                        exclude_patterns=exclude_patterns,
                    )
                )
                if len(urls) >= max_urls:
                    return urls[:max_urls]
            return urls
        return [
            url
            for url in _find_loc_values(root)
            if _matches_pattern_filters(
                url,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
        ][:max_urls]

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
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        perplexity_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or {}
        self._perplexity_client = perplexity_client
        self._http_client = http_client

    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, self._config)
        query = str(config.get("query") or "")
        if not query:
            return []
        max_urls = int(config.get("max_urls") or 25)
        return await self._web_search(
            query,
            max_urls=max_urls,
            model=str(config.get("model") or "sonar"),
        )

    async def _web_search(self, query: str, *, max_urls: int, model: str = "sonar") -> list[str]:
        if self._perplexity_client is not None:
            return _urls_from_search_results(
                await _maybe_await(_call_search_client(self._perplexity_client, query, max_urls))
            )[:max_urls]
        api_key = os.getenv("PERPLEXITY_API_KEY") or os.getenv("PPLX_API_KEY")
        if not api_key:
            return []
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return authoritative web results with source citations.",
                },
                {"role": "user", "content": query},
            ],
        }
        if self._http_client is not None:
            response = await self._http_client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        else:
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
    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, {})
        urls = config.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        return [url for url in urls if isinstance(url, str)]


class PricingPageProcessor(WebSearchProcessor):
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        perplexity_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        super().__init__(config, perplexity_client=perplexity_client, http_client=http_client)
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, self._config)
        max_urls = int(config.get("max_urls") or 25)
        query = str(config.get("query") or _named_query(config, "pricing plans enterprise billing"))
        if not query:
            return []
        urls = await self._web_search(query, max_urls=max_urls)
        return await _filter_candidate_urls(
            urls,
            max_urls=max_urls,
            guard=self._guard,
            include_domains=_domain_list(config.get("include_domains")),
            include_patterns=[
                *_pattern_list(config.get("include_patterns")),
                *_pattern_list(config.get("url_patterns")),
                *_PRICING_URL_PATTERNS,
            ],
            exclude_patterns=_pattern_list(config.get("exclude_patterns")),
        )


class OfficialDocsProcessor(WebSearchProcessor):
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        perplexity_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        super().__init__(config, perplexity_client=perplexity_client, http_client=http_client)
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, self._config)
        max_urls = int(config.get("max_urls") or 25)
        query = str(
            config.get("query")
            or _named_query(config, "official docs documentation API help learn")
        )
        if not query:
            return []
        urls = await self._web_search(query, max_urls=max_urls)
        return await _filter_candidate_urls(
            urls,
            max_urls=max_urls,
            guard=self._guard,
            include_domains=_domain_list(config.get("include_domains")),
            include_patterns=[
                *_pattern_list(config.get("include_patterns")),
                *_pattern_list(config.get("url_patterns")),
                *_DOCS_URL_PATTERNS,
            ],
            exclude_patterns=_pattern_list(config.get("exclude_patterns")),
        )


class ChangelogProcessor(WebSearchProcessor):
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        perplexity_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        super().__init__(config, perplexity_client=perplexity_client, http_client=http_client)
        self._http_client = http_client
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, self._config)
        max_urls = int(config.get("max_urls") or 25)
        urls: list[str] = []
        feed_url = str(config.get("feed_url") or config.get("url") or "")
        if feed_url:
            xml_text = await self._fetch_text(feed_url)
            urls.extend(_parse_feed_urls(xml_text))

        query = str(config.get("query") or _named_query(config, "changelog releases what's new"))
        if query:
            urls.extend(await self._web_search(query, max_urls=max_urls))

        return await _filter_candidate_urls(
            urls,
            max_urls=max_urls,
            guard=self._guard,
            include_domains=_domain_list(config.get("include_domains")),
            include_patterns=[
                *_pattern_list(config.get("include_patterns")),
                *_pattern_list(config.get("url_patterns")),
                *_CHANGELOG_URL_PATTERNS,
            ],
            exclude_patterns=_pattern_list(config.get("exclude_patterns")),
        )

    async def _fetch_text(self, url: str) -> str:
        resolved = await self._guard.validate_url(url)
        if self._http_client is not None:
            response = await self._http_client.get(url, follow_redirects=True, timeout=15.0)
        else:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(url)
        response.raise_for_status()
        await self._guard.validate_rebinding(str(response.url), resolved)
        return response.text


class ReviewSiteProcessor(WebSearchProcessor):
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        perplexity_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
        guard: SSRFGuard | None = None,
    ) -> None:
        super().__init__(config, perplexity_client=perplexity_client, http_client=http_client)
        self._guard = guard or SSRFGuard()

    async def expand(self, source: CrawlSource | None = None) -> list[str]:
        config = _source_config(source, self._config)
        max_urls = int(config.get("max_urls") or 25)
        query = str(
            config.get("query")
            or _named_query(config, "reviews G2 Capterra TrustRadius GetApp")
        )
        if not query:
            return []
        configured_domains = set(_domain_list(config.get("include_domains")))
        allowed_domains = (
            configured_domains & _REVIEW_SITE_DOMAINS
            if configured_domains
            else _REVIEW_SITE_DOMAINS
        )
        urls = await self._web_search(query, max_urls=max_urls)
        return await _filter_candidate_urls(
            urls,
            max_urls=max_urls,
            guard=self._guard,
            include_domains=sorted(allowed_domains),
            include_patterns=_pattern_list(config.get("include_patterns")),
            exclude_patterns=_pattern_list(config.get("exclude_patterns")),
        )


def processor_for(source_type: CrawlSourceType) -> SourceProcessor:
    processors: dict[CrawlSourceType, SourceProcessor] = {
        "sitemap": SitemapProcessor(),
        "rss": RssProcessor(),
        "web_search": WebSearchProcessor(),
        "manual": ManualProcessor(),
        "pricing": PricingPageProcessor(),
        "official_docs": OfficialDocsProcessor(),
        "changelog": ChangelogProcessor(),
        "review_site": ReviewSiteProcessor(),
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


def _source_config(source: CrawlSource | None, fallback: dict[str, Any]) -> dict[str, Any]:
    return source.config if source is not None else fallback


def _pattern_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item]
    return []


def _domain_list(value: Any) -> list[str]:
    domains = _pattern_list(value)
    return [domain.lower().removeprefix("www.") for domain in domains]


def _named_query(config: dict[str, Any], suffix: str) -> str:
    competitor = str(config.get("competitor") or "").strip()
    return f"{competitor} {suffix}".strip()


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _call_search_client(client: Any, query: str, max_urls: int) -> Any:
    search = getattr(client, "search", None)
    if search is not None:
        try:
            return search(query, max_results=max_urls)
        except TypeError:
            return search(query, max_urls)
    if callable(client):
        return client(query, max_urls)
    raise TypeError("perplexity_client must be callable or expose search()")


def _urls_from_search_results(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return _extract_urls_from_obj(value)
    if not isinstance(value, Iterable):
        return []

    urls: list[str] = []
    for item in value:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            url = item.get("url") or item.get("link")
            if url:
                urls.append(str(url))
        else:
            url = getattr(item, "url", None)
            if url:
                urls.append(str(url))
    return urls


def _matches_pattern_filters(
    url: str,
    *,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> bool:
    if include_patterns and not any(
        re.search(pattern, url, flags=re.IGNORECASE) for pattern in include_patterns
    ):
        return False
    return not any(re.search(pattern, url, flags=re.IGNORECASE) for pattern in exclude_patterns)


def _matches_domain(url: str, include_domains: list[str]) -> bool:
    if not include_domains:
        return True
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in include_domains)


async def _filter_candidate_urls(
    urls: Iterable[str],
    *,
    max_urls: int,
    guard: SSRFGuard,
    include_domains: list[str],
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not isinstance(url, str) or url in seen:
            continue
        seen.add(url)
        if not _matches_domain(url, include_domains):
            continue
        if not _matches_pattern_filters(
            url,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        ):
            continue
        try:
            await guard.validate_url(url)
        except SSRFError:
            continue
        filtered.append(url)
        if len(filtered) >= max_urls:
            break
    return filtered


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
