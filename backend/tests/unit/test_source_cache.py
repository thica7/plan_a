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
