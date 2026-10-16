"""Optional deployment acceleration; durable business state remains outside Redis."""

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache

from packages.infrastructure.redis_runtime import RedisRuntime


@dataclass(frozen=True)
class RedisOptions:
    cache_enabled: bool = False
    rate_limit_enabled: bool = False
    url: str | None = field(default=None, repr=False)
    cache_ttl_seconds: int = 300
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60
    timeout_seconds: float = 0.25


@lru_cache(maxsize=1)
def redis_options() -> RedisOptions:
    def enabled(name):
        value = os.getenv(name, "false").strip().lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError(f"{name} must be true or false")
        return value in {"true", "1"}

    def integer(name, default, maximum):
        value = int(os.getenv(name, str(default)))
        if not 1 <= value <= maximum:
            raise ValueError(f"{name} is outside the supported range")
        return value

    timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", ".25"))
    if not math.isfinite(timeout) or not 0.01 <= timeout <= 2:
        raise ValueError("REDIS_CONNECT_TIMEOUT_SECONDS must be 0.01–2")
    return RedisOptions(
        cache_enabled=enabled("REDIS_CACHE_ENABLED"),
        rate_limit_enabled=enabled("REDIS_RATE_LIMIT_ENABLED"),
        url=os.getenv("REDIS_URL"),
        cache_ttl_seconds=integer("REDIS_CACHE_TTL_SECONDS", 300, 86400),
        rate_limit_requests=integer("REDIS_RATE_LIMIT_REQUESTS", 10, 100000),
        rate_limit_window_seconds=integer("REDIS_RATE_LIMIT_WINDOW_SECONDS", 60, 3600),
        timeout_seconds=timeout,
    )


@lru_cache(maxsize=1)
def get_redis_runtime() -> RedisRuntime:
    options = redis_options()
    return RedisRuntime(
        url=options.url,
        enabled=options.cache_enabled or options.rate_limit_enabled,
        timeout_seconds=options.timeout_seconds,
    )
