"""Bounded in-process work sharing; futures never cross event-loop boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any

from packages.infrastructure.execution_control import ExecutionCapacityError


class SingleFlightCapacityError(ExecutionCapacityError):
    """The bounded local flight cannot accept another caller."""


@dataclass
class _Entry:
    task: asyncio.Task
    waiters: int = 0
    draining: bool = False


class SingleFlight:
    def __init__(self, *, max_keys: int = 256, max_waiters_per_key: int = 64) -> None:
        if any(type(value) is not int or value < 1 for value in (max_keys, max_waiters_per_key)):
            raise ValueError("Singleflight limits must be positive integers")
        self._max_keys = max_keys
        self._max_waiters_per_key = max_waiters_per_key
        self._entries: dict[tuple[asyncio.AbstractEventLoop, Hashable], _Entry] = {}
        self._lock = Lock()

    async def do(self, key: Hashable, work: Callable[[], Awaitable[Any]]) -> Any:
        scoped_key = (asyncio.get_running_loop(), key)
        with self._lock:
            entry = self._entries.get(scoped_key)
            if entry is not None and entry.draining:
                raise SingleFlightCapacityError("Singleflight key is draining")
            if entry is None:
                if len(self._entries) >= self._max_keys:
                    raise SingleFlightCapacityError("Singleflight key capacity exceeded")
                entry = _Entry(asyncio.create_task(work()))
                self._entries[scoped_key] = entry
                entry.task.add_done_callback(lambda task: self._finished(scoped_key, entry, task))
            if entry.waiters >= self._max_waiters_per_key:
                raise SingleFlightCapacityError("Singleflight waiter capacity exceeded")
            entry.waiters += 1
        try:
            return deepcopy(await asyncio.shield(entry.task))
        finally:
            with self._lock:
                entry.waiters -= 1
                if not entry.waiters and not entry.task.done() and not entry.draining:
                    # A thread-backed work coroutine must drain its real computation
                    # before finishing cancellation, so its entry keeps occupying capacity.
                    entry.draining = True
                    entry.task.cancel()

    def _finished(self, key, entry, task) -> None:
        if not task.cancelled():
            task.exception()  # Also consume failures after every caller has cancelled.
        with self._lock:
            if self._entries.get(key) is entry:
                self._entries.pop(key)
