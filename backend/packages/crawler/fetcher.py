"""httpx-based async page fetcher with timeout, size limit, and redirect handling."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from .models import CrawlRequest, CrawlResult, ParsedPage
from .policy import DomainPolicy, SSRFError, SSRFGuard

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}
_LIMITS = httpx.Limits(max_connections=50, max_keepalive_connections=20)
_CONNECT_TIMEOUT_SECONDS = 5.0
_MAX_RETRIES = 3
_MAX_REDIRECTS = 10

logger = logging.getLogger(__name__)


class PageFetcher:
    """Fetches web pages via httpx with policy enforcement."""

    def __init__(self, policy: DomainPolicy | None = None) -> None:
        self._policy = policy or DomainPolicy()
        self._ssrf_guard = SSRFGuard()
        self._clients: dict[bool, httpx.AsyncClient] = {}

    async def _get_client(self, *, verify: bool = True) -> httpx.AsyncClient:
        client = self._clients.get(verify)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                headers=_DEFAULT_HEADERS,
                follow_redirects=True,
                verify=verify,
                limits=_LIMITS,
                timeout=httpx.Timeout(
                    15.0,
                    connect=_CONNECT_TIMEOUT_SECONDS,
                    read=15.0,
                    write=15.0,
                    pool=5.0,
                ),
            )
            self._clients[verify] = client
        return client

    async def close(self) -> None:
        for client in self._clients.values():
            if not client.is_closed:
                await client.aclose()
        self._clients.clear()

    async def fetch(self, request: CrawlRequest) -> CrawlResult:
        """Fetch a single page, respecting policy."""
        start = time.monotonic()

        # Policy checks
        if self._policy.is_denied(request.url):
            return CrawlResult(
                request=request, success=False,
                error=f"Domain denied: {request.url}",
                duration_ms=0, retries=0,
            )

        try:
            await self._ssrf_guard.validate_url(request.url)
        except SSRFError as exc:
            return CrawlResult(
                request=request,
                success=False,
                error=str(exc),
                duration_ms=0,
                retries=0,
            )

        client = await self._get_client(verify=request.verify)

        if request.respect_robots:
            allowed = await self._policy.check_robots(request.url, client)
            if not allowed:
                return CrawlResult(
                    request=request, success=False,
                    error="Blocked by robots.txt",
                    duration_ms=(time.monotonic() - start) * 1000,
                    retries=0,
                )

        # Acquire rate limit
        await self._policy.acquire(request.url)
        try:
            return await self._do_fetch(request, start)
        finally:
            self._policy.release(request.url)

    async def _do_fetch(self, request: CrawlRequest, start: float) -> CrawlResult:
        try:
            resp, retries = await self._get_with_retries(request)

            # Size limit
            byte_limit = min(request.max_bytes, request.max_total_bytes)
            content = resp.content[:byte_limit]
            text = _decode_response_content(resp, content)
            if _render_mode_allows(request.render_js):
                rendered = await self._render_with_playwright(str(resp.url), request)
                if rendered:
                    text = rendered[:byte_limit]
                    content = text.encode("utf-8", errors="replace")
            content_hash = hashlib.sha256(content).hexdigest()[:16]

            page = ParsedPage(
                url=str(resp.url),
                title="",
                text="",
                markdown="",
                html=text,
                meta_description="",
                content_hash=content_hash,
                content_length=len(content),
                content_type=resp.headers.get("content-type", ""),
                status_code=resp.status_code,
                fetched_at=datetime.now(UTC),
            )

            return CrawlResult(
                request=request, page=page,
                success=200 <= resp.status_code < 400,
                error=None if 200 <= resp.status_code < 400 else f"HTTP {resp.status_code}",
                duration_ms=(time.monotonic() - start) * 1000,
                retries=retries,
            )

        except httpx.TimeoutException:
            return CrawlResult(
                request=request, success=False,
                error="Timeout after retries",
                duration_ms=(time.monotonic() - start) * 1000,
                retries=_MAX_RETRIES,
            )
        except httpx.HTTPError as exc:
            return CrawlResult(
                request=request, success=False,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
                retries=_MAX_RETRIES,
            )
        except SSRFError as exc:
            return CrawlResult(
                request=request, success=False,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
                retries=_MAX_RETRIES,
            )

    async def _get_with_retries(self, request: CrawlRequest) -> tuple[httpx.Response, int]:
        timeout = httpx.Timeout(
            request.timeout_seconds,
            connect=min(_CONNECT_TIMEOUT_SECONDS, request.timeout_seconds),
            read=request.timeout_seconds,
            write=request.timeout_seconds,
            pool=5.0,
        )
        retries = 0
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._request_with_redirects(request, timeout)
                return response, retries
            except (httpx.TimeoutException, httpx.TransportError):
                retries += 1
                if attempt >= _MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise httpx.TimeoutException("Exhausted retries")

    async def _request_with_redirects(
        self,
        request: CrawlRequest,
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        client = await self._get_client(verify=request.verify)
        current_url = request.url
        expected_addresses = await self._ssrf_guard.validate_url(current_url)
        for _ in range(_MAX_REDIRECTS + 1):
            response = await client.get(
                current_url,
                timeout=timeout,
                follow_redirects=False,
            )
            if not response.is_redirect:
                await self._ssrf_guard.validate_rebinding(str(response.url), expected_addresses)
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current_url = urljoin(str(response.url), location)
            expected_addresses = await self._ssrf_guard.validate_url(current_url)
        raise httpx.TooManyRedirects("Exceeded maximum redirects")

    async def _render_with_playwright(
        self,
        url: str,
        request: CrawlRequest,
    ) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright is not installed; returning static crawl result")
            return None

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page()
                try:
                    await page.goto(
                        url,
                        wait_until="networkidle",
                        timeout=int(request.timeout_seconds * 1000),
                    )
                    return await page.content()
                finally:
                    await browser.close()
        except Exception:
            logger.warning("Playwright render failed; returning static crawl result", exc_info=True)
            return None


def _render_mode_allows(render_js: bool) -> bool:
    mode = os.getenv("KB_JS_RENDER", "auto").strip().lower()
    if mode == "never":
        return False
    if mode == "always":
        return True
    return render_js


def _decode_response_content(response: httpx.Response, content: bytes) -> str:
    charset = _charset_from_content_type(response.headers.get("content-type", ""))
    if charset:
        return content.decode(charset, errors="replace")

    guessed = (response.encoding or "").lower()
    if guessed in {"", "ascii", "latin-1", "iso-8859-1", "windows-1252", "cp1252"}:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return content.decode(response.encoding or "utf-8", errors="replace")


def _charset_from_content_type(content_type: str) -> str | None:
    match = re.search(r"charset\s*=\s*['\"]?([^;'\"]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None
