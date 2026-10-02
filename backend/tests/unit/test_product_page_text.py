from __future__ import annotations

import asyncio
import hashlib
import threading
from importlib import import_module

import httpx
import pytest

from packages.crawler.policy import SSRFGuard
from packages.tools.evidence_fetch import _basic_fetch_is_sufficient
from packages.tools.fetch_page import _html_to_text, fetch_page


def _product_html(
    navigation: str = "Browse all products", footer: str = "Privacy and cookies",
) -> str:
    return f"""<!doctype html>
    <html>
      <head><title>Handheld specifications</title></head>
      <body>
        <nav><a href="/products">{navigation}</a></nav>
        <main><article>
          <h1>Handheld specifications</h1>
          <p>This portable game system has a rechargeable battery and supports
             both handheld play and connection to a television at home.</p>
          <table>
            <tr><th>Screen</th><td>7.4-inch touch screen</td></tr>
            <tr><th>Storage</th><td>512GB internal storage</td></tr>
          </table>
        </article></main>
        <footer>{footer}</footer>
      </body>
    </html>"""


def _public_resolver(_host: str, port: int, *_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.215.14", port))]


def test_product_text_excludes_navigation_and_footer() -> None:
    text = _html_to_text(_product_html())

    assert "Browse all products" not in text
    assert "Privacy and cookies" not in text
    assert "portable game system" in text


def test_product_specification_rows_remain_separate() -> None:
    text = _html_to_text(_product_html())
    paragraphs = text.splitlines()
    screen = next(paragraph for paragraph in paragraphs if "Screen" in paragraph)
    storage = next(paragraph for paragraph in paragraphs if "Storage" in paragraph)

    assert "7.4-inch" in screen
    assert "512GB" in storage
    assert screen != storage


@pytest.mark.asyncio
async def test_deeply_nested_product_specs_are_not_truncated() -> None:
    body = (
        '<html><body><nav>Account navigation</nav><main>'
        + '<div>' * 260
        + '<table><tr><th>Screen</th><td>7.4-inch</td></tr>'
        '<tr><th>Storage</th><td>512GB</td></tr></table>'
        + '</div>' * 260
        + '</main><footer>Privacy footer</footer></body></html>'
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=body, headers={"Content-Type": "text/html"}, request=request,
    ))
    result = await fetch_page(
        "https://example.com/product", guard=SSRFGuard(resolver=_public_resolver),
        transport=transport,
    )

    assert result.ok is True
    assert any("Screen" in line and "7.4-inch" in line for line in result.text.splitlines())
    assert any("Storage" in line and "512GB" in line for line in result.text.splitlines())
    assert "Account navigation" not in result.text
    assert "Privacy footer" not in result.text


@pytest.mark.asyncio
async def test_event_loop_responds_while_product_html_is_being_parsed(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def paused_parser(body: str) -> str:
        started.set()
        release.wait(timeout=5.0)  # Watchdog only; success depends on response order.
        try:
            return _html_to_text(body)
        finally:
            finished.set()

    async def event_loop_responder() -> bool:
        assert await asyncio.to_thread(started.wait, 5.0)
        responded_during_parse = not finished.is_set()
        release.set()
        return responded_during_parse

    monkeypatch.setattr(import_module("packages.tools.fetch_page"), "_html_to_text", paused_parser)
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=_product_html(), headers={"Content-Type": "text/html"}, request=request,
    ))
    try:
        responded_during_parse, result = await asyncio.gather(
            event_loop_responder(),
            fetch_page(
                "https://example.com/product", guard=SSRFGuard(resolver=_public_resolver),
                transport=transport,
            ),
        )
    finally:
        release.set()

    assert responded_during_parse is True
    assert result.ok is True
    assert "7.4-inch" in result.text
    assert "512GB" in result.text


def test_short_html_keeps_safe_text_fallback() -> None:
    body = """<title>A &amp; B</title>
    <script>script secret</script><style>style secret</style>
    <noscript>noscript secret</noscript><svg><text>svg secret</text></svg>"""

    assert _html_to_text(body) == "A & B"


def test_empty_extraction_fallback_excludes_navigation_and_footer() -> None:
    body = """<title>A &amp; B</title><nav>Account</nav><footer>Privacy</footer>
    <script>script secret</script><style>style secret</style>
    <noscript>noscript secret</noscript><svg><text>svg secret</text></svg>"""

    assert _html_to_text(body) == "A & B"


@pytest.mark.parametrize(("body", "expected"), [
    ("", ""),
    ("<", "<"),
    ("<span>A &amp; B<script>script secret</script>", "A & B"),
])
def test_empty_or_malformed_short_html_keeps_safe_text(body: str, expected: str) -> None:
    assert _html_to_text(body) == expected


@pytest.mark.asyncio
async def test_fetch_page_hashes_cleaned_product_body() -> None:
    bodies = {
        "/first": _product_html(),
        "/second": _product_html("Shop account support", "Terms and copyright"),
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=bodies[request.url.path],
        headers={"Content-Type": "text/html; charset=utf-8"}, request=request,
    ))
    guard = SSRFGuard(resolver=_public_resolver)
    results = [
        await fetch_page(f"https://example.com{path}", guard=guard, transport=transport)
        for path in bodies
    ]

    for path, result in zip(bodies, results, strict=True):
        assert result.ok is True
        assert result.status_code == 200
        assert result.title == "Handheld specifications"
        assert result.content_type == "text/html"
        assert "7.4-inch" in result.text
        assert "512GB" in result.text
        text_hash = hashlib.sha256(result.text.encode("utf-8")).hexdigest()[:16]
        html_hash = hashlib.sha256(bodies[path].encode("utf-8")).hexdigest()[:16]
        assert result.content_hash == text_hash
        assert result.content_hash != html_hash

    assert results[0].text == results[1].text
    assert results[0].content_hash == results[1].content_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    "<html><body><nav>Browse all products</nav><footer>Privacy and cookies</footer></body></html>",
    """<html><head><title>Specifications</title>
    <script>Screen 7.4-inch Storage 512GB</script></head><body></body></html>""",
])
async def test_pages_without_product_content_do_not_pass_evidence_quality(body: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=body, headers={"Content-Type": "text/html"}, request=request,
    ))
    result = await fetch_page(
        "https://example.com/product", guard=SSRFGuard(resolver=_public_resolver),
        transport=transport,
    )

    assert "7.4-inch" not in result.text
    assert "512GB" not in result.text
    assert _basic_fetch_is_sufficient(result, min_text_chars=120) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["nav", "footer"])
@pytest.mark.parametrize("declaration", ["", '<?xml version="1.0" encoding="UTF-8"?>'])
async def test_long_navigation_and_footer_do_not_become_product_body(
    tag: str, declaration: str,
) -> None:
    links = "".join(
        f'<a href="/category-{index}">Products account services support store privacy '
        f'warranty customer assistance category {index}</a>'
        for index in range(6)
    )
    body = f"{declaration}<html><body><{tag}>{links}</{tag}></body></html>"
    assert len(links) > 120
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=body, headers={"Content-Type": "text/html"}, request=request,
    ))
    result = await fetch_page(
        "https://example.com/navigation", guard=SSRFGuard(resolver=_public_resolver),
        transport=transport,
    )

    assert result.text == ""
    assert result.ok is False
    assert _basic_fetch_is_sufficient(result, min_text_chars=120) is False
