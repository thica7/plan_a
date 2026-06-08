from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from webfetch_v2.models import FetchResult
from webfetch_v2.paths import cache_dir as default_cache_dir

INDEX_FILE = "index.json"


@dataclass(frozen=True)
class CacheEntry:
    key: str
    directory: str
    result_path: str
    markdown_path: str | None
    rendered_html_path: str | None
    screenshot_path: str | None
    created_at: str
    url: str | None = None
    final_url: str | None = None
    title: str | None = None
    ok: bool | None = None
    quality_score: float | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_cache(result: FetchResult, *, cache_root: str | Path | None = None) -> CacheEntry:
    root = Path(cache_root) if cache_root else default_cache_dir()
    key = cache_key(result.url, result.final_url)
    directory = root / key
    directory.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(timezone.utc).isoformat()
    result_payload = result.to_dict()
    result_payload["cache_created_at"] = created_at

    result_path = directory / "result.json"
    result_path.write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    markdown_path = None
    if result.markdown:
        markdown_file = directory / "content.md"
        markdown_file.write_text(result.markdown, encoding="utf-8")
        markdown_path = str(markdown_file)

    rendered_html_path = _copy_if_exists(result.artifacts.rendered_html_path, directory / "rendered.html")
    screenshot_path = _copy_if_exists(result.artifacts.screenshot_path, directory / "screenshot.png")

    manifest = CacheEntry(
        key=key,
        directory=str(directory),
        result_path=str(result_path),
        markdown_path=markdown_path,
        rendered_html_path=rendered_html_path,
        screenshot_path=screenshot_path,
        created_at=created_at,
        url=result.url,
        final_url=result.final_url,
        title=result.title,
        ok=result.ok,
        quality_score=result.quality.score,
        failure_reason=result.diagnostics.failure_reason,
    )
    manifest_path = directory / "cache.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _update_index(root, manifest)
    return manifest


def load_cached_result_by_url(url: str, *, cache_root: str | Path | None = None) -> dict[str, Any] | None:
    root = Path(cache_root) if cache_root else default_cache_dir()
    index = _read_index(root)
    key = index.get("by_url", {}).get(url)
    if not key:
        return None
    return load_cached_result(key, cache_root=root)


def load_cached_result(key: str, *, cache_root: str | Path | None = None) -> dict[str, Any] | None:
    root = Path(cache_root) if cache_root else default_cache_dir()
    result_path = root / key / "result.json"
    manifest_path = root / key / "cache.json"
    if not result_path.exists():
        return None
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if manifest_path.exists():
        payload["cache"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["cache"]["hit"] = True
    return payload


def list_cache(*, cache_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(cache_root) if cache_root else default_cache_dir()
    index = _read_index(root)
    entries = list(index.get("entries", {}).values())
    return sorted(entries, key=lambda item: item.get("created_at") or "", reverse=True)


def cache_key(url: str, final_url: str | None = None) -> str:
    material = f"{url}\n{final_url or ''}".encode("utf-8", errors="ignore")
    return hashlib.sha256(material).hexdigest()[:24]


def _copy_if_exists(source: str | None, target: Path) -> str | None:
    if not source:
        return None
    source_path = Path(source)
    if not source_path.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return str(target)


def _update_index(root: Path, entry: CacheEntry) -> None:
    root.mkdir(parents=True, exist_ok=True)
    index = _read_index(root)
    index.setdefault("entries", {})[entry.key] = entry.to_dict()
    by_url = index.setdefault("by_url", {})
    if entry.url:
        by_url[entry.url] = entry.key
    if entry.final_url:
        by_url[entry.final_url] = entry.key
    (root / INDEX_FILE).write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_index(root: Path) -> dict[str, Any]:
    path = root / INDEX_FILE
    if not path.exists():
        return {"entries": {}, "by_url": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": {}, "by_url": {}}