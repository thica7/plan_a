"""Final QA batching preserves transport, budget, and cache provenance."""

import json
from dataclasses import replace

import httpx
import pytest
from test_final_question_reconciliation import reviewed, scope_case
from test_task_delivery_budget import task_service

from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.orchestrator.llm_execution import LLMExecutionMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("second_batch", ["valid", "foreign", "unavailable"])
async def test_two_batches_use_real_admission_and_cache_without_new_transport(
    monkeypatch, second_batch
):
    detail, service, record = await scope_case(monkeypatch)
    provider_service, _ = await task_service()
    service._settings = replace(
        service._settings,
        writer_task_execution_enabled=True,
        llm_max_output_tokens=1600,
        run_llm_max_tokens=80000,
        run_llm_max_calls=24,
    )
    service._llm = provider_service._llm
    # The Writer fixture already finished under its own legacy budget. Start
    # the isolated final-QA replay with the limits selected above.
    record.llm_budget = None
    record.detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    assert budget.max_calls == 24 and budget.max_tokens == 80000
    # scope_case mocks Writer calls; final QA exercises the actual trace,
    # admission, provider adapter, and conservative usage accounting paths.
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    original = service._build_reflector_qa_issues(detail)[0]
    issues = [
        original.model_copy(
            update={
                "id": f"issue-{index}",
                "problem": "Q1: " + "condition remains unmet. " * 100 + str(index),
            }
        )
        for index in range(2)
    ]
    requests = []
    first_response = None

    async def post(url, payload, headers):
        nonlocal first_response
        user = payload["messages"][1]["content"]
        batch = json.loads(user.split("\nJSON:\n", 1)[1])
        requests.append(batch)
        assert len(user.encode()) <= 6000
        assert [row["issue_id"] for row in batch["findings"]] == [f"issue-{len(requests) - 1}"]
        response = reviewed(batch)
        if len(requests) == 1:
            first_response = response
        elif second_batch == "foreign":
            response = first_response
        elif second_batch == "unavailable":
            return httpx.Response(503, text="Controlled offline unavailability")
        # Deliberately omit usage: each attempted request must retain its full
        # byte-bound input plus output reservation, including the failed batch.
        return httpx.Response(200, json={"choices": [{"message": {"content": response}}]})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await reconcile_question_findings(service, record, issues, evidence_issues=[])
    expected_kept = [] if second_batch == "valid" else ["issue-1"]
    assert [issue.id for issue in result] == expected_kept
    assert len(requests) == 2
    spans = [span for span in detail.trace_spans if span.name == "final_question_reconciliation"]
    assert len(spans) == 2
    assert [span.status for span in spans] == [
        "ok",
        "error" if second_batch == "unavailable" else "ok",
    ]
    assert all(span.metadata["llm_transport_attempts"] == 1 for span in spans)
    assert all(span.metadata["llm_request_attempts"] == 1 for span in spans)
    assert all(span.metadata["llm_phase"] == "final_qa:run" for span in spans)
    conservative_charge = sum(
        len(span.full_input.encode()) + 256 + span.metadata["llm_max_output_tokens"]
        for span in spans
    )
    assert sum(span.metadata["llm_tokens_charged"] for span in spans) == conservative_charge
    assert service._run_llm_budget(record) is budget
    assert budget.tokens_used == conservative_charge
    assert budget.calls == 2 and budget.tokens_reserved == 0
    assert budget.max_calls == 24 and budget.max_tokens == 80000
    assert budget.tokens_used <= budget.max_tokens
    receipt = json.loads(detail.trace_spans[-1].full_output)
    assert receipt["planned_batches"] == 2
    assert receipt["unsent_issue_ids"] == []
    assert [row["issue_id"] for row in receipt["model_review"]["reviews"]] == (
        ["issue-0", "issue-1"] if second_batch == "valid" else ["issue-0"]
    )

    cached_result = await reconcile_question_findings(service, record, issues, evidence_issues=[])
    assert [issue.id for issue in cached_result] == expected_kept
    assert len(requests) == 2
    assert (
        len([span for span in detail.trace_spans if span.name == "final_question_reconciliation"])
        == 2
    )
    assert budget.calls == 2 and budget.tokens_used == conservative_charge
    assert budget.tokens_reserved == 0
