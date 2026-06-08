from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.tools.webfetch_runtime import resolve_webfetch_v2_root


@dataclass(frozen=True)
class AdvancedFetchQuality:
    score: float = 0.0
    text_length: int = 0
    has_title: bool = False
    has_captcha: bool = False
    looks_like_login: bool = False
    looks_like_block: bool = False
    js_required: bool = False
    content_too_short: bool = False


@dataclass(frozen=True)
class AdvancedFetchResult:
    url: str
    final_url: str
    ok: bool
    fetch_method: str
    title: str
    text: str
    markdown: str
    status_code: int | None = None
    content_type: str = ""
    quality: AdvancedFetchQuality = field(default_factory=AdvancedFetchQuality)
    failure_reason: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def snippet(self) -> str:
        return self.text[:700]


async def advanced_fetch_page(
    url: str,
    *,
    mode: str = "auto",
    timeout_seconds: float = 15.0,
    quality_threshold: float = 0.55,
    profile: str | None = None,
    artifact_dir: str | None = None,
    screenshot: bool = False,
    webfetch_root: Path | None = None,
) -> AdvancedFetchResult:
    """Fetch a page through the vendored webfetch_v2 CLI.

    The subprocess boundary keeps Playwright/browser dependencies optional for plan_a.
    Use persistent profiles only with explicit user authorization.
    """

    root = resolve_webfetch_v2_root(webfetch_root)
    command = [
        sys.executable,
        "-m",
        "webfetch_v2",
        "fetch",
        url,
        "--mode",
        mode,
        "--timeout",
        str(timeout_seconds),
        "--quality-threshold",
        str(quality_threshold),
    ]
    if profile:
        command.extend(["--profile", profile])
    if artifact_dir:
        command.extend(["--artifact-dir", artifact_dir])
    if screenshot:
        command.append("--screenshot")

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
    except Exception as exc:  # noqa: BLE001 - tool failure is surfaced as fetch data.
        return AdvancedFetchResult(
            url=url,
            final_url=url,
            ok=False,
            fetch_method="failed",
            title="",
            text="",
            markdown="",
            failure_reason="advanced_fetch_subprocess_error",
            error=str(exc),
        )

    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    if not stdout_text:
        return AdvancedFetchResult(
            url=url,
            final_url=url,
            ok=False,
            fetch_method="failed",
            title="",
            text="",
            markdown="",
            failure_reason="advanced_fetch_empty_output",
            error=stderr_text or f"exit_code={process.returncode}",
        )

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return AdvancedFetchResult(
            url=url,
            final_url=url,
            ok=False,
            fetch_method="failed",
            title="",
            text="",
            markdown="",
            failure_reason="advanced_fetch_invalid_json",
            error=f"{exc}; stderr={stderr_text}",
        )

    quality_payload = payload.get("quality") or {}
    diagnostics = payload.get("diagnostics") or {}
    return AdvancedFetchResult(
        url=str(payload.get("url") or url),
        final_url=str(payload.get("final_url") or url),
        ok=bool(payload.get("ok")),
        fetch_method=str(payload.get("fetch_method") or "unknown"),
        status_code=payload.get("status_code"),
        content_type=str(payload.get("content_type") or ""),
        title=str(payload.get("title") or ""),
        text=str(payload.get("text") or ""),
        markdown=str(payload.get("markdown") or ""),
        quality=AdvancedFetchQuality(
            score=float(quality_payload.get("score") or 0.0),
            text_length=int(quality_payload.get("text_length") or 0),
            has_title=bool(quality_payload.get("has_title")),
            has_captcha=bool(quality_payload.get("has_captcha")),
            looks_like_login=bool(quality_payload.get("looks_like_login")),
            looks_like_block=bool(quality_payload.get("looks_like_block")),
            js_required=bool(quality_payload.get("js_required")),
            content_too_short=bool(quality_payload.get("content_too_short")),
        ),
        failure_reason=diagnostics.get("failure_reason"),
        error=diagnostics.get("error") or stderr_text or None,
        raw=payload,
    )
