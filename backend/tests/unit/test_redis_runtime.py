"""Offline contract tests; the fake does not execute or validate Redis Lua."""

import asyncio
import importlib
import re
import sys
import time
import types
from typing import Any

import pytest


def runtime_module():
    try:
        return importlib.import_module("packages.infrastructure.redis_runtime")
    except ModuleNotFoundError:
        pytest.fail("optional Redis runtime has not been implemented")


class FakeClient:
    """Models command responses and server time without opening any socket."""

    def __init__(self) -> None:
        self.server_ms = 100_250
        self.values: dict[str, tuple[Any, int]] = {}
        self.windows: dict[str, tuple[int, int]] = {}
        self.calls: list[tuple] = []
        self.failure: Exception | None = None
        self.delay = 0.0
        self.closed = False
        self.eval_response: Any = None

    async def _before(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure

    async def get(self, key: str) -> Any:
        self.calls.append(("get", key))
        await self._before()
        value, expires_ms = self.values.get(key, (None, 0))
        return value if expires_ms > self.server_ms else None

    async def set(self, key: str, value: bytes, *, ex: int) -> bool:
        self.calls.append(("set", key, value, ex))
        await self._before()
        self.values[key] = (value, self.server_ms + ex * 1000)
        return True

    async def eval(self, script: str, numkeys: int, *args) -> Any:
        self.calls.append(("eval", script, numkeys, *args))
        await self._before()
        if self.eval_response is not None:
            return self.eval_response
        key, limit, window_ms = args
        current_window = self.server_ms // window_ms
        stored_window, count = self.windows.get(key, (-1, 0))
        if stored_window != current_window:
            count = 0
        allowed = count < limit
        if allowed:
            count += 1
        self.windows[key] = (current_window, count)
        retry = 0 if allowed else ((current_window + 1) * window_ms - self.server_ms + 999) // 1000
        return [int(allowed), retry, max(0, limit - count)]

    async def ping(self) -> bool:
        self.calls.append(("ping",))
        await self._before()
        return True

    async def aclose(self) -> None:
        self.calls.append(("aclose",))
        self.closed = True


@pytest.mark.asyncio
async def test_disabled_runtime_never_uses_injected_client() -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(client=client)
    key = runtime.cache_key("fetch", "https://example.com/page")

    assert runtime.enabled is False
    assert await runtime.get_json(key) is None
    assert await runtime.set_json(key, {"body": "cached"}, ttl_seconds=30) is False
    assert await runtime.ping() is False
    decision = await runtime.check_rate_limit("server-owned-user", limit=2, window_seconds=10)
    assert (decision.allowed, decision.retry_after_seconds, decision.remaining) == (True, 0, 2)
    await runtime.aclose()
    assert client.calls == []


def test_cache_keys_are_stable_hashed_and_isolate_namespace_and_policy() -> None:
    module = runtime_module()
    first = module.RedisRuntime(namespace="workspace-a")
    same = module.RedisRuntime(namespace="workspace-a")
    other = module.RedisRuntime(namespace="workspace-b")
    parts = ("https://user:secret@example.com/page?token=private", {"strategy": "v1", "js": False})
    key = first.cache_key(*parts)

    assert key == same.cache_key(parts[0], {"js": False, "strategy": "v1"})
    assert key != other.cache_key(*parts)
    assert key != first.cache_key(parts[0], {"strategy": "v2", "js": False})
    assert re.fullmatch(r"plan-a:workspace-a:cache:[a-f0-9]{64}", key)
    assert all(secret not in key for secret in ("user", "secret", "example.com", "private"))


@pytest.mark.asyncio
async def test_cache_round_trip_keeps_capture_time_and_expires_at_ttl() -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client)
    key = runtime.cache_key("fetch", "https://example.com")
    value = {
        "captured_at": "2026-10-01T02:03:04Z",
        "body": "原始正文",
        "links": [None, 1, True, 2.5],
    }

    assert await runtime.set_json(key, value, ttl_seconds=3) is True
    assert type(client.values[key][0]) is bytes
    client.server_ms += 2999
    assert await runtime.get_json(key) == value
    client.server_ms += 1
    assert await runtime.get_json(key) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", [0, -1, True, 1.5, 11])
async def test_cache_rejects_invalid_or_unbounded_ttl(ttl) -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client, max_cache_ttl_seconds=10)

    assert await runtime.set_json(runtime.cache_key("page"), {}, ttl_seconds=ttl) is False
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [b"binary", (1, 2), {1: "key"}, {"nan": float("nan")}, {"inf": float("inf")}, object()]
)
async def test_cache_rejects_non_json_values(value) -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client)

    assert await runtime.set_json(runtime.cache_key("page"), value, ttl_seconds=10) is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_cache_rejects_cyclic_and_overdeep_values() -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client)
    cyclic: list = []
    cyclic.append(cyclic)
    deep: list = []
    for _ in range(40):
        deep = [deep]

    for value in (cyclic, deep):
        assert await runtime.set_json(runtime.cache_key("page"), value, ttl_seconds=10) is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_cache_bounds_encoded_byte_size_on_reads_and_writes() -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client, max_cache_bytes=6)
    key = runtime.cache_key("page")

    assert await runtime.set_json(key, "中文", ttl_seconds=10) is False
    assert client.calls == []
    assert await runtime.set_json(key, "four", ttl_seconds=10) is True
    assert await runtime.get_json(key) == "four"
    client.values[key] = (b'"seven"', client.server_ms + 1000)
    assert await runtime.get_json(key) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"{broken",
        b"\xff",
        b"NaN",
        b"1e999",
        b'{"duplicate":1,"duplicate":2}',
        "{}",
        bytearray(b"{}"),
    ],
)
async def test_cache_corrupt_or_non_bytes_response_is_a_miss(payload) -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client)
    key = runtime.cache_key("page")
    client.values[key] = (payload, client.server_ms + 1000)

    assert await runtime.get_json(key) is None


@pytest.mark.asyncio
async def test_cache_rejects_arbitrary_or_other_namespace_keys() -> None:
    client = FakeClient()
    module = runtime_module()
    runtime = module.RedisRuntime(enabled=True, client=client)
    other = module.RedisRuntime(namespace="other")

    for key in ("https://user:secret@example.com", other.cache_key("page")):
        assert await runtime.get_json(key) is None
        assert await runtime.set_json(key, {}, ttl_seconds=10) is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_disconnect_is_cache_miss_and_rate_backend_unavailable() -> None:
    client = FakeClient()
    client.failure = ConnectionError("redis://user:secret@private-host")
    module = runtime_module()
    runtime = module.RedisRuntime(enabled=True, client=client)
    key = runtime.cache_key("page")

    assert await runtime.get_json(key) is None
    assert await runtime.set_json(key, {}, ttl_seconds=10) is False
    assert await runtime.ping() is False
    with pytest.raises(module.RedisBackendUnavailable) as caught:
        await runtime.check_rate_limit("user", limit=1, window_seconds=10)
    assert str(caught.value) == "Redis rate limit backend unavailable"
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_fixed_window_boundary_uses_fake_server_time_only(monkeypatch) -> None:
    client = FakeClient()
    module = runtime_module()
    runtime = module.RedisRuntime(enabled=True, client=client)
    monkeypatch.setattr(time, "time", lambda: 9_999_999_999)

    first = await runtime.check_rate_limit("workspace:user", limit=2, window_seconds=10)
    second = await runtime.check_rate_limit("workspace:user", limit=2, window_seconds=10)
    third = await runtime.check_rate_limit("workspace:user", limit=2, window_seconds=10)
    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert (third.allowed, third.retry_after_seconds, third.remaining) == (False, 10, 0)
    client.server_ms = 109_999
    assert (
        await runtime.check_rate_limit("workspace:user", limit=2, window_seconds=10)
    ).retry_after_seconds == 1
    client.server_ms = 110_000
    reset = await runtime.check_rate_limit("workspace:user", limit=2, window_seconds=10)
    assert (reset.allowed, reset.remaining, reset.retry_after_seconds) == (True, 1, 0)
    assert all(call[0] == "eval" and call[2] == 1 and len(call) == 6 for call in client.calls)


@pytest.mark.asyncio
async def test_rate_keys_isolate_scope_namespace_and_policy_without_plain_identity() -> None:
    client = FakeClient()
    module = runtime_module()
    first = module.RedisRuntime(enabled=True, client=client, namespace="a")
    second = module.RedisRuntime(enabled=True, client=client, namespace="b")

    assert (await first.check_rate_limit("private-user", limit=1, window_seconds=10)).allowed
    assert not (await first.check_rate_limit("private-user", limit=1, window_seconds=10)).allowed
    assert (await first.check_rate_limit("other-user", limit=1, window_seconds=10)).allowed
    assert (await first.check_rate_limit("private-user", limit=2, window_seconds=10)).allowed
    assert (await first.check_rate_limit("private-user", limit=1, window_seconds=20)).allowed
    assert (await second.check_rate_limit("private-user", limit=1, window_seconds=10)).allowed
    assert all("private-user" not in call[3] and ":rate:" in call[3] for call in client.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        [True, 0, 0],
        [2, 0, 0],
        [0, 0, 0],
        [0, -1, 0],
        [1, 0, -1],
        [1, 0, 3],
        [1, 1, 0],
        [0, 11, 0],
        [0, 1, 1],
        ["1", "0", "0"],
    ],
)
async def test_invalid_rate_response_is_backend_unavailable(response) -> None:
    client = FakeClient()
    client.eval_response = response if response is not None else "bad"
    module = runtime_module()
    runtime = module.RedisRuntime(enabled=True, client=client)

    with pytest.raises(module.RedisBackendUnavailable):
        await runtime.check_rate_limit("user", limit=2, window_seconds=10)


@pytest.mark.asyncio
async def test_short_operation_deadline_applies_to_cache_ping_and_rate() -> None:
    client = FakeClient()
    client.delay = 10
    module = runtime_module()
    runtime = module.RedisRuntime(enabled=True, client=client, timeout_seconds=0.01)
    key = runtime.cache_key("page")

    async with asyncio.timeout(0.5):
        assert await runtime.get_json(key) is None
        assert await runtime.set_json(key, {}, ttl_seconds=10) is False
        assert await runtime.ping() is False
        with pytest.raises(module.RedisBackendUnavailable):
            await runtime.check_rate_limit("user", limit=2, window_seconds=10)


@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_cache_miss() -> None:
    client = FakeClient()
    client.failure = asyncio.CancelledError()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client)

    with pytest.raises(asyncio.CancelledError):
        await runtime.get_json(runtime.cache_key("page"))


@pytest.mark.asyncio
async def test_enabled_client_is_created_lazily_with_bounded_io_and_no_retries(monkeypatch) -> None:
    client = FakeClient()
    calls = []

    class Retry:
        def __init__(self, backoff, retries) -> None:
            self.retries = retries

    def from_url(url, **kwargs):
        calls.append((url, kwargs))
        return client

    redis = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_asyncio.Redis = types.SimpleNamespace(from_url=from_url)
    redis_backoff = types.ModuleType("redis.backoff")
    redis_backoff.NoBackoff = type("NoBackoff", (), {})
    redis_retry = types.ModuleType("redis.asyncio.retry")
    redis_retry.Retry = Retry
    monkeypatch.setitem(sys.modules, "redis.retry", None)
    for name, value in (
        ("redis", redis),
        ("redis.asyncio", redis_asyncio),
        ("redis.backoff", redis_backoff),
        ("redis.asyncio.retry", redis_retry),
    ):
        monkeypatch.setitem(sys.modules, name, value)
    runtime = runtime_module().RedisRuntime("redis://unused/0", enabled=True, timeout_seconds=0.25)

    assert calls == []
    assert await runtime.ping() is True
    assert await runtime.ping() is True
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["socket_connect_timeout"] == 0.25
    assert kwargs["socket_timeout"] == 0.25
    assert kwargs["decode_responses"] is False
    assert kwargs["retry_on_timeout"] is False
    assert kwargs["retry"].retries == 0
    assert kwargs["max_connections"] <= 20
    await runtime.aclose()
    assert client.closed
    assert await runtime.ping() is False


@pytest.mark.asyncio
async def test_url_query_cannot_override_io_or_decode_safety() -> None:
    runtime = runtime_module().RedisRuntime(
        "redis://unused/0?socket_timeout=100&decode_responses=True", enabled=True
    )

    assert await runtime.ping() is False
    with pytest.raises(runtime_module().RedisBackendUnavailable):
        await runtime.check_rate_limit("user", limit=1, window_seconds=10)


@pytest.mark.asyncio
async def test_aclose_without_use_does_not_create_client(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "redis", None)
    runtime = runtime_module().RedisRuntime("redis://unused/0", enabled=True)

    await runtime.aclose()
    assert await runtime.ping() is False


@pytest.mark.asyncio
async def test_missing_optional_dependency_keeps_cache_safe_and_rate_closed(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.delitem(sys.modules, "redis.asyncio", raising=False)
    module = runtime_module()
    runtime = module.RedisRuntime("redis://unused/0", enabled=True)

    assert await runtime.get_json(runtime.cache_key("page")) is None
    assert await runtime.ping() is False
    with pytest.raises(module.RedisBackendUnavailable):
        await runtime.check_rate_limit("user", limit=1, window_seconds=10)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"namespace": "bad:namespace"},
        {"namespace": "https://secret"},
        {"namespace": ""},
        {"timeout_seconds": 0},
        {"timeout_seconds": 6},
        {"timeout_seconds": float("nan")},
        {"max_cache_bytes": 0},
        {"max_cache_ttl_seconds": True},
    ],
)
def test_invalid_runtime_configuration_fails_locally(kwargs) -> None:
    with pytest.raises(ValueError):
        runtime_module().RedisRuntime(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,limit,window",
    [
        ("", 1, 10),
        (None, 1, 10),
        ("user", 0, 10),
        ("user", True, 10),
        ("user", 1, 0),
        ("user", 1, 1.5),
    ],
)
async def test_invalid_rate_policy_rejected_before_command(scope, limit, window) -> None:
    client = FakeClient()
    runtime = runtime_module().RedisRuntime(enabled=True, client=client)

    with pytest.raises(ValueError):
        await runtime.check_rate_limit(scope, limit=limit, window_seconds=window)
    assert client.calls == []
