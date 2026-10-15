from datetime import datetime
from types import SimpleNamespace

import pytest

import packages.tools.evidence_fetch as evidence_fetch
from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan
from packages.skills.registry import SkillRegistry
from packages.tools.advanced_fetch import AdvancedFetchQuality, AdvancedFetchResult
from packages.tools.fetch_page import FetchPageResult


@pytest.mark.asyncio
async def test_price_request_tries_advanced_when_readable_html_has_no_amount(monkeypatch):
    url = "https://example.com/pricing"
    calls = []

    async def basic(_url, **kwargs):
        return FetchPageResult(
            url=url,
            ok=True,
            title="Plans & Pricing",
            text="Starter Free limited access. Includes unlimited drafts and templates. " * 3,
            content_hash="basic",
        )

    async def advanced(_url, **kwargs):
        calls.append(kwargs["mode"])
        return AdvancedFetchResult(
            url=url,
            final_url=url,
            ok=True,
            fetch_method="static",
            title="Plans & Pricing",
            text="Professional Full seat USD 16/mo billed annually. " * 4,
            markdown="",
            quality=AdvancedFetchQuality(score=0.9, text_length=200),
        )

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page(url, require_price_content=True)
    assert calls == ["browser"]
    assert result.advanced_fetch_attempted
    assert "USD 16" in result.text
    assert result.capture_metadata["price_content_found"] is True


@pytest.mark.asyncio
async def test_price_request_without_advanced_budget_keeps_policy_as_incomplete(monkeypatch):
    async def basic(url, **kwargs):
        return FetchPageResult(
            url=url,
            ok=True,
            title="Billing policy",
            text="Annual billing costs less. Your plan renews automatically. " * 4,
            content_hash="policy",
        )

    async def advanced(url, **kwargs):
        raise AssertionError("Budget exhausted")

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page(
        "https://example.com/billing",
        require_price_content=True,
        allow_advanced=False,
    )
    assert result.ok
    assert not result.advanced_fetch_attempted
    assert result.capture_metadata["price_content_found"] is False


@pytest.mark.asyncio
async def test_price_request_does_not_render_access_blocked_page(monkeypatch):
    async def basic(url, **kwargs):
        return FetchPageResult(
            url=url,
            ok=True,
            title="Sign in",
            text="Please sign in to continue. " * 6,
            content_hash="login",
        )

    async def advanced(url, **kwargs):
        raise AssertionError("Access restrictions must remain respected")

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page(
        "https://example.com/pricing",
        require_price_content=True,
    )
    assert not result.ok
    assert result.failure_reason == "login_page"


@pytest.mark.asyncio
@pytest.mark.parametrize('product,dimension,url,public_retry', [
    ('A', 'pricing', 'https://example.com/pricing', False),
    ('Coda', 'feature', 'https://help.superhuman.com/hc/en-us/articles/46210367411469-Comment-on-docs', True),
    ('Coda', 'feature', 'https://superhuman.com/plans/mail', False),
])
async def test_actual_collector_fetch_propagates_price_requirement(monkeypatch, product, dimension, url, public_retry):
    import packages.orchestrator.service as service_module

    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    now = datetime(2026, 10, 7)
    detail = RunDetail(
        id="fetch-price",
        topic="产品价格",
        status="running",
        execution_mode="demo",
        created_at=now,
        updated_at=now,
        plan=AnalysisPlan(topic="产品价格", competitors=[product], dimensions=[dimension]),
    )
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    captured = []

    async def robots(*args, **kwargs):
        return SimpleNamespace(allowed=True)

    async def fetch(url, **kwargs):
        captured.append(kwargs)
        return evidence_fetch.EvidenceFetchResult(
            url=url,
            ok=True,
            title="Pricing",
            text="USD 20 per month",
            content_hash="price",
        )

    monkeypatch.setattr(service, "_trace_robots", robots)
    monkeypatch.setattr(service_module, "fetch_evidence_page", fetch)
    await service._trace_fetch(record, "collector", dimension, url)
    assert bool(captured[0].get("require_price_content")) == (dimension == 'pricing')
    assert bool(captured[0].get("public_document_browser_retry")) == public_retry


@pytest.mark.asyncio
async def test_browser_failure_is_visible_without_exporting_raw_error(monkeypatch):
    async def basic(url, **kwargs):
        return FetchPageResult(
            url=url,
            ok=True,
            title="Billing policy",
            text="Annual billing costs less. " * 8,
            content_hash="policy",
        )

    async def advanced(url, **kwargs):
        return AdvancedFetchResult(
            url=url,
            final_url=url,
            ok=False,
            title="",
            text="",
            markdown="",
            fetch_method="browser",
            failure_reason="advanced_fetch_timeout",
            error="secret=private-value",
        )

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", advanced)
    result = await evidence_fetch.fetch_evidence_page(
        "https://example.com/pricing", require_price_content=True
    )
    assert result.ok
    assert result.capture_metadata["price_capture_failure_reason"] == "advanced_fetch_timeout"
    assert "private-value" not in str(result.capture_metadata)
