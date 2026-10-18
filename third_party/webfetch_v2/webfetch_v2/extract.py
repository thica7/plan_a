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

EXTRACTOR_BONUS = {
    "trafilatura": 0.08,
    "readability": 0.06,
    "article_text": 0.05,
    "main_text": 0.03,
    "body_text": 0.0,
    "regex_body_text": -0.03,
}


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

    source_bytes = html_body.encode('utf-8')
    source_html = source_bytes[:2_000_000].decode('utf-8', errors='ignore')
    source_truncated = len(source_bytes) > 2_000_000
    raw_candidates = _raw_extraction_candidates(html_body)
    if not raw_candidates:
        return ExtractedContent(text="", extraction=ExtractionResult(method="none", source_html=source_html,
                                                                     source_html_truncated=source_truncated))

    scored: list[tuple[str, str, float, int, str | None]] = []
    for method, text, error in raw_candidates:
        text = '\n'.join(collapse_space(line) for line in text.splitlines() if line.strip())
        text = _restore_headings(html_body, text)
        quality = score_quality(title, text, status_code=status_code)
        score = _candidate_score(quality, method)
        scored.append((method, text, score, len(text), error))

    best = max(scored, key=lambda item: (item[2], EXTRACTOR_BONUS.get(item[0], 0.0), item[3]))
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
        extraction=ExtractionResult(method=best[0], candidates=candidates, headings=extract_headings(html_body),
                                    source_html=source_html, source_html_truncated=source_truncated),
    )


def _restore_headings(html_body: str, text: str) -> str:
    """Keep original section scope when a clean extractor omits headings."""
    if not text or BeautifulSoup is None:
        return text
    soup = BeautifulSoup(html_body, 'html.parser')
    for tag in soup(['nav', 'footer', 'script', 'style', 'noscript', 'svg', 'template']):
        tag.decompose()
    for tag in soup.select('[hidden], [aria-hidden="true"]'):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.I)):
        tag.decompose()
    source_text = collapse_space(soup.get_text(' '))
    nodes = soup.find_all(re.compile(r'^(?:h[1-6]|p|li|blockquote|table)$'))
    insertions: dict[int, list[str]] = {}
    for index, node in enumerate(nodes):
        if not re.fullmatch(r'h[1-6]', node.name):
            continue
        heading = collapse_space(node.get_text(' '))
        if not heading or re.search(r'(?m)^\s*' + re.escape(heading) + r'\s*$', text):
            continue
        for block in nodes[index + 1:index + 13]:
            if re.fullmatch(r'h[1-6]', block.name):
                break
            anchor = collapse_space(block.get_text(' '))
            if len(anchor) < 16:
                continue
            matches = list(re.finditer(r'\s+'.join(map(re.escape, anchor.split())), text))
            if not matches:
                continue
            if len(matches) == 1 and source_text.count(anchor) == 1:
                position = matches[0].start()
                insertions.setdefault(position, []).append(heading)
            # Repeated content cannot establish the original section position.
            break
    for position in sorted(insertions, reverse=True):
        prefix = '\n' if position and text[position - 1] != '\n' else ''
        text = text[:position] + prefix + '\n'.join(insertions[position]) + '\n' + text[position:]
    return text


def extract_headings(html_body: str) -> list[tuple[int, str]]:
    if BeautifulSoup is None:
        return [(int(match.group(1)), collapse_space(re.sub(r'(?s)<[^>]*>', ' ', match.group(2))))
                for match in re.finditer(r'(?is)<h([1-6])\b[^>]*>(.*?)</h\1\s*>', html_body)]
    soup = BeautifulSoup(html_body, 'html.parser')
    for tag in soup(['nav', 'footer', 'script', 'style']):
        tag.decompose()
    for tag in soup.select('[hidden], [aria-hidden="true"]'):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.I)):
        tag.decompose()
    return [(int(tag.name[1]), collapse_space(tag.get_text(' ')))
            for tag in soup.find_all(re.compile(r'^h[1-6]$')) if tag.get_text().strip()]


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
    # A public page's navigation commonly contains "Log in". Require an auth
    # page title, an opening auth form, or an explicit access requirement.
    looks_like_login = bool(
        re.search(r"^(?:sign[ -]?in|log[ -]?in|登录|登入)(?:\b|\s|$)", title.strip(), re.IGNORECASE)
        or re.search(
            r"^(?:continue with (?:google|microsoft)|请(?:先)?登录)",
            lowered.strip(),
        )
        or re.search(
            r"(?:please (?:sign|log) in|login required|(?:sign|log) in "
            r"(?:is required|to (?:continue|access|view))|请(?:先)?登录)",
            lowered[:600],
        )
        or (
            re.search(r"sign[ -]?in|log[ -]?in|登录|登入", lowered[:600])
            and re.search(r"\bpassword\b|密码", lowered[:600])
            and re.search(r"\b(?:email|username)\b|邮箱|用户名", lowered[:600])
        )
    )
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
            candidates.append(("article_text", article.get_text("\n"), None))
        main = soup.find("main")
        if main:
            candidates.append(("main_text", main.get_text("\n"), None))
        body = soup.body or soup
        candidates.append(("body_text", body.get_text("\n"), None))
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
    bonus = EXTRACTOR_BONUS.get(method, 0.0)
    return max(0.0, min(1.0, quality.score + bonus))
