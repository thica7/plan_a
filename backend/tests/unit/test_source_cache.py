import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from packages.tools.evidence_fetch import EvidenceFetchResult


class Cache:
    def __init__(self):
        self.rows = {}

    def cache_key(self, *parts):
        return repr(parts)

    async def get_json(self, key):
        return self.rows.get(key)

    async def set_json(self, key, value, *, ttl_seconds):
        self.rows[key] = value
        return True


def result(url="https://example.com/docs", **overrides):
    body = "Editors can edit the document on paid plans."
    values = dict(
        url=url,
        ok=True,
        title="Example docs",
        text=body,
        content_hash=hashlib.sha256(body.encode()).hexdigest()[:16],
        source_material_level="full_source",
        status_code=200,
        quality_score=0.8,
    )
    values.update(overrides)
    return EvidenceFetchResult(**values)


@pytest.mark.asyncio
async def test_cached_source_retains_original_capture_time_and_does_not_fetch_again():
    from packages.infrastructure.source_cache import cached_fetch

    calls, cache = [], Cache()

    async def fetch():
        calls.append(1)
        return result()

    first = await cached_fetch(
        "https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60
    )
    second = await cached_fetch(
        "https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60
    )
    assert calls == [1]
    assert first.captured_at == second.captured_at
    assert second.cache_hit and not first.cache_hit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,options,overrides",
    [
        ("https://user:secret@example.com/docs", {}, {}),
        ("https://example.com/docs?token=secret", {}, {}),
        ("https://example.com/pricing", {}, {}),
        ("https://example.com/docs", {"require_price_content": True}, {}),
        ("https://example.com/docs", {}, {"ok": False}),
        ("https://example.com/docs", {}, {"source_material_level": "unknown"}),
        ("https://example.com/docs", {}, {"fetch_method": "model_summary"}),
        ("https://example.com/docs", {}, {"content_hash": "wrong"}),
    ],
)
async def test_uncacheable_or_unverified_inputs_always_fetch(url, options, overrides):
    from packages.infrastructure.source_cache import cached_fetch

    calls, cache = [], Cache()

    async def fetch():
        calls.append(1)
        return result(url, **overrides)

    for _ in range(2):
        await cached_fetch(url, fetch, options=options, runtime=cache, ttl_seconds=60)
    assert calls == [1, 1]
    assert not cache.rows


@pytest.mark.asyncio
async def test_cache_rejects_expired_future_or_tampered_captures():
    from packages.infrastructure.source_cache import cached_fetch

    calls, cache = [], Cache()

    async def fetch():
        calls.append(1)
        return result()

    await cached_fetch("https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60)
    for changed in [
        datetime.now(UTC) - timedelta(seconds=61),
        datetime.now(UTC) + timedelta(minutes=1),
    ]:
        row = next(iter(cache.rows.values()))
        row["result"]["captured_at"] = changed.isoformat()
        await cached_fetch(
            "https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60
        )
    row = next(iter(cache.rows.values()))
    row["result"]["text"] = "tampered"
    await cached_fetch("https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60)
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_fetch_policy_options_are_part_of_cache_key():
    from packages.infrastructure.source_cache import cached_fetch

    calls, cache = [], Cache()

    async def fetch():
        calls.append(1)
        return result()

    for options in [{"allow_advanced": False}, {"allow_advanced": True}, {"allow_advanced": False}]:
        await cached_fetch(
            "https://example.com/docs", fetch, options=options, runtime=cache, ttl_seconds=60
        )
    assert calls == [1, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("text_length", "broken"),
        ("capture_metadata", 42),
        ("capture_metadata", {"document_headings": 42}),
    ],
)
async def test_malformed_cache_business_fields_are_misses(field, value):
    from packages.infrastructure.source_cache import cached_fetch

    calls, cache = [], Cache()

    async def fetch():
        calls.append(1)
        return result()

    await cached_fetch("https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60)
    next(iter(cache.rows.values()))["result"][field] = value
    current = await cached_fetch(
        "https://example.com/docs", fetch, options={}, runtime=cache, ttl_seconds=60
    )
    assert len(calls) == 2 and not current.cache_hit


@pytest.mark.asyncio
async def test_capture_adapter_uses_cached_original_capture_time():
    from packages.research.capture import capture_candidate
    from packages.research.models import SourceCandidate

    captured = datetime(2026, 10, 1, tzinfo=UTC)

    async def fetch(url):
        return replace(result(url), captured_at=captured, cache_hit=True)

    page = await capture_candidate(
        SourceCandidate(title="docs", url="https://example.com/docs", origin="web_search"), fetch
    )
    assert page.captured_at == captured
    assert page.metadata["source_cache_hit"] is True


@pytest.mark.asyncio
async def test_public_fetch_entry_reuses_cache_and_preserves_price_bypass(monkeypatch):
    from packages.infrastructure import redis_config
    from packages.tools import evidence_fetch

    cache, calls = Cache(), []
    monkeypatch.setattr(
        redis_config, "redis_options", lambda: redis_config.RedisOptions(cache_enabled=True)
    )
    monkeypatch.setattr(redis_config, "get_redis_runtime", lambda: cache)

    async def transport(url, **options):
        calls.append(options)
        return result(url)

    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    first = await evidence_fetch.fetch_evidence_page("https://example.com/docs")
    second = await evidence_fetch.fetch_evidence_page("https://example.com/docs")
    await evidence_fetch.fetch_evidence_page("https://example.com/docs", require_price_content=True)
    assert len(calls) == 2
    assert calls[-1]["require_price_content"] is True
    assert not first.cache_hit and second.cache_hit
    assert first.captured_at == second.captured_at


@pytest.mark.asyncio
async def test_disabled_cache_public_entry_does_not_construct_runtime(monkeypatch):
    from packages.infrastructure import redis_config
    from packages.tools import evidence_fetch

    monkeypatch.setattr(redis_config, "redis_options", lambda: redis_config.RedisOptions())

    def forbidden():
        pytest.fail("disabled cache must not initialize Redis")

    monkeypatch.setattr(redis_config, "get_redis_runtime", forbidden)

    async def transport(url, **options):
        return result(url)

    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    value = await evidence_fetch.fetch_evidence_page("https://example.com/docs")
    assert value.ok and not value.cache_hit


@pytest.mark.asyncio
async def test_redis_off_public_entry_coalesces_32_cold_calls_and_copies_metadata(monkeypatch):
    import asyncio

    from packages.infrastructure import redis_config
    from packages.tools import evidence_fetch

    monkeypatch.setattr(redis_config, "redis_options", lambda: redis_config.RedisOptions())
    monkeypatch.setattr(redis_config, "get_redis_runtime", lambda: pytest.fail("Redis off"))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    captured = datetime.now(UTC) - timedelta(seconds=10)

    async def transport(url, **options):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return result(url, captured_at=captured, capture_metadata={"nested": [[1]]})

    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    tasks = [asyncio.create_task(evidence_fetch.fetch_evidence_page("https://example.com/docs"))
             for _ in range(32)]
    await entered.wait()
    await asyncio.sleep(0)
    release.set()
    values = await asyncio.gather(*tasks)
    assert calls == 1
    assert all(value.captured_at == captured for value in values)
    values[0].capture_metadata["nested"][0].append(2)
    assert all(value.capture_metadata["nested"] == [[1]] for value in values[1:])


@pytest.mark.asyncio
@pytest.mark.parametrize("url,options", [
    ("https://example.com/docs", {"force_refresh": True}),
    ("https://example.com/docs", {"require_price_content": True}),
    ("https://example.com/pricing", {}),
    ("https://example.com/billing", {}),
    ("https://example.com/plans", {}),
    ("https://u:secret@example.com/docs", {}),
    ("https://example.com/docs?token=secret", {}),
    ("https://example.com/docs#private", {}),
])
async def test_public_entry_bypasses_sharing_and_redis_for_sensitive_or_fresh_inputs(
    monkeypatch, url, options,
):
    import asyncio

    from packages.infrastructure import redis_config
    from packages.tools import evidence_fetch

    monkeypatch.setattr(redis_config, "redis_options",
                        lambda: redis_config.RedisOptions(cache_enabled=True))
    monkeypatch.setattr(redis_config, "get_redis_runtime", lambda: pytest.fail("must bypass Redis"))
    calls = 0

    async def transport(url, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return result(url)

    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    await asyncio.gather(*(evidence_fetch.fetch_evidence_page(url, **options) for _ in range(4)))
    assert calls == 4


class SharedMutexClient:
    """Offline command contract only; this fake does not execute Redis Lua."""

    def __init__(self):
        self.values = {}
        self.now_ms = 0
        self.acquired = 0

    async def get(self, key):
        value, expiry = self.values.get(key, (None, 0))
        return value if expiry > self.now_ms else None

    async def set(self, key, value, *, ex=None, nx=False, px=None):
        if nx and await self.get(key) is not None:
            return None
        self.values[key] = (value, self.now_ms + (px if px is not None else ex * 1000))
        if nx:
            self.acquired += 1
        return True

    async def eval(self, script, numkeys, *args):
        from packages.infrastructure.redis_runtime import CACHE_PUBLISH_LUA, CACHE_RELEASE_LUA

        if script == CACHE_RELEASE_LUA:
            key, owner = args
            if await self.get(key) == owner:
                self.values.pop(key, None)
                return 1
            return 0
        assert script == CACHE_PUBLISH_LUA and numkeys == 2
        lock_key, cache_key, owner, value, ttl = args
        if await self.get(lock_key) == owner:
            await self.set(cache_key, value, ex=ttl)
            return 1
        return 0


@pytest.mark.asyncio
async def test_distinct_redis_runtimes_share_cold_page_mutex(monkeypatch):
    import asyncio

    from packages.infrastructure.redis_runtime import RedisRuntime
    from packages.infrastructure.source_cache import cached_fetch

    client = SharedMutexClient()
    first = RedisRuntime(enabled=True, client=client)
    second = RedisRuntime(enabled=True, client=client)
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(.03)
        return result()

    values = await asyncio.gather(*(
        cached_fetch("https://example.com/docs", fetch, options={}, runtime=runtime, ttl_seconds=60)
        for runtime in (first, second)
    ))
    assert calls == 1 and client.acquired == 1
    assert values[0].captured_at == values[1].captured_at
    assert sorted(value.cache_hit for value in values) == [False, True]


@pytest.mark.asyncio
async def test_expired_owner_cannot_publish_or_release_new_owner_cache():
    from packages.infrastructure.redis_runtime import RedisRuntime

    client = SharedMutexClient()
    first = RedisRuntime(enabled=True, client=client)
    second = RedisRuntime(enabled=True, client=client)
    key = first.cache_key("https://u:secret@example.com/?token=private")
    assert await first.acquire_cache_lock(key, "old", ttl_ms=10) is True
    client.now_ms = 10
    assert await second.acquire_cache_lock(key, "new", ttl_ms=10) is True
    assert await second.publish_cache(key, "new", {"version": 2}, ttl_seconds=60)
    assert not await first.publish_cache(key, "old", {"version": 1}, ttl_seconds=60)
    assert not await first.release_cache_lock(key, "old")
    assert await first.get_json(key) == {"version": 2}
    assert await second.release_cache_lock(key, "new")
    assert all("secret" not in item and "example.com" not in item for item in client.values)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_redis_owner_failure_or_cancellation_releases_mutex(cancel):
    import asyncio

    from packages.infrastructure.redis_runtime import RedisRuntime
    from packages.infrastructure.source_cache import cached_fetch

    client = SharedMutexClient()
    runtime = RedisRuntime(enabled=True, client=client)
    entered = asyncio.Event()

    async def broken():
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        raise ValueError("synthetic")

    task = asyncio.create_task(cached_fetch("https://example.com/docs", broken, options={},
                                             runtime=runtime, ttl_seconds=60))
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await task
    for _ in range(10):
        await asyncio.sleep(0)
    assert client.acquired == 1
    assert not any([await client.get(key) for key in list(client.values)])


@pytest.mark.asyncio
@pytest.mark.parametrize("with_record", [False, True])
@pytest.mark.parametrize("dimension,refresh", [("feature", True), ("pricing", False)])
async def test_collector_actual_fetch_guard_receives_refresh_and_price_intent(
    monkeypatch, with_record, dimension, refresh,
):
    from types import SimpleNamespace

    import packages.agents.collectors.logic as collector_module
    from packages.infrastructure import redis_config
    from packages.orchestrator.service import RunRecord
    from packages.tools import evidence_fetch
    from test_collector_knowledge_scope import service_and_detail

    service, detail = service_and_detail(dimension)
    detail.evidence_refresh_active = refresh
    record = RunRecord(detail=detail) if with_record else None
    if record is not None:
        service._runs[detail.id] = record
    calls = []
    monkeypatch.setattr(redis_config, "redis_options",
                        lambda: redis_config.RedisOptions(cache_enabled=True))
    monkeypatch.setattr(redis_config, "get_redis_runtime",
                        lambda: pytest.fail("intent must bypass"))

    async def robots(*args, **kwargs):
        return SimpleNamespace(allowed=True)

    async def transport(url, **options):
        calls.append(options)
        return result(url)

    class PipelineReached(Exception):
        pass

    async def pipeline(brief, *, fetch, **kwargs):
        await fetch("https://example.com/docs")
        raise PipelineReached

    monkeypatch.setattr(service, "_trace_robots", robots)
    monkeypatch.setattr(collector_module, "run_research_pipeline", pipeline)
    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    with pytest.raises(PipelineReached):
        await service._source_from_search_result(
            detail, "Vacuum X Pro", dimension,
            SimpleNamespace(url="https://example.com/docs", title="docs", snippet="body",
                            provider=None, date=None, last_updated=None),
            record=record,
        )
    assert len(calls) == 1
    assert calls[0]["require_price_content"] == (dimension == "pricing")


@pytest.mark.asyncio
async def test_public_entry_inflight_options_are_distinct(monkeypatch):
    import asyncio

    from packages.infrastructure import redis_config
    from packages.tools import evidence_fetch

    monkeypatch.setattr(redis_config, "redis_options", lambda: redis_config.RedisOptions())
    calls = []

    async def transport(url, **options):
        calls.append(options["allow_advanced"])
        await asyncio.sleep(.01)
        return result(url)

    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    await asyncio.gather(*(evidence_fetch.fetch_evidence_page(
        "https://example.com/docs", allow_advanced=value,
    ) for value in [True, False, True, False]))
    assert sorted(calls) == [False, True]


@pytest.mark.asyncio
async def test_deepseek_public_entry_keeps_each_call_out_of_cache_and_flight(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from packages.infrastructure import redis_config
    from packages.tools import evidence_fetch

    monkeypatch.setattr(redis_config, "get_redis_runtime", lambda: pytest.fail("provider bypass"))
    settings = SimpleNamespace(deepseek_web_api_enabled=True, resolved_deepseek_api_key="fake")
    calls = 0

    async def transport(url, **options):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return result(url, capture_metadata={"web_api_requests": 1})

    monkeypatch.setattr(evidence_fetch, "_fetch_evidence_page", transport)
    values = await asyncio.gather(*(evidence_fetch.fetch_evidence_page(
        "https://example.com/docs", deepseek_settings=settings,
    ) for _ in range(4)))
    assert calls == 4 and sum(value.capture_metadata["web_api_requests"] for value in values) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during_release", [False, True])
async def test_cancel_after_set_commit_before_ack_releases_own_lease(cancel_during_release):
    import asyncio

    from packages.infrastructure import source_cache
    from packages.infrastructure.redis_runtime import CACHE_RELEASE_LUA, RedisRuntime
    class CommitBeforeAck(SharedMutexClient):
        def __init__(self):
            super().__init__()
            self.committed = asyncio.Event()
            self.release_calls = 0
            self.lock_key = None
            self.release_started = asyncio.Event()
            self.release_ack = asyncio.Event()

        async def set(self, key, value, *, ex=None, nx=False, px=None):
            answer = await super().set(key, value, ex=ex, nx=nx, px=px)
            if nx and answer is True:
                self.lock_key = key
                self.committed.set()
                await asyncio.Event().wait()
            return answer

        async def eval(self, script, numkeys, *args):
            if script == CACHE_RELEASE_LUA:
                self.release_calls += 1
                self.release_started.set()
                if cancel_during_release:
                    await self.release_ack.wait()
            return await super().eval(script, numkeys, *args)

    client = CommitBeforeAck()
    runtime = RedisRuntime(enabled=True, client=client, timeout_seconds=5)
    fetch_calls = 0

    async def fetch():
        nonlocal fetch_calls
        fetch_calls += 1
        return result()

    caller = asyncio.create_task(source_cache.cached_fetch(
        "https://example.com/docs", fetch, options={}, runtime=runtime, ttl_seconds=60,
    ))
    await asyncio.wait_for(client.committed.wait(), 1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    if cancel_during_release:
        await asyncio.wait_for(client.release_started.wait(), 1)
        entry = next(iter(source_cache._SOURCE_FLIGHT._entries.values()))
        entry.task.cancel()
        await asyncio.sleep(0)
        client.release_ack.set()
    async with asyncio.timeout(1):
        while source_cache._SOURCE_FLIGHT._entries:
            await asyncio.sleep(0)
    assert fetch_calls == 0
    assert client.release_calls == 1
    assert await client.get(client.lock_key) is None
