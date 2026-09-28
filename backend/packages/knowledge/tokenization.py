"""Shared lexical tokens: Latin words and overlapping CJK bigrams."""

from __future__ import annotations

import re

_PARTS = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+")


def lexical_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for part in _PARTS.findall(text.casefold()):
        if "\u3400" <= part[0] <= "\u9fff":
            tokens.extend(part[index : index + 2] for index in range(len(part) - 1))
            if len(part) == 1:
                tokens.append(part)
        else:
            tokens.append(part)
    return tokens


def fts_tokens(text: str) -> str:
    return " ".join(lexical_tokens(text))
