import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_deepseek_search import install_response
from test_deepseek_search_runtime import make_service
from test_deepseek_web_api import web_settings
import test_question_semantic_focus as source_fixtures

import packages.tools.evidence_fetch as evidence_fetch
from packages.crawler.policy import SSRFGuard
from packages.research.capture import capture_candidate
from packages.research.capture.official import verify_registered_capture
from packages.research.evidence import admit_evidence_items
from packages.research.evidence.admission import raw_source_from_capture
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.extraction.semantic import semantic_extraction, semantic_page_allowed
from packages.research.models import ResearchResult
from packages.tools.fetch_page import FetchPageResult

source = source_fixtures.source

URL = "https://docs.example-suite.test/rules"
TITLE = "Example Suite rules"
QUOTE = "Members can edit shared pages on all plans."
BODY = ("# Example Suite rules\n\nGuide to shared collaboration documents and member permissions.\n\n"
        + QUOTE + "\n\n## Other settings\n\nShared documents support collaboration.\n")


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    async def resolve(self, hostname, port):
        return {"127.0.0.1"} if hostname in {"localhost", "127.0.0.1"} else {"8.8.8.8"}
    monkeypatch.setattr(SSRFGuard, "resolve", resolve)


async def fetch(**kwargs):
    from packages.tools.deepseek_fetch import deepseek_fetch_page
    return await deepseek_fetch_page(kwargs.pop("url", URL), settings=web_settings(), **kwargs)


async def test_fetch_returns_exact_markdown_with_bound_receipt_and_unknown_origin_status(monkeypatch):
    requests = install_response(monkeypatch, {"title": TITLE, "content": BODY})
    result = await fetch()
    assert result.ok and result.text == BODY
    assert result.status_code is None and result.url == URL
    assert result.source_updated_at is None and result.source_published_at is None
    assert result.source_material_level == "full_source"
    assert result.content_hash == hashlib.sha256(BODY.encode()).hexdigest()
    assert result.fetch_method == "deepseek_web_fetch"
    assert result.advanced_fetch_attempted is True
    assert result.captured_at.tzinfo is not None
    assert str(requests[0].url) == "https://api.deepseek.com/v1/tools/fetch"
    assert requests[0].headers["Authorization"] == "Bearer test-deepseek-key"
    assert json.loads(requests[0].content) == {"url": URL}
    metadata = result.capture_metadata
    assert metadata["origin_status"] == "unknown" and metadata["final_url_observed"] is False
    receipt = metadata["provider_retrieval_receipt"]
    assert receipt["provider"] == "deepseek"
    assert receipt["provider_api_status"] == 200
    assert receipt["requested_url"] == URL and receipt["title"] == TITLE
    assert receipt["content_sha256"] == result.content_hash
    assert receipt["captured_at"] == result.captured_at.isoformat()
    assert metadata["web_api_requests"] == metadata["web_api_successful_responses"] == 1
    assert metadata["web_api_billable_requests_estimate"] == 1
    assert metadata["llm_tokens_charged"] == 0
    assert metadata["document_headings"] == [(1, "Example Suite rules"), (2, "Other settings")]
    for anchor in metadata["document_heading_anchors"]:
        assert BODY[anchor["start"]:anchor["end"]] == anchor["title"]
        assert anchor["content_sha256"] == result.content_hash


@pytest.mark.parametrize("payload", [{}, [], {"title": None, "content": BODY},
    {"title": TITLE, "content": {}}, {"title": "", "content": BODY},
    {"title": TITLE, "content": ""}])
async def test_fetch_rejects_invalid_schema_and_empty_material(monkeypatch, payload):
    requests = install_response(monkeypatch, payload)
    result = await fetch()
    assert not result.ok and result.source_material_level == "unknown"
    assert result.failure_reason and len(requests) == 1
    assert "provider_retrieval_receipt" not in result.capture_metadata


@pytest.mark.parametrize("title,body", [("Sign in", "Please sign in to continue. " * 8),
    ("Human verification", "Complete the CAPTCHA to continue. " * 8),
    ("404 Not Found", "This page could not be found. " * 8),
    (TITLE, "%PDF-1.7\n endobj" * 30), (TITLE, "Loading...")])
async def test_fetch_cannot_promote_login_captcha_binary_or_weak_content(monkeypatch, title, body):
    install_response(monkeypatch, {"title": title, "content": body})
    result = await fetch()
    assert not result.ok and result.quality_score < .5
    assert result.source_material_level == "unknown"


@pytest.mark.parametrize("status", [301, 400, 401, 402, 403, 404, 429, 500, 503])
async def test_fetch_redacts_provider_errors_and_does_not_retry(monkeypatch, status):
    requests = install_response(monkeypatch, {"error": "test-deepseek-key secret"}, status=status)
    result = await fetch()
    assert not result.ok and result.status_code is None
    assert f"HTTP {status}" in result.error and "test-deepseek-key" not in result.error
    assert len(requests) == 1
    assert result.capture_metadata["web_api_requests"] == 1
    assert result.capture_metadata["web_api_billable_requests_estimate"] == 0


@pytest.mark.parametrize("failure", ["json", "timeout", "connect"])
async def test_fetch_transport_failures_are_redacted(monkeypatch, failure):
    async def fail(request):
        if failure == "json":
            return httpx.Response(200, text="bad json test-deepseek-key")
        error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        raise error("test-deepseek-key secret", request=request)
    requests = install_response(monkeypatch, {}, handler=fail)
    result = await fetch()
    assert not result.ok and "test-deepseek-key" not in result.error
    assert len(requests) == 1


@pytest.mark.parametrize("url", ["http://localhost/a", "http://127.0.0.1/a", "file:///etc/passwd",
    "https://user:secret@example.com/a", "https://example.com:bad/a"])
async def test_fetch_ssrf_and_credentials_are_rejected_before_provider_transport(monkeypatch, url):
    requests = install_response(monkeypatch, {"title": TITLE, "content": BODY})
    result = await fetch(url=url)
    assert not result.ok and requests == []
    assert result.advanced_fetch_attempted is False
    assert result.failure_reason == "policy_blocked"
    assert "secret" not in result.error


@pytest.mark.parametrize("mode", ["weak", "gap", "good", "budget", "denied", "login", "policy"])
async def test_evidence_upgrade_uses_one_existing_advanced_slot_without_browser(monkeypatch, mode):
    requests = install_response(monkeypatch, {"title": TITLE, "content": BODY})
    good = mode in {"good", "gap"}
    async def basic(url, **kwargs):
        return FetchPageResult(url=url, ok=mode not in {"denied", "policy"}, title="Sign in" if mode == "login" else TITLE,
            text="Please sign in to continue. " * 8 if mode == "login" else BODY if good else "Loading...",
            status_code=403 if mode == "denied" else 200,
            error="Blocked by robots.txt" if mode == "policy" else None,
            content_hash="basic", capture_metadata={"capture_incomplete": True, "capture_gaps": ["missing_disclosure"]} if mode == "gap" else {})
    async def browser(*args, **kwargs):
        raise AssertionError("Standalone Fetch owns this advanced attempt")
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", browser)
    result = await evidence_fetch.fetch_evidence_page(URL, deepseek_settings=web_settings(),
        allow_advanced=mode != "budget", public_document_browser_retry=True)
    attempted = mode in {"weak", "gap"}
    assert len(requests) == int(attempted)
    assert result.advanced_fetch_attempted is attempted
    if attempted:
        assert result.ok and result.fetch_method == "deepseek_web_fetch"
    if mode == "gap":
        assert result.capture_metadata["capture_incomplete"] is True


async def test_failed_provider_upgrade_preserves_basic_and_diagnostic_without_browser(monkeypatch):
    requests = install_response(monkeypatch, {"error": "secret"}, status=402)
    async def basic(url, **kwargs):
        return FetchPageResult(url=url, ok=True, title=TITLE, text=BODY, status_code=200,
            content_hash="basic-hash", capture_metadata={"capture_incomplete": True})
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    result = await evidence_fetch.fetch_evidence_page(URL, deepseek_settings=web_settings(), require_price_content=True)
    assert len(requests) == 1
    assert result.text == BODY and result.content_hash == "basic-hash" and result.status_code == 200
    assert result.advanced_fetch_attempted is True
    assert result.capture_metadata["capture_upgrade_failure_reason"]
    assert result.capture_metadata["price_content_found"] is False
    assert result.capture_metadata["web_api_requests"] == 1


async def test_trace_fetch_passes_settings_privately_and_accounts_advanced_budget(monkeypatch):
    from packages.agents import SubagentContext
    from packages.tools.robots import RobotsCheckResult
    import packages.orchestrator.service as service_module
    service, record = await make_service(deepseek_web_api_enabled=True)
    seen = []
    async def robots(*args, **kwargs):
        return RobotsCheckResult(url=URL, robots_url=URL + "/robots.txt", allowed=True, checked=True)
    async def capture(url, **kwargs):
        seen.append(kwargs)
        return evidence_fetch.EvidenceFetchResult(url=url, ok=False, title="", text="", content_hash="failure",
            advanced_fetch_attempted=kwargs.get("allow_advanced", True))
    monkeypatch.setattr(service, "_trace_robots", robots)
    monkeypatch.setattr(service_module, "fetch_evidence_page", capture)
    context = SubagentContext(run_id=record.detail.id, agent="collector", subagent="feature::Switch")
    await service._trace_fetch(record, "collector", context.subagent, URL, context)
    assert seen[0]["deepseek_settings"] is service._settings
    usage = record.detail.collector_research_usage[context.subagent]
    assert usage.advanced_fetch_attempts == 1
    assert "test-deepseek-key" not in record.detail.trace_spans[-1].model_dump_json()


async def test_real_fetch_capture_semantic_admission_sqlite_and_snapshot(source, monkeypatch, tmp_path):
    from packages.knowledge.repository import KnowledgeRepository
    from packages.orchestrator.service import RunRecord
    from packages.research.question_delivery import _build_question_delivery, _replay_question_delivery
    from test_collector_knowledge_scope import service_and_detail
    install_response(monkeypatch, {"title": TITLE, "content": BODY})
    brief, candidate, _ = source(BODY, questions=("Can members edit shared pages?",), path="rules")
    captured = await capture_candidate(candidate, lambda url: fetch(url=url))
    assert captured.status == "ok" and captured.status_code is None
    official = captured.metadata["official_source_verification"]
    assert official["status"] == "verified"
    assert "provider retrieval" in official["scope"] and "unobserved" in official["scope"]
    assert official["final_url"] is None
    assert semantic_page_allowed(brief, captured)
    extraction = semantic_extraction(brief, captured, {"facts": [{"quote": QUOTE}]})
    assert extraction.fields
    items = admit_evidence_items([extraction], brief=brief, captured_pages=[captured], candidates=[candidate])
    assert items and all(item.status == "accepted" for item in items)
    normalized = normalized_fields_from_evidence_items(items)
    raw = raw_source_from_capture(brief, candidate, captured, confidence=.8, snippet=QUOTE,
        metadata={"normalized_fields": [row.model_dump(mode="json") for row in normalized]})
    result = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[captured],
        extractions=[extraction], evidence_items=items, normalized_fields=normalized)
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "provider.sqlite"))
    monkeypatch.setenv("KB_SEMANTIC_INDEXING_ENABLED", "false")
    service, detail = service_and_detail()
    detail.id, detail.topic = brief.run_id, brief.topic
    detail.plan.topic = brief.topic
    detail.plan.competitors = [brief.competitor]
    detail.raw_sources = [raw]
    record = RunRecord(detail=detail)
    await service._persist_captured_sources_to_kb(record, detail, [raw], result)
    assert raw.metadata["kb_full_source_ingest_status"] == "stored"
    async with KnowledgeRepository() as repo:
        document = await repo.get_document(raw.metadata["kb_document_id"])
    assert document.text == BODY
    assert document.metadata["origin_status"] == "unknown"
    capsule = _build_question_delivery(detail, brief, result, [raw], [])
    replayed = _replay_question_delivery(detail, capsule, {document.id: document}, authorized_brief=brief)
    assert replayed["verified_item_ids"]
    forged_document = document.model_copy(deep=True)
    forged_document.metadata["provider_retrieval_receipt"]["provider"] = "other"
    rejected = _replay_question_delivery(detail, capsule, {document.id: forged_document}, authorized_brief=brief)
    assert not rejected["verified_item_ids"]
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")
    assert any(f.quote == QUOTE and f.status == "supported" for f in snapshot.facts if f.field == "evidence_terms")


@pytest.mark.parametrize("mutation", ["missing", "endpoint", "provider", "protocol", "method", "status", "url", "title", "hash", "time", "origin", "final", "summary", "material", "page_url", "page_hash", "page_title"])
async def test_provider_receipt_is_bound_and_replayed_not_a_boolean_flag(source, monkeypatch, mutation):
    install_response(monkeypatch, {"title": TITLE, "content": BODY})
    brief, candidate, _ = source(BODY, path="rules")
    page = await capture_candidate(candidate, lambda url: fetch(url=url))
    assert page.status == "ok"
    receipt = page.metadata["provider_retrieval_receipt"]
    if mutation == "missing":
        page.metadata.pop("provider_retrieval_receipt")
    elif mutation == "page_url":
        page.requested_url += "?forged=1"
    elif mutation == "page_hash":
        page.content_hash = "forged"
    elif mutation == "page_title":
        page.title = "Other product"
    elif mutation == "summary":
        page.fetch_method = "deepseek_web_fetch_summary"
    elif mutation == "material":
        page.source_material_level = "unknown"
    else:
        key, value = {
            "endpoint": ("endpoint", "https://evil.example/fetch"), "provider": ("provider", "other"),
            "protocol": ("protocol", "forged"), "method": ("method", "GET"),
            "status": ("provider_api_status", 403), "url": ("requested_url", URL + "/foreign"),
            "title": ("title", "Other product"), "hash": ("content_sha256", "wrong"),
            "time": ("captured_at", (datetime.now(UTC) - timedelta(days=1)).isoformat()),
            "origin": ("origin_status", 200), "final": ("final_url_observed", True),
        }[mutation]
        receipt[key] = value
    assert verify_registered_capture(brief.competitor, page)["status"] == "rejected"
    assert not semantic_page_allowed(brief, page)


async def test_provider_blocked_shell_cannot_be_treated_as_full_source(monkeypatch):
    install_response(monkeypatch, {"title": "Access Denied", "content": "You do not have permission to access this resource. " * 8})
    result = await fetch()
    assert not result.ok and result.source_material_level == "unknown"


async def test_markdown_heading_anchors_ignore_fences_and_bind_duplicate_occurrences(monkeypatch):
    body = ("````markdown\n# Hidden example\n```\n# Still hidden\n````\n"
            "# Rules\n" + BODY + "\n# Rules\n")
    install_response(monkeypatch, {"title": TITLE, "content": body})
    result = await fetch()
    assert result.ok
    anchors = result.capture_metadata["document_heading_anchors"]
    assert all("hidden" not in item["title"].casefold() for item in anchors)
    assert [a["occurrence"] for a in anchors if a["title"] == "Rules"] == [1, 2]
    assert all(body[a["start"]:a["end"]] == a["title"] for a in anchors)


@pytest.mark.parametrize("enabled,key", [(False, "search-key"), (True, None)])
async def test_disabled_or_missing_key_keeps_existing_browser_route(monkeypatch, enabled, key):
    from packages.tools.advanced_fetch import AdvancedFetchQuality, AdvancedFetchResult
    from test_deepseek_search import _settings
    requests = install_response(monkeypatch, {})
    called = []
    async def basic(url, **kwargs):
        return FetchPageResult(url=url, ok=True, title="Loading", text="Loading...", content_hash="basic")
    async def browser(url, **kwargs):
        called.append(url)
        return AdvancedFetchResult(url=url, final_url=url, ok=True, fetch_method="browser",
            title=TITLE, text=BODY, markdown=BODY, status_code=200, quality=AdvancedFetchQuality(score=.9))
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", browser)
    result = await evidence_fetch.fetch_evidence_page(URL, deepseek_settings=_settings(
        deepseek_web_api_enabled=enabled, ark_api_key=key))
    assert result.fetch_method == "webfetch_v2:browser" and called == [URL] and requests == []


async def test_provider_bypasses_redis_and_settings_never_enter_legacy_cache_options(monkeypatch):
    from types import SimpleNamespace
    import packages.infrastructure.redis_config as redis_config
    import packages.infrastructure.source_cache as source_cache
    seen = []
    async def cached(url, call, **kwargs):
        seen.append(kwargs["options"])
        return await call()
    async def basic(url, **kwargs):
        return FetchPageResult(url=url, ok=True, title=TITLE, text=BODY, content_hash="basic")
    monkeypatch.setattr(redis_config, "redis_options", lambda: SimpleNamespace(cache_enabled=True, cache_ttl_seconds=300))
    monkeypatch.setattr(redis_config, "get_redis_runtime", lambda: object())
    monkeypatch.setattr(source_cache, "cached_fetch", cached)
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    await evidence_fetch.fetch_evidence_page(URL, deepseek_settings=web_settings())
    assert seen == []
    await evidence_fetch.fetch_evidence_page(URL)
    assert len(seen) == 1
    assert "deepseek_web_api_enabled" not in seen[0]
    assert "test-deepseek-key" not in json.dumps(seen[0])
    assert "deepseek_settings" not in seen[0]


async def test_provider_fetch_trace_does_not_report_generation_tokens(monkeypatch):
    from packages.tools.robots import RobotsCheckResult
    install_response(monkeypatch, {"title": TITLE, "content": BODY})
    async def basic(url, **kwargs):
        return FetchPageResult(url=url, ok=True, title="Loading", text="Loading...", content_hash="basic")
    async def robots(*args, **kwargs):
        return RobotsCheckResult(url=URL, robots_url=URL + "/robots.txt", allowed=True, checked=True)
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    service, record = await make_service(deepseek_web_api_enabled=True)
    monkeypatch.setattr(service, "_trace_robots", robots)
    result = await service._trace_fetch(record, "planner", None, URL)
    assert result.ok and result.fetch_method == "deepseek_web_fetch"
    span = record.detail.trace_spans[-1]
    assert span.input_tokens_estimate == span.output_tokens_estimate == 0
    assert span.metadata["web_api_requests"] == 1
    assert service._run_llm_budget(record).tokens_used == 0


@pytest.mark.parametrize("title,body,min_chars", [
    ("HTTP 500 Internal Server Error",
     "# HTTP 500 Internal Server Error\n\nAn HTTP 500 response indicates an unexpected server failure. "
     "To diagnose the problem, inspect the application logs and correlate the request identifier. "
     "This guide explains how administrators can distinguish application errors from gateway errors.", 120),
    ("Service unavailable troubleshooting",
     "# Service unavailable troubleshooting\n\nThe HTTP 503 status means the server cannot handle a request. "
     "Clients can inspect the Retry-After header to choose a retry delay. Administrators should check "
     "upstream capacity and deployment health before changing the application configuration.", 120),
    (TITLE, "# Member permissions\n\nMembers can edit shared pages on all plans.", 40),
    (TITLE, "# Product limits\n\n| Plan | Members |\n| --- | --- |\n| Basic | 5 |\n| Team | 25 |", 40),
    (TITLE, "# Product rules\n\n[Home](/) | [Docs](/docs)\n\n" + BODY, 120),
])
async def test_provider_quality_keeps_explanatory_articles_and_real_product_material(
    monkeypatch, title, body, min_chars
):
    install_response(monkeypatch, {"title": title, "content": body})
    result = await fetch(min_text_chars=min_chars)
    assert result.ok and result.text == body
    assert result.source_material_level == "full_source"
    assert result.status_code is None
    assert result.capture_metadata["origin_status"] == "unknown"


@pytest.mark.parametrize("body,reason", [
    ("# 500 Internal Server Error\n\nThe server encountered an internal error and was unable to complete your request. Please try again later.\n\nAn error occurred while processing your request.", "provider_error_page"),
    ("# Service unavailable\n\nThis service is temporarily unavailable due to maintenance. Please try again in a few minutes. Thank you for your patience.", "provider_error_page"),
    ("\n".join(f"[Section {i}](https://example.com/docs/{i})" for i in range(10)), "navigation_only"),
])
async def test_provider_api_200_error_shells_never_acquire_receipts_or_source_qualification(
    source, monkeypatch, body, reason
):
    install_response(monkeypatch, {"title": TITLE, "content": body})
    result = await fetch()
    assert result.ok is False and result.failure_reason == reason
    assert result.source_material_level == "unknown" and result.quality_score < .5
    assert "provider_retrieval_receipt" not in result.capture_metadata
    assert result.status_code is None and result.capture_metadata["provider_api_status"] == 200
    assert result.capture_metadata["web_api_billable_requests_estimate"] == 1
    brief, candidate, _ = source(body, path="rules")
    captured = await capture_candidate(candidate, lambda url: fetch(url=url))
    assert captured.status != "ok"
    assert captured.metadata["official_source_verification"]["status"] == "rejected"
    assert not semantic_page_allowed(brief, captured)


async def test_known_empty_fetch_content_has_no_billable_request_estimate(monkeypatch):
    install_response(monkeypatch, {"title": TITLE, "content": ""})
    result = await fetch()
    assert not result.ok
    assert result.capture_metadata["web_api_successful_responses"] == 1
    assert result.capture_metadata["web_api_billable_requests_estimate"] == 0


@pytest.mark.parametrize("footer", [
    "Request ID: 9845d4b6bca4\n\nCopyright 2026 Miro. All rights reserved.",
    "Cloudflare Ray ID: 9845d4b6bca4\n\nPowered by Edge Service",
])
async def test_error_shell_footers_cannot_supply_document_body_or_official_qualification(
    monkeypatch, footer
):
    from test_official_registry import fixture
    from packages.research.models import ResearchBrief
    candidate, _ = fixture()
    body = ("# Service unavailable\n\nThis service is temporarily unavailable due to maintenance. "
            "Please try again in a few minutes. Thank you for your patience.\n\n" + footer)
    install_response(monkeypatch, {"title": "Miro Help Center", "content": body})
    result = await fetch(url=candidate.url)
    assert result.ok is False and result.failure_reason == "provider_error_page"
    assert "provider_retrieval_receipt" not in result.capture_metadata
    captured = await capture_candidate(candidate, lambda url: fetch(url=url))
    brief = ResearchBrief(run_id="footer-guard", competitor="Miro", dimension="feature",
        product_category="collaboration", topic="editing permissions")
    assert captured.status != "ok"
    assert captured.metadata["official_source_verification"]["status"] == "rejected"
    assert not semantic_page_allowed(brief, captured)


async def test_real_document_with_diagnostic_and_copyright_footer_keeps_original_body(monkeypatch):
    body = BODY + "\nRequest ID: 9845d4b6bca4\n\nCopyright 2026 Example Suite. All rights reserved."
    install_response(monkeypatch, {"title": TITLE, "content": body})
    result = await fetch()
    assert result.ok and result.text == body
    assert result.content_hash == hashlib.sha256(body.encode()).hexdigest()
    assert result.source_material_level == "full_source"


@pytest.mark.parametrize("provider_enabled", [True, False])
async def test_trace_fetch_redis_cache_keeps_current_attempt_accounting_and_legacy_reuse(
    monkeypatch, provider_enabled
):
    from test_source_cache import Cache
    from packages.infrastructure import redis_config
    from packages.tools.robots import RobotsCheckResult
    cache, basic_calls = Cache(), []
    requests = install_response(monkeypatch, {"error": "denied"}, status=402)
    monkeypatch.setattr(redis_config, "redis_options", lambda: redis_config.RedisOptions(cache_enabled=True))
    monkeypatch.setattr(redis_config, "get_redis_runtime", lambda: cache)
    async def basic(url, **kwargs):
        basic_calls.append(url)
        return FetchPageResult(url=url, ok=True, title=TITLE, text=BODY,
            content_hash=hashlib.sha256(BODY.encode()).hexdigest(), status_code=200,
            capture_metadata={"capture_incomplete": True, "capture_gaps": ["missing_disclosure"]}
                if provider_enabled else {})
    async def robots(*args, **kwargs):
        return RobotsCheckResult(url=URL, robots_url=URL + "/robots.txt", allowed=True, checked=True)
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    service, record = await make_service(deepseek_web_api_enabled=provider_enabled)
    monkeypatch.setattr(service, "_trace_robots", robots)
    first = await service._trace_fetch(record, "collector", "feature::Switch", URL)
    second = await service._trace_fetch(record, "collector", "feature::Switch", URL)
    assert first.ok and second.ok
    actual_api = len(requests)
    traced_api = sum(span.metadata.get("web_api_requests", 0) for span in record.detail.trace_spans)
    assert actual_api == traced_api == (2 if provider_enabled else 0)
    assert len(basic_calls) == (2 if provider_enabled else 1)
    assert second.cache_hit is (not provider_enabled)
    assert record.detail.collector_research_usage["feature::Switch"].advanced_fetch_attempts == (
        2 if provider_enabled else 0)
    if provider_enabled:
        assert cache.rows == {}
    else:
        assert cache.rows
        assert all("deepseek_web_api_enabled" not in key for key in cache.rows)
        assert first.captured_at == second.captured_at


@pytest.mark.parametrize("phase", ["basic", "policy", "client", "submitted", "total_timeout"])
async def test_cancelled_fetch_retains_actual_provider_attempt_without_consuming_generation(
    monkeypatch, phase
):
    from packages.tools.robots import RobotsCheckResult

    entered = asyncio.Event()
    original_cancellations, basic_calls = [], []

    async def wait_for_cancellation():
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError as exc:
            original_cancellations.append(exc)
            raise

    async def pending_provider(request):
        await wait_for_cancellation()

    real_client = httpx.AsyncClient
    requests = install_response(monkeypatch, {}, handler=pending_provider)

    async def basic(url, **kwargs):
        basic_calls.append(url)
        if phase == "basic":
            await wait_for_cancellation()
        return FetchPageResult(url=url, ok=True, title="Loading", text="Loading...", content_hash="basic")

    async def pending_policy(self, url):
        await wait_for_cancellation()

    async def pending_client(self):
        await wait_for_cancellation()

    async def browser(*args, **kwargs):
        raise AssertionError("Cancellation must propagate without a browser retry")

    async def robots(*args, **kwargs):
        return RobotsCheckResult(url=URL, robots_url=URL + "/robots.txt", allowed=True, checked=True)

    if phase == "policy":
        monkeypatch.setattr(SSRFGuard, "validate_url", pending_policy)
    elif phase == "client":
        monkeypatch.setattr(real_client, "__aenter__", pending_client)
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", browser)
    service, record = await make_service(deepseek_web_api_enabled=True)
    monkeypatch.setattr(service, "_trace_robots", robots)
    task = asyncio.create_task(service._trace_fetch(record, "collector", "feature::Switch", URL))
    await asyncio.wait_for(entered.wait(), timeout=1)
    if phase == "total_timeout":
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task, timeout=.01)
    else:
        task.cancel("caller cancellation remains private")
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
        assert cancelled.value is original_cancellations[0]
    submitted = phase in {"submitted", "total_timeout"}
    assert len(requests) == int(submitted)
    assert basic_calls == [URL]
    spans = [span for span in record.detail.trace_spans if span.kind == "fetch"]
    assert len(spans) == 1
    span = spans[0]
    assert span.status == "error" and span.metadata["ok"] is False
    assert span.metadata["failure_reason"] == "fetch_cancelled"
    assert span.metadata["web_api_requests"] == int(submitted)
    assert span.metadata["advanced_fetch_attempted"] is submitted
    assert span.metadata["web_api_successful_responses"] == 0
    assert span.metadata["web_api_billable_requests_estimate"] == 0
    assert span.metadata["web_api_billing_unknown_requests"] == int(submitted)
    assert span.metadata["web_api_billing_outcome"] == ("unknown" if submitted else "not_requested")
    assert span.metadata["provider_api_status"] is None
    assert record.detail.collector_research_usage["feature::Switch"].advanced_fetch_attempts == int(submitted)
    budget = service._run_llm_budget(record)
    assert budget.calls == budget.tokens_used == budget.tokens_reserved == budget.cost_used_usd == 0
    assert span.input_tokens_estimate == span.output_tokens_estimate == span.cost_estimate_usd == 0
    assert "test-deepseek-key" not in span.model_dump_json()
    assert "caller cancellation remains private" not in span.model_dump_json()


@pytest.mark.parametrize("status", [200, 402])
async def test_completed_provider_fetch_is_traced_once_with_existing_budget_semantics(monkeypatch, status):
    from packages.tools.robots import RobotsCheckResult

    requests = install_response(monkeypatch, {"title": TITLE, "content": BODY}, status=status)

    async def basic(url, **kwargs):
        return FetchPageResult(url=url, ok=True, title="Loading", text="Loading...", content_hash="basic")

    async def robots(*args, **kwargs):
        return RobotsCheckResult(url=URL, robots_url=URL + "/robots.txt", allowed=True, checked=True)

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    service, record = await make_service(deepseek_web_api_enabled=True)
    monkeypatch.setattr(service, "_trace_robots", robots)
    result = await service._trace_fetch(record, "collector", "feature::Switch", URL)
    spans = [span for span in record.detail.trace_spans if span.kind == "fetch"]
    assert len(spans) == len(requests) == 1
    assert result.ok is (status == 200)
    assert spans[0].metadata["web_api_requests"] == 1
    assert spans[0].metadata["web_api_successful_responses"] == int(status == 200)
    assert spans[0].metadata["web_api_billable_requests_estimate"] == int(status == 200)
    assert record.detail.collector_research_usage["feature::Switch"].advanced_fetch_attempts == 1
    assert service._run_llm_budget(record).calls == 0
