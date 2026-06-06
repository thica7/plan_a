from __future__ import annotations

from urllib.parse import urlparse

from packages.research.models import SourceCandidate


def invalid_candidate_reason(candidate: SourceCandidate) -> str:
    parsed = urlparse(candidate.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid_url"
    host = (parsed.hostname or "").casefold()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local_url_not_allowed"
    return ""


def fallback_candidate_reason(candidate: SourceCandidate) -> str:
    if candidate.origin == "homepage_derived" and candidate.confidence < 0.6:
        return "deferred_low_confidence_homepage_derived"
    if candidate.origin in {"perplexity", "web_search"} and candidate.confidence < 0.5:
        return "deferred_low_confidence_search_result"
    return ""


def capture_failure_reason(result: object | None) -> str:
    if result is None:
        return "fetch_returned_none"
    failure_reason = str(getattr(result, "failure_reason", "") or "").strip()
    if failure_reason:
        return failure_reason
    error = str(getattr(result, "error", "") or "").strip()
    if error:
        return error
    status_code = getattr(result, "status_code", None)
    if status_code:
        return f"http_{status_code}"
    return "fetch_failed"
