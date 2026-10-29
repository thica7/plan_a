"""Bounded legacy metadata IO; cancellation joins the borrowed worker slot."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial

from .errors import TaskCenterPoolBusy, TaskCenterUnavailable


class MetadataIO:
    def __init__(self, *, concurrency=4, timeout=5):
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="task-metadata"
        )
        self._slots = asyncio.Semaphore(concurrency)
        self._timeout = timeout
        self._pending = set()
        self._closed = False

    async def run(self, function, *args, **kwargs):
        if self._closed:
            raise TaskCenterUnavailable("task center is stopping")
        try:
            await asyncio.wait_for(self._slots.acquire(), self._timeout)
        except TimeoutError:
            raise TaskCenterPoolBusy("task center metadata workers are busy") from None
        if self._closed:
            self._slots.release()
            raise TaskCenterUnavailable("task center is stopping")
        future = asyncio.get_running_loop().run_in_executor(
            self._executor, copy_context().run, partial(function, *args, **kwargs)
        )
        self._pending.add(future)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Do not release the slot while its synchronous transaction still runs.
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    # The caller's cancellation remains authoritative after joining.
                    break
            if not future.cancelled():
                future.exception()
            raise
        finally:
            self._pending.discard(future)
            self._slots.release()

    async def close(self):
        self._closed = True
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        self._executor.shutdown(wait=True)
