from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

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
    advanced_fetch_attempted: bool = False
    quality_score: float = 0.0
    text_length: int = 0
    failure_reason: str | None = None
    content_type: str = ""
    capture_metadata: dict[str, Any] = field(default_factory=dict)
    source_published_at: str | None = None
    source_updated_at: str | None = None

    @property
    def snippet(self) -> str:
        return self.text[:700]


async def fetch_evidence_page(
    url: str,
    *,
    allow_advanced: bool = True,
    timeout_seconds: float = 12.0,
    min_text_chars: int = 120,
    advanced_quality_threshold: float = 0.55,
) -> EvidenceFetchResult:
    """Fetch evidence through the fast HTTP path, then webfetch_v2 when quality is weak."""

    basic = await fetch_page(url, timeout_seconds=timeout_seconds)
    if _basic_fetch_is_policy_blocked(basic):
        return _from_basic_fetch(
            basic,
            fetch_method="basic_httpx_policy_blocked",
            failure_reason="policy_blocked",
        )
    if basic.status_code in {401, 403}:
        return _from_basic_fetch(
            basic, fetch_method="basic_httpx_access_blocked",
            failure_reason="access_denied",
        )
    content_problem = _basic_content_problem(basic)
    if content_problem in {"login_page", "captcha_page"}:
        return _from_basic_fetch(
            basic, fetch_method="basic_httpx_access_blocked",
            failure_reason=content_problem,
        )
    if not content_problem and _basic_fetch_is_sufficient(basic, min_text_chars=min_text_chars):
        return _from_basic_fetch(basic)
    if not allow_advanced:
        return _from_basic_fetch(
            basic,
            fetch_method="basic_httpx_low_quality",
            failure_reason=content_problem or "content_too_short",
        )

    advanced = await advanced_fetch_page(
        url,
        mode="auto",
        timeout_seconds=max(15.0, timeout_seconds),
        quality_threshold=advanced_quality_threshold,
        capture_network=True,
    )
    if _advanced_fetch_is_better(advanced, basic, advanced_quality_threshold):
        return _from_advanced_fetch(advanced)

    if basic.ok:
        return _from_basic_fetch(
            basic,
            fetch_method="basic_httpx_low_quality",
            failure_reason=content_problem or "content_too_short",
            advanced_fetch_attempted=True,
        )
    return _from_failed_fetch(basic, advanced)


def _basic_fetch_is_sufficient(result: FetchPageResult, *, min_text_chars: int) -> bool:
    minimum = (
        min(min_text_chars, 40) if result.content_type == "application/pdf" else min_text_chars
    )
    return result.ok and len(result.text.strip()) >= minimum


def _basic_content_problem(result: FetchPageResult) -> str | None:
    if not result.ok:
        return None
    title = result.title.casefold().strip()
    start = result.text[:500].casefold().strip()
    if any(term in f"{title} {start}" for term in ("captcha", "verify you are human", "验证码")):
        return "captcha_page"
    if re.search(r"^(sign[ -]?in|log[ -]?in|登录|登入)(?:\b|\s|$)", title) or start.startswith(
        ("please sign in", "please log in", "请登录", "请先登录")
    ):
        return "login_page"
    if re.search(r"^(404|not found|page not found|页面不存在)", title) or start.startswith(
        ("this page could not be found", "page not found", "页面不存在")
    ):
        return "soft_404"
    navigation_markers = ("skip to main content", "open menu", "sign in", "sign up", "cookie")
    if sum(marker in start for marker in navigation_markers) >= 4:
        return "navigation_only"
    if len(result.text.strip()) < 40:
        return "content_too_short"
    return None


def _basic_fetch_is_policy_blocked(result: FetchPageResult) -> bool:
    if result.ok or not result.error:
        return False
    return result.error.startswith(
        (
            "Unsupported URL scheme",
            "URL hostname is required",
            "Hostname did not resolve",
            "Blocked ",
            "DNS rebinding detected",
        )
    )


def _advanced_fetch_is_better(
    advanced: AdvancedFetchResult,
    basic: FetchPageResult,
    quality_threshold: float,
) -> bool:
    if not advanced.ok:
        return False
    if (
        advanced.quality.has_captcha
        or advanced.quality.looks_like_login
        or advanced.quality.looks_like_block
        or _basic_content_problem(FetchPageResult(
            url=advanced.final_url, ok=True, title=advanced.title,
            text=advanced.text or advanced.markdown, content_hash="",
        )) in {"login_page", "captcha_page", "soft_404", "navigation_only"}
    ):
        return False
    if advanced.quality.score >= quality_threshold:
        return True
    return len(advanced.text.strip()) > max(len(basic.text.strip()), 0)


def _from_basic_fetch(
    result: FetchPageResult,
    *,
    fetch_method: str = "basic_httpx",
    failure_reason: str | None = None,
    advanced_fetch_attempted: bool = False,
) -> EvidenceFetchResult:
    return EvidenceFetchResult(
        url=result.url,
        ok=result.ok and failure_reason is None,
        title=result.title,
        text=result.text,
        content_hash=result.content_hash,
        status_code=result.status_code,
        error=result.error,
        fetch_method=fetch_method,
        advanced_fetch_attempted=advanced_fetch_attempted,
        quality_score=0.8 if result.ok and failure_reason is None else 0.0,
        text_length=len(result.text),
        failure_reason=failure_reason,
        content_type=result.content_type,
    )


def _from_advanced_fetch(result: AdvancedFetchResult) -> EvidenceFetchResult:
    text = result.text or result.markdown
    artifacts = result.raw.get("artifacts")
    network = result.raw.get("network")
    diagnostics = result.raw.get("diagnostics")
    network_summary = [
        {"url": item.get("url"), "status": item.get("status")}
        for item in network[:20] if isinstance(item, dict)
    ] if isinstance(network, list) else []
    return EvidenceFetchResult(
        url=result.final_url or result.url,
        ok=result.ok,
        title=result.title,
        text=text,
        content_hash=_hash_text(text or result.title or result.final_url or result.url),
        status_code=result.status_code,
        error=result.error,
        fetch_method=f"webfetch_v2:{result.fetch_method}",
        advanced_fetch_attempted=True,
        quality_score=result.quality.score,
        text_length=result.quality.text_length or len(text),
        failure_reason=result.failure_reason,
        content_type=result.content_type,
        capture_metadata={
            "webfetch_artifacts": artifacts if isinstance(artifacts, dict) else {},
            "webfetch_network": network_summary,
            "webfetch_diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
        },
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
        advanced_fetch_attempted=True,
        quality_score=advanced.quality.score,
        text_length=advanced.quality.text_length or len(advanced.text or basic.text),
        failure_reason=failure_reason,
    )


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
