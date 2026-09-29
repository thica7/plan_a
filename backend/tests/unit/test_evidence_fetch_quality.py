from __future__ import annotations

import pytest

import packages.tools.evidence_fetch as evidence_fetch
from packages.tools.advanced_fetch import AdvancedFetchQuality, AdvancedFetchResult
from packages.tools.fetch_page import FetchPageResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "text", "expected_reason"),
    [
        ("Sign in", "Please sign in to continue. " * 12, "login_page"),
        ("Human verification", "Complete the CAPTCHA to continue. " * 12, "captcha_page"),
        ("404 Not Found", "This page could not be found. " * 12, "soft_404"),
    ],
)
async def test_long_blocked_shell_is_not_accepted_as_evidence(
    monkeypatch, title, text, expected_reason
) -> None:
    calls: list[str] = []

    async def basic(url, **_kwargs):
        return FetchPageResult(url=url, ok=True, title=title, text=text, content_hash="shell")

    async def advanced(url, **_kwargs):
        calls.append(url)
        return AdvancedFetchResult(
            url=url, final_url=url, ok=False, fetch_method="browser",
            title="", text="", markdown="", failure_reason="playwright_not_available",
        )

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page("https://example.com/product")
    assert calls == (["https://example.com/product"] if expected_reason == "soft_404" else [])
    assert result.ok is False
    assert result.quality_score < 0.55
    assert result.failure_reason == expected_reason


@pytest.mark.asyncio
async def test_ordinary_product_copy_uses_fast_path(monkeypatch) -> None:
    text = "The product provides rechargeable battery power for ordinary home cleaning. " * 3

    async def basic(url, **_kwargs):
        return FetchPageResult(url=url, ok=True, title="Product features", text=text, content_hash="content")

    async def advanced(_url, **_kwargs):
        raise AssertionError("Good HTML should not open a browser")

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page("https://example.com/product")
    assert result.ok is True
    assert result.fetch_method == "basic_httpx"
    assert result.quality_score > 0.55


@pytest.mark.asyncio
async def test_low_quality_basic_skips_advanced_when_budget_disallows_it(monkeypatch) -> None:
    async def basic(url, **_kwargs):
        return FetchPageResult(
            url=url, ok=True, title="Loading", text="Loading...", content_hash="short"
        )

    async def advanced(_url, **_kwargs):
        raise AssertionError("Advanced fetch must not run after budget is exhausted")

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page(
        "https://example.com/product", allow_advanced=False
    )
    assert result.ok is False
    assert result.fetch_method == "basic_httpx_low_quality"
    assert result.failure_reason == "content_too_short"


@pytest.mark.asyncio
async def test_short_but_readable_pdf_does_not_require_browser(monkeypatch) -> None:
    async def basic(url, **_kwargs):
        return FetchPageResult(
            url=url, ok=True, title="product.pdf", content_type="application/pdf",
            text="Official current price is 19 dollars per month.", content_hash="pdf-text",
        )

    async def advanced(_url, **_kwargs):
        raise AssertionError("Extracted PDF text does not require a browser")

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page("https://example.com/product.pdf")
    assert result.ok is True
    assert result.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_browser_login_shell_does_not_replace_weak_basic_evidence(monkeypatch) -> None:
    url = "https://example.com/product"

    async def basic(_url, **_kwargs):
        return FetchPageResult(url=url, ok=True, title="Loading", text="Loading...", content_hash="weak")

    async def advanced(_url, **_kwargs):
        return AdvancedFetchResult(
            url=url, final_url=url, ok=True, fetch_method="browser",
            title="Sign in", text="Please sign in to see this product. " * 10,
            markdown="", quality=AdvancedFetchQuality(score=0.5, looks_like_login=True),
        )

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page(url)
    assert result.ok is False
    assert result.quality_score < 0.55
