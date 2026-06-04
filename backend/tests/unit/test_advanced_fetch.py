import asyncio
import json

import pytest

from packages.config import Settings
from packages.governance import build_tool_registry_report
from packages.tools import advanced_fetch_page


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_advanced_fetch_page_parses_webfetch_v2_payload(monkeypatch, tmp_path) -> None:
    payload = {
        "url": "https://example.com/pricing",
        "final_url": "https://example.com/pricing",
        "ok": True,
        "fetch_method": "playwright",
        "status_code": 200,
        "content_type": "text/html",
        "title": "Example pricing",
        "text": "Pricing plan details",
        "markdown": "# Example pricing",
        "quality": {
            "score": 0.91,
            "text_length": 20,
            "has_title": True,
            "has_captcha": False,
            "looks_like_login": False,
            "looks_like_block": False,
            "js_required": True,
            "content_too_short": False,
        },
        "diagnostics": {"failure_reason": None, "error": None},
    }
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def fake_subprocess(*args: object, **kwargs: object) -> _FakeProcess:
        calls.append((args, kwargs))
        return _FakeProcess(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    result = await advanced_fetch_page(
        "https://example.com/pricing",
        mode="browser",
        timeout_seconds=9,
        artifact_dir=str(tmp_path / "artifacts"),
        screenshot=True,
        webfetch_root=tmp_path,
    )

    assert result.ok is True
    assert result.fetch_method == "playwright"
    assert result.title == "Example pricing"
    assert result.quality.score == 0.91
    assert result.quality.js_required is True
    assert result.snippet == "Pricing plan details"
    assert calls
    assert "--screenshot" in calls[0][0]
    assert calls[0][1]["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_advanced_fetch_page_surfaces_invalid_json(monkeypatch, tmp_path) -> None:
    async def fake_subprocess(*args: object, **kwargs: object) -> _FakeProcess:  # noqa: ARG001
        return _FakeProcess(b"not-json", b"broken")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    result = await advanced_fetch_page("https://example.com", webfetch_root=tmp_path)

    assert result.ok is False
    assert result.failure_reason == "advanced_fetch_invalid_json"
    assert "broken" in (result.error or "")


def test_tool_registry_lists_advanced_fetch_as_guarded_when_unconfigured(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("WEBFETCH_V2_ROOT", str(tmp_path / "missing-webfetch-v2"))
    report = build_tool_registry_report(
        Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            compliance_require_trace_context=True,
        )
    )

    entry = next(item for item in report.entries if item.name == "advanced_fetch_page")
    assert entry.status == "guarded"
    assert entry.allowed_in_real_mode is False
    assert "WEBFETCH_V2_ROOT" in entry.reason
