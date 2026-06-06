"""Pydantic models for the Crawling subsystem."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


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


CrawlSourceType = Literal["sitemap", "rss", "web_search", "manual"]
CrawlFrontierStatus = Literal["pending", "running", "done", "failed", "cancelled"]


class CrawlSourceCreate(BaseModel):
    type: CrawlSourceType
    config: dict[str, Any]


class CrawlSource(BaseModel):
    id: str
    type: CrawlSourceType
    config: dict[str, Any]
    created_at: datetime


class CrawlFrontierItem(BaseModel):
    id: str
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
