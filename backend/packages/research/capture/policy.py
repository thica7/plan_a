from __future__ import annotations

import re
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


def capture_rejection_reason(
    *,
    ok: bool,
    title: str,
    text: str,
    markdown: str = "",
) -> str:
    if not ok:
        return ""
    content = (text or markdown).strip()
    normalized = f"{title}\n{content}".casefold()
    if _looks_like_binary_or_pdf(content):
        return "captured_binary_or_unreadable_text"
    if _looks_like_soft_404(normalized, title):
        return "captured_soft_404"
    if len(content) < 40 and not _has_concrete_text_signal(normalized):
        return "captured_text_too_short"
    if _looks_like_navigation_only(normalized) and not _has_concrete_text_signal(normalized):
        return "captured_navigation_only"
    return ""


def _looks_like_binary_or_pdf(text: str) -> bool:
    if not text:
        return False
    if "%pdf" in text[:80].casefold() or " endobj" in text.casefold():
        return True
    replacement_ratio = text.count("\ufffd") / max(1, len(text))
    control_ratio = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t") / max(
        1, len(text)
    )
    return replacement_ratio > 0.02 or control_ratio > 0.01


def _looks_like_soft_404(normalized: str, title: str) -> bool:
    if title.casefold().strip() in {"404", "not found", "404: this page could not be found"}:
        return True
    markers = (
        "page not found",
        "404 not found",
        "this page could not be found",
        "this page does not exist",
        "this page doesn't exist",
        "we couldn't find that page",
        "we could not find that page",
    )
    return any(marker in normalized for marker in markers) or bool(
        re.search(r"(?:^|\s)404(?:\s|:|-)", normalized) and "not found" in normalized
    )


def _looks_like_navigation_only(normalized: str) -> bool:
    nav_markers = (
        "skip to main content",
        "open menu",
        "toggle theme",
        "sign in",
        "sign up",
        "log in",
        "cookie",
        "search docs",
        "navigation",
    )
    return sum(1 for marker in nav_markers if marker in normalized) >= 4


def _has_concrete_text_signal(normalized: str) -> bool:
    return bool(
        re.search(
            r"(?:\$\d+|\d+\s*(?:k|m|%|tokens?|users?|seats?)|supports|provides|"
            r"includes|offers|built for|used by|api|pricing|enterprise|feature|"
            r"customer|developer|model)",
            normalized,
        )
    )
