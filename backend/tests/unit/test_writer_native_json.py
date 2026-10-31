"""Native JSON mode is opt-in, raw, and part of the actual transport."""

import httpx
import pytest
from test_llm_client import _settings

from packages.llm import DoubaoClient, LLMError


@pytest.mark.asyncio
async def test_native_json_sends_http_mode_and_returns_exact_raw(monkeypatch):
    client = DoubaoClient(_settings(llm_provider_name="deepseek"))
    raw = ' {"value": 2} \n'

    async def post(url, payload, headers):
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": raw}}]})

    monkeypatch.setattr(client, "_post_chat_completion", post)
    assert (
        await client.complete_text(system="Return JSON", user="JSON", response_format="json_object")
        == raw
    )
    assert client.last_raw_response() == raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,finish",
    [
        ('{"a":1} {"b":2}', "stop"),
        ('{"a":1,"a":2}', "stop"),
        (" ", "stop"),
        ('{"a":', "length"),
    ],
)
async def test_native_json_rejects_malformed_blank_and_length_preserving_raw(
    monkeypatch, raw, finish
):
    client = DoubaoClient(_settings(llm_provider_name="deepseek"))

    async def post(url, payload, headers):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": raw},
                        "finish_reason": finish,
                    }
                ]
            },
        )

    monkeypatch.setattr(client, "_post_chat_completion", post)
    with pytest.raises(LLMError):
        await client.complete_text(system="JSON", user="JSON", response_format="json_object")
    assert client.last_raw_response() == raw


@pytest.mark.asyncio
async def test_native_json_unsupported_provider_does_not_send_or_fall_back(monkeypatch):
    client = DoubaoClient(_settings())

    async def post(*args):
        pytest.fail("unsupported mode must not reach transport")

    monkeypatch.setattr(client, "_post_chat_completion", post)
    with pytest.raises(LLMError, match="JSON|json"):
        await client.complete_text(system="JSON", user="JSON", response_format="json_object")


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,finish", [(" ", "stop"), ('{"valid":true}', "length")])
async def test_real_budget_wrapper_preserves_failed_native_raw_with_timeout_task(
    monkeypatch, raw, finish
):
    from test_execution_limits import _service

    service, record = await _service(
        llm_provider_name="deepseek", run_llm_max_tokens=240000, llm_max_retries=0
    )

    async def post(url, payload, headers):
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": raw}, "finish_reason": finish}]}
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    with pytest.raises(LLMError):
        await service._trace_llm_text(
            record,
            agent="writer",
            subagent="Example/feature",
            name="test_native_json",
            system="Return JSON",
            user="JSON",
            timeout_seconds=10,
            max_request_attempts=1,
            response_format="json_object",
            response_contract="writer-task-json-v1",
        )
    span = record.detail.trace_spans[-1]
    assert span.status == "error" and span.full_output == raw
    assert span.metadata["response_format"] == "json_object"
    assert span.metadata["response_contract"] == "writer-task-json-v1"
