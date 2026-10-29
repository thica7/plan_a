"""Explicit production knowledge mode and safe local inference dispatch."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import os
from typing import Any


def retrieval_mode_from_env() -> str:
    mode = os.getenv("KB_RETRIEVAL_MODE", "sparse").strip().lower()
    if mode not in {"sparse", "hybrid", "dense"}:
        raise ValueError(f"Unknown KB retrieval mode: {mode}")
    return mode


def semantic_indexing_enabled() -> bool:
    return retrieval_mode_from_env() in {"hybrid", "dense"} and os.getenv(
        "KB_EMBEDDING_PROVIDER", "hash"
    ).strip().lower() in {"local-e5", "local", "local-sentence-transformer", "bge-m3", "http"}


async def call_provider(function: Any, *args: Any) -> Any:
    # Only model computation leaves the event loop. SQLite/Qdrant stay on their owner thread.
    provider = getattr(function, "__self__", None)
    if getattr(provider, "requested_provider", "").startswith("local-"):
        # Shield the executor future: cancelling an await cannot stop a started
        # Python thread. Keep the caller alive until that computation really exits.
        context = contextvars.copy_context()
        worker = asyncio.get_running_loop().run_in_executor(None, context.run, function, *args)
        cancelled = False
        while True:
            try:
                value = await asyncio.shield(worker)
                break
            except asyncio.CancelledError:
                cancelled = True
                if worker.done():
                    break
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError() from None
                raise
        if cancelled:
            if not worker.cancelled():
                worker.exception()
            raise asyncio.CancelledError()
        return value
    value = function(*args)
    return await value if inspect.isawaitable(value) else value
