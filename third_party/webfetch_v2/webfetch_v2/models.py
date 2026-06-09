from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FetchMode(str, Enum):
    STATIC = "static"
    BROWSER = "browser"
    AUTO = "auto"


@dataclass(frozen=True)
class Link:
    url: str
    text: str = ""


@dataclass(frozen=True)
class NetworkEntry:
    url: str
    method: str
    status: int | None
    resource_type: str
    content_type: str = ""
    size: int | None = None
    body_sample: str | None = None


@dataclass(frozen=True)
class ExtractionCandidate:
    method: str
    score: float
    text_length: int
    selected: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    method: str
    candidates: list[ExtractionCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class Quality:
    score: float
    text_length: int
    has_title: bool
    has_captcha: bool = False
    looks_like_login: bool = False
    looks_like_block: bool = False
    js_required: bool = False
    content_too_short: bool = False
    cookie_banner_detected: bool = False


@dataclass(frozen=True)
class Diagnostics:
    elapsed_ms: int
    warnings: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    error: str | None = None
    retries: int = 0


@dataclass(frozen=True)
class Artifacts:
    screenshot_path: str | None = None
    rendered_html_path: str | None = None


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    ok: bool
    fetch_method: str
    status_code: int | None
    content_type: str
    title: str
    text: str
    markdown: str
    links: list[Link]
    quality: Quality
    diagnostics: Diagnostics
    artifacts: Artifacts = field(default_factory=Artifacts)
    network: list[NetworkEntry] = field(default_factory=list)
    extraction: ExtractionResult = field(default_factory=lambda: ExtractionResult(method="unknown"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)