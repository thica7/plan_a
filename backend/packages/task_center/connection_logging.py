"""Keep raw driver connection diagnostics out of this module's logs."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_protected_connection = ContextVar("task_center_protected_connection", default=False)


class _ConnectionLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Drop the entire record before handlers see msg, args or exception data.
        # Other tasks and threads retain their ordinary driver diagnostics.
        return not _protected_connection.get()


_connection_filter = _ConnectionLogFilter()


@contextmanager
def protected_connection_logging() -> Iterator[None]:
    logging.getLogger("psycopg").addFilter(_connection_filter)
    token = _protected_connection.set(True)
    try:
        yield
    finally:
        _protected_connection.reset(token)
