from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packages.identity import normalize_dimension_key


@dataclass(frozen=True)
class DimensionRef:
    key: str
    label: str


def normalize_dimension_ref(value: str | None, *, label: str | None = None) -> DimensionRef:
    key = normalize_dimension_key(value)
    return DimensionRef(key=key, label=label or (value or key))


def normalize_dimension_refs(
    values: Iterable[str],
    *,
    allowed: Iterable[str] | None = None,
    fallback: Iterable[str] = (),
    require: Iterable[str] = (),
    max_count: int | None = None,
) -> list[str]:
    allowed_map = {normalize_dimension_key(item): item for item in allowed or [] if item}
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        key = normalize_dimension_key(value)
        if not key or key in seen:
            continue
        if allowed_map and key not in allowed_map:
            continue
        seen.add(key)
        result.append(allowed_map.get(key, key))
        if max_count is not None and len(result) >= max_count:
            break

    if not result:
        for value in fallback:
            key = normalize_dimension_key(value)
            if not key or key in seen:
                continue
            if allowed_map and key not in allowed_map:
                continue
            seen.add(key)
            result.append(allowed_map.get(key, key))

    for value in require:
        key = normalize_dimension_key(value)
        if not key or key in seen:
            continue
        if allowed_map and key not in allowed_map:
            continue
        seen.add(key)
        result.append(allowed_map.get(key, key))

    return result
