"""Final QA batching preserves transport, budget, and cache provenance."""

import json
from dataclasses import replace

import httpx
import pytest
from question_review_fixture import review_payload as decode_review_payload
from test_final_question_reconciliation import QUESTION, finding_context, reviewed, scope_case
from test_task_delivery_budget import task_service

from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.orchestrator.llm_execution import LLMExecutionMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("second_batch", ["valid", "foreign", "unavailable"])
async def test_complete_context_batches_use_real_admission_and_bounded_partial_cache_resume(
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
    failed_batch_ids = []
    question_id = detail.report_dimension_audits[0].answer_coverage[0].question_id
    independent_id = f"final-question-{question_id}"

    async def post(url, payload, headers):
        nonlocal first_response
        user = payload["messages"][1]["content"]
        batch = decode_review_payload(user.split("\nJSON:\n", 1)[1])
        requests.append(batch)
        assert len(user.encode()) <= 8192
        batch_ids = [row["issue_id"] for row in batch["findings"]]
        assert batch_ids and set(batch_ids) <= {independent_id, "issue-0", "issue-1"}
        for row in batch["findings"]:
            context = finding_context(batch, row)
            assert context["question"] == QUESTION
            assert context["request_context"]["parents"][0]["text"] == QUESTION
        response = reviewed(batch)
        if len(requests) == 1:
            first_response = response
        if "issue-1" in batch_ids and second_batch != "valid":
            failed_batch_ids[:] = batch_ids
            if second_batch == "foreign":
                response = first_response
            else:
                return httpx.Response(503, text="Controlled offline unavailability")
        # Deliberately omit usage: each attempted request must retain its full
        # byte-bound input plus output reservation, including the failed batch.
        return httpx.Response(200, json={"choices": [{"message": {"content": response}}]})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await reconcile_question_findings(service, record, issues, evidence_issues=[])
    expected_kept = [] if second_batch == "valid" else ["issue-1"]
    assert [issue.id for issue in result] == expected_kept
    # The readable named question context keeps all same-question findings whole.
    initial_calls = 3 if second_batch == "foreign" else 2
    assert len(requests) == initial_calls
    assert [row["issue_id"] for batch in requests for row in batch["findings"]] == [
        independent_id, "issue-0", "issue-1"] + (["issue-1"] if second_batch == "foreign" else [])
    spans = [span for span in detail.trace_spans if span.name == "final_question_reconciliation"]
    assert len(spans) == initial_calls
    assert [span.status for span in spans] == [
        "ok",
        "error" if second_batch == "unavailable" else "ok",
    ] + (["ok"] if second_batch == "foreign" else [])
    complete = json.loads(detail.trace_spans[-1].full_input)['findings']
    expected = {row['issue_id']: row for row in complete}
    from packages.agents.qa.independent_question_review import INDEPENDENT_SYSTEM
    from packages.agents.qa.question_review_transport import dumps, final_review_batches, loads
    for span, batch in zip(spans, requests, strict=True):
        wire = loads(span.full_input.split('\nJSON:\n', 1)[1])
        rebuilt, omitted = final_review_batches(
            [expected[row['issue_id']] for row in batch['findings']],
            batch['basis_hash'], max_bytes=8192, max_batches=1)
        assert not omitted and wire == rebuilt[0]
        assert span.full_input == INDEPENDENT_SYSTEM + '\n\n\nJSON:\n' + dumps(wire)
        assert all(row == expected[row['issue_id']] for row in batch['findings'])
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
    assert budget.calls == initial_calls and budget.tokens_reserved == 0
    assert budget.max_calls == 24 and budget.max_tokens == 80000
    assert budget.tokens_used <= budget.max_tokens
    receipt = json.loads(detail.trace_spans[-1].full_output)
    assert receipt["planned_batches"] == initial_calls
    assert receipt["unsent_issue_ids"] == []
    assert [row["issue_id"] for row in receipt["model_review"]["reviews"]] == (
        [independent_id, "issue-0", "issue-1"]
        if second_batch == "valid" else [independent_id, "issue-0"]
    )
    assert receipt['model_execution'] == ('completed' if second_batch == 'valid' else 'partial')

    cached_result = await reconcile_question_findings(service, record, issues, evidence_issues=[])
    assert [issue.id for issue in cached_result] == expected_kept
    expected_calls = 2 if second_batch == 'valid' else 3
    assert len(requests) == expected_calls
    if second_batch != 'valid':
        assert [row['issue_id'] for row in requests[-1]['findings']] == failed_batch_ids
        assert failed_batch_ids == ['issue-1']
    assert (
        len([span for span in detail.trace_spans if span.name == "final_question_reconciliation"])
        == expected_calls
    )
    spans = [span for span in detail.trace_spans if span.name == 'final_question_reconciliation']
    conservative_charge = sum(
        len(span.full_input.encode()) + 256 + span.metadata['llm_max_output_tokens']
        for span in spans)
    assert budget.calls == expected_calls and budget.tokens_used == conservative_charge
    assert budget.tokens_reserved == 0
    final_result = await reconcile_question_findings(service, record, issues, evidence_issues=[])
    assert final_result == cached_result
    assert len(requests) == expected_calls  # No third paid attempt for an unsuccessful finding.
