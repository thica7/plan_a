from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class FetchPageResult:
    url: str
    ok: bool
    title: str
    text: str
    content_hash: str
    status_code: int | None = None
    error: str | None = None

    @property
    def snippet(self) -> str:
        return self.text[:700]


async def fetch_page(url: str, timeout_seconds: float = 12.0) -> FetchPageResult:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; CompetiscopeBot/0.1; +https://example.local/competiscope)"
        )
    }
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - fetch failure is data, not a pipeline failure.
        return FetchPageResult(
            url=url,
            ok=False,
            title="",
            text="",
            content_hash=_hash_text(f"{url}:{exc}"),
            status_code=getattr(getattr(exc, "response", None), "status_code", None),
            error=str(exc),
        )

    body = response.text
    title = _extract_title(body)
    text = _html_to_text(body)
    return FetchPageResult(
        url=str(response.url),
        ok=bool(text),
        title=title,
        text=text,
        content_hash=_hash_text(text or body),
        status_code=response.status_code,
    )


def _extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _collapse_space(html.unescape(match.group(1)))


def _html_to_text(body: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", body)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return _collapse_space(cleaned)


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
