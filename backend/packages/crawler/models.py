"""Pydantic models for the Crawling subsystem."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class CrawlRequest(BaseModel):
    """Request to crawl a single URL."""

    url: str
    run_id: str | None = None
    competitor: str | None = None
    dimension: str | None = None
    render_js: bool = False
    timeout_seconds: float = 15.0
    respect_robots: bool = True
    verify: bool = True
    max_bytes: int = 5_000_000  # 5 MB
    max_depth: int = 2
    max_urls: int = 1_000
    max_total_bytes: int = 50_000_000


class ParsedPage(BaseModel):
    """Structured output from parsing a crawled page."""

    url: str
    title: str = ""
    text: str = ""
    markdown: str = ""
    html: str = ""
    meta_description: str = ""
    meta_keywords: list[str] = []
    tables: list[dict[str, Any]] = []
    links: list[str] = []
    fetched_at: datetime
    content_hash: str
    content_length: int = 0
    content_type: str = ""
    status_code: int = 0


class CrawlResult(BaseModel):
    """Result of a crawl attempt."""

    request: CrawlRequest
    page: ParsedPage | None = None
    success: bool
    error: str | None = None
    duration_ms: float = 0.0
    retries: int = 0


CrawlSourceType = Literal[
    "sitemap",
    "rss",
    "web_search",
    "manual",
    "pricing",
    "official_docs",
    "changelog",
    "review_site",
]
CrawlFrontierStatus = Literal["pending", "running", "done", "failed", "cancelled"]


class _PatternConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)

    @field_validator("include_patterns", "exclude_patterns", "url_patterns", check_fields=False)
    @classmethod
    def _validate_regex_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern {pattern!r}: {exc}") from exc
        return value


class SitemapSourceConfig(_PatternConfig):
    url: str | None = None
    sitemap_url: str | None = None
    max_urls: int = Field(default=1_000, ge=1)


class PricingSourceConfig(_PatternConfig):
    query: str | None = None
    competitor: str | None = None
    max_urls: int = Field(default=25, ge=1)
    include_domains: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)


class OfficialDocsSourceConfig(_PatternConfig):
    query: str | None = None
    competitor: str | None = None
    max_urls: int = Field(default=25, ge=1)
    include_domains: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)


class ChangelogSourceConfig(_PatternConfig):
    url: str | None = None
    feed_url: str | None = None
    query: str | None = None
    competitor: str | None = None
    max_urls: int = Field(default=25, ge=1)
    include_domains: list[str] = Field(default_factory=list)
    url_patterns: list[str] = Field(default_factory=list)


class ReviewSiteSourceConfig(_PatternConfig):
    query: str | None = None
    competitor: str | None = None
    max_urls: int = Field(default=25, ge=1)
    include_domains: list[str] = Field(default_factory=list)


_SOURCE_CONFIG_SCHEMAS: dict[CrawlSourceType, type[BaseModel]] = {
    "sitemap": SitemapSourceConfig,
    "pricing": PricingSourceConfig,
    "official_docs": OfficialDocsSourceConfig,
    "changelog": ChangelogSourceConfig,
    "review_site": ReviewSiteSourceConfig,
}


class CrawlSourceCreate(BaseModel):
    type: CrawlSourceType = Field(validation_alias=AliasChoices("type", "source_type"))
    config: dict[str, Any] = Field(default_factory=dict)
    competitor: str | None = None
    dimension: str | None = None
    priority: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_source_config(self) -> CrawlSourceCreate:
        schema = _SOURCE_CONFIG_SCHEMAS.get(self.type)
        if schema is not None:
            self.config = schema.model_validate(self.config).model_dump(exclude_none=True)
        return self


class CrawlSource(BaseModel):
    id: str
    type: CrawlSourceType
    config: dict[str, Any]
    competitor: str | None = None
    dimension: str | None = None
    priority: int = 100
    created_at: datetime


class CrawlFrontierItem(BaseModel):
    id: str
    source_id: str | None = None
    source_type: CrawlSourceType
    url: str
    canonical_url: str
    competitor: str | None = None
    dimension: str | None = None
    priority: int = 100
    depth: int = 0
    status: CrawlFrontierStatus = "pending"
    attempts: int = 0
    next_run_at: datetime
    last_error: str | None = None
    parent_id: str | None = None
    discovered_at: datetime
    run_id: str | None = None


class CrawlFrontierStats(BaseModel):
    queued: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0
