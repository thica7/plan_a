from __future__ import annotations

import httpx
import pytest

from app.routes import crawl as crawl_route
from packages.crawler.models import (
    CrawlSource,
    CrawlSourceCreate,
    PricingSourceConfig,
)
from packages.crawler.policy import SSRFGuard
from packages.crawler.repository import CrawlerRepository
from packages.crawler.sources import (
    ChangelogProcessor,
    OfficialDocsProcessor,
    PricingPageProcessor,
    ReviewSiteProcessor,
    SitemapProcessor,
)


def _resolver_for(*addresses: str):
    def resolver(host: str, port: int, *args, **kwargs):
        return [(2, 1, 6, "", (address, port)) for address in addresses]

    return resolver


class FakeSearchClient:
    def __init__(self, urls: list[str]) -> None:
        self.urls = urls
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int) -> list[str]:
        self.queries.append(query)
        return self.urls[:max_results]


@pytest.mark.asyncio
async def test_pricing_processor_uses_query_template_and_url_patterns() -> None:
    search = FakeSearchClient(
        [
            "https://example.com/pricing",
            "https://example.com/blog/pricing-recap",
            "https://example.com/enterprise",
            "https://other.example/plans",
        ]
    )
    processor = PricingPageProcessor(
        {"competitor": "Acme", "include_domains": ["example.com"], "max_urls": 10},
        perplexity_client=search,
        guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
    )

    urls = await processor.expand()

    assert search.queries == ["Acme pricing plans enterprise billing"]
    assert urls == ["https://example.com/pricing", "https://example.com/enterprise"]


@pytest.mark.asyncio
async def test_pricing_processor_returns_empty_without_search_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PPLX_API_KEY", raising=False)

    processor = PricingPageProcessor({"competitor": "Acme"})

    assert await processor.expand() == []


@pytest.mark.asyncio
async def test_official_docs_processor_allows_docs_subdomain() -> None:
    search = FakeSearchClient(
        [
            "https://docs.example.com/reference",
            "https://example.com/api/overview",
            "https://example.com/blog",
        ]
    )
    processor = OfficialDocsProcessor(
        {"competitor": "Acme", "include_domains": ["example.com"], "max_urls": 10},
        perplexity_client=search,
        guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
    )

    assert await processor.expand() == [
        "https://docs.example.com/reference",
        "https://example.com/api/overview",
    ]


@pytest.mark.asyncio
async def test_changelog_processor_combines_rss_and_search_paths() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item><title>A</title><link>https://example.com/changelog/a</link></item>
        <item><title>B</title><link>https://example.com/blog/b</link></item>
      </channel>
    </rss>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=feed)

    search = FakeSearchClient(["https://example.com/releases/c"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        processor = ChangelogProcessor(
            {
                "feed_url": "https://example.com/feed.xml",
                "competitor": "Acme",
                "include_domains": ["example.com"],
            },
            perplexity_client=search,
            http_client=client,
            guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
        )

        assert await processor.expand() == [
            "https://example.com/changelog/a",
            "https://example.com/releases/c",
        ]


@pytest.mark.asyncio
async def test_review_site_processor_limits_to_review_domains() -> None:
    search = FakeSearchClient(
        [
            "https://www.g2.com/products/acme/reviews",
            "https://www.capterra.com/p/123/acme/",
            "https://example.com/reviews/acme",
            "https://trustradius.com/products/acme/reviews",
        ]
    )
    processor = ReviewSiteProcessor(
        {"competitor": "Acme", "max_urls": 10},
        perplexity_client=search,
        guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
    )

    assert await processor.expand() == [
        "https://www.g2.com/products/acme/reviews",
        "https://www.capterra.com/p/123/acme/",
        "https://trustradius.com/products/acme/reviews",
    ]


@pytest.mark.asyncio
async def test_sitemap_processor_applies_include_patterns() -> None:
    async with _sitemap_client(
        [
            "https://example.com/docs/a",
            "https://example.com/pricing",
        ]
    ) as client:
        processor = SitemapProcessor(
            {"url": "https://example.com/sitemap.xml", "include_patterns": [r"/docs/"]},
            http_client=client,
            guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
        )

        assert await processor.expand() == ["https://example.com/docs/a"]


@pytest.mark.asyncio
async def test_sitemap_processor_applies_exclude_and_combined_patterns() -> None:
    async with _sitemap_client(
        [
            "https://example.com/docs/current",
            "https://example.com/docs/archive/old",
            "https://example.com/pricing",
        ]
    ) as client:
        processor = SitemapProcessor(
            {
                "url": "https://example.com/sitemap.xml",
                "include_patterns": [r"/docs/"],
                "exclude_patterns": [r"/archive/"],
            },
            http_client=client,
            guard=SSRFGuard(resolver=_resolver_for("93.184.216.34")),
        )

        assert await processor.expand() == ["https://example.com/docs/current"]


def test_new_source_type_and_config_schema_validation() -> None:
    request = CrawlSourceCreate(
        source_type="pricing",
        config={"competitor": "Acme", "include_patterns": [r"/pricing"]},
    )

    assert request.type == "pricing"
    assert PricingSourceConfig.model_validate(request.config).competitor == "Acme"
    with pytest.raises(ValueError):
        PricingSourceConfig.model_validate({"include_patterns": ["["]})


@pytest.mark.asyncio
async def test_crawl_route_persists_source_metadata_and_frontier_source_id(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = str(tmp_path / "crawler.db")

    async def open_repo() -> CrawlerRepository:
        repo = CrawlerRepository(db_path)
        await repo.initialise()
        return repo

    class FakeProcessor:
        async def expand(self, source: CrawlSource) -> list[str]:
            assert source.type == "pricing"
            return ["https://example.com/pricing"]

    def fake_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(crawl_route, "_open_crawler_repository", open_repo)
    monkeypatch.setattr(crawl_route, "processor_for", lambda source_type: FakeProcessor())
    monkeypatch.setattr(crawl_route.asyncio, "create_task", fake_create_task)

    detail = await crawl_route.create_crawl_source(
        CrawlSourceCreate(
            source_type="pricing",
            config={"competitor": "Acme", "max_urls": 5},
            dimension="pricing",
            priority=7,
        )
    )

    repo = CrawlerRepository(db_path)
    await repo.initialise()
    try:
        source = await repo.get_source(detail.source.id)
        frontier = await repo.list_frontier(source_id=detail.source.id)
    finally:
        await repo.close()

    assert source is not None
    assert source.type == "pricing"
    assert source.competitor == "Acme"
    assert source.dimension == "pricing"
    assert source.priority == 7
    assert source.config["competitor"] == "Acme"
    assert frontier[0].source_id == source.id
    assert frontier[0].source_type == "pricing"
    assert frontier[0].competitor == "Acme"
    assert frontier[0].dimension == "pricing"
    assert frontier[0].priority == 7


def _sitemap_client(urls: list[str]) -> httpx.AsyncClient:
    locs = "\n".join(f"<url><loc>{url}</loc></url>" for url in urls)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        {locs}
    </urlset>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=xml)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
