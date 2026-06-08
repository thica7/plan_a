from __future__ import annotations

from pathlib import Path


def data_dir() -> Path:
    return Path.home() / ".webfetch_v2"


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def profile_dir(profile: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in profile)
    return profiles_dir() / safe


def cache_dir() -> Path:
    return data_dir() / "cache"
