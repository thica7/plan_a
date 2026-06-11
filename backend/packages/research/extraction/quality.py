from __future__ import annotations

import re

_MAX_QUOTE_CHARS = 420

_NAVIGATION_MARKERS = (
    "skip to content",
    "skip to main content",
    "navigation menu",
    "toggle navigation",
    "open menu",
    "search docs",
    "search clear",
    "sign in",
    "sign up",
    "log in",
    "create account",
    "cookie",
    "privacy policy",
    "terms of use",
    "back to blog",
    "on this page",
    "copy code",
    "view all",
)

_ENCODING_MARKERS = ("\ufffd", "Ã", "Â", "â€", "â€™", "â€œ", "â€\u009d")

_DIMENSION_SIGNALS: dict[str, tuple[str, ...]] = {
    "pricing": (
        "$",
        "usd",
        "pricing",
        "price",
        "plan",
        "billing",
        "per user",
        "per seat",
        "per month",
        "per year",
        "token",
        "mtok",
        "enterprise",
        "contact sales",
        "定价",
        "价格",
        "计费",
        "按月",
        "按年",
        "席位",
        "预算",
        "企业",
    ),
    "persona": (
        "customer",
        "customers",
        "developer",
        "developers",
        "team",
        "teams",
        "enterprise",
        "use case",
        "workflow",
        "productivity",
        "organization",
        "用户",
        "客户",
        "开发者",
        "团队",
        "企业",
        "使用场景",
        "工作流",
        "组织",
    ),
    "feature": (
        "feature",
        "model",
        "api",
        "agent",
        "workflow",
        "coding",
        "codebase",
        "repository",
        "context",
        "security",
        "admin",
        "sso",
        "sdk",
        "功能",
        "模型",
        "代理",
        "工作流",
        "编码",
        "代码",
        "代码库",
        "上下文",
        "安全",
        "管理",
    ),
}


def quote_window_from_match(
    text: str,
    *,
    match_start: int,
    match_end: int,
    dimension: str,
    before: int = 140,
    after: int = 280,
) -> str:
    """Return a cleaned evidence quote around a matched business term."""
    if not text:
        return ""
    start = max(0, match_start - before)
    end = min(len(text), match_end + after)
    start = _expand_to_word_start(text, start)
    end = _expand_to_word_end(text, end)
    quote = clean_evidence_quote(text[start:end], dimension=dimension)
    return "" if quote_quality_problem(quote, dimension=dimension) else quote


def clean_evidence_quote(
    text: str,
    *,
    dimension: str,
    max_chars: int = _MAX_QUOTE_CHARS,
) -> str:
    normalized = _normalize_whitespace(text)
    normalized = _trim_leading_boilerplate(normalized)
    if len(normalized) <= max_chars:
        return normalized

    sentence = _best_signal_sentence(normalized, dimension=dimension, max_chars=max_chars)
    if sentence:
        return sentence
    return _clip_at_word_boundary(normalized, max_chars)


def quote_quality_problem(text: str, *, dimension: str = "") -> str | None:
    quote = _normalize_whitespace(text)
    if len(quote) < 32:
        return "quote_too_short"
    if noise_problem := text_noise_problem(quote):
        return noise_problem.replace("text_", "quote_", 1)
    normalized = quote.casefold()
    has_signal = _has_dimension_signal(dimension, normalized)
    if not has_signal:
        return "quote_missing_dimension_signal"
    return None


def text_noise_problem(text: str) -> str | None:
    quote = _normalize_whitespace(text)
    if not quote:
        return None
    if _encoding_noise_ratio(quote) > 0.015:
        return "text_encoding_noise"
    normalized = quote.casefold()
    marker_count = sum(1 for marker in _NAVIGATION_MARKERS if marker in normalized)
    if marker_count >= 4:
        return "text_navigation_boilerplate"
    if marker_count >= 2 and not _looks_like_business_sentence(normalized):
        return "text_navigation_boilerplate"
    if _looks_like_install_or_code_noise(normalized):
        return "text_code_or_install_noise"
    if _looks_like_truncated_fragment(quote):
        return "text_truncated_fragment"
    return None


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" -|\t\r\n")


def _expand_to_word_start(text: str, start: int) -> int:
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    return start


def _expand_to_word_end(text: str, end: int) -> int:
    while end < len(text) and text[end : end + 1].isalnum():
        end += 1
    return end


def _trim_leading_boilerplate(text: str) -> str:
    normalized = text
    lowered = normalized.casefold()
    for marker in _NAVIGATION_MARKERS:
        idx = lowered.find(marker)
        if idx != 0:
            continue
        tail = re.sub(r"^[\s\-|:]+", "", normalized[idx + len(marker) :])
        if len(tail) >= 40:
            normalized = tail
            lowered = normalized.casefold()
    return normalized


def _best_signal_sentence(text: str, *, dimension: str, max_chars: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    candidates = [
        _clip_at_word_boundary(part, max_chars)
        for part in parts
        if len(part.strip()) >= 40 and _has_dimension_signal(dimension, part.casefold())
    ]
    return candidates[0] if candidates else ""


def _clip_at_word_boundary(text: str, max_chars: int) -> str:
    clipped = text[:max_chars].rstrip()
    boundary = max(clipped.rfind("."), clipped.rfind(";"), clipped.rfind(","))
    if boundary >= 80:
        return clipped[: boundary + 1].strip()
    space = clipped.rfind(" ")
    if space >= 80:
        return clipped[:space].strip()
    return clipped.strip()


def _encoding_noise_ratio(text: str) -> float:
    marker_hits = sum(text.count(marker) for marker in _ENCODING_MARKERS)
    control_hits = sum(
        1 for char in text if ord(char) < 32 and char not in "\n\r\t"
    )
    return (marker_hits + control_hits) / max(1, len(text))


def _looks_like_install_or_code_noise(normalized_text: str) -> bool:
    markers = ("curl ", "install.cmd", "npm install", "pip install", "copy code")
    return sum(1 for marker in markers if marker in normalized_text) >= 2


def _looks_like_business_sentence(normalized_text: str) -> bool:
    return any(
        signal in normalized_text
        for signals in _DIMENSION_SIGNALS.values()
        for signal in signals
    )


def _looks_like_truncated_fragment(text: str) -> bool:
    match = re.search(r"\w+", text, flags=re.UNICODE)
    if not match:
        return True
    first_word = match.group(0)
    if not first_word.isascii():
        return False
    suspicious_prefixes = {
        "mpletions",
        "ull",
        "ctions",
        "oser",
        "ownload",
        "ublished",
    }
    return first_word.casefold() in suspicious_prefixes


def _has_dimension_signal(dimension: str, normalized_text: str) -> bool:
    key = dimension.casefold()
    if "pricing" in key:
        signals = _DIMENSION_SIGNALS["pricing"]
    elif "persona" in key or "user" in key or "buyer" in key:
        signals = _DIMENSION_SIGNALS["persona"]
    else:
        signals = _DIMENSION_SIGNALS["feature"]
    if any(signal in normalized_text for signal in signals):
        return True
    if "pricing" in key:
        return bool(
            re.search(
                r"(?:\$|usd|eur|cny|rmb|\d+\s*(?:/|per)\s*(?:token|seat|month|year|user))",
                normalized_text,
            )
        )
    return False
