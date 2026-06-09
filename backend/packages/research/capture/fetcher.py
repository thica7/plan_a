from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from packages.research.capture.webfetch_adapter import fetch_candidate_page
from packages.research.models import CapturedPage, SourceCandidate

FetchCallable = Callable[[str], Awaitable[Any]]


async def capture_candidate(
    candidate: SourceCandidate,
    fetch: FetchCallable,
) -> CapturedPage:
    return await fetch_candidate_page(candidate, fetch)
