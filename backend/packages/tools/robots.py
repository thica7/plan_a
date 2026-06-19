from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from packages.crawler.policy import SSRFError, SSRFGuard

DEFAULT_USER_AGENT = "CompetiscopeBot"
_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class RobotsCheckResult:
    url: str
    robots_url: str
    allowed: bool
    checked: bool
    status_code: int | None = None
    error: str | None = None


async def robots_check(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = 4.0,
    guard: SSRFGuard | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RobotsCheckResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return RobotsCheckResult(
            url=url,
            robots_url="",
            allowed=False,
            checked=False,
            error="invalid_url",
        )

    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    try:
        ssrf_guard = guard or SSRFGuard()
        current_url = robots_url
        expected_addresses = await ssrf_guard.validate_url(current_url)
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url)
                if not response.is_redirect:
                    await ssrf_guard.validate_rebinding(str(response.url), expected_addresses)
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(str(response.url), location)
                expected_addresses = await ssrf_guard.validate_url(current_url)
            else:
                return RobotsCheckResult(
                    url=url,
                    robots_url=robots_url,
                    allowed=False,
                    checked=False,
                    error="robots_redirect_limit_exceeded",
                )
    except SSRFError as exc:
        return RobotsCheckResult(
            url=url,
            robots_url=robots_url,
            allowed=False,
            checked=False,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - robots failure should not collapse a research run.
        return RobotsCheckResult(
            url=url,
            robots_url=robots_url,
            allowed=True,
            checked=False,
            error=str(exc),
        )

    if response.status_code >= 400:
        return RobotsCheckResult(
            url=url,
            robots_url=robots_url,
            allowed=True,
            checked=False,
            status_code=response.status_code,
            error=f"robots.txt returned {response.status_code}",
        )

    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    return RobotsCheckResult(
        url=url,
        robots_url=robots_url,
        allowed=parser.can_fetch(user_agent, url),
        checked=True,
        status_code=response.status_code,
    )
