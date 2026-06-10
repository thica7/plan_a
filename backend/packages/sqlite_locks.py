"""Shared in-process SQLite write locks."""

from __future__ import annotations

import asyncio
import os
from typing import Any

_WRITE_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def write_lock_for(db_path: str) -> asyncio.Lock:
    """Return one asyncio lock per event loop and absolute database path."""
    key = (id(asyncio.get_running_loop()), os.path.abspath(db_path))
    lock = _WRITE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _WRITE_LOCKS[key] = lock
    return lock


async def _execute_and_close(connection: Any, sql: str) -> None:
    cursor = await connection.execute(sql)
    await cursor.close()


async def _fetchone_and_close(connection: Any, sql: str) -> Any:
    cursor = await connection.execute(sql)
    try:
        return await cursor.fetchone()
    finally:
        await cursor.close()


async def apply_sqlite_pragmas(connection: Any) -> str:
    """Apply shared SQLite pragmas, falling back when WAL sidecars are unsupported."""
    try:
        row = await _fetchone_and_close(connection, "PRAGMA journal_mode = WAL")
        journal_mode = str(row[0]).lower() if row else "wal"
    except Exception:
        if getattr(connection, "in_transaction", False):
            await connection.rollback()
        try:
            row = await _fetchone_and_close(connection, "PRAGMA journal_mode = DELETE")
            journal_mode = str(row[0]).lower() if row else "delete"
        except Exception:
            journal_mode = "unknown"

    await _execute_and_close(connection, "PRAGMA busy_timeout = 30000")
    await _execute_and_close(connection, "PRAGMA synchronous = NORMAL")
    await _execute_and_close(connection, "PRAGMA temp_store = MEMORY")
    await _execute_and_close(connection, "PRAGMA cache_size = -20000")
    await _execute_and_close(connection, "PRAGMA foreign_keys = ON")
    if getattr(connection, "in_transaction", False):
        await connection.commit()
    return journal_mode


async def begin_immediate_transaction(connection: Any) -> None:
    """Start a write transaction after clearing any stale implicit transaction."""
    if getattr(connection, "in_transaction", False):
        await connection.rollback()

    try:
        await _execute_and_close(connection, "BEGIN IMMEDIATE")
    except Exception as exc:
        if "cannot start a transaction within a transaction" not in str(exc).lower():
            raise
        await connection.rollback()
        await _execute_and_close(connection, "BEGIN IMMEDIATE")


async def commit_sqlite_transaction(connection: Any, *, attempts: int = 2) -> None:
    """Commit a write transaction, retrying briefly on transient SQLite locks."""
    delay = 0.25
    for attempt in range(attempts):
        try:
            await connection.commit()
            return
        except Exception as exc:
            locked = "database is locked" in str(exc).lower()
            if not locked or attempt == attempts - 1:
                if getattr(connection, "in_transaction", False):
                    await connection.rollback()
                raise
            await asyncio.sleep(delay)
            delay *= 2
