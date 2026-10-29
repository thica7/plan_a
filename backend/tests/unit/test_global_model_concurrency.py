from __future__ import annotations

import asyncio
import multiprocessing
from contextlib import suppress
from pathlib import Path

import httpx
import pytest
from packages.config import Settings
from packages.infrastructure.execution_control import (
    ExecutionConflictError,
    ExecutionTimeoutError,
    ExecutionUnavailableError,
)
from packages.infrastructure.execution_factory import create_execution_coordinator
from packages.knowledge.retrieval import DefaultQueryRewriter
from packages.llm.doubao_client import DoubaoClient
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget, current_llm_execution
from packages.search.deepseek_client import DeepSeekSearchClient


def _settings(path, **overrides):
    return Settings(**{
        "ark_api_key": "synthetic-primary-key",
        "ark_model": "synthetic-model",
        "ark_base_url": "https://model.invalid",
        "deepseek_api_key": "synthetic-search-key",
        "llm_max_retries": 0,
        "llm_retry_backoff_seconds": 0,
        "execution_control_enabled": True,
        "execution_control_journal_path": str(path),
        "llm_max_concurrency": 1,
        "execution_model_wait_seconds": 0.1,
        **overrides,
    })


def _response(request):
    if request.url.path.endswith("/messages"):
        return httpx.Response(200, json={
            "content": [{"type": "web_search_tool_result", "content": []}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        })
    return httpx.Response(200, json={
        "choices": [{"message": {"content": '{"rewrites": ["alternate query"]}'}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    })


def _install_transport(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(handler),
    ))


def _caller(kind, settings):
    if kind == "native":
        client = DeepSeekSearchClient(settings)
        return client, lambda: client.search("synthetic query")
    client = DoubaoClient(settings)
    if kind == "json":
        return client, lambda: client.complete_json(system="s", user="u", schema_hint="{}")
    if kind == "rewrite":
        rewriter = DefaultQueryRewriter(client)
        return client, lambda: rewriter.rewrite("synthetic query", num_rewrites=1)
    return client, lambda: client.complete_text(system="s", user="u")


def _execution():
    budget = RunLLMBudget(20, 10, delivery_reserves={"writer:test": 1000})
    checkpoints = []
    execution = LLMCallExecution(
        budget, True, phase="writer:test", input_tokens=20, max_output_tokens=40,
        checkpoint=lambda: checkpoints.append((budget.calls, budget.tokens_reserved)),
    )
    return execution, checkpoints


async def _budgeted(execution, call):
    token = current_llm_execution.set(execution)
    try:
        execution.reserve()
        return await call()
    finally:
        execution.settle()
        current_llm_execution.reset(token)


async def _wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


def _mixed_process(path, active, peak, ready, start):
    async def work():
        settings = _settings(Path(path), llm_max_concurrency=2, execution_model_wait_seconds=5)
        calls = [_caller(kind, settings)[1] for kind in ("text", "rewrite", "native")]

        async def transport(request):
            with active.get_lock():
                active.value += 1
                peak.value = max(peak.value, active.value)
            try:
                await asyncio.sleep(0.08)
                return _response(request)
            finally:
                with active.get_lock():
                    active.value -= 1

        real_client = httpx.AsyncClient
        httpx.AsyncClient = lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(transport),
        )
        ready.put("ready")
        await asyncio.to_thread(start.wait, 10)
        results = await asyncio.gather(*(call() for call in calls))
        assert results[1] == ["alternate query"]

    asyncio.run(work())


def test_spawned_processes_share_transport_pool_for_generation_rewrite_and_native(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    active, peak = ctx.Value("i", 0), ctx.Value("i", 0)
    ready, start = ctx.Queue(), ctx.Event()
    workers = [ctx.Process(target=_mixed_process, args=(
        str(tmp_path / "journal.db"), active, peak, ready, start,
    )) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for _ in workers:
            assert ready.get(timeout=15) == "ready"
        start.set()
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
        assert active.value == 0
        assert peak.value == 2
    finally:
        start.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(5)
        ready.close()


@pytest.mark.parametrize("kind", ["text", "json", "native"])
@pytest.mark.parametrize("failure", ["timeout", "cancel"])
async def test_unsent_slot_wait_failure_refunds_only_its_budget(
    tmp_path, monkeypatch, kind, failure,
):
    settings = _settings(tmp_path / "journal.db")
    coordinator = create_execution_coordinator(settings)
    _, call = _caller(kind, settings)
    requests = []

    async def transport(request):
        requests.append(request)
        return _response(request)

    _install_transport(monkeypatch, transport)
    execution, checkpoints = _execution()
    # Another call's reservation in the same budget must survive the refund.
    other = LLMCallExecution(execution.budget, False, input_tokens=7, max_output_tokens=3)
    other.reserve()
    async with coordinator.model_slot():
        task = asyncio.create_task(_budgeted(execution, call))
        if failure == "cancel":
            await _wait_until(lambda: bool(checkpoints))
            await asyncio.sleep(0.02)
            task.cancel()
        expected = asyncio.CancelledError if failure == "cancel" else ExecutionTimeoutError
        with pytest.raises(expected):
            await task
    assert requests == []
    assert execution.transport_attempts == execution.attempts == execution.pending_attempts == 0
    budget = execution.budget
    assert budget.calls == 1 and budget.repairs == 0
    assert budget.tokens_reserved == 10 and budget.tokens_used == 0
    assert budget.cost_reserved_usd == pytest.approx(budget.cost(7, 3))
    assert budget.cost_used_usd == 0
    assert budget.delivery_charged["writer:test"] == 0
    assert budget.delivery_calls["writer:test"] == 0
    assert budget.reservation_settled.is_set()
    assert checkpoints == [(2, 70), (1, 10)]
    # Both the cancelled/expired waiter and the holder return the kernel slot.
    async with coordinator.model_slot():
        pass


@pytest.mark.parametrize("kind", ["text", "native"])
async def test_standalone_or_unbudgeted_wait_timeout_does_not_send(tmp_path, monkeypatch, kind):
    settings = _settings(tmp_path / "journal.db")
    coordinator = create_execution_coordinator(settings)
    client, call = _caller(kind, settings)
    requests = []

    async def transport(request):
        requests.append(request)
        return _response(request)

    _install_transport(monkeypatch, transport)
    async with coordinator.model_slot():
        with pytest.raises(ExecutionTimeoutError):
            await call()
    assert requests == []
    if kind == "native":
        metadata = client.consume_last_metadata()
        assert metadata["llm_transport_attempts"] == metadata["run_llm_calls_used"] == 0
        assert metadata["llm_tokens_charged"] == metadata["llm_cost_charged_usd"] == 0
        assert client._standalone_budget.tokens_reserved == 0


@pytest.mark.parametrize("kind", ["text", "native"])
async def test_sent_cancellation_keeps_unknown_charge_and_returns_slot(tmp_path, monkeypatch, kind):
    settings = _settings(tmp_path / "journal.db")
    _, call = _caller(kind, settings)
    entered = asyncio.Event()

    async def transport(request):
        entered.set()
        await asyncio.Event().wait()

    _install_transport(monkeypatch, transport)
    execution, _ = _execution()
    task = asyncio.create_task(_budgeted(execution, call))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert execution.transport_attempts == execution.budget.calls == 1
    assert execution.budget.tokens_used == execution.tokens_charged == 60
    assert execution.budget.cost_used_usd == pytest.approx(execution.budget.cost(20, 40))
    assert execution.budget.tokens_reserved == execution.budget.cost_reserved_usd == 0
    async with create_execution_coordinator(settings).model_slot():
        pass


@pytest.mark.parametrize("kind", ["text", "native"])
async def test_disabled_clients_send_without_creating_coordination_files(
    tmp_path, monkeypatch, kind,
):
    settings = _settings(tmp_path / "absent" / "journal.db", execution_control_enabled=False)
    _, call = _caller(kind, settings)
    _install_transport(monkeypatch, _response)
    await call()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["text", "native"])
@pytest.mark.parametrize("invalid", ["policy", "storage", "mismatch"])
def test_clients_fail_closed_on_invalid_coordination(tmp_path, kind, invalid):
    path = tmp_path / "journal.db"
    if invalid == "policy":
        settings = _settings(path, llm_max_concurrency=0)
    elif invalid == "storage":
        path.mkdir()
        settings = _settings(path)
    else:
        create_execution_coordinator(_settings(path))
        settings = _settings(path, llm_max_concurrency=2)
    with pytest.raises((ExecutionUnavailableError, ExecutionConflictError)):
        _caller(kind, settings)


async def test_retry_and_backup_use_shared_slot_but_backoff_releases_it(tmp_path, monkeypatch):
    settings = _settings(
        tmp_path / "journal.db", llm_max_retries=1,
        backup_llm_api_key="synthetic-backup", backup_llm_model="synthetic-backup-model",
        backup_llm_base_url="https://backup.invalid",
    )
    retry = DoubaoClient(settings)
    _, other_call = _caller("native", settings)
    backoff, resume = asyncio.Event(), asyncio.Event()
    requests = []

    async def sleep(_):
        backoff.set()
        await resume.wait()

    async def transport(request):
        requests.append(str(request.url))
        if request.url.host == "model.invalid":
            return httpx.Response(503, text="synthetic retry")
        return _response(request)

    monkeypatch.setattr(retry, "_sleep_before_retry", sleep)
    _install_transport(monkeypatch, transport)
    execution, _ = _execution()
    task = asyncio.create_task(_budgeted(
        execution, lambda: retry.complete_text(system="s", user="u"),
    ))
    try:
        await asyncio.wait_for(backoff.wait(), 2)
        await asyncio.wait_for(other_call(), 1)
        # Holding the independently created pool prevents the retry from sending.
        coordinator = create_execution_coordinator(settings)
        async with coordinator.model_slot():
            resume.set()
            await asyncio.sleep(0.02)
            assert len(requests) == 2
        await task
    finally:
        resume.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert [httpx.URL(url).host for url in requests] == [
        "model.invalid", "api.deepseek.com", "model.invalid", "backup.invalid",
    ]
    assert execution.transport_attempts == execution.budget.calls == 3


@pytest.mark.parametrize("next_attempt", ["retry", "backup"])
async def test_later_slot_failure_preserves_previously_sent_unknown_usage(
    tmp_path, monkeypatch, next_attempt,
):
    settings = _settings(
        tmp_path / "journal.db", llm_max_retries=int(next_attempt == "retry"),
        backup_llm_api_key="synthetic-backup", backup_llm_model="synthetic-backup-model",
        backup_llm_base_url="https://backup.invalid",
    )
    client = DoubaoClient(settings)
    coordinator = create_execution_coordinator(settings)
    backoff, resume = asyncio.Event(), asyncio.Event()
    requests = []

    async def sleep(_):
        backoff.set()
        await resume.wait()

    original = client._complete_text_with_provider

    async def provider_call(provider, **kwargs):
        if provider.name == "backup":
            backoff.set()
            await resume.wait()
        return await original(provider, **kwargs)

    async def transport(request):
        requests.append(request)
        return httpx.Response(503, text="synthetic retry")

    monkeypatch.setattr(client, "_sleep_before_retry", sleep)
    monkeypatch.setattr(client, "_complete_text_with_provider", provider_call)
    _install_transport(monkeypatch, transport)
    execution, _ = _execution()
    task = asyncio.create_task(_budgeted(
        execution, lambda: client.complete_text(system="s", user="u"),
    ))
    await asyncio.wait_for(backoff.wait(), 2)
    async with coordinator.model_slot():
        resume.set()
        with pytest.raises(ExecutionTimeoutError):
            await task
    assert len(requests) == execution.transport_attempts == execution.budget.calls == 1
    assert execution.tokens_charged == execution.budget.tokens_used == 60
    assert execution.budget.cost_used_usd == pytest.approx(execution.budget.cost(20, 40))
    assert execution.budget.delivery_charged["writer:test"] == 60
    assert execution.budget.delivery_calls["writer:test"] == 1
    assert execution.budget.tokens_reserved == execution.budget.cost_reserved_usd == 0


@pytest.mark.parametrize("kind", ["text", "native"])
async def test_sent_provider_timeout_keeps_unknown_charge_and_returns_slot(
    tmp_path, monkeypatch, kind,
):
    settings = _settings(tmp_path / "journal.db")
    _, call = _caller(kind, settings)

    async def transport(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    _install_transport(monkeypatch, transport)
    execution, _ = _execution()
    with pytest.raises(Exception, match="timed out|超时"):
        await _budgeted(execution, call)
    assert execution.transport_attempts == execution.budget.calls == 1
    assert execution.budget.tokens_used == execution.tokens_charged == 60
    assert execution.budget.cost_used_usd == pytest.approx(execution.budget.cost(20, 40))
    assert execution.budget.tokens_reserved == execution.budget.cost_reserved_usd == 0
    async with create_execution_coordinator(settings).model_slot():
        pass


@pytest.mark.parametrize("kind", ["text", "json", "native"])
async def test_runtime_storage_failure_refunds_unsent_reservation(
    tmp_path, monkeypatch, kind,
):
    path = tmp_path / "journal.db"
    _, call = _caller(kind, _settings(path))
    requests = []

    async def transport(request):
        requests.append(request)
        return _response(request)

    _install_transport(monkeypatch, transport)
    path.rename(tmp_path / "saved.db")
    path.mkdir()
    execution, checkpoints = _execution()
    with pytest.raises(ExecutionUnavailableError):
        await _budgeted(execution, call)
    assert requests == []
    assert execution.attempts == execution.transport_attempts == execution.pending_attempts == 0
    assert execution.budget.calls == execution.budget.repairs == execution.budget.tokens_used == 0
    assert execution.budget.tokens_reserved == execution.budget.cost_reserved_usd == 0
    assert execution.budget.cost_used_usd == 0
    assert execution.budget.delivery_charged["writer:test"] == 0
    assert execution.budget.delivery_calls["writer:test"] == 0
    assert checkpoints == [(1, 60), (0, 0)]
