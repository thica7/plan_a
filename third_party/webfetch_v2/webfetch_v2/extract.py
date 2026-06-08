from __future__ import annotations

import html
import importlib.util
import re
from dataclasses import dataclass
from urllib.parse import urljoin

try:
    from bs4 import BeautifulSoup
except Exception:  # noqa: BLE001 - bs4 is optional for the no-install smoke path.
    BeautifulSoup = None  # type: ignore[assignment]

from webfetch_v2.models import ExtractionCandidate, ExtractionResult, Link, Quality

BLOCK_PATTERNS = [
    r"checking your browser",
    r"just a moment",
    r"access denied",
    r"temporarily blocked",
    r"unusual traffic",
    r"enable cookies",
    r"cloudflare",
    r"akamai",
]

CAPTCHA_PATTERNS = [
    r"captcha",
    r"hcaptcha",
    r"recaptcha",
    r"turnstile",
    r"verify you are human",
]

LOGIN_PATTERNS = [
    r"sign in",
    r"log in",
    r"login required",
    r"create an account",
    r"continue with google",
    r"continue with microsoft",
]

JS_REQUIRED_PATTERNS = [
    r"enable javascript",
    r"javascript is required",
    r"you need to enable javascript",
    r"this app works best with javascript",
]

COOKIE_BANNER_PATTERNS = [
    r"accept cookies",
    r"cookie settings",
    r"manage cookies",
    r"we use cookies",
    r"同意.*cookie",
    r"接受.*cookie",
]


@dataclass(frozen=True)
class ExtractedContent:
    text: str
    extraction: ExtractionResult


def extract_title(html_body: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_body, "html.parser")
        if soup.title and soup.title.string:
            return collapse_space(soup.title.string)
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return collapse_space(str(og_title["content"]))
    match = re.search(r"<title[^>]*>(.*?)</title>", html_body, flags=re.IGNORECASE | re.DOTALL)
    return collapse_space(match.group(1)) if match else ""


def extract_best_content(html_body: str, title: str, *, status_code: int | None = None) -> ExtractedContent:
    """Return the best available content extraction plus candidate diagnostics.

    Optional extractors are used only when their packages are installed. The baseline
    extractor remains BeautifulSoup/regex so default operation has no heavy dependency.
    """

    raw_candidates = _raw_extraction_candidates(html_body)
    if not raw_candidates:
        return ExtractedContent(text="", extraction=ExtractionResult(method="none"))

    scored: list[tuple[str, str, float, int, str | None]] = []
    for method, text, error in raw_candidates:
        text = collapse_space(text)
        quality = score_quality(title, text, status_code=status_code)
        score = _candidate_score(quality, method)
        scored.append((method, text, score, len(text), error))

    best = max(scored, key=lambda item: (item[2], item[3]))
    candidates = [
        ExtractionCandidate(
            method=method,
            score=round(score, 3),
            text_length=text_length,
            selected=method == best[0] and text_length == best[3],
            error=error,
        )
        for method, _text, score, text_length, error in scored
    ]
    return ExtractedContent(
        text=best[1],
        extraction=ExtractionResult(method=best[0], candidates=candidates),
    )


def html_to_text(html_body: str) -> str:
    return _baseline_body_text(html_body)


def html_to_markdown(title: str, text: str) -> str:
    if not text:
        return ""
    if title:
        return f"# {title}\n\n{text}\n"
    return f"{text}\n"


def extract_links(html_body: str, base_url: str, limit: int = 100) -> list[Link]:
    links: list[Link] = []
    seen: set[str] = set()
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_body, "html.parser")
        anchors = (
            (str(a.get("href", "")).strip(), collapse_space(a.get_text(" ")))
            for a in soup.find_all("a", href=True)
        )
    else:
        anchors = (
            (m.group(1), "")
            for m in re.finditer(r"(?is)<a\s+[^>]*href=['\"]([^'\"]+)['\"]", html_body)
        )
    for href, text in anchors:
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        links.append(Link(url=url, text=text[:200]))
        if len(links) >= limit:
            break
    return links


def score_quality(title: str, text: str, *, status_code: int | None = None) -> Quality:
    lowered = text.lower()
    has_captcha = any(re.search(pattern, lowered) for pattern in CAPTCHA_PATTERNS)
    looks_like_block = any(re.search(pattern, lowered) for pattern in BLOCK_PATTERNS)
    looks_like_login = any(re.search(pattern, lowered) for pattern in LOGIN_PATTERNS)
    js_required = any(re.search(pattern, lowered) for pattern in JS_REQUIRED_PATTERNS)
    cookie_banner_detected = any(re.search(pattern, lowered) for pattern in COOKIE_BANNER_PATTERNS)
    text_length = len(text)
    content_too_short = text_length < 300

    score = 0.0
    if status_code is not None and 200 <= status_code < 300:
        score += 0.2
    if title:
        score += 0.15
    if text_length >= 300:
        score += 0.25
    if text_length >= 1200:
        score += 0.25
    if not any([has_captcha, looks_like_block, js_required]):
        score += 0.15
    if looks_like_login:
        score -= 0.15
    if has_captcha or looks_like_block:
        score -= 0.35
    if js_required:
        score -= 0.2

    score = max(0.0, min(1.0, round(score, 3)))
    return Quality(
        score=score,
        text_length=text_length,
        has_title=bool(title),
        has_captcha=has_captcha,
        looks_like_login=looks_like_login,
        looks_like_block=looks_like_block,
        js_required=js_required,
        content_too_short=content_too_short,
        cookie_banner_detected=cookie_banner_detected,
    )


def failure_reason_from_quality(quality: Quality) -> str | None:
    if quality.has_captcha:
        return "captcha_or_human_verification"
    if quality.looks_like_block:
        return "bot_challenge_or_access_block"
    if quality.looks_like_login:
        return "login_required_or_authorized_session_needed"
    if quality.js_required:
        return "javascript_required"
    if quality.content_too_short:
        return "content_too_short"
    return None


def collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _raw_extraction_candidates(html_body: str) -> list[tuple[str, str, str | None]]:
    candidates: list[tuple[str, str, str | None]] = []
    candidates.extend(_optional_trafilatura_candidate(html_body))
    candidates.extend(_optional_readability_candidate(html_body))

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_body, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "template"]):
            tag.decompose()
        article = soup.find("article")
        if article:
            candidates.append(("article_text", article.get_text(" "), None))
        main = soup.find("main")
        if main:
            candidates.append(("main_text", main.get_text(" "), None))
        body = soup.body or soup
        candidates.append(("body_text", body.get_text(" "), None))
    else:
        candidates.append(("regex_body_text", _baseline_body_text(html_body), None))
    return _dedupe_candidates(candidates)


def _optional_trafilatura_candidate(html_body: str) -> list[tuple[str, str, str | None]]:
    if importlib.util.find_spec("trafilatura") is None:
        return []
    try:
        import trafilatura

        extracted = trafilatura.extract(html_body, include_comments=False, include_tables=True)
        return [("trafilatura", extracted or "", None)] if extracted else []
    except Exception as exc:  # noqa: BLE001 - optional extractor failures are diagnostics.
        return [("trafilatura", "", str(exc))]


def _optional_readability_candidate(html_body: str) -> list[tuple[str, str, str | None]]:
    if importlib.util.find_spec("readability") is None:
        return []
    try:
        from readability import Document

        summary_html = Document(html_body).summary()
        return [("readability", _baseline_body_text(summary_html), None)]
    except Exception as exc:  # noqa: BLE001 - optional extractor failures are diagnostics.
        return [("readability", "", str(exc))]


def _baseline_body_text(html_body: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_body, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "template"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.body or soup
        return collapse_space(main.get_text(" "))
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", html_body)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    return collapse_space(cleaned)


def _dedupe_candidates(candidates: list[tuple[str, str, str | None]]) -> list[tuple[str, str, str | None]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str, str | None]] = []
    for method, text, error in candidates:
        key = collapse_space(text)[:500]
        if not key and not error:
            continue
        if key in seen and not error:
            continue
        seen.add(key)
        deduped.append((method, text, error))
    return deduped


def _candidate_score(quality: Quality, method: str) -> float:
    bonus = {
        "trafilatura": 0.08,
        "readability": 0.06,
        "article_text": 0.05,
        "main_text": 0.03,
        "body_text": 0.0,
        "regex_body_text": -0.03,
    }.get(method, 0.0)
    return max(0.0, min(1.0, quality.score + bonus))