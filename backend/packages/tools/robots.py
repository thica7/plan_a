from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

DEFAULT_USER_AGENT = "CompetiscopeBot"


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
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(robots_url)
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
