from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from packages.crawler.models import CrawlSource
from packages.crawler.policy import SSRFError, SSRFGuard
from packages.crawler.repository import CrawlerRepository
from packages.crawler.sources import RssProcessor, SitemapProcessor


def _resolver_for(*addresses: str):
    def resolver(host: str, port: int, *args, **kwargs):
        return [
            (
                2,
                1,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolver


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.1.1",
        "fe80::1",
        "169.254.169.254",
        "fd00:ec2::254",
        "224.0.0.1",
        "255.255.255.255",
        "240.0.0.1",
        "0.0.0.0",
    ],
)
async def test_ssrf_guard_blocks_non_public_ranges(address: str) -> None:
    guard = SSRFGuard(resolver=_resolver_for(address))

    with pytest.raises(SSRFError):
        await guard.validate_url("https://target.example/page")


@pytest.mark.asyncio
async def test_ssrf_guard_detects_dns_rebinding() -> None:
    calls = 0

    def resolver(host: str, port: int, *args, **kwargs):
        nonlocal calls
        calls += 1
        address = "93.184.216.34" if calls == 1 else "10.0.0.1"
        return [(2, 1, 6, "", (address, port))]

    guard = SSRFGuard(resolver=resolver)
    resolved = await guard.validate_url("https://target.example/page")

    with pytest.raises(SSRFError):
        await guard.validate_rebinding("https://target.example/page", resolved)


@pytest.mark.asyncio
async def test_sitemap_processor_expands_local_fixture(tmp_path) -> None:
    fixture = tmp_path / "sitemap.xml"
    fixture.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/a</loc></url>
            <url><loc>https://example.com/b</loc></url>
        </urlset>
        """,
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture.read_text(encoding="utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        processor = SitemapProcessor(
            client=client,
            guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
        )
        source = CrawlSource(
            id="source-1",
            type="sitemap",
            config={"url": "https://example.com/sitemap.xml"},
            created_at=datetime.now(UTC),
        )

        assert await processor.expand(source) == [
            "https://example.com/a",
            "https://example.com/b",
        ]


@pytest.mark.asyncio
async def test_rss_processor_expands_mock_feed() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Feed</title>
        <item><title>A</title><link>https://example.com/a</link></item>
        <item><title>B</title><link>https://example.com/b</link></item>
      </channel>
    </rss>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=feed)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        processor = RssProcessor(
            client=client,
            guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
        )
        source = CrawlSource(
            id="source-1",
            type="rss",
            config={"url": "https://example.com/feed.xml"},
            created_at=datetime.now(UTC),
        )

        assert await processor.expand(source) == [
            "https://example.com/a",
            "https://example.com/b",
        ]


@pytest.mark.asyncio
async def test_frontier_persists_dedupes_and_tracks_status(tmp_path) -> None:
    db_path = str(tmp_path / "crawler.db")
    repo = CrawlerRepository(db_path)
    await repo.initialise()
    try:
        source = await repo.create_source("manual", {"urls": ["https://example.com/a"]})
        added = await repo.add_frontier_items(
            ["https://example.com/a#section", "https://example.com/a"],
            source_type="manual",
            run_id=source.id,
        )

        claimed = await repo.claim_pending(limit=10)
        await repo.mark_done(claimed[0].id)
        stats = await repo.stats(source_id=source.id)

        assert added == 1
        assert len(claimed) == 1
        assert stats.done == 1
        assert stats.queued == 0
    finally:
        await repo.close()

    restarted = CrawlerRepository(db_path)
    await restarted.initialise()
    try:
        sources = await restarted.list_sources()
        stats = await restarted.stats(source_id=source.id)

        assert [item.id for item in sources] == [source.id]
        assert stats.done == 1
    finally:
        await restarted.close()
