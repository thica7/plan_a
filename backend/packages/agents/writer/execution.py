from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def bounded_segment_map(
    segments: Sequence[T],
    worker: Callable[[T, int], Awaitable[R]],
    *,
    concurrency: int,
) -> list[R]:
    """Start only a fixed number of workers while retaining input order."""
    started = time.perf_counter()
    pending = iter(enumerate(segments))
    results: dict[int, R] = {}

    async def consume() -> None:
        for index, segment in pending:
            queued_ms = max(0, int((time.perf_counter() - started) * 1000))
            results[index] = await worker(segment, queued_ms)

    tasks = [asyncio.create_task(consume()) for _ in range(min(len(segments), max(1, concurrency)))]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return [results[index] for index in range(len(segments))]
