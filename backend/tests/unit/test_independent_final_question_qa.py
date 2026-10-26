"""Independent final question QA runs without a successful Reflector."""

import json
import traceback
from dataclasses import replace

import httpx
import pytest
from question_review_fixture import review_payload as decode_review_payload
from test_final_question_reconciliation import QUESTION, reviewed, scope_case

from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.llm.errors import LLMError, LLMExecutionLimitError
from packages.orchestrator.llm_execution import LLMExecutionMixin
from packages.schema.models import TraceSpan


def payload_from(kwargs):
    return decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])


def context_for(payload, row):
    return payload.get("question_contexts", {}).get(row.get("context_id"), row)


def receipt(detail):
    return json.loads(
        next(
            span.full_output
            for span in reversed(detail.trace_spans)
            if span.name == "final_question_reconciliation_receipt"
        )
    )


async def independent_case(monkeypatch):
    detail, service, record = await scope_case(monkeypatch, reflections=False)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    return detail, service, record


def traced_model_double(monkeypatch, service, model):
    """An offline QA double supplies the actual adapter's trace envelope too."""
    async def traced(record, **kwargs):
        status, response, transports = 'error', '', 1
        try:
            response = await model(record, **kwargs)
            status = 'ok'
            return response
        except LLMExecutionLimitError:
            transports = 0
            raise
        finally:
            record.detail.trace_spans.append(TraceSpan(
                id=f'qa-double-{len(record.detail.trace_spans)}', kind='llm', agent='qa',
                name=kwargs['name'], status=status, duration_ms=0,
                full_input=kwargs['system'] + '\n\n' + kwargs['user'], full_output=response,
                metadata={'llm_transport_attempts': transports,
                          'llm_request_attempts': transports},
            ))
    monkeypatch.setattr(service, '_trace_llm_text', traced)


@pytest.mark.asyncio
async def test_no_reflector_still_checks_complete_current_question_and_visible_answer(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        payload = payload_from(kwargs)
        row = payload["findings"][0]
        context = context_for(payload, row)
        assert row["independent_question_check"] is True
        assert context["question"] == QUESTION
        assert context["answer"]["answer"] in context["visible_answer"]
        assert context["claims"][0]["source_span_bindings"]
        assert len(kwargs["user"].encode()) <= 8192
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(calls) == 1
    output = receipt(detail)
    assert output["planned_issue_ids"] == output["sent_issue_ids"]
    assert output["valid_review_issue_ids"] == output["planned_issue_ids"]
    assert output["timeout_issue_ids"] == output["unsent_issue_ids"] == []
    assert output["model_execution"] == "completed"
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_independent_qa_detects_omitted_branch_through_real_qa_entry(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        payload = payload_from(kwargs)
        result = json.loads(reviewed(payload, "keep"))
        result["reviews"][0].update(
            finding_fully_addressed=False,
            remaining_gaps=["The independent second action has no visible answer."],
        )
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    await service._real_qa_step(record)
    assert len(calls) == 1
    independent = [
        issue
        for issue in detail.qa_findings
        if issue.metadata.get("issue_kind") == "independent_final_question"
    ]
    assert len(independent) == 1 and independent[0].severity == "blocker"
    assert "second action" in independent[0].problem


@pytest.mark.asyncio
async def test_timeout_is_receipted_and_can_resume_once_without_permanent_failed_cache(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("controlled final QA timeout")
        return reviewed(payload_from(kwargs))

    traced_model_double(monkeypatch, service, model)
    first = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(first) == 1 and first[0].severity == "blocker"
    output = receipt(detail)
    assert output["sent_issue_ids"] == output["timeout_issue_ids"] == output["planned_issue_ids"]
    assert output["valid_review_issue_ids"] == []
    assert output["unsent_issue_ids"] == []
    assert output["model_execution"] != "completed"
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(calls) == 2
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_admission_rejection_remains_unsent_and_does_not_consume_review_attempt(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise LLMExecutionLimitError("run_llm_call_budget_exhausted")
        return reviewed(payload_from(kwargs))

    traced_model_double(monkeypatch, service, model)
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    output = receipt(detail)
    assert output["sent_issue_ids"] == []
    assert output["unsent_issue_ids"] == output["planned_issue_ids"]
    assert not any(output["attempts_by_issue_id"].values())
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_invalid_or_missing_returns_never_become_valid_and_retries_are_bounded(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        payload = payload_from(kwargs)
        result = json.loads(reviewed(payload))
        result["reviews"][0]["support_digest"] = "0" * 64
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    for _ in range(4):
        assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    assert len(calls) == 2
    output = receipt(detail)
    assert output["valid_review_issue_ids"] == []
    assert set(output["attempts_by_issue_id"].values()) == {2}
    assert output["model_execution"] != "completed"


@pytest.mark.asyncio
async def test_diagnostic_review_cannot_approve_nonvisible_or_unverified_answer(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    answer = detail.report_dimension_audits[0].answer_coverage[0]
    detail.report_md = detail.report_md.replace(answer.answer, "VISIBLE TAMPERED ANSWER")
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        payload = payload_from(kwargs)
        row = payload["findings"][0]
        context = context_for(payload, row)
        assert row["diagnostic_only"] is True
        assert "VISIBLE TAMPERED ANSWER" in context["visible_answer"]
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    result = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1
    assert len(result) == 1 and result[0].severity == "blocker"


@pytest.mark.asyncio
async def test_legacy_no_reflector_still_skips_semantic_question_qa(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    detail.reflections = []

    async def forbidden(*args, **kwargs):
        pytest.fail("Default legacy flow must stay unchanged")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []


@pytest.mark.asyncio
async def test_independent_review_cannot_relabel_a_direct_answer_as_a_safe_limitation(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)

    async def model(record, **kwargs):
        return reviewed(payload_from(kwargs), "current_limitation")

    traced_model_double(monkeypatch, service, model)
    result = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(result) == 1 and result[0].severity == "blocker"
    assert receipt(detail)["passed_question_ids"] == []


@pytest.mark.asyncio
async def test_provider_wrapped_timeout_is_receipted_as_timeout(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)

    async def model(record, **kwargs):
        try:
            raise httpx.ReadTimeout("controlled offline provider timeout")
        except httpx.TimeoutException as exc:
            raise LLMError("LLM request timed out") from exc

    traced_model_double(monkeypatch, service, model)
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    output = receipt(detail)
    assert output["timeout_issue_ids"] == output["sent_issue_ids"] == output["planned_issue_ids"]


@pytest.mark.asyncio
async def test_current_questions_are_scheduled_before_historical_findings(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    original = service._build_reflector_qa_issues(detail)[0]
    issues = [
        original.model_copy(
            update=dict(
                id=f"old-{index}", problem="Q1: " + "condition remains unmet. " * 100 + str(index)
            )
        )
        for index in range(2)
    ]
    calls = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        calls.append(payload)
        if len(calls) == 1:
            assert payload["findings"][0]["independent_question_check"] is True
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, issues, evidence_issues=[])
    output = receipt(detail)
    assert output["planned_issue_ids"][0].startswith("final-question-")
    assert output["planned_issue_ids"][0] in output["valid_review_issue_ids"]


@pytest.mark.asyncio
async def test_partial_legal_response_caches_valid_rows_and_only_resumes_missing_rows(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    original = service._build_reflector_qa_issues(detail)[0]
    issues = [original, original.model_copy(update=dict(id="second-finding"))]
    calls = []
    completed_id = None

    async def model(record, **kwargs):
        nonlocal completed_id
        payload = payload_from(kwargs)
        calls.append(payload)
        response = json.loads(reviewed(payload))
        if len(calls) == 1:
            response["reviews"] = response["reviews"][:1]
            completed_id = response["reviews"][0]["issue_id"]
        else:
            assert completed_id not in {row["issue_id"] for row in payload["findings"]}
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, issues, evidence_issues=[])
    output = receipt(detail)
    assert output["model_execution"] == "partial"
    assert output["valid_review_issue_ids"] == [completed_id]
    assert len(output["model_unreviewed_issue_ids"]) == 2
    assert await reconcile_question_findings(service, record, issues, evidence_issues=[]) == []
    assert len(calls) == 2
    assert receipt(detail)["model_execution"] == "completed"


@pytest.mark.asyncio
async def test_oversized_complete_context_is_unsent_with_explicit_pending_reason(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    from packages.agents.qa import independent_question_review

    monkeypatch.setattr(independent_question_review, "TASK_REVIEW_BYTES", 1)

    async def forbidden(*args, **kwargs):
        pytest.fail("Complete oversized questions must not be truncated and dispatched")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    result = await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    assert output["unsent_issue_ids"] == output["omitted_issue_ids"] == output["planned_issue_ids"]
    assert "context" in output["unreviewed_reasons"][output["planned_issue_ids"][0]].lower()
    assert "context" in result[0].problem.lower()
    assert not any(output["attempts_by_issue_id"].values())


@pytest.mark.asyncio
async def test_all_current_questions_keep_fixed_plan_and_resume_unsent_window(monkeypatch):
    question = "\n".join(
        [
            QUESTION,
            QUESTION.replace("Can it purge", "Under this scenario, can it purge"),
            QUESTION.replace("Can it purge", "With these grants, can it purge"),
        ]
    )
    detail, service, record = await independent_case(monkeypatch)
    detail.plan.decision_brief.decision_question = question
    from packages.agents.qa import question_reconciliation

    monkeypatch.setattr(question_reconciliation, "MAX_FINDINGS", 1)
    calls = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        calls.append(payload)
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    first = await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    assert len(output["planned_issue_ids"]) == 3
    assert len(output["valid_review_issue_ids"]) == 3
    assert len(output["unsent_issue_ids"]) == 0
    assert len(first) == 3  # The edited, unreplayed report remains diagnostic only.
    assert output["model_execution"] == "completed"
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 3
    assert len(calls) == 3
    assert receipt(detail)["model_execution"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_kind", ["outer", "provider_wrapped"])
async def test_actual_timeout_transport_preserves_byte_charge_and_checkpoint_on_resume(
    monkeypatch, timeout_kind
):
    from test_task_delivery_budget import task_service

    detail, service, record = await independent_case(monkeypatch)
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
    service._checkpoint_llm_budget(record, budget)
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    requests = []

    async def post(url, payload, headers):
        batch = decode_review_payload(payload["messages"][1]["content"].split("\nJSON:\n", 1)[1])
        requests.append(batch)
        if len(requests) == 1:
            if timeout_kind == "provider_wrapped":
                raise httpx.ReadTimeout("controlled httpx adapter timeout")
            raise TimeoutError("controlled adapter timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content": reviewed(batch)}}]})

    if timeout_kind == "provider_wrapped":

        async def http_post(client, url, **kwargs):
            return await post(url, kwargs["json"], kwargs["headers"])

        monkeypatch.setattr(httpx.AsyncClient, "post", http_post)
    else:
        monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    assert len(requests) == 1
    assert receipt(detail)["timeout_issue_ids"] == receipt(detail)["sent_issue_ids"]
    checkpoint = dict(detail.llm_budget_checkpoint)
    record.llm_budget = None
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(requests) == 2
    spans = [span for span in detail.trace_spans if span.name == "final_question_reconciliation"]
    assert [span.status for span in spans] == ["error", "ok"]
    assert all(span.metadata["llm_transport_attempts"] == 1 for span in spans)
    charge = sum(len(span.full_input.encode()) + 256 + 1600 for span in spans)
    restored = service._run_llm_budget(record)
    assert checkpoint["calls"] == 1 and checkpoint["tokens_charged"] > 0
    assert restored.calls == 2 and restored.tokens_used == charge and restored.tokens_reserved == 0
    assert (restored.max_calls, restored.max_tokens) == (24, 80000)
    assert receipt(detail)["model_execution"] == "completed"


@pytest.mark.asyncio
async def test_missing_audits_without_candidates_never_report_a_completed_model_review(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    deterministic = service._build_reflector_qa_issues(detail)[0].model_copy(
        update={"id": "missing-report-audits", "detected_by": "schema", "target_agent": "writer"}
    )
    detail.report_dimension_audits = []
    detail.reflections = []

    async def forbidden(*args, **kwargs):
        pytest.fail("A missing audit must preserve its deterministic blocker without a model call")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    result = await reconcile_question_findings(service, record, [deterministic], evidence_issues=[])
    output = receipt(detail)
    assert result == [deterministic]
    assert output["planned_issue_ids"] == output["valid_review_issue_ids"] == []
    assert output["model_execution"] == "not_requested"
    assert output["passed_question_ids"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_retries", [0, 2])
async def test_paid_attempt_limit_caps_actual_provider_retries_and_remaining_resume(
    monkeypatch, initial_retries
):
    from test_task_delivery_budget import task_service

    detail, service, record = await independent_case(monkeypatch)
    provider, _ = await task_service()
    provider._llm._settings = replace(provider._llm._settings, llm_max_retries=initial_retries)
    service._settings = replace(
        service._settings,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
        llm_max_retries=initial_retries,
    )
    service._llm = provider._llm
    record.llm_budget = None
    detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        return httpx.Response(503, text="controlled persistent offline unavailability")

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    assert len(requests) == min(initial_retries + 1, 2)
    provider._llm._settings = replace(provider._llm._settings, llm_max_retries=2)
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    assert len(requests) == 2
    assert len(await reconcile_question_findings(service, record, [], evidence_issues=[])) == 1
    assert len(requests) == 2
    output = receipt(detail)
    assert set(output["attempts_by_issue_id"].values()) == {2}
    assert output["valid_review_issue_ids"] == []
    assert output["model_execution"] == "unavailable"
    spans = [span for span in detail.trace_spans if span.name == "final_question_reconciliation"]
    assert sum(span.metadata["llm_transport_attempts"] for span in spans) == 2
    assert sum(span.metadata["llm_request_attempts"] for span in spans) == 2
    expected_charge = sum(
        (len(span.full_input.encode()) + 256 + 1600) * span.metadata["llm_request_attempts"]
        for span in spans
    )
    assert budget.tokens_used == expected_charge and budget.tokens_reserved == 0
    assert budget.calls == 2 and (budget.max_calls, budget.max_tokens) == (24, 80000)
    assert service._llm._settings.llm_max_retries == 2


@pytest.mark.asyncio
async def test_preserved_provider_timeout_cause_never_exposes_raw_provider_credentials(monkeypatch):
    from test_task_delivery_budget import task_service

    service, _ = await task_service()
    provider_key = service._llm._settings.ark_api_key

    async def http_post(client, url, **kwargs):
        raise httpx.ReadTimeout(f"Controlled provider failure included {provider_key}")

    monkeypatch.setattr(httpx.AsyncClient, "post", http_post)
    with pytest.raises(LLMError) as captured:
        await service._llm.complete_text(system="offline", user="offline")
    formatted = "".join(traceback.format_exception(captured.value))
    assert provider_key not in formatted
    cause = captured.value
    found_timeout = False
    while cause is not None:
        found_timeout = found_timeout or isinstance(cause, httpx.ReadTimeout)
        cause = cause.__cause__
    assert found_timeout


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["budget_rejected", "fallback_unavailable", "fallback_valid"])
async def test_real_adapter_retains_any_timeout_across_later_failure_or_success(
    monkeypatch, outcome
):
    from test_task_delivery_budget import task_service

    detail, service, record = await independent_case(monkeypatch)
    provider, _ = await task_service()
    provider._llm._settings = replace(
        provider._llm._settings,
        llm_max_retries=2 if outcome == "budget_rejected" else 0,
        backup_llm_api_key="offline-backup" if outcome != "budget_rejected" else "",
        backup_llm_model="offline-backup" if outcome != "budget_rejected" else "",
        backup_llm_base_url="https://backup.example.invalid",
    )
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
    if outcome == "budget_rejected":
        budget.calls = 23
        # All but one of the protected final-QA calls already happened.
        budget.delivery_calls["final_qa:run"] = (
            budget.delivery_call_reserves["final_qa:run"] - 1
        )
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    requests = []

    async def http_post(client, url, **kwargs):
        batch = decode_review_payload(
            kwargs["json"]["messages"][1]["content"].split("\nJSON:\n", 1)[1])
        requests.append(batch)
        if len(requests) == 1:
            raise httpx.ReadTimeout("controlled first-provider timeout")
        if outcome == "fallback_valid":
            return httpx.Response(
                200, json={"choices": [{"message": {"content": reviewed(batch)}}]}
            )
        return httpx.Response(503, text="controlled fallback failure")

    monkeypatch.setattr(httpx.AsyncClient, "post", http_post)
    result = await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    assert len(requests) == (1 if outcome == "budget_rejected" else 2)
    assert output["timeout_issue_ids"] == output["sent_issue_ids"] == output["planned_issue_ids"]
    assert set(output["attempts_by_issue_id"].values()) == {len(requests)}
    span = next(
        span
        for span in reversed(detail.trace_spans)
        if span.name == "final_question_reconciliation"
    )
    assert span.metadata["llm_timeout_attempts"] == 1
    assert span.metadata["llm_transport_attempts"] == len(requests)
    if outcome == "fallback_valid":
        assert result == [] and output["model_execution"] == "completed"
        assert output["valid_review_issue_ids"] == output["planned_issue_ids"]
        assert output["unresolved_timeout_issue_ids"] == []
        assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
        assert receipt(detail)["timeout_issue_ids"] == output["timeout_issue_ids"]
        assert len(requests) == 2
    else:
        assert len(result) == 1 and output["model_execution"] != "completed"
        assert output["valid_review_issue_ids"] == []
        assert output["unresolved_timeout_issue_ids"] == output["planned_issue_ids"]
