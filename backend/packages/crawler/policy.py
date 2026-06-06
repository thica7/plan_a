"""Policy engine: robots.txt compliance, domain rate limits, allow/deny lists."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

# Per-domain rate limit defaults
DEFAULT_RATE_LIMIT_SECONDS = 2.0
DEFAULT_MAX_CONCURRENT_PER_DOMAIN = 2

# Domains that are always blocked
DENY_DOMAINS: set[str] = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
}

# User agent for robots.txt checks
USER_AGENT = "CompetiscopeBot/1.0 (+https://competiscope.example.com/bot)"

_CLOUD_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}


class SSRFError(ValueError):
    """Raised when a URL resolves to a blocked network destination."""


class SSRFGuard:
    """Resolve and validate crawler destinations before fetching."""

    def __init__(
        self,
        *,
        dns_rebinding_protection: bool = True,
        resolver: Callable[..., list[tuple]] | None = None,
    ) -> None:
        self.dns_rebinding_protection = dns_rebinding_protection
        self._resolver = resolver or socket.getaddrinfo

    async def validate_url(self, url: str) -> set[str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise SSRFError(f"Unsupported URL scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if not hostname:
            raise SSRFError("URL hostname is required")
        addresses = await self.resolve(hostname, parsed.port or _default_port(parsed.scheme))
        if not addresses:
            raise SSRFError(f"Hostname did not resolve: {hostname}")
        for address in addresses:
            self.validate_ip(address)
        return addresses

    async def validate_rebinding(self, url: str, expected_addresses: set[str]) -> None:
        if not self.dns_rebinding_protection:
            return
        resolved = await self.validate_url(url)
        if expected_addresses and expected_addresses.isdisjoint(resolved):
            raise SSRFError("DNS rebinding detected")

    async def resolve(self, hostname: str, port: int) -> set[str]:
        infos = await asyncio.to_thread(
            self._resolver,
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
        addresses: set[str] = set()
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                addresses.add(str(sockaddr[0]))
        return addresses

    @staticmethod
    def validate_ip(address: str) -> None:
        ip = ipaddress.ip_address(address)
        if ip in _CLOUD_METADATA_IPS:
            raise SSRFError(f"Blocked cloud metadata address: {ip}")
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or not ip.is_global
        ):
            raise SSRFError(f"Blocked non-public address: {ip}")
        if ip.version == 4 and int(ip) == 0xFFFFFFFF:
            raise SSRFError(f"Blocked broadcast address: {ip}")


class DomainPolicy:
    """Manages robots.txt caching and per-domain rate limits."""

    def __init__(
        self,
        *,
        default_rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
        domain_rate_limits: dict[str, float] | None = None,
    ) -> None:
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._last_access: dict[str, float] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._global_semaphore = asyncio.Semaphore(10)
        self._default_rate_limit_seconds = default_rate_limit_seconds
        self._domain_rate_limits = domain_rate_limits or {}

    def is_denied(self, url: str) -> bool:
        domain = urlparse(url).hostname or ""
        return domain in DENY_DOMAINS

    async def check_robots(self, url: str, client: httpx.AsyncClient) -> bool:
        """Return True if the URL is allowed by robots.txt."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        if origin not in self._robots_cache:
            robots_url = f"{origin}/robots.txt"
            rp = RobotFileParser()
            try:
                resp = await client.get(robots_url, timeout=5.0, follow_redirects=False)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    # No robots.txt = everything allowed
                    rp.allow_all = True
            except Exception:
                rp.allow_all = True
            self._robots_cache[origin] = rp

        return self._robots_cache[origin].can_fetch(USER_AGENT, url)

    async def acquire(self, url: str) -> None:
        """Acquire per-domain and global rate limit."""
        domain = urlparse(url).hostname or "unknown"

        if domain not in self._semaphores:
            self._semaphores[domain] = asyncio.Semaphore(DEFAULT_MAX_CONCURRENT_PER_DOMAIN)

        await self._global_semaphore.acquire()
        await self._semaphores[domain].acquire()

        # Rate limit: wait if too soon since last access to this domain
        import time
        now = time.monotonic()
        last = self._last_access.get(domain, 0.0)
        rate_limit = self._domain_rate_limits.get(domain, self._default_rate_limit_seconds)
        wait = rate_limit - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_access[domain] = time.monotonic()

    def release(self, url: str) -> None:
        domain = urlparse(url).hostname or "unknown"
        if domain in self._semaphores:
            self._semaphores[domain].release()
        self._global_semaphore.release()


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80
