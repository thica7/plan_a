"""Final QA explicitly echoes answer IDs and advances complete pending windows."""

import json
from dataclasses import replace

import httpx
import pytest
from test_final_question_reconciliation import QUESTION, reviewed
from test_independent_final_question_qa import (
    independent_case,
    payload_from,
    receipt,
    traced_model_double,
)

from packages.agents.qa import independent_question_review as independent
from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.orchestrator.llm_execution import LLMExecutionMixin


def add_questions(detail, count):
    detail.plan.decision_brief.decision_question = "\n".join(
        QUESTION.replace("Can it purge", f"In scenario {index}, can it purge")
        for index in range(count)
    )


@pytest.mark.asyncio
async def test_explicit_answer_echo_ids_do_not_borrow_visible_local_task_ids(monkeypatch):
    from test_task_projection import projected_case
    from test_writer_question_delivery import service_for

    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.snapshot import current_snapshot

    old_record, audit, _, _ = projected_case()
    service, record = service_for(old_record.detail)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    record.detail.report_md = render_dimension_report(
        record.detail, [audit], snapshot=current_snapshot(record.detail)
    )
    calls = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        calls.append(payload)
        finding = payload["findings"][0]
        context = payload.get("question_contexts", {}).get(finding.get("context_id"), finding)
        assert finding["expected_claim_ids"] == context["answer"]["claim_ids"] == []
        assert context["task_answers"] and context["claims"]
        assert context["task_support_claim_ids"] == [context["claims"][0]["id"]]
        result = json.loads(reviewed(payload, "keep"))
        result["reviews"][0].update(
            finding_fully_addressed=False,
            remaining_gaps=["A supported local task does not complete the whole question."],
        )
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    issues = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1
    output = receipt(record.detail)
    assert output["valid_review_issue_ids"] == output["planned_issue_ids"]
    assert issues and all(issue.severity == "blocker" for issue in issues)


@pytest.mark.asyncio
async def test_current_pass_advances_beyond_two_complete_windows(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    add_questions(detail, 4)
    from packages.agents.qa import question_reconciliation

    monkeypatch.setattr(question_reconciliation, "MAX_FINDINGS", 1)
    calls = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        calls.append(payload)
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    issues = await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    assert len(calls) == 4
    assert len(output["valid_review_issue_ids"]) == 4
    assert output["unsent_issue_ids"] == []
    assert len(issues) == 4  # Changed original questions still need actual answer qualification.


@pytest.mark.asyncio
async def test_resume_prioritizes_unseen_windows_before_failed_paid_attempts(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    add_questions(detail, 3)
    from packages.agents.qa import question_reconciliation

    monkeypatch.setattr(question_reconciliation, "MAX_FINDINGS", 1)
    monkeypatch.setattr(independent, "MAX_REVIEW_BATCHES", 1, raising=False)
    calls = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        calls.append(payload)
        result = json.loads(reviewed(payload))
        if len(calls) == 1:
            result["reviews"][0]["support_digest"] = "0" * 64
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    first = receipt(detail)
    assert len(calls) == 1 and len(first["unsent_issue_ids"]) == 2
    failed = first["sent_issue_ids"][0]
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert calls[1]["findings"][0]["issue_id"] != failed
    assert receipt(detail)["attempts_by_issue_id"][failed] == 1


@pytest.mark.asyncio
async def test_pending_complete_window_keeps_qa_reservation_until_resumed(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    add_questions(detail, 3)
    from packages.agents.qa import question_reconciliation

    monkeypatch.setattr(question_reconciliation, "MAX_FINDINGS", 1)
    monkeypatch.setattr(independent, "MAX_REVIEW_BATCHES", 1, raising=False)

    async def model(record, **kwargs):
        return reviewed(payload_from(kwargs))

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert "final_qa:run" not in service._run_llm_budget(record).delivery_finished
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert "final_qa:run" in service._run_llm_budget(record).delivery_finished


@pytest.mark.asyncio
async def test_new_run_protects_question_review_call_floor_without_raising_global_cap():
    from test_task_delivery_budget import task_service

    service, record = await task_service()
    record.detail.plan.decision_brief.decision_question = "\n".join(
        f"Example Suite: Can guest {index} export a document?" for index in range(3)
    )
    budget = service._run_llm_budget(record)
    assert budget.delivery_call_reserves["final_qa:run"] == 4
    assert (budget.max_calls, budget.max_tokens) == (24, 80000)


@pytest.mark.asyncio
async def test_real_adapter_uses_last_four_calls_and_keeps_cached_reviews(monkeypatch):
    from test_task_delivery_budget import task_service

    detail, service, record = await independent_case(monkeypatch)
    add_questions(detail, 4)
    provider, _ = await task_service()
    service._settings = replace(
        service._settings,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
    )
    service._llm = provider._llm
    record.llm_budget = None
    detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    budget.calls = 20
    budget.delivery_calls["final_qa:run"] = 1
    from packages.agents.qa import question_reconciliation

    monkeypatch.setattr(question_reconciliation, "MAX_FINDINGS", 1)
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    requests = []

    async def post(url, payload, headers):
        batch = payload_from({"user": payload["messages"][1]["content"]})
        requests.append(batch)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": reviewed(batch)}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    service._llm._post_chat_completion = post
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    assert len(requests) == 4 and budget.calls == 24
    assert len(output["valid_review_issue_ids"]) == 4 and output["unsent_issue_ids"] == []
    assert "final_qa:run" in budget.delivery_finished
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(requests) == 4 and budget.calls == 24
    assert detail.llm_budget_checkpoint["calls"] == 24


@pytest.mark.asyncio
async def test_restored_explicit_review_call_floor_is_not_inflated():
    from test_task_delivery_budget import task_service

    service, record = await task_service()
    record.detail.llm_budget_checkpoint = {
        "calls": 10,
        "repairs": 0,
        "tokens_charged": 20000,
        "cost_charged_usd": 0.0,
        "delivery_limit:final_qa:run": 10000,
        "delivery_call_limit:final_qa:run": 1,
    }
    budget = service._run_llm_budget(record)
    assert budget.delivery_call_reserves["final_qa:run"] == 1
    assert budget.max_calls == 24 and budget.tokens_used == 20000


@pytest.mark.asyncio
async def test_complete_review_envelope_fits_its_reserved_global_budget():
    from test_task_delivery_budget import task_service

    service, record = await task_service()
    budget = service._run_llm_budget(record)
    expected = (
        len(independent.INDEPENDENT_SYSTEM.encode())
        + independent.TASK_REVIEW_BYTES
        + 256
        + 1600
        + 2
    )
    assert budget.delivery_reserves["final_qa:run"] >= expected
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    budget.tokens_used = 80000 - budget.delivery_reserves["final_qa:run"]
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    service._llm._post_chat_completion = post
    payload = '{"version":1,"basis_hash":"offline","findings":[]}'
    user = " " * (independent.TASK_REVIEW_BYTES - len(payload.encode())) + payload
    await service._trace_llm_text(
        record,
        agent="qa",
        subagent=None,
        name="final_question_reconciliation",
        system=independent.INDEPENDENT_SYSTEM,
        user=user,
        max_output_tokens=1600,
    )
    assert len(requests) == 1 and budget.tokens_used == 80000
    assert (budget.max_calls, budget.max_tokens) == (24, 80000)


@pytest.mark.asyncio
async def test_new_basis_reopens_pending_review_without_resetting_charges(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(payload_from(kwargs))
        if len(calls) == 2:
            raise TimeoutError("controlled new-basis timeout")
        return reviewed(calls[-1], "keep")

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    budget = service._run_llm_budget(record)
    assert "final_qa:run" in budget.delivery_finished
    budget.tokens_used, budget.calls = 2345, 7
    budget.delivery_charged["final_qa:run"] = 500
    budget.delivery_calls["final_qa:run"] = 1
    service._checkpoint_llm_budget(record, budget)
    detail.report_md += "\nRevision marker.\n"
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert receipt(detail)["resumable_issue_ids"]
    assert "final_qa:run" not in budget.delivery_finished
    assert (budget.tokens_used, budget.calls, budget.delivery_charged["final_qa:run"]) == (
        2345,
        7,
        500,
    )
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 3 and "final_qa:run" in budget.delivery_finished
