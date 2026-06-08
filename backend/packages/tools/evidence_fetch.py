from __future__ import annotations

import hashlib
from dataclasses import dataclass

from packages.tools.advanced_fetch import AdvancedFetchResult, advanced_fetch_page
from packages.tools.fetch_page import FetchPageResult, fetch_page


@dataclass(frozen=True)
class EvidenceFetchResult:
    url: str
    ok: bool
    title: str
    text: str
    content_hash: str
    status_code: int | None = None
    error: str | None = None
    fetch_method: str = "basic_httpx"
    quality_score: float = 0.0
    text_length: int = 0
    failure_reason: str | None = None

    @property
    def snippet(self) -> str:
        return self.text[:700]


async def fetch_evidence_page(
    url: str,
    *,
    timeout_seconds: float = 12.0,
    min_text_chars: int = 120,
    advanced_quality_threshold: float = 0.55,
) -> EvidenceFetchResult:
    """Fetch evidence through the fast HTTP path, then webfetch_v2 when quality is weak."""

    basic = await fetch_page(url, timeout_seconds=timeout_seconds)
    if _basic_fetch_is_sufficient(basic, min_text_chars=min_text_chars):
        return _from_basic_fetch(basic)

    advanced = await advanced_fetch_page(
        url,
        mode="auto",
        timeout_seconds=max(15.0, timeout_seconds),
        quality_threshold=advanced_quality_threshold,
    )
    if _advanced_fetch_is_better(advanced, basic, advanced_quality_threshold):
        return _from_advanced_fetch(advanced)

    if basic.ok:
        return _from_basic_fetch(
            basic,
            fetch_method="basic_httpx_low_quality",
            failure_reason=advanced.failure_reason
            or advanced.error
            or "advanced_fetch_low_quality",
        )
    return _from_failed_fetch(basic, advanced)


def _basic_fetch_is_sufficient(result: FetchPageResult, *, min_text_chars: int) -> bool:
    return result.ok and len(result.text.strip()) >= min_text_chars


def _advanced_fetch_is_better(
    advanced: AdvancedFetchResult,
    basic: FetchPageResult,
    quality_threshold: float,
) -> bool:
    if not advanced.ok:
        return False
    if advanced.quality.score >= quality_threshold:
        return True
    return len(advanced.text.strip()) > max(len(basic.text.strip()), 0)


def _from_basic_fetch(
    result: FetchPageResult,
    *,
    fetch_method: str = "basic_httpx",
    failure_reason: str | None = None,
) -> EvidenceFetchResult:
    return EvidenceFetchResult(
        url=result.url,
        ok=result.ok,
        title=result.title,
        text=result.text,
        content_hash=result.content_hash,
        status_code=result.status_code,
        error=result.error,
        fetch_method=fetch_method,
        quality_score=1.0 if result.ok else 0.0,
        text_length=len(result.text),
        failure_reason=failure_reason,
    )


def _from_advanced_fetch(result: AdvancedFetchResult) -> EvidenceFetchResult:
    text = result.text or result.markdown
    return EvidenceFetchResult(
        url=result.final_url or result.url,
        ok=result.ok,
        title=result.title,
        text=text,
        content_hash=_hash_text(text or result.title or result.final_url or result.url),
        status_code=result.status_code,
        error=result.error,
        fetch_method=f"webfetch_v2:{result.fetch_method}",
        quality_score=result.quality.score,
        text_length=result.quality.text_length or len(text),
        failure_reason=result.failure_reason,
    )


def _from_failed_fetch(
    basic: FetchPageResult,
    advanced: AdvancedFetchResult,
) -> EvidenceFetchResult:
    failure_reason = advanced.failure_reason or basic.error or advanced.error or "fetch_failed"
    error = advanced.error or basic.error
    return EvidenceFetchResult(
        url=advanced.final_url or advanced.url or basic.url,
        ok=False,
        title=advanced.title or basic.title,
        text=advanced.text or basic.text,
        content_hash=_hash_text(f"{basic.url}:{failure_reason}:{error or ''}"),
        status_code=advanced.status_code or basic.status_code,
        error=error,
        fetch_method=f"webfetch_v2:{advanced.fetch_method}",
        quality_score=advanced.quality.score,
        text_length=advanced.quality.text_length or len(advanced.text or basic.text),
        failure_reason=failure_reason,
    )


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
