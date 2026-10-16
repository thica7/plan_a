import asyncio
import json
from types import SimpleNamespace

from packages.infrastructure import redis_acceptance


def test_preview_never_initializes_runtime(monkeypatch, capsys):
    def forbidden(**kwargs):
        raise AssertionError("preview must not connect")

    monkeypatch.setattr(redis_acceptance, "RedisRuntime", forbidden)
    assert redis_acceptance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False


def test_live_probe_uses_unique_namespace_ttl_and_real_adapter_contract(monkeypatch):
    namespaces = []

    class Runtime:
        def __init__(self, **kwargs):
            namespaces.append(kwargs["namespace"])
            self.value = None
            self.count = 0

        async def ping(self):
            return True

        def cache_key(self, *parts):
            return "probe"

        async def set_json(self, key, value, *, ttl_seconds):
            assert ttl_seconds == 1
            self.value = value
            return True

        async def get_json(self, key):
            return self.value

        async def check_rate_limit(self, scope, *, limit, window_seconds):
            self.count += 1
            return SimpleNamespace(
                allowed=self.count <= limit, retry_after_seconds=0 if self.count <= limit else 1
            )

        async def aclose(self):
            pass

    async def elapsed(seconds):
        assert seconds > 1
        runtime_instances[-1].value = None

    runtime_instances = []

    def factory(**kwargs):
        value = Runtime(**kwargs)
        runtime_instances.append(value)
        return value

    monkeypatch.setattr(redis_acceptance, "RedisRuntime", factory)
    monkeypatch.setattr(redis_acceptance, "sleep", elapsed)
    for _ in range(2):
        report = asyncio.run(redis_acceptance.verify("redis://localhost:6379/0"))
        assert report["executed"] is True and report["allowed"] == 10
        assert report["denied"] == 10 and report["ttl_expired"] is True
    assert len(set(namespaces)) == 2
