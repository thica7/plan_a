import asyncio
import json

import httpx
import pytest

from packages.config import Settings
from packages.crawler.policy import SSRFGuard
from packages.governance import build_tool_registry_report
from packages.tools import (
    AdvancedFetchQuality,
    AdvancedFetchResult,
    FetchPageResult,
    advanced_fetch_page,
    fetch_evidence_page,
    fetch_page,
)
from packages.tools.webfetch_runtime import DEFAULT_WEBFETCH_V2_ROOT, resolve_webfetch_v2_root
from packages.research.capture.webfetch_adapter import fetch_candidate_page
from packages.research.evidence.admission import raw_source_from_capture
from packages.research.models import ResearchBrief, SourceCandidate


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


class _HangingProcess:
    def __init__(self) -> None:
        self.finished = asyncio.Event()
        self.killed = False
        self.returncode = None

    async def communicate(self) -> tuple[bytes, bytes]:
        await self.finished.wait()
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.finished.set()

    async def wait(self) -> int:
        await self.finished.wait()
        return self.returncode or 0


@pytest.mark.asyncio
async def test_advanced_fetch_has_total_timeout_and_cleans_up_subprocess(monkeypatch, tmp_path):
    process = _HangingProcess()

    async def fake_subprocess(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    result = await asyncio.wait_for(
        advanced_fetch_page("https://example.com", timeout_seconds=0.02, webfetch_root=tmp_path),
        timeout=0.5,
    )
    assert result.ok is False
    assert result.failure_reason == "advanced_fetch_timeout"
    assert process.killed is True


@pytest.mark.asyncio
async def test_advanced_fetch_cancellation_kills_subprocess(monkeypatch, tmp_path):
    process = _HangingProcess()

    async def fake_subprocess(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    task = asyncio.create_task(advanced_fetch_page("https://example.com", webfetch_root=tmp_path))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed is True


def _resolver_for(*addresses: str):
    def resolver(host: str, port: int, *args, **kwargs):
        return [(2, 1, 6, "", (address, port)) for address in addresses]

    return resolver


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
async def test_browser_diagnostics_can_reach_a_cited_source(monkeypatch, tmp_path) -> None:
    url = "https://example.com/dynamic-product"
    payload = {
        "url": url, "final_url": url, "ok": True, "fetch_method": "browser",
        "title": "Dynamic product", "text": "This product provides a rechargeable battery.",
        "markdown": "", "quality": {"score": .9, "text_length": 47},
        "diagnostics": {"warnings": ["rendered_after_navigation"]},
        "artifacts": {"rendered_html_path": "/tmp/example-rendered.html"},
        "network": [{"url": "https://example.com/api/product", "status": 200}],
    }
    calls = []

    async def fake_subprocess(*args, **_kwargs):
        calls.extend(args)
        return _FakeProcess(json.dumps(payload).encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    advanced = await advanced_fetch_page(
        url, capture_network=True, webfetch_root=tmp_path,
    )
    assert "--capture-network" in calls

    async def return_advanced(_url, **_kwargs):
        return advanced

    async def basic(_url, **_kwargs):
        return FetchPageResult(url=url, ok=True, title="Loading", text="Loading...", content_hash="short")

    monkeypatch.setattr("packages.tools.evidence_fetch.fetch_page", basic)
    monkeypatch.setattr("packages.tools.evidence_fetch.advanced_fetch_page", return_advanced)
    result = await fetch_evidence_page(url)
    candidate = SourceCandidate(title="Product", url=url, origin="web_search")
    page = await fetch_candidate_page(candidate, lambda _url: asyncio.sleep(0, result=result))
    source = raw_source_from_capture(
        ResearchBrief(run_id="run", topic="product", competitor="Product", dimension="feature"),
        candidate, page, confidence=.7,
    )
    assert source.metadata["webfetch_artifacts"]["rendered_html_path"] == "/tmp/example-rendered.html"
    assert source.metadata["webfetch_network"][0]["url"] == "https://example.com/api/product"


def test_default_webfetch_v2_root_is_vendored_with_plan_a() -> None:
    assert DEFAULT_WEBFETCH_V2_ROOT.name == "webfetch_v2"
    assert DEFAULT_WEBFETCH_V2_ROOT.parent.name == "third_party"
    assert (DEFAULT_WEBFETCH_V2_ROOT / "webfetch_v2" / "__main__.py").exists()


def test_blank_webfetch_v2_root_uses_vendored_default(monkeypatch) -> None:
    monkeypatch.setenv("WEBFETCH_V2_ROOT", "")
    assert resolve_webfetch_v2_root() == DEFAULT_WEBFETCH_V2_ROOT


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
    assert "webfetch_v2" in entry.reason


@pytest.mark.asyncio
async def test_fetch_page_blocks_private_destinations_before_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise AssertionError("blocked destinations must not be requested")

    result = await fetch_page(
        "http://internal.example",
        guard=SSRFGuard(resolver=_resolver_for("127.0.0.1")),
        transport=httpx.MockTransport(handler),
    )

    assert result.ok is False
    assert result.status_code is None
    assert "Blocked non-public address" in (result.error or "")


@pytest.mark.asyncio
async def test_fetch_page_blocks_redirect_to_private_destination() -> None:
    def resolver(host: str, port: int, *args, **kwargs):
        address = "93.184.216.34" if host == "example.com" else "127.0.0.1"
        return [(2, 1, 6, "", (address, port))]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        raise AssertionError("private redirect target must not be requested")

    result = await fetch_page(
        "https://example.com/start",
        guard=SSRFGuard(resolver=resolver),
        transport=httpx.MockTransport(handler),
    )

    assert result.ok is False
    assert "Blocked non-public address" in (result.error or "")


@pytest.mark.asyncio
async def test_fetch_evidence_page_falls_back_to_webfetch_v2_for_weak_basic_fetch(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def fake_basic_fetch(url: str, timeout_seconds: float = 12.0) -> FetchPageResult:
        calls.append(f"basic:{timeout_seconds}")
        return FetchPageResult(
            url=url,
            ok=True,
            title="Loading",
            text="Loading...",
            content_hash="basic-low-quality",
            status_code=200,
        )

    async def fake_advanced_fetch(
        url: str,
        *,
        mode: str = "auto",
        timeout_seconds: float = 15.0,
        quality_threshold: float = 0.55,
        **_: object,
    ) -> AdvancedFetchResult:
        calls.append(f"advanced:{mode}:{timeout_seconds}:{quality_threshold}")
        return AdvancedFetchResult(
            url=url,
            final_url=url,
            ok=True,
            fetch_method="playwright",
            title="Example pricing",
            text="Example pricing starts at $10 per seat for enterprise teams.",
            markdown="",
            status_code=200,
            quality=AdvancedFetchQuality(score=0.92, text_length=60, has_title=True),
        )

    monkeypatch.setattr("packages.tools.evidence_fetch.fetch_page", fake_basic_fetch)
    monkeypatch.setattr("packages.tools.evidence_fetch.advanced_fetch_page", fake_advanced_fetch)

    result = await fetch_evidence_page("https://example.com/pricing")

    assert result.ok is True
    assert result.fetch_method == "webfetch_v2:playwright"
    assert result.quality_score == 0.92
    assert result.text.startswith("Example pricing")
    assert calls == ["basic:12.0", "advanced:auto:15.0:0.55"]


@pytest.mark.asyncio
async def test_fetch_evidence_page_does_not_fallback_after_policy_block(monkeypatch) -> None:
    async def fake_basic_fetch(url: str, timeout_seconds: float = 12.0) -> FetchPageResult:
        return FetchPageResult(
            url=url,
            ok=False,
            title="",
            text="",
            content_hash="blocked",
            error="Blocked non-public address: 127.0.0.1",
        )

    async def fail_advanced_fetch(*args: object, **kwargs: object) -> AdvancedFetchResult:
        raise AssertionError("policy blocked URLs must not reach advanced fetch")

    monkeypatch.setattr("packages.tools.evidence_fetch.fetch_page", fake_basic_fetch)
    monkeypatch.setattr("packages.tools.evidence_fetch.advanced_fetch_page", fail_advanced_fetch)

    result = await fetch_evidence_page("http://internal.example")

    assert result.ok is False
    assert result.fetch_method == "basic_httpx_policy_blocked"
    assert result.failure_reason == "policy_blocked"


@pytest.mark.asyncio
async def test_fetch_evidence_page_preserves_structured_failure_reason(monkeypatch) -> None:
    async def fake_basic_fetch(url: str, timeout_seconds: float = 12.0) -> FetchPageResult:
        return FetchPageResult(
            url=url,
            ok=False,
            title="",
            text="",
            content_hash="basic-failed",
            status_code=403,
            error="403 Forbidden",
        )

    async def fake_advanced_fetch(*_args, **_kwargs):
        raise AssertionError("Access-denied pages must not open the browser fallback")

    monkeypatch.setattr("packages.tools.evidence_fetch.fetch_page", fake_basic_fetch)
    monkeypatch.setattr("packages.tools.evidence_fetch.advanced_fetch_page", fake_advanced_fetch)

    result = await fetch_evidence_page("https://example.com/private")

    assert result.ok is False
    assert result.status_code == 403
    assert result.fetch_method == "basic_httpx_access_blocked"
    assert result.failure_reason == "access_denied"
