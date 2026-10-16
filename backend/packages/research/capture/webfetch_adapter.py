from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from packages.business_intel.official_registry import registered_product
from packages.research.capture.official import verify_registered_capture
from packages.research.capture.policy import capture_failure_reason, capture_rejection_reason
from packages.research.models import CapturedPage, SourceCandidate
from packages.tools.evidence_fetch import EvidenceFetchResult

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
    dynamic_product = registered_product(candidate.competitor) is not None
    title = str(getattr(result, "title", "") or ("" if dynamic_product else candidate.title))
    rejection_reason = capture_rejection_reason(
        ok=ok,
        title=title,
        text=text,
        markdown=markdown,
    )
    quality_score = float(getattr(result, "quality_score", 1.0 if ok else 0.0) or 0.0)
    if rejection_reason:
        quality_score = min(quality_score, 0.2)
    page = CapturedPage(
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
        source_published_at=getattr(result, "source_published_at", None),
        source_updated_at=getattr(result, "source_updated_at", None),
        captured_at=(
            result.captured_at
            if isinstance(result, EvidenceFetchResult) and result.captured_at
            else datetime.now(UTC)
        ),
        source_material_level=(
            "full_source" if isinstance(result, EvidenceFetchResult)
            and result.source_material_level == "full_source" and ok and not rejection_reason
            and (text.strip() or markdown.strip())
            and "summary" not in result.fetch_method.casefold()
            else "unknown"
        ),
        metadata=dict(getattr(result, "capture_metadata", {}) or {}),
    )
    page.metadata.pop("official_source_verification", None)
    if isinstance(result, EvidenceFetchResult) and result.cache_hit:
        page.metadata["source_cache_hit"] = True
    if dynamic_product:
        receipt = verify_registered_capture(candidate.competitor, page)
        page.metadata["official_source_verification"] = receipt
        if receipt["status"] != "verified":
            page.status = "rejected"
            page.failure_reason = receipt["reason"]
    return page


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
