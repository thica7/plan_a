import httpx
import pytest

from packages.config import Settings
from packages.llm import DoubaoClient, LLMError, LLMUsage


def _settings(**overrides: object) -> Settings:
    values = {
        "demo_mode": True,
        "ark_api_key": "primary-key",
        "ark_model": "primary-model",
        "ark_base_url": "https://ark.example/api/v3",
        "llm_timeout_seconds": 10,
        "llm_temperature": 0.2,
        "llm_max_retries": 0,
        "llm_retry_backoff_seconds": 0.0,
    }
    values.update(overrides)
    return Settings(**values)


def test_extract_json_accepts_trailing_text_after_first_object() -> None:
    client = DoubaoClient(
        _settings()
    )

    payload = client._extract_json('{"ok": true}\n{"extra": false}')

    assert payload == {"ok": True}


def test_parse_usage_records_provider_tokens() -> None:
    client = DoubaoClient(
        _settings()
    )

    usage = client._parse_usage({"prompt_tokens": 11, "completion_tokens": "7", "total_tokens": 18})

    assert usage == LLMUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18)


@pytest.mark.asyncio
async def test_complete_text_falls_back_to_backup_provider(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            calls.append((url, str(json["model"])))
            if len(calls) == 1:
                return httpx.Response(500, text="primary unavailable")
            assert headers["Authorization"] == "Bearer backup-key"
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "backup ok"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                },
            )

    monkeypatch.setattr("packages.llm.doubao_client.httpx.AsyncClient", FakeAsyncClient)
    client = DoubaoClient(
        _settings(
            backup_llm_api_key="backup-key",
            backup_llm_base_url="https://openrouter.example/api/v1",
            backup_llm_model="backup-model",
        )
    )

    content = await client.complete_text(system="system", user="user")

    assert content == "backup ok"
    assert calls == [
        ("https://ark.example/api/v3/chat/completions", "primary-model"),
        ("https://openrouter.example/api/v1/chat/completions", "backup-model"),
    ]
    assert client.last_provider() == "backup"
    assert client.last_model() == "backup-model"
    route = client.last_route_decision()
    assert route is not None
    assert route.status == "selected"
    assert route.selected is not None
    assert route.selected.provider_kind == "primary"
    assert route.fallback is not None
    assert route.fallback.provider_kind == "backup"
    assert client.consume_last_usage() == LLMUsage(
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
    )


@pytest.mark.asyncio
async def test_complete_text_retries_retryable_status_before_failing_over(monkeypatch) -> None:
    calls = 0

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "retry ok"}}]},
            )

    monkeypatch.setattr("packages.llm.doubao_client.httpx.AsyncClient", FakeAsyncClient)
    client = DoubaoClient(_settings(llm_max_retries=1))

    content = await client.complete_text(system="system", user="user")

    assert content == "retry ok"
    assert calls == 2
    assert client.last_provider() == "doubao"


@pytest.mark.asyncio
async def test_complete_text_does_not_retry_non_retryable_status(monkeypatch) -> None:
    calls = 0

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(401, text="bad key")

    monkeypatch.setattr("packages.llm.doubao_client.httpx.AsyncClient", FakeAsyncClient)
    client = DoubaoClient(_settings(llm_max_retries=2))

    with pytest.raises(LLMError, match="401"):
        await client.complete_text(system="system", user="user")

    assert calls == 1


@pytest.mark.asyncio
async def test_complete_json_falls_back_when_primary_returns_invalid_json(monkeypatch) -> None:
    calls = 0

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            nonlocal calls
            calls += 1
            content = "not json" if calls == 1 else '{"ok": true}'
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("packages.llm.doubao_client.httpx.AsyncClient", FakeAsyncClient)
    client = DoubaoClient(
        _settings(
            backup_llm_api_key="backup-key",
            backup_llm_base_url="https://openrouter.example/api/v1",
            backup_llm_model="backup-model",
        )
    )

    payload = await client.complete_json(system="system", user="user", schema_hint='{"ok": bool}')

    assert payload == {"ok": True}
    assert calls == 2
    assert client.last_provider() == "backup"


@pytest.mark.asyncio
async def test_complete_text_uses_backup_first_when_route_selects_backup(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            calls.append((url, str(json["model"])))
            assert headers["Authorization"] == "Bearer backup-key"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "backup only"}}]},
            )

    monkeypatch.setattr("packages.llm.doubao_client.httpx.AsyncClient", FakeAsyncClient)
    client = DoubaoClient(
        _settings(
            ark_api_key=None,
            ark_model=None,
            backup_llm_api_key="backup-key",
            backup_llm_base_url="https://openrouter.example/api/v1",
            backup_llm_model="backup-model",
        )
    )

    content = await client.complete_text(system="system", user="user")

    assert content == "backup only"
    assert calls == [("https://openrouter.example/api/v1/chat/completions", "backup-model")]
    route = client.last_route_decision()
    assert route is not None
    assert route.status == "fallback"
    assert route.selected is not None
    assert route.selected.provider_kind == "backup"


@pytest.mark.asyncio
async def test_complete_text_blocks_when_model_router_policy_blocks(monkeypatch) -> None:
    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> httpx.Response:
            raise AssertionError("Blocked model routes must not call the provider.")

    monkeypatch.setattr("packages.llm.doubao_client.httpx.AsyncClient", FakeAsyncClient)
    client = DoubaoClient(_settings(compliance_redaction_enabled=False))

    with pytest.raises(LLMError, match="LLM model route blocked"):
        await client.complete_text(system="system", user="user")

    route = client.last_route_decision()
    assert route is not None
    assert route.status == "blocked"
    assert "redaction" in " ".join(route.blocked_reasons)
