from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float = 0.0
    remaining: int = 0


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._events: dict[str, deque[tuple[float, str | None]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        unique_id: str | None = None,
    ) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(allowed=True, remaining=0)
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0][0] <= cutoff:
                events.popleft()
            if unique_id is not None and any(event_id == unique_id for _, event_id in events):
                return RateLimitDecision(allowed=True, remaining=max(0, limit - len(events)))
            if len(events) >= limit:
                retry_after = max(0.0, window_seconds - (now - events[0][0]))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after,
                    remaining=0,
                )
            events.append((now, unique_id))
            return RateLimitDecision(allowed=True, remaining=max(0, limit - len(events)))
