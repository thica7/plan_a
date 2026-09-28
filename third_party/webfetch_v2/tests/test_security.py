from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from webfetch_v2 import fetcher
from webfetch_v2.security import (
    PublicURLBlocked,
    open_public_connection,
    public_egress_proxy,
    validate_public_url,
)


def test_private_destination_and_redirect_are_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        "webfetch_v2.security.socket.getaddrinfo",
        lambda host, port, **kwargs: [(None, None, None, None, ("127.0.0.1", port))],
    )
    with pytest.raises(PublicURLBlocked):
        validate_public_url("https://example.com/page")
    with pytest.raises(PublicURLBlocked):
        validate_public_url("http://127.0.0.1/private")


@pytest.mark.asyncio
async def test_static_fetch_rejects_private_host_before_opening_connection(monkeypatch) -> None:
    monkeypatch.setattr(
        "webfetch_v2.security.socket.getaddrinfo",
        lambda host, port, **kwargs: [(None, None, None, None, ("127.0.0.1", port))],
    )

    def fail_if_opened(*args, **kwargs):
        raise AssertionError("Private destination reached the HTTP opener")

    monkeypatch.setattr(fetcher, "_fetch_static_http", fail_if_opened)
    result = await fetcher._fetch_static("http://127.0.0.1/private", timeout_seconds=1)
    assert result.ok is False
    assert "Blocked" in (result.diagnostics.error or "")


@pytest.mark.asyncio
async def test_browser_blocks_private_subresource_before_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "webfetch_v2.security.socket.getaddrinfo",
        lambda host, port, **kwargs: [(None, None, None, None, ("127.0.0.1", port))],
    )

    class Route:
        def __init__(self) -> None:
            self.request = SimpleNamespace(url="http://127.0.0.1/private")
            self.aborted = False
            self.continued = False

        async def abort(self) -> None:
            self.aborted = True

        async def continue_(self) -> None:
            self.continued = True

    route = Route()
    await fetcher._route_public_request(route)
    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
async def test_egress_connection_uses_validated_ip_without_second_dns_lookup(monkeypatch) -> None:
    lookups = 0
    connected: list[tuple[str, int]] = []

    def changing_dns(host, port, **kwargs):
        nonlocal lookups
        lookups += 1
        address = "93.184.216.34" if lookups == 1 else "127.0.0.1"
        return [(None, None, None, None, (address, port))]

    async def fake_connect(host: str, port: int):
        connected.append((host, port))
        return object(), object()

    monkeypatch.setattr("webfetch_v2.security.socket.getaddrinfo", changing_dns)
    monkeypatch.setattr("webfetch_v2.security.asyncio.open_connection", fake_connect)
    await open_public_connection("example.com", 443)
    assert connected == [("93.184.216.34", 443)]
    assert lookups == 1


@pytest.mark.asyncio
async def test_static_fetch_traverses_guarded_proxy(monkeypatch) -> None:
    request_lines: list[str] = []

    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_lines.append((await reader.readline()).decode().strip())
        while (await reader.readline()) not in {b"\r\n", b"\n", b""}:
            pass
        body = b"<html><title>Product</title><body>Product supports shared planning for teams and project notes.</body></html>"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    original_dns = __import__("socket").getaddrinfo

    def public_dns(host, port, *args, **kwargs):
        if host == "example.com":
            return [(None, None, None, None, ("93.184.216.34", port))]
        return original_dns(host, port, *args, **kwargs)

    monkeypatch.setattr(
        "webfetch_v2.security.socket.getaddrinfo", public_dns,
    )
    monkeypatch.setattr(
        "webfetch_v2.security.open_public_connection",
        lambda host, port: asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1]),
    )
    try:
        async with public_egress_proxy() as proxy_url:
            result = await fetcher._fetch_static(
                "http://example.com/product", timeout_seconds=2, proxy_url=proxy_url,
            )
        assert request_lines == ["GET /product HTTP/1.1"]
        assert result.title == "Product"
        assert "shared planning" in result.text
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_proxy_rejects_private_connect_destination() -> None:
    async with public_egress_proxy() as proxy_url:
        port = int(proxy_url.rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT 127.0.0.1:8000 HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n")
        await writer.drain()
        response = await reader.readline()
        assert response.startswith(b"HTTP/1.1 403")
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_browser_launch_uses_guarded_proxy_and_routes_requests(monkeypatch) -> None:
    launch_options: dict = {}
    routed: list[str] = []

    class Page:
        url = "https://example.com/product"

        async def goto(self, *args, **kwargs):
            return SimpleNamespace(status=200, headers={"content-type": "text/html"})

        async def wait_for_load_state(self, *args, **kwargs) -> None:
            return None

        async def content(self) -> str:
            return "<html><title>Product</title><body>Product supports team planning and shared notes.</body></html>"

        async def title(self) -> str:
            return "Product"

        def locator(self, selector: str):
            return SimpleNamespace(inner_text=self._inner_text)

        async def _inner_text(self, **kwargs) -> str:
            return "Product supports team planning and shared notes."

    class Context:
        async def new_page(self):
            return Page()

        async def route(self, pattern, handler) -> None:
            routed.append(pattern)

        async def close(self) -> None:
            return None

    class Browser:
        async def new_context(self, **kwargs):
            return Context()

        async def close(self) -> None:
            return None

    class BrowserType:
        async def launch(self, **kwargs):
            launch_options.update(kwargs)
            return Browser()

    class Playwright:
        chromium = BrowserType()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    module = types.ModuleType("playwright.async_api")
    module.async_playwright = Playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    monkeypatch.setattr(fetcher, "validate_public_url", lambda url: None)
    result = await fetcher._fetch_browser(
        "https://example.com/product", timeout_seconds=2, profile=None,
        artifact_dir=None, screenshot=False, capture_network=False,
        proxy_url="http://127.0.0.1:8765",
    )
    assert result.fetch_method == "browser"
    assert launch_options["proxy"] == {"server": "http://127.0.0.1:8765"}
    assert "--proxy-bypass-list=<-loopback>" in launch_options["args"]
    assert routed == ["**/*"]
