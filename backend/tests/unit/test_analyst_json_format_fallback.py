"""One-shot format failures preserve original evidence and explicit degradation."""

from datetime import UTC, datetime

import httpx
import pytest
from test_execution_limits import _service

from packages.llm.errors import LLMError
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.schema.models import RawSource


async def anonymous_service():
    service, record = await _service(
        analyst_react_enabled=False, llm_max_retries=0, llm_max_output_tokens=2048
    )
    detail = record.detail
    detail.plan.competitors = ["Example Suite"]
    detail.plan.dimensions = ["feature"]
    quote = "Guests must sign in before accessing individually invited documents."
    now = datetime.now(UTC)
    detail.raw_sources = [
        RawSource(
            id="anonymous-original",
            competitor="Example Suite",
            dimension="feature",
            source_type="official_docs",
            title="Original access rule",
            url="https://example.invalid/access",
            snippet=quote,
            content_hash="original-content",
            confidence=0.9,
            extracted_at=now,
            metadata={
                "source_material_level": "full_source",
                "last_verified_at": now.isoformat(),
                "normalized_fields": [
                    {
                        "kind": "feature",
                        "competitor": "Example Suite",
                        "dimension": "feature",
                        "slot": "access-rule",
                        "support_level": "documented",
                        "confidence": 0.9,
                        "evidence_terms": [quote],
                        "evidence_quote": quote,
                        "evidence_item_ids": ["anonymous-observation"],
                    }
                ],
            },
        )
    ]
    return service, record, quote


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"feature_tree":{"summary_claims":[{"claim":"unfinished"',
        '{"feature_tree": {invalid}}',
        "The response did not produce a JSON object.",
    ],
)
async def test_actual_provider_format_error_uses_one_source_bound_fallback_without_retry(content):
    service, record, quote = await anonymous_service()
    requests = []

    async def malformed(url, payload, headers):
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 2048},
            },
        )

    service._llm._post_chat_completion = malformed
    await service._real_analyst_branch_step(record, "feature", "Example Suite")
    assert len(requests) == 1 and requests[0]["max_tokens"] == 2048
    claims = record.detail.competitor_knowledge["Example Suite"].feature_tree.summary_claims
    assert claims and all(claim.source_ids == ["anonymous-original"] for claim in claims)
    assert all(quote in claim.claim for claim in claims)
    completed = next(
        event
        for event in reversed(record.events)
        if event.type == "node_completed" and event.agent == "analyst"
    )
    assert completed.payload["module_status"] == "fallback"
    assert completed.payload["fallback"]["used"] is True
    assert "llm_json_format_error" in completed.payload["fallback"]["reason"]
    assert "analysis_timeout" not in completed.payload["react"]
    spans = [span for span in record.detail.trace_spans if span.kind == "llm"]
    assert len(spans) == 1 and spans[0].status == "error"
    assert spans[0].metadata["llm_transport_attempts"] == 1
    assert record.detail.evidence_consumptions[0].status == "validated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        LLMError("LLM request failed with 401: Unauthorized"),
        LLMError(
            "LLM JSON request failed for all providers: anonymous: "
            "LLM request failed with 403: Forbidden"
        ),
        LLMError("LLM model route blocked: restricted provider"),
        LLMError("ARK_API_KEY and ARK_MODEL are required for real execution mode."),
        LLMError(
            "LLM JSON request failed for all providers: first: "
            "Expecting ',' delimiter: line 2 column 1 (char 10) | "
            "second: LLM request failed with 401: Unauthorized"
        ),
        EvidenceUseRejectedError("evidence dependencies changed"),
    ],
)
async def test_auth_config_mixed_provider_and_evidence_errors_are_not_hidden_by_fallback(error):
    service, record, _ = await anonymous_service()
    calls = []

    async def rejected(*args, **kwargs):
        calls.append(True)
        raise error

    service._trace_llm_json = rejected
    with pytest.raises(type(error)) as caught:
        await service._real_analyst_branch_step(record, "feature", "Example Suite")
    assert caught.value is error and calls == [True]
    assert record.detail.competitor_knowledge == {}
    assert not any(
        event.type == "node_completed" and event.agent == "analyst" for event in record.events
    )


@pytest.mark.asyncio
async def test_missing_admitted_sources_skip_instead_of_fabricating_a_fallback():
    service, record, _ = await anonymous_service()
    record.detail.raw_sources = []

    async def forbidden(*args, **kwargs):
        pytest.fail("a source-free branch must not call a model")

    service._trace_llm_json = forbidden
    await service._real_analyst_branch_step(record, "feature", "Example Suite")
    completed = next(
        event
        for event in reversed(record.events)
        if event.type == "node_completed" and event.agent == "analyst"
    )
    assert completed.payload["module_status"] == "skipped"
    assert completed.payload["execution_reason"] == "no_accepted_evidence"
    assert record.detail.competitor_knowledge == {}
