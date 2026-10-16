"""Discardable JSON cache and fixed window rate limits using optional Redis.

Redis is never an authority for evidence, idempotency, or billing. Callers must
supply trusted server-derived rate scopes and validate cached business content.
No Redis dependency is imported and no connection is opened until first use.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Protocol, TypeAlias
from urllib.parse import urlsplit

JSONValue: TypeAlias = "None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]"


class RedisClient(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, *, ex: int) -> object: ...

    async def eval(self, script: str, numkeys: int, *args: object) -> object: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class RedisBackendUnavailable(RuntimeError):
    """An enabled rate limiter could not obtain an authoritative decision."""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


# TIME, counter update and absolute expiry run atomically on one server. The key
# is supplied via KEYS, with no client clock or dynamically constructed keys.
RATE_LIMIT_LUA = """
local server_time = redis.call('TIME')
local now_ms = tonumber(server_time[1]) * 1000 + math.floor(tonumber(server_time[2]) / 1000)
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local window = math.floor(now_ms / window_ms)
local reset_ms = (window + 1) * window_ms
local state = redis.call('HMGET', KEYS[1], 'window', 'count')
local count = 0
if tonumber(state[1]) == window then
    count = tonumber(state[2])
    if not count or count < 0 or count > limit then
        return {-1, 0, 0}
    end
end
if count >= limit then
    return {0, math.ceil((reset_ms - now_ms) / 1000), 0}
end
count = count + 1
redis.call('HSET', KEYS[1], 'window', window, 'count', count)
redis.call('PEXPIREAT', KEYS[1], reset_ms)
return {1, 0, limit - count}
"""


def _positive_integer(value: object, maximum: int | None = None) -> bool:
    return type(value) is int and value > 0 and (maximum is None or value <= maximum)


def _is_json(value: object, depth: int = 0) -> bool:
    if depth > 32:
        return False
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_is_json(item, depth + 1) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_json(item, depth + 1) for key, item in value.items())
    return False


def _json_bytes(value: object) -> bytes:
    if not _is_json(value):
        raise ValueError("Value must contain only bounded JSON types")
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


class RedisRuntime:
    """Lazy async Redis adapter with bounded I/O and no automatic retries."""

    def __init__(
        self,
        url: str | None = None,
        *,
        enabled: bool = False,
        namespace: str = "plan-a",
        timeout_seconds: float = 0.2,
        max_cache_bytes: int = 1_000_000,
        max_cache_ttl_seconds: int = 86_400,
        client: RedisClient | None = None,
    ) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if (
            type(namespace) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", namespace) is None
        ):
            raise ValueError("Invalid Redis namespace")
        if (
            type(timeout_seconds) not in (float, int)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 5
        ):
            raise ValueError("Redis timeout must be greater than zero and at most five seconds")
        if not _positive_integer(max_cache_bytes):
            raise ValueError("max_cache_bytes must be a positive integer")
        if not _positive_integer(max_cache_ttl_seconds, 31_536_000):
            raise ValueError("max_cache_ttl_seconds must be between one second and one year")
        self.enabled = enabled
        self._url = url
        self._prefix = f"plan-a:{namespace}:"
        self._timeout_seconds = float(timeout_seconds)
        self._max_cache_bytes = max_cache_bytes
        self._max_cache_ttl_seconds = max_cache_ttl_seconds
        self._client = client
        self._closed = False

    def _key(self, category: str, parts: JSONValue) -> str:
        digest = hashlib.sha256(_json_bytes(parts)).hexdigest()
        return f"{self._prefix}{category}:{digest}"

    def cache_key(self, *parts: JSONValue) -> str:
        """Hash all key material; callers include their cache policy/version."""
        return self._key("cache", list(parts))

    def _valid_cache_key(self, key: object) -> bool:
        return (
            type(key) is str
            and re.fullmatch(re.escape(self._prefix) + r"cache:[a-f0-9]{64}", key) is not None
        )

    def _get_client(self) -> RedisClient:
        if self._closed or not self.enabled:
            raise RuntimeError("Redis runtime is inactive")
        if self._client is None:
            if type(self._url) is not str:
                raise ValueError("Redis URL is required")
            parsed = urlsplit(self._url)
            # redis-py URL query options override kwargs, including timeouts and
            # decoding. Use a plain URL so those safety bounds remain enforced.
            if (
                parsed.scheme not in {"redis", "rediss"}
                or not parsed.hostname
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Redis URL must use redis/rediss with no query or fragment")
            from redis.asyncio import Redis
            from redis.asyncio.retry import Retry
            from redis.backoff import NoBackoff

            self._client = Redis.from_url(
                self._url,
                socket_connect_timeout=self._timeout_seconds,
                socket_timeout=self._timeout_seconds,
                decode_responses=False,
                retry_on_timeout=False,
                retry=Retry(NoBackoff(), 0),
                max_connections=20,
                health_check_interval=0,
            )
        return self._client

    async def get_json(self, key: str) -> JSONValue | None:
        """Return a bounded JSON value, treating cache/backend errors as misses."""
        if not self.enabled or not self._valid_cache_key(key):
            return None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                payload = await self._get_client().get(key)
            if type(payload) is not bytes or len(payload) > self._max_cache_bytes:
                return None
            value = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
            return value if _is_json(value) else None
        except Exception:
            return None

    async def set_json(self, key: str, value: JSONValue, *, ttl_seconds: int) -> bool:
        """Write JSON with a mandatory TTL, rejecting unbounded/invalid values."""
        if (
            not self.enabled
            or not self._valid_cache_key(key)
            or not _positive_integer(ttl_seconds, self._max_cache_ttl_seconds)
        ):
            return False
        try:
            payload = _json_bytes(value)
            if len(payload) > self._max_cache_bytes:
                return False
            async with asyncio.timeout(self._timeout_seconds):
                return await self._get_client().set(key, payload, ex=ttl_seconds) is True
        except Exception:
            return False

    async def check_rate_limit(
        self, scope: str, *, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        """Consume one allowance for a trusted server-derived scope.

        Disabled limits allow requests. Enabled limits fail closed on backend
        errors; their generic exception message never contains URL credentials.
        """
        if type(scope) is not str or not scope.strip() or len(scope) > 4096:
            raise ValueError("Rate limit scope must be a nonempty bounded string")
        if not _positive_integer(limit, 2_147_483_647) or not _positive_integer(
            window_seconds, 31_536_000
        ):
            raise ValueError("Rate limit policy must use bounded positive integers")
        if not self.enabled:
            return RateLimitDecision(True, 0, limit)
        try:
            key = self._key("rate", [scope, limit, window_seconds])
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._get_client().eval(
                    RATE_LIMIT_LUA, 1, key, limit, window_seconds * 1000
                )
            if (
                type(result) not in (list, tuple)
                or len(result) != 3
                or any(type(value) is not int for value in result)
            ):
                raise ValueError("Invalid rate limit response")
            allowed, retry_after, remaining = result
            if allowed == 1 and retry_after == 0 and 0 <= remaining < limit:
                return RateLimitDecision(True, 0, remaining)
            if allowed == 0 and 1 <= retry_after <= window_seconds and remaining == 0:
                return RateLimitDecision(False, retry_after, 0)
            raise ValueError("Invalid rate limit response")
        except Exception:
            raise RedisBackendUnavailable("Redis rate limit backend unavailable") from None

    async def ping(self) -> bool:
        """Bounded readiness check; disabled, closed or unavailable returns false."""
        if not self.enabled:
            return False
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._get_client().ping() is True
        except Exception:
            return False

    async def aclose(self) -> None:
        """Close an already-created client without creating a new connection."""
        if self._closed:
            return
        self._closed = True
        if self.enabled and self._client is not None:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    await self._client.aclose()
            except Exception:
                pass
