from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webfetch_v2.cache import load_cached_result_by_url, write_cache
from webfetch_v2.fetcher import fetch_url
from webfetch_v2.models import FetchMode
from webfetch_v2.paths import cache_dir


@dataclass(frozen=True)
class BatchItem:
    url: str
    name: str | None = None
    metadata: dict[str, Any] | None = None


async def run_batch(
    items: list[BatchItem],
    *,
    mode: FetchMode | str = FetchMode.AUTO,
    timeout_seconds: float = 15.0,
    quality_threshold: float = 0.55,
    cache: bool = False,
    prefer_cache: bool = False,
    cache_root: str | Path | None = None,
    artifact_dir: str | Path | None = None,
    screenshot: bool = False,
    capture_network: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    selected_mode = FetchMode(mode)
    for item in items:
        payload: dict[str, Any] | None = None
        if prefer_cache:
            payload = load_cached_result_by_url(item.url, cache_root=cache_root)

        if payload is None:
            item_artifact_dir = artifact_dir
            if cache and item_artifact_dir is None and selected_mode == FetchMode.BROWSER:
                item_artifact_dir = cache_dir() / "artifacts" / _safe_name(item.url)
            result = await fetch_url(
                item.url,
                mode=selected_mode,
                timeout_seconds=timeout_seconds,
                quality_threshold=quality_threshold,
                artifact_dir=item_artifact_dir,
                screenshot=screenshot,
                capture_network=capture_network,
            )
            payload = result.to_dict()
            if cache:
                payload["cache"] = write_cache(result, cache_root=cache_root).to_dict()
        payload["batch"] = {
            "name": item.name,
            "metadata": item.metadata or {},
        }
        results.append(payload)

    ok_count = sum(1 for result in results if result.get("ok"))
    failed_count = len(results) - ok_count
    return {
        "summary": {
            "total": len(results),
            "ok": ok_count,
            "failed": failed_count,
        },
        "results": sorted(
            results,
            key=lambda result: result.get("quality", {}).get("score", 0),
            reverse=True,
        ),
    }


def load_batch_items(path: str | Path) -> list[BatchItem]:
    source = Path(path)
    if source.suffix.lower() == ".txt":
        return _load_txt_items(source)
    data = json.loads(source.read_text(encoding="utf-8"))
    return _items_from_json(data)


def _load_txt_items(path: Path) -> list[BatchItem]:
    items: list[BatchItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        items.append(BatchItem(url=stripped))
    return items


def _items_from_json(data: Any) -> list[BatchItem]:
    if isinstance(data, list):
        return [_item_from_value(value) for value in data]
    if isinstance(data, dict):
        items: list[BatchItem] = []
        for group, values in data.items():
            if not isinstance(values, list):
                continue
            for value in values:
                item = _item_from_value(value)
                metadata = dict(item.metadata or {})
                metadata.setdefault("group", group)
                items.append(BatchItem(url=item.url, name=item.name, metadata=metadata))
        return items
    raise ValueError("batch input must be a JSON list/dict or a text file of URLs")


def _item_from_value(value: Any) -> BatchItem:
    if isinstance(value, str):
        return BatchItem(url=value)
    if isinstance(value, dict) and value.get("url"):
        metadata = {key: val for key, val in value.items() if key not in {"url", "name"}}
        return BatchItem(url=str(value["url"]), name=value.get("name"), metadata=metadata)
    raise ValueError(f"invalid batch item: {value!r}")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:80] or "item"
