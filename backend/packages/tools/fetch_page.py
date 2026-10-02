from __future__ import annotations

import asyncio
import hashlib
import html
import re
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urljoin

import httpx
from lxml.etree import ParserError
from lxml.html import HTMLParser, document_fromstring, tostring
from pypdf import PdfReader
from trafilatura import extract as trafilatura_extract
from trafilatura.settings import use_config

from packages.crawler.policy import SSRFError, SSRFGuard

_MAX_REDIRECTS = 8
_DEFAULT_MAX_BYTES = 2_000_000
# Keep short specification tables out of trafilatura's unstructured baseline rescue.
_HTML_TEXT_CONFIG = use_config()
_HTML_TEXT_CONFIG.set("DEFAULT", "MIN_EXTRACTED_SIZE", "0")


@dataclass(frozen=True)
class FetchPageResult:
    url: str
    ok: bool
    title: str
    text: str
    content_hash: str
    status_code: int | None = None
    error: str | None = None
    content_type: str = ""

    @property
    def snippet(self) -> str:
        return self.text[:700]


async def fetch_page(
    url: str,
    timeout_seconds: float = 12.0,
    *,
    guard: SSRFGuard | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchPageResult:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; CompetiscopeBot/0.1; +https://example.local/competiscope)"
        )
    }
    ssrf_guard = guard or SSRFGuard()
    try:
        response = None
        current_url = url
        expected_addresses = await ssrf_guard.validate_url(current_url)
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers=headers,
            transport=transport,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url)
                if not response.is_redirect:
                    await ssrf_guard.validate_rebinding(str(response.url), expected_addresses)
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(str(response.url), location)
                expected_addresses = await ssrf_guard.validate_url(current_url)
            else:
                raise httpx.TooManyRedirects("Exceeded maximum redirects")
        if response is None:
            raise httpx.HTTPError("No response returned")
        response.raise_for_status()
    except (Exception, SSRFError) as exc:  # noqa: BLE001 - fetch failure is data, not a pipeline failure.
        return FetchPageResult(
            url=url,
            ok=False,
            title="",
            text="",
            content_hash=_hash_text(f"{url}:{exc}"),
            status_code=getattr(getattr(exc, "response", None), "status_code", None),
            error=str(exc),
        )

    body = response.content[: max(0, max_bytes)].decode(
        response.encoding or "utf-8", errors="replace",
    )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold().strip()
    if content_type == "application/pdf":
        try:
            text = await asyncio.to_thread(_extract_pdf_text, response.content[:max(0, max_bytes)])
        except Exception as exc:
            return FetchPageResult(
                url=str(response.url), ok=False, title="", text="",
                content_hash=_hash_text(str(response.url)), status_code=response.status_code,
                error=f"PDF extraction failed: {exc}", content_type=content_type,
            )
        return FetchPageResult(
            url=str(response.url), ok=bool(text), title=str(response.url.path.rsplit("/", 1)[-1]),
            text=text, content_hash=_hash_text(text or str(response.url)),
            status_code=response.status_code,
            error=None if text else "PDF has no extractable text; OCR is required",
            content_type=content_type,
        )
    if content_type.startswith(("image/", "audio/", "video/")) or content_type == "application/octet-stream":
        return FetchPageResult(
            url=str(response.url), ok=False, title="", text="",
            content_hash=_hash_text(str(response.url)), status_code=response.status_code,
            error=f"Unsupported content type: {content_type}", content_type=content_type,
        )
    title = _extract_title(body)
    text = await asyncio.to_thread(_html_to_text, body)
    return FetchPageResult(
        url=str(response.url),
        ok=bool(text),
        title=title,
        text=text,
        content_hash=_hash_text(text or body),
        status_code=response.status_code,
        content_type=content_type,
    )


def _extract_pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload), strict=False)
    if reader.is_encrypted:
        return ""
    return "\n\n".join(
        (page.extract_text() or "").strip()
        for page in reader.pages[:20]
    ).strip()[:100_000]


def _extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _collapse_space(html.unescape(match.group(1)))


def _html_to_text(body: str) -> str:
    try:
        parser = HTMLParser(encoding="utf-8", huge_tree=True)
        tree = document_fromstring(body.encode("utf-8"), parser=parser)
    except (ParserError, ValueError):
        tree = None
    if tree is not None:
        for node in tree.xpath("//nav | //footer"):
            node.drop_tree()
        body = tostring(tree, encoding="unicode")
    text = trafilatura_extract(
        tree if tree is not None else body,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        config=_HTML_TEXT_CONFIG,
    )
    if text and text.strip():
        return text.strip()
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", body)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return _collapse_space(cleaned)


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
