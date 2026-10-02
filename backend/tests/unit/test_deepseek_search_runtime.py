import asyncio

import pytest
from test_deepseek_search import _settings, install_response, native_response

from packages.llm.errors import LLMExecutionLimitError
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.research.discovery.providers import search_result_candidates
from packages.research.models import ResearchBrief
from packages.research.pipeline import _discover_candidates
from packages.schema.api_dto import RunCreateRequest
from packages.search import SearchFilters, SearchResult, WebSearchError
from packages.skills.registry import SkillRegistry


async def make_service(**overrides):
    service = RunService(
        SkillRegistry.from_default_path(),
        _settings(enterprise_store_backend="memory", **overrides),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="非 AI 产品规格调研",
            competitors=["Nintendo Switch 2"],
            dimensions=["feature"],
            research_depth="quick",
            execution_mode="demo",
        )
    )
    return service, service._runs[detail.id]


async def search(service, record, *, query="规格", filters=None):
    return await service._trace_search(
        record, agent="planner", subagent=None, query=query, max_results=3, filters=filters
    )


async def test_runtime_routes_to_deepseek_without_perplexity_key(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service()
    results = await search(service, record)
    assert len(requests) == 1
    assert results[0].provider == "deepseek"


async def test_native_search_actual_usage_and_cost_are_in_run_budget_and_trace(monkeypatch):
    install_response(monkeypatch, native_response())
    service, record = await make_service()
    await search(service, record)
    budget = service._run_llm_budget(record)
    assert budget.calls == 1
    assert budget.tokens_used == 160
    assert budget.tokens_reserved == 0
    assert budget.cost_used_usd == pytest.approx(budget.cost(130, 30, 20))
    span = record.detail.trace_spans[-1]
    assert span.kind == "search" and span.provider == "deepseek"
    assert span.input_tokens_estimate == 130
    assert span.output_tokens_estimate == 30
    assert span.metadata["native_search_requests"] == 1
    assert span.metadata["token_usage_source"] == "provider"
    assert span.metadata["prompt_tokens"] == 130
    assert span.metadata["completion_tokens"] == 30
    assert span.metadata["prompt_cache_hit_tokens"] == 20
    assert span.cost_estimate_usd == pytest.approx(budget.cost_used_usd, abs=1e-8)


@pytest.mark.parametrize(
    "overrides", [{"run_llm_max_tokens": 100}, {"run_llm_max_cost_usd": 0.00001}]
)
async def test_native_search_budget_exhaustion_blocks_transport(monkeypatch, overrides):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service(**overrides)
    with pytest.raises(LLMExecutionLimitError):
        await search(service, record)
    assert requests == []
    span = record.detail.trace_spans[-1]
    assert span.status == "error"
    assert span.metadata["llm_request_attempts"] == 0
    assert span.cost_estimate_usd == 0
    assert span.input_tokens_estimate == span.output_tokens_estimate == 0


async def test_successful_search_reused_in_same_run_without_extra_cost(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service()
    first = await search(service, record)
    second = await search(service, record)
    assert first == second
    assert len(requests) == 1
    assert service._run_llm_budget(record).calls == 1
    span = record.detail.trace_spans[-1]
    assert span.metadata["search_cache_hit"] is True
    assert span.cost_estimate_usd == 0
    assert span.input_tokens_estimate == span.output_tokens_estimate == 0


async def test_concurrent_duplicate_search_uses_one_paid_request(monkeypatch):
    import httpx

    async def delayed(_request):
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=native_response())

    requests = install_response(monkeypatch, {}, handler=delayed)
    service, record = await make_service()
    results = await asyncio.gather(search(service, record), search(service, record))
    assert results[0] == results[1]
    assert len(requests) == 1
    assert service._run_llm_budget(record).calls == 1


async def test_filters_do_not_share_cache_entries(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service()
    await search(service, record)
    filtered = await search(
        service, record, filters=SearchFilters(search_domain_filter=["example.com"])
    )
    assert len(filtered) == 1
    assert len(requests) == 2


async def test_evidence_refresh_always_performs_fresh_search(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service()
    await search(service, record)
    record.detail.evidence_refresh_active = True
    await search(service, record)
    assert len(requests) == 2
    assert service._run_llm_budget(record).calls == 2


async def test_cache_expires_after_five_minutes(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service()
    await search(service, record)
    for key, (_when, results) in record.search_cache.items():
        record.search_cache[key] = (0, results)
    await search(service, record)
    assert len(requests) == 2


async def test_failed_search_does_not_cache_and_retains_unknown_cost(monkeypatch):
    requests = install_response(monkeypatch, {"error": "failed"}, status=503)
    service, record = await make_service()
    for _ in range(2):
        with pytest.raises(WebSearchError):
            await search(service, record)
    assert len(requests) == 2
    assert service._run_llm_budget(record).calls == 2
    assert service._run_llm_budget(record).tokens_used > 32000
    assert record.search_cache == {}
    assert record.detail.trace_spans[-1].input_tokens_estimate > 16000


async def test_cancelled_search_settles_and_leaves_error_trace(monkeypatch):
    started = asyncio.Event()

    async def waiting(_request):
        started.set()
        await asyncio.Event().wait()

    install_response(monkeypatch, {}, handler=waiting)
    service, record = await make_service()
    task = asyncio.create_task(search(service, record))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    budget = service._run_llm_budget(record)
    assert budget.calls == 1 and budget.tokens_reserved == 0
    assert budget.tokens_used > 16000
    assert record.detail.trace_spans[-1].status == "error"
    assert record.search_cache == {}


async def test_search_budget_survives_record_reconstruction(monkeypatch):
    install_response(monkeypatch, native_response())
    service, record = await make_service()
    await search(service, record)
    record.llm_budget = None
    record.detail.llm_budget_checkpoint = {}  # Legacy journals without a checkpoint.
    budget = service._run_llm_budget(record)
    assert budget.calls == 1 and budget.tokens_used == 160


async def test_same_query_in_another_run_is_not_reused(monkeypatch):
    requests = install_response(monkeypatch, native_response())
    service, record = await make_service()
    await search(service, record)
    detail = await service.create_run(
        RunCreateRequest(
            topic="第二个调研任务",
            competitors=["Steam Deck"],
            dimensions=["feature"],
        )
    )
    await search(service, service._runs[detail.id])
    assert len(requests) == 2


async def test_search_provider_provenance_reaches_pipeline_candidates():
    brief = ResearchBrief(
        run_id="test",
        topic="主机规格",
        competitor="Nintendo Switch 2",
        dimension="feature",
        include_trusted_sources=False,
        include_homepage_candidates=False,
        max_search_queries=1,
    )

    async def native_search(_query, _max_results):
        return [
            SearchResult(
                title="Nintendo Switch 2",
                url="https://nintendo.com/specs",
                snippet="",
                provider="deepseek",
            )
        ]

    candidates = await _discover_candidates(
        brief, search=native_search, seed_candidates=[], repair_tasks=[]
    )
    assert candidates[0].origin == "deepseek"
    assert candidates[0].metadata["search_provider"] == "deepseek"


def test_unmarked_legacy_search_results_keep_explicit_origin():
    brief = ResearchBrief(run_id="test", topic="产品", competitor="产品", dimension="feature")
    candidates = search_result_candidates(
        brief, [SearchResult("产品", "https://example.com", "")], origin="perplexity"
    )
    assert candidates[0].origin == "perplexity"


def test_deepseek_low_confidence_candidates_obey_existing_capture_policy():
    from packages.research.capture.policy import fallback_candidate_reason
    from packages.research.models import SourceCandidate

    candidate = SourceCandidate(
        title="无关资料", url="https://example.com", origin="deepseek", confidence=0.48
    )
    assert fallback_candidate_reason(candidate) == "deferred_low_confidence_search_result"


async def test_refresh_replaces_old_cache_after_refresh_flag_is_cleared(monkeypatch):
    import httpx

    count = 0

    async def versioned(_request):
        nonlocal count
        count += 1
        response = native_response()
        response["content"][1]["content"][0]["title"] = f"version-{count}"
        return httpx.Response(200, json=response)

    requests = install_response(monkeypatch, {}, handler=versioned)
    service, record = await make_service()
    assert (await search(service, record))[0].title == "version-1"
    record.detail.evidence_refresh_active = True
    assert (await search(service, record))[0].title == "version-2"
    record.detail.evidence_refresh_active = False
    assert (await search(service, record))[0].title == "version-2"
    assert len(requests) == 2


async def test_enterprise_gap_fill_uses_selected_deepseek_search(monkeypatch):
    from types import SimpleNamespace

    from app.routers import enterprise
    from packages.auth import EnterpriseUserContext

    calls = install_response(monkeypatch, native_response())
    project = SimpleNamespace(workspace_id="workspace")
    store = SimpleNamespace(list_report_versions=lambda **_kwargs: [])
    monkeypatch.setattr(enterprise, "_project_or_404", lambda *_args: project)

    async def gaps(*_args):
        return object()

    monkeypatch.setattr(enterprise, "get_project_evidence_gaps", gaps)

    async def fill(*_args, **kwargs):
        return await kwargs["search"]("补充产品规格", 3)

    monkeypatch.setattr(enterprise, "fill_evidence_gaps_online", fill)
    monkeypatch.setattr(
        enterprise, "capture_gap_fill_source_snapshots", lambda result, **_kwargs: result
    )
    monkeypatch.setattr(
        enterprise, "_with_gap_fill_release_gate_delta", lambda result, **_kwargs: result
    )
    results = await enterprise.fill_project_evidence_gaps(
        "project",
        store,
        EnterpriseUserContext(user_id="test", workspace_id="workspace", role="analyst"),
        _settings(),
        None,
    )
    assert len(calls) == 1 and results[0].provider == "deepseek"


async def test_generic_product_review_does_not_add_coding_feature_taxonomy():
    from packages.schema.models import RawSource, TargetProduct

    service, record = await make_service()
    record.detail.plan.target_product = TargetProduct(
        name="Nintendo Switch 2", category="便携游戏设备"
    )
    record.detail.raw_sources = [
        RawSource(
            id="console-specs",
            competitor="Nintendo Switch 2",
            dimension="feature",
            source_type="webpage_verified",
            title="Nintendo Switch 2 review",
            snippet="Nintendo Switch 2 review: a 1080p screen and 256 GB storage.",
            content_hash="hash",
            confidence=0.9,
        )
    ]
    service._merge_structured_knowledge_payload(
        record.detail,
        "Nintendo Switch 2",
        "feature",
        {
            "feature_tree": {
                "nodes": [
                    {
                        "name": "显示",
                        "description": "1080p 屏幕",
                        "claims": [
                            {
                                "claim": "1080p screen",
                                "source_ids": ["console-specs"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
                "summary_claims": [],
            },
        },
    )
    nodes = record.detail.competitor_knowledge["Nintendo Switch 2"].feature_tree.nodes
    assert [node.name for node in nodes] == ["显示"]


async def test_generic_product_fallback_keeps_claims_without_coding_features():
    service, record = await make_service()
    payload = service._deterministic_structured_knowledge_payload(
        competitor="Nintendo Switch 2",
        dimension="feature",
        dimension_sources=[
            {
                "id": "console-specs",
                "title": "Nintendo Switch 2 review",
                "confidence": 0.9,
                "snippet": "Nintendo Switch 2 review: 1080p display",
                "source_type": "webpage_verified",
                "metadata": {
                    "normalized_fields": [
                        {
                            "kind": "feature",
                            "slot": "capability_1",
                            "evidence_quote": "Nintendo Switch 2 review: 1080p display",
                        }
                    ]
                },
            }
        ],
    )
    nodes = payload["feature_tree"]["nodes"]
    assert all(node["name"] != "Code review and security" for node in nodes)
    assert nodes[0]["claims"][0]["source_ids"] == ["console-specs"]


async def test_analyst_fallback_accepts_null_normalized_fields_from_legacy_source():
    service, _record = await make_service()
    payload = service._deterministic_structured_knowledge_payload(
        competitor="Nintendo Switch 2",
        dimension="feature",
        dimension_sources=[
            {
                "id": "console-specs",
                "title": "Nintendo Switch 2 specifications",
                "confidence": 0.9,
                "snippet": "Nintendo Switch 2 has a 1080p display.",
                "source_type": "webpage_verified",
                "metadata": {"normalized_fields": None},
            }
        ],
    )
    assert payload["feature_tree"]["summary_claims"][0]["source_ids"] == ["console-specs"]


@pytest.mark.parametrize(
    "identity_status,expected_first", [("verified", "user-url"), ("unverified", "search-url")]
)
def test_verified_user_product_page_survives_search_candidate_limit(
    identity_status, expected_first
):
    from packages.research.discovery.ranking import rank_and_dedupe_candidates
    from packages.research.models import SourceCandidate

    user_page = SourceCandidate(
        id="user-url",
        title="Nintendo Switch 2 specifications",
        url="https://nintendo.com/specs",
        origin="web_search",
        confidence=0.55,
        metadata={
            "user_supplied_url": True,
            "identity_status": identity_status,
            "authority": "unverified",
        },
    )
    searched = SourceCandidate(
        id="search-url",
        title="Nintendo Switch 2 review",
        url="https://review.example.com/switch",
        origin="deepseek",
        confidence=0.72,
    )
    candidates = rank_and_dedupe_candidates(
        [searched, user_page], competitor="Nintendo Switch 2", dimension="feature"
    )[:1]
    assert candidates[0].id == expected_first
    assert user_page.origin == "web_search" and user_page.metadata["authority"] == "unverified"
