"""Retrieve Markdown through DeepSeek without claiming an observed origin response."""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from packages.config import Settings
from packages.crawler.policy import SSRFError, SSRFGuard
from packages.research.capture.policy import capture_rejection_reason
from packages.tools.evidence_fetch import EvidenceFetchResult, _basic_content_problem
from packages.tools.fetch_page import FetchPageResult

DEEPSEEK_FETCH_ENDPOINT = "https://api.deepseek.com/v1/tools/fetch"
DEEPSEEK_FETCH_PROTOCOL = "deepseek_web_fetch_v1"
DEEPSEEK_FETCH_METHOD = "deepseek_web_fetch"


async def deepseek_fetch_page(
    url: str, *, settings: Settings, timeout_seconds: float = 12.0,
    min_text_chars: int = 120, guard: SSRFGuard | None = None,
) -> EvidenceFetchResult:
    metadata = {
        "provider": "deepseek", "endpoint": DEEPSEEK_FETCH_ENDPOINT,
        "requested_url": url, "origin_status": "unknown", "final_url_observed": False,
        "provider_api_status": None, "web_api_requests": 0,
        "web_api_successful_responses": 0, "web_api_billable_requests_estimate": 0,
        "billing_basis": "provider_success_request_estimate_not_invoice",
        "llm_request_attempts": 0, "llm_tokens_charged": 0, "llm_cost_charged_usd": 0.0,
    }

    def failed(reason, error):
        return EvidenceFetchResult(
            url=url, ok=False, title="", text="", content_hash="",
            error=error, failure_reason=reason, fetch_method=DEEPSEEK_FETCH_METHOD,
            advanced_fetch_attempted=bool(metadata["web_api_requests"]),
            capture_metadata=dict(metadata),
        )

    if not settings.deepseek_web_api_enabled or not settings.resolved_deepseek_api_key:
        return failed("provider_disabled", "DeepSeek Fetch API 未启用")
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password:
            raise SSRFError("URL credentials are not allowed")
        await (guard or SSRFGuard()).validate_url(url)
    except (ValueError, OSError):
        return failed("policy_blocked", "DeepSeek Fetch 目标 URL 未通过安全检查")
    # Credentials only ever go to this fixed official endpoint; redirects are disabled.
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            metadata["web_api_requests"] = 1
            response = await client.post(
                DEEPSEEK_FETCH_ENDPOINT, json={"url": url},
                headers={"Authorization": f"Bearer {settings.resolved_deepseek_api_key}"},
            )
            metadata["provider_api_status"] = response.status_code
            if response.status_code == 200:
                metadata["web_api_successful_responses"] = 1
                metadata["web_api_billable_requests_estimate"] = 1
    except asyncio.CancelledError as exc:
        # Preserve only accounting on the original cancellation, never credentials or material.
        exc._deepseek_fetch_metadata = {
            key: value for key, value in metadata.items()
            if key.startswith(("web_api_", "llm_")) or key in {"billing_basis", "provider_api_status"}
        }
        raise
    except httpx.TimeoutException:
        return failed("provider_timeout", "DeepSeek Fetch API 超时")
    except httpx.HTTPError:
        return failed("provider_connection_failed", "DeepSeek Fetch API 连接失败")
    if response.status_code != 200:
        return failed("provider_http_error", f"DeepSeek Fetch API 失败（HTTP {response.status_code}）")
    try:
        data = response.json()
    except ValueError:
        return failed("provider_invalid_json", "DeepSeek Fetch API 返回无效 JSON")
    if (not isinstance(data, dict) or not isinstance(data.get("title"), str)
            or not isinstance(data.get("content"), str)):
        return failed("provider_invalid_schema", "DeepSeek Fetch API 返回无效 title/content 结构")
    title, body = data["title"], data["content"]
    if body == "":
        metadata["web_api_billable_requests_estimate"] = 0
    if not title.strip() or not body.strip():
        return failed("provider_empty_material", "DeepSeek Fetch API 未返回完整标题和正文")
    problem = _basic_content_problem(FetchPageResult(
        url=url, ok=True, title=title, text=body, content_hash="",
    )) or capture_rejection_reason(ok=True, title=title, text=body) or _provider_body_problem(body)
    if re.match(r"^(?:access denied|forbidden|403(?:\b|:)|permission denied)(?:\b|:)", title.strip(), re.I):
        problem = "access_denied"
    if problem or len(body.strip()) < min_text_chars:
        return failed(problem or "content_too_short", "DeepSeek Fetch 正文未通过内容质量检查")
    captured = datetime.now(UTC)
    digest = hashlib.sha256(body.encode()).hexdigest()
    anchors = _markdown_heading_anchors(body, digest)
    metadata.update(
        content_sha256=digest, captured_at=captured.isoformat(),
        document_headings=[(item["level"], item["title"]) for item in anchors],
        document_heading_anchors=anchors,
        provider_retrieval_receipt={
            "protocol": DEEPSEEK_FETCH_PROTOCOL, "provider": "deepseek",
            "endpoint": DEEPSEEK_FETCH_ENDPOINT, "method": "POST",
            "requested_url": url, "title": title, "content_sha256": digest,
            "captured_at": captured.isoformat(), "provider_api_status": 200,
            "web_api_requests": 1, "web_api_successful_responses": 1,
            "source_material_level": "full_source", "origin_status": "unknown",
            "final_url_observed": False,
        },
    )
    return EvidenceFetchResult(
        url=url, ok=True, title=title, text=body, content_hash=digest,
        status_code=None, fetch_method=DEEPSEEK_FETCH_METHOD, advanced_fetch_attempted=True,
        quality_score=.8, text_length=len(body), content_type="text/markdown",
        source_material_level="full_source", captured_at=captured, capture_metadata=metadata,
    )



def _provider_body_problem(body: str) -> str | None:
    # Link labels and headings alone do not provide the requested document body.
    without_links = re.sub(r"!?\[[^\]\n]*\]\([^\n]*?\)", "", body)
    footer = re.compile(
        r"\s*(?:(?:(?:[\w.-]+\s+)?ray|request)[ -]?id\s*:\s*[\w.:-]+"
        r"|(?:copyright(?:\s+©)?\s+|[©Ⓒ]\s*|\(c\)\s*)\d{4}\b.*"
        r"|all rights reserved\.?|powered\s+by\s+.{1,120})\s*", re.I,
    )
    prose = "\n".join(line for line in without_links.splitlines()
                      if not re.match(r"^\s{0,3}#{1,6}\s", line)
                      and not footer.fullmatch(line))
    if without_links != body and not re.search(r"\w", prose):
        return "navigation_only"
    # Inspect the body, not the title: technical error-reference articles remain valid.
    statements = [part.strip() for part in re.split(r"[.!?]+(?:\s+|$)|\n+", prose)
                  if re.search(r"\w", part)]
    notice = re.compile(
        r"(?:(?:the|this|our) (?:server|service|site|website)\b.*"
        r"(?:internal error|unavailable|under maintenance|unable to (?:complete|process)).*"
        r"|an error occurred while (?:processing|handling) (?:your|the) request"
        r"|please try again(?: later| in a few (?:minutes|moments))?"
        r"|thank you for your patience|we apologize for (?:the|any) inconvenience"
        r"|(?:http\s+)?5\d\d(?:[ :\-]+[a-z ]+)?"
        r"|internal server error|service unavailable|bad gateway|gateway timeout)", re.I,
    )
    if statements and all(notice.fullmatch(part) for part in statements):
        return "provider_error_page"
    return None


def _markdown_heading_anchors(body: str, digest: str) -> list[dict]:
    anchors, occurrences = [], {}
    fence = None
    offset = 0
    for line in body.splitlines(keepends=True):
        fenced = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fenced:
            marker = fenced.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif (marker[0] == fence[0] and len(marker) >= fence[1]
                  and not line[fenced.end():].strip()):
                fence = None
        elif fence is None:
            match = re.fullmatch(r"(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*\r?\n?", line)
            if match:
                title = match.group(2)
                occurrence = occurrences.get(title, 0) + 1
                occurrences[title] = occurrence
                anchors.append(dict(level=len(match.group(1)), title=title,
                    start=offset + match.start(2), end=offset + match.end(2),
                    occurrence=occurrence, content_sha256=digest))
        offset += len(line)
    return anchors
