from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEBFETCH_V2_ROOT = PROJECT_ROOT / "third_party" / "webfetch_v2"


def resolve_webfetch_v2_root(webfetch_root: Path | None = None) -> Path:
    if webfetch_root is not None:
        return webfetch_root
    configured_root = os.environ.get("WEBFETCH_V2_ROOT", "").strip()
    return Path(configured_root) if configured_root else DEFAULT_WEBFETCH_V2_ROOT
