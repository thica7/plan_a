"""Async crawler scheduler: manages crawl jobs with concurrency, retry, and rate limiting."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from .fetcher import PageFetcher
from .models import CrawlFrontierItem, CrawlRequest, CrawlResult
from .parser import parse_html
from .policy import DomainPolicy
from .repository import CrawlerRepository

logger = logging.getLogger(__name__)


class CrawlerScheduler:
    """Manages a pool of crawl tasks with bounded concurrency and callbacks."""

    def __init__(
        self,
        *,
        max_concurrent: int = 5,
        repository: CrawlerRepository | None = None,
        pending_batch_size: int = 10,
        on_result: Callable[[CrawlResult], Awaitable[None]] | None = None,
        on_progress: Callable[[dict[str, int]], Awaitable[None]] | None = None,
    ) -> None:
        self._policy = DomainPolicy()
        self._fetcher = PageFetcher(policy=self._policy)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._repository = repository or CrawlerRepository()
        self._owns_repository = repository is None
        self._pending_batch_size = pending_batch_size
        self._on_result = on_result
        self._on_progress = on_progress
        self._running = False
        self._consumer_task: asyncio.Task[None] | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._progress = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
        }

    async def start(self) -> None:
        """Start the background consumer loop."""
        if self._running:
            return
        await self._repository.initialise()
        self._running = True
        self._consumer_task = asyncio.create_task(self._consumer())

    async def stop(self) -> None:
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        await self._fetcher.close()
        if self._owns_repository:
            await self._repository.close()

    async def enqueue(self, request: CrawlRequest, *, priority: int = 100) -> None:
        """Add a crawl request to the queue."""
        await self._repository.initialise()
        added = await self._repository.add_frontier_items(
            [request.url],
            source_type="manual",
            competitor=request.competitor,
            dimension=request.dimension,
            priority=priority,
            run_id=request.run_id,
        )
        self._progress["queued"] += added
        await self._emit_progress()

    async def crawl_sync(self, request: CrawlRequest) -> CrawlResult:
        """Crawl a single URL synchronously (for tool-style invocations)."""
        async with self._semaphore:
            result = await self._fetcher.fetch(request)
            if result.success and result.page:
                result.page = parse_html(result.page)
                if _should_auto_render(result) and not request.render_js:
                    rendered_result = await self._fetcher.fetch(
                        request.model_copy(update={"render_js": True})
                    )
                    if rendered_result.success and rendered_result.page:
                        rendered_result.page = parse_html(rendered_result.page)
                        return rendered_result
            return result

    async def crawl_batch(self, requests: list[CrawlRequest]) -> list[CrawlResult]:
        """Crawl multiple URLs concurrently."""
        tasks = [self.crawl_sync(req) for req in requests]
        return await asyncio.gather(*tasks)

    def progress(self) -> dict[str, int]:
        """Return a snapshot of queue progress counters."""
        return dict(self._progress)

    async def _consumer(self) -> None:
        """Background loop consuming the crawl queue."""
        while self._running:
            items = await self._repository.claim_pending(limit=self._pending_batch_size)
            if not items:
                await asyncio.sleep(1.0)
                continue

            for item in items:
                task = asyncio.create_task(self._handle_frontier_item(item))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)

    async def _handle_frontier_item(self, item: CrawlFrontierItem) -> None:
        self._progress["queued"] = max(0, self._progress["queued"] - 1)
        self._progress["running"] += 1
        await self._emit_progress()
        try:
            source_config = {}
            if item.run_id:
                source = await self._repository.get_source(item.run_id)
                source_config = source.config if source else {}
            max_depth = _int_config(source_config, "max_depth", 2)
            max_urls = _int_config(source_config, "max_urls", 1_000)
            max_total_bytes = _int_config(source_config, "max_total_bytes", 50_000_000)
            request = CrawlRequest(
                url=item.url,
                run_id=item.run_id,
                competitor=item.competitor,
                dimension=item.dimension,
                max_depth=max_depth,
                max_urls=max_urls,
                max_total_bytes=max_total_bytes,
            )
            result = await self.crawl_sync(request)

            if result.success:
                await self._repository.mark_done(item.id)
                self._progress["completed"] += 1
                if result.page and item.depth < request.max_depth:
                    await self._repository.add_frontier_items(
                        result.page.links,
                        source_type=item.source_type,
                        competitor=item.competitor,
                        dimension=item.dimension,
                        priority=item.priority + 10,
                        depth=item.depth + 1,
                        parent_id=item.id,
                        run_id=item.run_id,
                        max_urls=request.max_urls,
                    )
            else:
                await self._repository.mark_failed(item.id, result.error or "crawl failed")
                self._progress["failed"] += 1

            if self._on_result:
                try:
                    await self._on_result(result)
                except Exception:
                    logger.exception("on_result callback failed")
        finally:
            self._progress["running"] = max(0, self._progress["running"] - 1)
            await self._emit_progress()

    async def _emit_progress(self) -> None:
        if not self._on_progress:
            return
        try:
            await self._on_progress(self.progress())
        except Exception:
            logger.exception("on_progress callback failed")


def _should_auto_render(result: CrawlResult) -> bool:
    mode = os.getenv("KB_JS_RENDER", "auto").strip().lower()
    if mode != "auto" or not result.page:
        return False
    html = result.page.html
    return len(result.page.text.strip()) < 100 or (
        "window.__INITIAL_STATE__" in html or "data-reactroot" in html
    )


def _int_config(config: dict[str, object], key: str, default: int) -> int:
    try:
        return int(config.get(key) or default)
    except (TypeError, ValueError):
        return default
