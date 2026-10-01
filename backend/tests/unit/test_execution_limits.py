from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from packages.config import Settings, get_settings
from packages.llm import LLMError
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.schema.models import RawSource
from packages.skills.registry import SkillRegistry


async def _service(**limits):
    settings = Settings(
        demo_mode=False,
        ark_api_key="offline-test",
        ark_model="offline-test",
        ark_base_url="https://example.invalid",
        llm_timeout_seconds=1,
        llm_temperature=0.2,
        llm_retry_backoff_seconds=0,
    )
    for key, value in limits.items():
        object.__setattr__(settings, key, value)
    service = RunService(
        SkillRegistry.from_default_path(),
        settings,
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Bounded offline execution",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    return service, service._runs[detail.id]


async def _text_call(service, record, **kwargs):
    return await service._trace_llm_text(
        record,
        agent="writer",
        subagent=None,
        name="report_writer",
        system="test",
        user="test",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_llm_concurrency_and_queue_time_are_bounded() -> None:
    service, record = await _service(llm_max_concurrency=2)
    active = peak = 0

    async def complete_text(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return "Bounded result"

    service._llm.complete_text = complete_text
    await asyncio.gather(*(_text_call(service, record) for _ in range(6)))

    assert peak == 2
    spans = [span for span in record.detail.trace_spans if span.kind == "llm"]
    assert any(span.metadata["queue_wait_ms"] >= 10 for span in spans)
    assert sum(span.metadata["llm_request_attempts"] for span in spans) == 6


@pytest.mark.asyncio
async def test_run_call_budget_counts_transport_retries_and_rejects_later_calls() -> None:
    service, record = await _service(run_llm_max_calls=3)
    requests = 0

    async def post(url, payload, headers):
        nonlocal requests
        requests += 1
        return httpx.Response(429, text="Controlled retry")

    service._llm._post_chat_completion = post
    for _ in range(4):
        with pytest.raises(LLMError):
            await _text_call(service, record)

    assert requests == 3
    spans = [span for span in record.detail.trace_spans if span.kind == "llm"]
    assert sum(span.metadata["llm_request_attempts"] for span in spans) == 3
    assert spans[-1].metadata["degradation_reason"] == "run_llm_call_budget_exhausted"
    assert spans[-1].cost_estimate_usd == 0


@pytest.mark.asyncio
async def test_token_admission_prevents_transport_and_survives_recovery():
    service, record = await _service(run_llm_max_tokens=100, llm_max_output_tokens=10)
    async def forbidden(**kwargs):
        pytest.fail('An exhausted budget must not call the provider')
    service._llm.complete_text = forbidden
    with pytest.raises(LLMError, match='token_budget'):
        await _text_call(service, record)
    assert record.detail.trace_spans[-1].input_tokens_estimate == 0
    assert record.detail.trace_spans[-1].cost_estimate_usd == 0
    # Persisted charges, including unknown failed attempts, restore budget use.
    record.detail.trace_spans[-1].metadata['llm_tokens_charged'] = 99
    record.detail.trace_spans[-1].metadata['llm_cost_charged_usd'] = 0.0001
    record.llm_budget = None
    budget = service._run_llm_budget(record)
    assert budget.tokens_used == 99
    assert budget.cost_used_usd == 0.0001


@pytest.mark.asyncio
async def test_truncated_provider_output_is_charged_before_retry():
    service, record = await _service(llm_max_retries=1, llm_max_output_tokens=40,
                                    llm_provider_name='deepseek')
    responses = iter([
        httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': 'cut'}}],
                                 'usage': {'prompt_tokens': 10, 'completion_tokens': 40}}),
        httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                                 'usage': {'prompt_tokens': 10, 'completion_tokens': 2,
                                           'prompt_cache_hit_tokens': 5, 'prompt_cache_miss_tokens': 5}}),
    ])
    async def post(url, payload, headers):
        return next(responses)
    service._llm._post_chat_completion = post
    assert await _text_call(service, record) == 'ok'
    span = record.detail.trace_spans[-1]
    assert span.metadata['llm_tokens_charged'] == 62
    assert span.metadata['prompt_cache_hit_tokens'] == 5
    assert span.provider == 'deepseek'
    assert span.cost_estimate_usd == pytest.approx((15*0.3 + 5*0.006 + 42*1.2)/1e6)


@pytest.mark.asyncio
async def test_recovery_keeps_inflight_reservations_before_provider_returns():
    service, record = await _service(run_llm_max_tokens=9000)
    entered, release = asyncio.Event(), asyncio.Event()
    async def waiting(**kwargs):
        entered.set()
        await release.wait()
        return 'ok'
    service._llm.complete_text = waiting
    task = asyncio.create_task(_text_call(service, record))
    await entered.wait()
    expected = record.llm_budget.tokens_reserved
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert restored.calls == 1
    assert restored.tokens_used == expected
    release.set()
    await task


@pytest.mark.asyncio
async def test_timeout_provider_does_not_inherit_concurrent_backup_request():
    service, record = await _service(backup_llm_api_key='backup', backup_llm_model='backup-model',
                                    backup_llm_base_url='https://backup.invalid', llm_max_retries=0)
    entered = asyncio.Event()
    async def post(url, payload, headers):
        if payload['messages'][1]['content'] == 'first':
            entered.set()
            await asyncio.Event().wait()
        if 'backup.invalid' not in url:
            return httpx.Response(401, text='primary rejected')
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    service._llm._post_chat_completion = post
    first = asyncio.create_task(service._trace_llm_text(record, agent='writer', subagent=None,
        name='first', system='test', user='first', timeout_seconds=0.05))
    await entered.wait()
    await service._trace_llm_text(record, agent='writer', subagent=None,
        name='second', system='test', user='second')
    with pytest.raises(TimeoutError):
        await first
    span = next(s for s in record.detail.trace_spans if s.name == 'first')
    assert span.provider == 'doubao'
    assert span.model == 'offline-test'


@pytest.mark.asyncio
async def test_all_provider_failure_keeps_last_attempt_provenance():
    service, record = await _service(backup_llm_api_key='backup', backup_llm_model='backup-model',
                                    backup_llm_base_url='https://backup.invalid', llm_max_retries=0)
    async def post(url, payload, headers):
        return httpx.Response(401, text='provider rejected')
    service._llm._post_chat_completion = post
    with pytest.raises(LLMError):
        await _text_call(service, record)
    span = record.detail.trace_spans[-1]
    assert span.provider == 'backup'
    assert span.model == 'backup-model'


@pytest.mark.asyncio
async def test_run_repair_budget_is_shared_between_sections() -> None:
    service, record = await _service(run_llm_max_repairs=1)
    calls = 0

    async def complete_text(**kwargs):
        nonlocal calls
        calls += 1
        return "Repair"

    service._llm.complete_text = complete_text
    await _text_call(service, record, is_repair=True)
    with pytest.raises(LLMError, match="run_llm_repair_budget_exhausted"):
        await _text_call(service, record, is_repair=True)
    assert calls == 1


@pytest.mark.asyncio
async def test_writer_segment_concurrency_and_order_are_bounded() -> None:
    service, record = await _service(writer_segment_max_concurrency=2)
    active = peak = 0

    async def write_segment(_record, *, segment, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return segment["segment_name"], None

    service._writer_validated_segment_markdown = write_segment
    segments = [{"segment_name": str(index)} for index in range(7)]
    results = await service._writer_parallel_validated_segments(
        record,
        evidence_pack_result=None,
        segments=segments,
        timeout_seconds=1,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
    )
    assert peak == 2
    assert [result[1] for result in results] == [str(index) for index in range(7)]


@pytest.mark.asyncio
async def test_writer_segment_count_limit_fails_before_starting_work() -> None:
    service, record = await _service(writer_max_segments=2)

    async def unexpected_segment(*args, **kwargs):
        pytest.fail("Segments must be rejected before work starts")

    service._writer_validated_segment_markdown = unexpected_segment
    with pytest.raises(LLMError, match="writer_segment_limit_exceeded"):
        await service._writer_parallel_validated_segments(
            record,
            evidence_pack_result=None,
            segments=[{"segment_name": str(index)} for index in range(3)],
            timeout_seconds=1,
            language_guidance="",
            memory_context="",
            layer_context="",
            required_sections="",
        )


@pytest.mark.asyncio
async def test_graph_invocation_receives_explicit_fanout_limit() -> None:
    service, record = await _service(graph_max_concurrency=2)
    configs = []

    async def invoke(value, *, config):
        configs.append(config)
        return {}

    async def graph():
        return SimpleNamespace(ainvoke=invoke)

    service._get_real_graph = graph
    await service._invoke_graph(record, kind="real", thread_id="bounded", graph_input={})
    assert configs[0]["max_concurrency"] == 2


def test_execution_limits_are_configurable_from_environment(monkeypatch) -> None:
    values = {
        "GRAPH_MAX_CONCURRENCY": 2,
        "LLM_MAX_CONCURRENCY": 3,
        "WRITER_SEGMENT_MAX_CONCURRENCY": 2,
        "WRITER_MAX_SEGMENTS": 10,
        "RUN_LLM_MAX_CALLS": 20,
        "RUN_LLM_MAX_REPAIRS": 4,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        for key, value in values.items():
            assert getattr(settings, key.lower()) == value
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_analyst_timeout_excludes_waiting_for_llm_admission() -> None:
    service, record = await _service(
        llm_max_concurrency=1,
        analyst_react_enabled=False,
        analyst_branch_timeout_seconds=0.05,
    )
    record.detail.raw_sources = [
        RawSource(
            id="source-a",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            snippet="A Pro costs $10 per month.",
            content_hash="a",
            confidence=0.9,
        )
    ]

    async def complete_json(**kwargs):
        await asyncio.sleep(0.035)
        return {
            "pricing_model": {
                "tiers": [
                    {
                        "name": "Pro",
                        "claims": [
                            {
                                "claim": "A Pro costs $10 per month.",
                                "source_ids": ["source-a"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ]
            }
        }

    service._llm.complete_json = complete_json
    await asyncio.gather(
        *(service._real_analyst_branch_step(record, "pricing", "A") for _ in range(3))
    )
    completed = [
        event
        for event in service.get_trace(record.detail.id)
        if event.type == "node_completed" and event.agent == "analyst"
    ]
    assert len(completed) == 3
    assert all("analysis_timeout" not in event.payload["react"] for event in completed)


def test_obsolete_dimension_entrypoints_are_removed() -> None:
    assert not hasattr(RunService, "_real_collector_step")
    assert not hasattr(RunService, "_real_analyst_step")
    assert not hasattr(RunService, "_run_collector_react")
    assert not hasattr(RunService, "_run_analyst_react")
