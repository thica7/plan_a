from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

_CONTROL_CHAR_TRANSLATION = {
    codepoint: " "
    for codepoint in range(32)
    if codepoint not in {9, 10, 13}
}
_CONTROL_CHAR_TRANSLATION[0] = ""


def sanitize_postgres_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.encode("utf-8", errors="replace").decode("utf-8").translate(
        _CONTROL_CHAR_TRANSLATION
    )


def sanitize_postgres_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return sanitize_postgres_text(value)
    if isinstance(value, BaseModel):
        return sanitize_postgres_value(value.model_dump(mode="json"))
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            sanitize_postgres_text(str(key)) or "": sanitize_postgres_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [sanitize_postgres_value(item) for item in value]
    return value
