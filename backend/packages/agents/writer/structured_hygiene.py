from __future__ import annotations

import re


SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:#-]+$")
SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]", re.IGNORECASE)


def has_source_token(text: str) -> bool:
    return bool(SOURCE_TOKEN_RE.search(text))


def is_valid_source_id(source_id: str) -> bool:
    return bool(SOURCE_ID_RE.fullmatch(source_id))
