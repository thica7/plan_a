from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runtime_root() -> Path:
    configured = os.getenv("COMPETISCOPE_RUNTIME_ROOT")
    if not configured:
        return repo_root()
    path = Path(configured)
    if path.is_absolute():
        return path
    return repo_root().joinpath(path)


def runtime_path(*parts: str) -> Path:
    return runtime_root().joinpath(*parts)
