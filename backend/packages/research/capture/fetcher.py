from __future__ import annotations

from collections.abc import Awaitable, Callable

from packages.research.models import CapturedPage, SourceCandidate
from packages.tools.evidence_fetch import EvidenceFetchResult

FetchCallable = Callable[[str], Awaitable[EvidenceFetchResult]]


async def capture_candidate(
    candidate: SourceCandidate,
    fetch: FetchCallable,
) -> CapturedPage:
    result = await fetch(candidate.url)
    status = "ok" if result.ok else "failed"
    text = result.text or ""
    return CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=result.url or candidate.url,
        status=status,
        title=result.title,
        text=text,
        markdown=text,
        snippet=result.snippet,
        content_hash=result.content_hash,
        status_code=result.status_code,
        error=result.error,
        fetch_method=result.fetch_method,
        quality_score=result.quality_score,
        text_length=result.text_length or len(text),
        failure_reason=result.failure_reason,
    )
