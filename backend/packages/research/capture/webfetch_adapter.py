from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from packages.research.capture.policy import capture_failure_reason, capture_rejection_reason
from packages.research.models import CapturedPage, SourceCandidate

FetchCallable = Callable[[str], Awaitable[Any]]


async def fetch_candidate_page(
    candidate: SourceCandidate,
    fetch: FetchCallable,
) -> CapturedPage:
    result = await fetch(candidate.url)
    if result is None:
        return failed_capture(candidate, capture_failure_reason(result))
    ok = bool(getattr(result, "ok", False))
    text = str(getattr(result, "text", "") or "")
    markdown = str(getattr(result, "markdown", "") or text)
    title = str(getattr(result, "title", "") or candidate.title)
    rejection_reason = capture_rejection_reason(
        ok=ok,
        title=title,
        text=text,
        markdown=markdown,
    )
    quality_score = float(getattr(result, "quality_score", 1.0 if ok else 0.0) or 0.0)
    if rejection_reason:
        quality_score = min(quality_score, 0.2)
    return CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=str(getattr(result, "url", "") or candidate.url),
        status="rejected" if rejection_reason else "ok" if ok else "failed",
        title=title,
        text=text,
        markdown=markdown,
        snippet=str(getattr(result, "snippet", "") or text[:700]),
        content_hash=str(
            getattr(result, "content_hash", "") or content_hash(text or candidate.snippet)
        ),
        status_code=getattr(result, "status_code", None),
        error=getattr(result, "error", None),
        fetch_method=str(getattr(result, "fetch_method", "") or "basic_httpx"),
        quality_score=quality_score,
        text_length=int(getattr(result, "text_length", 0) or len(text)),
        failure_reason=rejection_reason or None if ok else capture_failure_reason(result),
    )


def failed_capture(candidate: SourceCandidate, reason: str) -> CapturedPage:
    content = candidate.snippet or candidate.title or candidate.url
    return CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=candidate.url,
        status="failed",
        title=candidate.title,
        text="",
        markdown="",
        snippet=candidate.snippet,
        content_hash=content_hash(content),
        error=reason,
        fetch_method="unavailable",
        quality_score=0.0,
        text_length=0,
        failure_reason=reason,
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
