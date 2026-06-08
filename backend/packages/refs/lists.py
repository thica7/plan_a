from __future__ import annotations

from collections.abc import Iterable


def merge_ordered_refs(*groups: Iterable[object | None]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            if value is None:
                continue
            ref = str(value).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            merged.append(ref)
    return merged
