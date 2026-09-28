from __future__ import annotations

import asyncio
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx

from webfetch_v2.extract import (
    extract_best_content,
    extract_links,
    extract_title,
    failure_reason_from_quality,
    html_to_markdown,
    score_quality,
)
from webfetch_v2.models import Artifacts, Diagnostics, FetchMode, FetchResult, NetworkEntry, Quality
from webfetch_v2.paths import profile_dir
from webfetch_v2.security import PublicURLBlocked, public_egress_proxy, validate_public_url

USER_AGENT = "Mozilla/5.0 (compatible; WebFetchV2/0.1; +https://example.local/webfetch-v2)"
NETWORK_BODY_SAMPLE_LIMIT = 4096
NETWORK_ENTRY_LIMIT = 80
NETWORK_RESOURCE_TYPES = {"document", "fetch", "xhr"}


async def fetch_url(
    url: str,
    *,
    mode: FetchMode | str = FetchMode.AUTO,
    timeout_seconds: float = 15.0,
    quality_threshold: float = 0.55,
    profile: str | None = None,
    artifact_dir: str | Path | None = None,
    screenshot: bool = False,
    capture_network: bool = False,
) -> FetchResult:
    selected_mode = FetchMode(mode)
    async with public_egress_proxy() as proxy_url:
        if selected_mode == FetchMode.STATIC:
            return await _fetch_static(url, timeout_seconds=timeout_seconds, proxy_url=proxy_url)
        if selected_mode == FetchMode.BROWSER:
            return await _fetch_browser(
                url,
                timeout_seconds=timeout_seconds,
                profile=profile,
                artifact_dir=artifact_dir,
                screenshot=screenshot,
                capture_network=capture_network,
                proxy_url=proxy_url,
            )

        static_result = await _fetch_static(url, timeout_seconds=timeout_seconds, proxy_url=proxy_url)
        if static_result.ok and static_result.quality.score >= quality_threshold:
            return static_result
        if _should_try_browser(static_result.quality):
            browser_result = await _fetch_browser(
                url,
                timeout_seconds=timeout_seconds,
                profile=profile,
                artifact_dir=artifact_dir,
                screenshot=screenshot,
                capture_network=capture_network,
                proxy_url=proxy_url,
                fallback_warning=f"static_fetch_low_quality:{static_result.diagnostics.failure_reason}",
            )
            if browser_result.ok or browser_result.quality.score > static_result.quality.score:
                return browser_result
        return static_result


async def _fetch_static(url: str, *, timeout_seconds: float, proxy_url: str | None = None) -> FetchResult:
    started = time.perf_counter()
    try:
        validate_public_url(url)
        if proxy_url is None:
            raise PublicURLBlocked("A public egress proxy is required")
        body_bytes, final_url, status_code, headers = await asyncio.to_thread(
            _fetch_static_http, url, proxy_url, timeout_seconds,
        )
    except (httpx.HTTPError, TimeoutError, OSError, PublicURLBlocked) as exc:
        elapsed_ms = _elapsed_ms(started)
        return _failed_result(
            url=url,
            final_url=url,
            method="static",
            elapsed_ms=elapsed_ms,
            reason="network_or_http_client_error",
            error=str(exc),
        )

    content_type = headers.get("content-type", "")
    charset = _charset_from_content_type(content_type) or "utf-8"
    body = body_bytes.decode(charset, errors="replace")
    title = extract_title(body)
    extracted = extract_best_content(body, title, status_code=status_code)
    text = extracted.text
    quality = score_quality(title, text, status_code=status_code)
    failure_reason = None if quality.score >= 0.55 else failure_reason_from_quality(quality)
    warnings = ["cookie_banner_may_obscure_content"] if quality.cookie_banner_detected else []
    return FetchResult(
        url=url,
        final_url=final_url,
        ok=200 <= status_code < 300 and quality.score >= 0.35 and not quality.has_captcha,
        fetch_method="static",
        status_code=status_code,
        content_type=content_type,
        title=title,
        text=text,
        markdown=html_to_markdown(title, text),
        links=extract_links(body, final_url),
        quality=quality,
        diagnostics=Diagnostics(
            elapsed_ms=_elapsed_ms(started),
            warnings=warnings,
            failure_reason=failure_reason,
        ),
        extraction=extracted.extraction,
    )


def _fetch_static_http(url: str, proxy_url: str, timeout_seconds: float):
    current_url = url
    with httpx.Client(
        proxy=proxy_url, trust_env=False, follow_redirects=False,
        timeout=timeout_seconds, headers={"User-Agent": USER_AGENT},
    ) as client:
        for _ in range(9):
            validate_public_url(current_url)
            response = client.get(current_url)
            if not response.is_redirect or not response.headers.get("location"):
                return response.content, str(response.url), response.status_code, response.headers
            current_url = urljoin(str(response.url), response.headers["location"])
    raise PublicURLBlocked("Too many redirects")


async def _fetch_browser(
    url: str,
    *,
    timeout_seconds: float,
    profile: str | None,
    artifact_dir: str | Path | None,
    screenshot: bool,
    capture_network: bool,
    proxy_url: str | None = None,
    fallback_warning: str | None = None,
) -> FetchResult:
    started = time.perf_counter()
    try:
        await asyncio.to_thread(validate_public_url, url)
        if proxy_url is None:
            raise PublicURLBlocked("A public egress proxy is required")
    except PublicURLBlocked as exc:
        return _failed_result(
            url=url, final_url=url, method="browser", elapsed_ms=_elapsed_ms(started),
            reason="policy_blocked", error=str(exc),
        )
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency may be absent.
        warnings = ["install Playwright with: pip install -e .[browser]; python -m playwright install chromium"]
        if fallback_warning:
            warnings.insert(0, fallback_warning)
        return _failed_result(
            url=url,
            final_url=url,
            method="browser",
            elapsed_ms=_elapsed_ms(started),
            reason="playwright_not_available",
            error=str(exc),
            warnings=warnings,
        )

    warnings = []
    if fallback_warning:
        warnings.append(fallback_warning)
    artifacts = Artifacts()
    network_entries: list[NetworkEntry] = []
    network_tasks = []
    artifact_path = Path(artifact_dir) if artifact_dir else None
    if artifact_path:
        artifact_path.mkdir(parents=True, exist_ok=True)

    try:
        async with async_playwright() as playwright:
            browser_type = playwright.chromium
            if profile:
                context = await browser_type.launch_persistent_context(
                    user_data_dir=str(profile_dir(profile)),
                    headless=True,
                    user_agent=USER_AGENT,
                    service_workers="block",
                    proxy={"server": proxy_url},
                    args=["--proxy-bypass-list=<-loopback>"],
                )
                page = context.pages[0] if context.pages else await context.new_page()
                browser = None
            else:
                browser = await browser_type.launch(
                    headless=True, proxy={"server": proxy_url},
                    args=["--proxy-bypass-list=<-loopback>"],
                )
                context = await browser.new_context(user_agent=USER_AGENT, service_workers="block")
                page = await context.new_page()

            await context.route("**/*", _route_public_request)

            if capture_network:
                page.on("response", lambda response: _schedule_network_capture(response, network_entries, network_tasks))

            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=min(timeout_seconds, 5.0) * 1000)
                except Exception:  # noqa: BLE001 - networkidle is helpful but not required.
                    warnings.append("networkidle_timeout")

                if network_tasks:
                    _done, pending = await asyncio.wait(network_tasks, timeout=2.0)
                    for task in pending:
                        task.cancel()

                rendered_html = await page.content()
                title = await page.title()
                visible_text = await page.locator("body").inner_text(timeout=3000)
                final_url = page.url
                await asyncio.to_thread(validate_public_url, final_url)
                status_code = response.status if response else None
                browser_extracted = extract_best_content(rendered_html, title, status_code=status_code)
                if browser_extracted.text and len(browser_extracted.text) >= len(visible_text) * 0.6:
                    visible_text = browser_extracted.text
                extraction = browser_extracted.extraction
                quality = score_quality(title, visible_text, status_code=status_code)
                failure_reason = None if quality.score >= 0.55 else failure_reason_from_quality(quality)
                if quality.cookie_banner_detected:
                    warnings.append("cookie_banner_may_obscure_content")

                if artifact_path:
                    safe_name = _safe_artifact_name(final_url)
                    html_path = artifact_path / f"{safe_name}.html"
                    html_path.write_text(rendered_html, encoding="utf-8")
                    screenshot_path = None
                    if screenshot:
                        screenshot_file = artifact_path / f"{safe_name}.png"
                        await page.screenshot(path=str(screenshot_file), full_page=True)
                        screenshot_path = str(screenshot_file)
                    artifacts = Artifacts(
                        screenshot_path=screenshot_path,
                        rendered_html_path=str(html_path),
                    )

                return FetchResult(
                    url=url,
                    final_url=final_url,
                    ok=(status_code is None or 200 <= status_code < 300)
                    and quality.score >= 0.35
                    and not quality.has_captcha,
                    fetch_method="browser",
                    status_code=status_code,
                    content_type=response.headers.get("content-type", "") if response else "",
                    title=title,
                    text=visible_text,
                    markdown=html_to_markdown(title, visible_text),
                    links=extract_links(rendered_html, final_url),
                    quality=quality,
                    diagnostics=Diagnostics(
                        elapsed_ms=_elapsed_ms(started),
                        warnings=warnings,
                        failure_reason=failure_reason,
                    ),
                    artifacts=artifacts,
                    network=network_entries[:NETWORK_ENTRY_LIMIT],
                    extraction=extraction,
                )
            finally:
                await context.close()
                if browser:
                    await browser.close()
    except Exception as exc:  # noqa: BLE001 - browser failures should be diagnosable data.
        return _failed_result(
            url=url,
            final_url=url,
            method="browser",
            elapsed_ms=_elapsed_ms(started),
            reason="browser_fetch_error",
            error=str(exc),
            warnings=warnings,
            network=network_entries[:NETWORK_ENTRY_LIMIT],
        )


async def _route_public_request(route) -> None:
    try:
        await asyncio.to_thread(validate_public_url, route.request.url)
    except PublicURLBlocked:
        await route.abort()
    else:
        await route.continue_()


def _schedule_network_capture(response, network_entries: list[NetworkEntry], network_tasks: list) -> None:
    try:
        import asyncio

        network_tasks.append(asyncio.create_task(_capture_network_response(response, network_entries)))
    except RuntimeError:
        return


async def _capture_network_response(response, network_entries: list[NetworkEntry]) -> None:
    if len(network_entries) >= NETWORK_ENTRY_LIMIT:
        return
    try:
        request = response.request
        resource_type = request.resource_type
        if resource_type not in NETWORK_RESOURCE_TYPES:
            return
        content_type = response.headers.get("content-type", "")
        body_sample = None
        size = None
        if _should_sample_body(content_type):
            try:
                body = await response.body()
                size = len(body)
                body_sample = body[:NETWORK_BODY_SAMPLE_LIMIT].decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - response bodies are best-effort diagnostics.
                body_sample = None
        network_entries.append(
            NetworkEntry(
                url=response.url,
                method=request.method,
                status=response.status,
                resource_type=resource_type,
                content_type=content_type,
                size=size,
                body_sample=body_sample,
            )
        )
    except Exception:  # noqa: BLE001 - network capture should not fail page extraction.
        return


def _should_sample_body(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(kind in lowered for kind in ["json", "text", "html", "xml"])


def _should_try_browser(quality: Quality) -> bool:
    return quality.js_required or quality.content_too_short or quality.score < 0.55


def _failed_result(
    *,
    url: str,
    final_url: str,
    method: str,
    elapsed_ms: int,
    reason: str,
    error: str | None = None,
    warnings: list[str] | None = None,
    status_code: int | None = None,
    network: list[NetworkEntry] | None = None,
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url,
        ok=False,
        fetch_method=method,
        status_code=status_code,
        content_type="",
        title="",
        text="",
        markdown="",
        links=[],
        quality=Quality(score=0.0, text_length=0, has_title=False, content_too_short=True),
        diagnostics=Diagnostics(
            elapsed_ms=elapsed_ms,
            warnings=warnings or [],
            failure_reason=reason,
            error=error,
        ),
        network=network or [],
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _safe_artifact_name(url: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in url)[:120]
    return safe or "page"


def _charset_from_content_type(content_type: str) -> str | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip()
    return None
