from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from packages.research.models import CapturedPage, SourceCandidate

FetchCallable = Callable[[str], Awaitable[Any]]


async def capture_candidate(
    candidate: SourceCandidate,
    fetch: FetchCallable,
) -> CapturedPage:
    result = await fetch(candidate.url)
    if result is None:
        return _failed_capture(candidate, "fetch_returned_none")
    status = "ok" if result.ok else "failed"
    text = result.text or ""
    return CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=getattr(result, "url", "") or candidate.url,
        status=status,
        title=getattr(result, "title", "") or candidate.title,
        text=text,
        markdown=text,
        snippet=getattr(result, "snippet", text[:700]),
        content_hash=getattr(result, "content_hash", "") or _content_hash(
            text or candidate.snippet or candidate.title
        ),
        status_code=getattr(result, "status_code", None),
        error=getattr(result, "error", None),
        fetch_method=getattr(result, "fetch_method", "basic_httpx"),
        quality_score=float(getattr(result, "quality_score", 1.0 if result.ok else 0.0) or 0.0),
        text_length=int(getattr(result, "text_length", 0) or len(text)),
        failure_reason=getattr(result, "failure_reason", None),
    )


def _failed_capture(candidate: SourceCandidate, reason: str) -> CapturedPage:
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
        content_hash=_content_hash(content),
        error=reason,
        fetch_method="unavailable",
        quality_score=0.0,
        text_length=0,
        failure_reason=reason,
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
