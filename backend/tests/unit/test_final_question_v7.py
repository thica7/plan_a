"""V7 isolates malformed rows while retaining exact transport and budget gates."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from test_final_question_reconciliation import reviewed
from test_independent_final_question_qa import (
    independent_case,
    payload_from,
    receipt,
    traced_model_double,
)
from test_remaining_question_review import add_questions
from test_task_delivery_budget import task_service

from packages.agents.qa import independent_question_review as qa
from packages.agents.qa.question_reconciliation import _review_response, reconcile_question_findings
from packages.orchestrator.llm_execution import LLMExecutionMixin


def parser():
    from packages.agents.qa.independent_review_response import parse_response

    return parse_response


def response_case():
    candidates = {
        key: dict(issue_id=key, question_id="q1", support_digest=str(index) * 64,
                  answer={"claim_ids": ["claim"]})
        for index, key in enumerate(("good", "bad", "keep"), 1)
    }
    response = json.loads(reviewed(dict(basis_hash="basis", findings=list(candidates.values()))))
    response["reviews"][2].update(disposition="keep", finding_fully_addressed=False,
                                  remaining_gaps=["Real unresolved branch."])
    return candidates, response


@pytest.mark.parametrize("mutation", ["digest", "type", "extra", "identity", "claim_ids"])
def test_row_failure_preserves_two_valid_rows_and_real_negative(mutation):
    candidates, response = response_case()
    bad = response["reviews"][1]
    if mutation == "digest":
        bad["support_digest"] += "0"
    elif mutation == "type":
        bad["finding_fully_addressed"] = "true"
    elif mutation == "extra":
        bad["invented"] = True
    elif mutation == "identity":
        bad["question_id"] = "q2"
    else:
        bad["claim_ids"] = ["other"]
    result = parser()(json.dumps(response), "basis", candidates)
    assert list(result.reviews) == ["good", "keep"]
    assert result.reviews["keep"].disposition == "keep"
    assert result.invalid_issue_ids == ["bad"] and result.missing_issue_ids == []


@pytest.mark.parametrize("mutation", ["version", "boolean_version", "basis", "extra", "dict",
    "too_many", "duplicate", "foreign", "duplicate_key", "nan", "row_key"])
def test_ambiguous_or_wrong_envelope_rejects_whole_batch(mutation):
    candidates, response = response_case()
    if mutation in {"version", "boolean_version", "basis", "extra"}:
        key, value = {"version": ("version", 2), "boolean_version": ("version", True),
                      "basis": ("basis_hash", "wrong"), "extra": ("extra", 1)}[mutation]
        response[key] = value
    elif mutation == "dict":
        response["reviews"] = {}
    elif mutation == "too_many":
        response["reviews"] *= 4
    elif mutation == "duplicate":
        response["reviews"][1]["issue_id"] = "good"
    elif mutation == "foreign":
        response["reviews"][1]["issue_id"] = "outside-batch"
    raw = json.dumps(response)
    if mutation == "duplicate_key":
        raw = raw.replace('"version": 1', '"version": 1, "version": 1', 1)
    elif mutation == "nan":
        raw = raw.replace('"finding_fully_addressed": true', '"finding_fully_addressed": NaN', 1)
    elif mutation == "row_key":
        raw = raw.replace('"issue_id": "good"', '"issue_id": "good", "issue_id": "good"', 1)
    with pytest.raises(ValueError):
        parser()(raw, "basis", candidates)


def test_missing_rows_are_distinct_from_invalid_rows():
    candidates, response = response_case()
    response["reviews"] = response["reviews"][:1]
    result = parser()(json.dumps(response), "basis", candidates)
    assert result.invalid_issue_ids == []
    assert result.missing_issue_ids == ["bad", "keep"]


def test_original_bitwarden_bad_digest_keeps_three_authentic_decisions():
    fixture = json.loads((Path(__file__).parent / "fixtures/qa_v7_bitwarden_bad_digest.json")
                        .read_text())
    assert (hashlib.sha256(fixture["response"].encode()).hexdigest()
            == fixture["source_output_sha256"])
    result = parser()(fixture["response"], fixture["basis_hash"], fixture["candidates"])
    assert [r.disposition for r in result.reviews.values()] == [
        "current_limitation", "keep", "keep"]
    assert result.invalid_issue_ids == ["qc-issue-6633afe79b837c6e"]
    assert result.missing_issue_ids == []
    # Explicit v6 replay keeps the historical all-or-nothing parser.
    with pytest.raises(ValueError):
        _review_response(fixture["response"], fixture["basis_hash"])


def test_protocol_and_legacy_system_are_frozen_without_ignored_artifacts():
    assert qa.PROTOCOL == "independent_questions_v7"
    assert hashlib.sha256(qa.INDEPENDENT_SYSTEM_V6.encode()).hexdigest() == (
        "077d6cffe1ace86417e94cb16baa4747ca081d285dc2a3f17ed70c2f931fae43")
    assert qa.INDEPENDENT_SYSTEM.startswith("Independent final question QA v7.")
    assert "background date" in qa.INDEPENDENT_SYSTEM
    assert "explicitly date-qualified" in qa.INDEPENDENT_SYSTEM
    assert "diagnostic_only must always keep" in qa.INDEPENDENT_SYSTEM
    assert qa.TASK_REVIEW_BYTES == 8192 and qa.MAX_REVIEW_OUTPUT_TOKENS == 1600
    assert qa.FINAL_QA_REQUEST_RESERVE == (
        len(qa.INDEPENDENT_SYSTEM.encode()) + 8192 + 256 + 1600 + 2)


async def three_findings(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    original = service._build_reflector_qa_issues(detail)
    # The independent fixture has no Reflector, so use its normal historical issue shape.
    if not original:
        from packages.schema.models import QCIssue, RedoScope

        qid = detail.report_dimension_audits[0].answer_coverage[0].question_id
        original = [QCIssue(id="history", severity="blocker", detected_by="reflector",
            target_agent="writer", target_competitor="Example Product", problem=qid + ": Review.",
            field_path="answer_coverage", metadata={"question_id": qid},
            redo_scope=RedoScope(kind="writer_only", rationale="review"))]
    return detail, service, record, [original[0].model_copy(update={"id": key})
                                   for key in ("bad-history", "keep-history")]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_kind", ["schema", "missing", "identity"])
async def test_real_adapter_retries_only_bad_rows_and_replays_transport_bound_cache(
    monkeypatch, bad_kind
):
    detail, service, record, issues = await three_findings(monkeypatch)
    provider, _ = await task_service()
    service._settings = replace(service._settings, run_llm_max_calls=24, run_llm_max_tokens=80000,
                                llm_max_output_tokens=1600)
    service._llm = provider._llm
    record.llm_budget = None
    detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service))
    calls = []

    async def post(url, request, headers):
        assert request["messages"][0]["content"] == qa.INDEPENDENT_SYSTEM
        assert request["max_tokens"] == 1600
        batch = payload_from({"user": request["messages"][1]["content"]})
        calls.append(batch)
        response = json.loads(reviewed(batch))
        for row in response["reviews"]:
            if row["issue_id"] == "keep-history":
                row.update(disposition="keep", finding_fully_addressed=False,
                           remaining_gaps=["Authentic semantic keep."])
            if row["issue_id"] == "bad-history" and len(calls) == 1:
                if bad_kind == "schema":
                    row["support_digest"] += "0"
                elif bad_kind == "identity":
                    row["support_digest"] = "0" * 64
        if bad_kind == "missing" and len(calls) == 1:
            response["reviews"] = [r for r in response["reviews"] if r["issue_id"] != "bad-history"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(response)}}]})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await reconcile_question_findings(service, record, issues, evidence_issues=[])
    assert [i.id for i in result] == ["keep-history"]
    assert len(calls) == 2
    assert [r["issue_id"] for r in calls[1]["findings"]] == ["bad-history"]
    output = receipt(detail)
    first, second = output["batch_receipts"]
    assert first["invalid_review_issue_ids"] == (["bad-history"] if bad_kind != "missing" else [])
    assert first["missing_review_issue_ids"] == (["bad-history"] if bad_kind == "missing" else [])
    assert second["valid_review_issue_ids"] == ["bad-history"]
    assert output["attempts_by_issue_id"]["bad-history"] == 2
    assert output["attempts_by_issue_id"]["keep-history"] == 1
    for bound in output["batch_receipts"]:
        span = next(s for s in detail.trace_spans if s.id == bound["span_id"])
        assert span.metadata["llm_transport_attempts"] == 1
        assert bound["full_input_sha256"] == hashlib.sha256(span.full_input.encode()).hexdigest()
        assert bound["full_output_sha256"] == hashlib.sha256(span.full_output.encode()).hexdigest()
    charged = budget.tokens_used
    record.detail = type(detail).model_validate_json(detail.model_dump_json())
    record.llm_budget = None
    assert [i.id for i in await reconcile_question_findings(service, record, issues,
              evidence_issues=[])] == ["keep-history"]
    assert len(calls) == 2 and service._run_llm_budget(record).tokens_used == charged


@pytest.mark.asyncio
@pytest.mark.parametrize("count,expected", [(4, 5), (5, 6), (6, 6)])
async def test_retry_spare_window_sends_initial_questions_before_one_retry(
    monkeypatch, count, expected
):
    detail, service, record = await independent_case(monkeypatch)
    add_questions(detail, count)
    calls = []

    async def model(record, **kwargs):
        batch = payload_from(kwargs)
        calls.append(batch)
        response = json.loads(reviewed(batch))
        if len(calls) == 1:
            response["reviews"][0]["support_digest"] += "0"
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == expected
    ids = [b["findings"][0]["issue_id"] for b in calls]
    assert len(set(ids[:count])) == count
    if count < 6:
        assert ids[-1] == ids[0]
    else:
        await reconcile_question_findings(service, record, [], evidence_issues=[])
        assert len(calls) == 7
    assert receipt(detail)["attempts_by_issue_id"][ids[0]] == 2


@pytest.mark.asyncio
async def test_always_invalid_row_stops_at_two_attempts_in_one_window(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        response = json.loads(reviewed(payload_from(kwargs)))
        response["reviews"][0]["support_digest"] += "0"
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 2 and set(receipt(detail)["attempts_by_issue_id"].values()) == {2}
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancellation_stops_queue_and_never_retries_in_current_window(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    add_questions(detail, 3)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        raise asyncio.CancelledError("controlled cancellation")

    traced_model_double(monkeypatch, service, model)
    with pytest.raises(asyncio.CancelledError):
        await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1
    assert len(receipt(detail)["sent_issue_ids"]) == 1
    assert len(receipt(detail)["unsent_issue_ids"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["attempts", "mode6", "v6_system_resigned", "repeated_batch",
                                    "classifications"])
async def test_cache_reconstructs_attempts_and_rejects_legacy_downgrade(monkeypatch, tamper):
    detail, service, record = await independent_case(monkeypatch)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        return reviewed(payload_from(kwargs))

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    local = detail.trace_spans[-1]
    output = json.loads(local.full_output)
    if tamper == "attempts":
        output["attempts_by_issue_id"] = {k: 99 for k in output["planned_issue_ids"]}
    elif tamper == "mode6":
        output["mode"] = "independent_questions_v6"
    elif tamper == "repeated_batch":
        output["batch_receipts"] *= 3
    elif tamper == "classifications":
        output["batch_receipts"][0].update(valid_review_issue_ids=[],
            invalid_review_issue_ids=output["planned_issue_ids"],
            missing_review_issue_ids=output["planned_issue_ids"])
    else:
        bound = output["batch_receipts"][0]
        span = next(s for s in detail.trace_spans if s.id == bound["span_id"])
        span.full_input = span.full_input.replace(
            qa.INDEPENDENT_SYSTEM, qa.INDEPENDENT_SYSTEM_V6, 1)
        bound["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    local.full_output = json.dumps(output)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == (2 if tamper in {"mode6", "v6_system_resigned"} else 1)
    assert set(receipt(detail)["attempts_by_issue_id"].values()) == {1}
    replayed = receipt(detail)["batch_receipts"][0]
    assert replayed["valid_review_issue_ids"] == output["planned_issue_ids"]
    assert replayed["invalid_review_issue_ids"] == replayed["missing_review_issue_ids"] == []


@pytest.mark.asyncio
async def test_explicit_v6_bound_replay_keeps_original_whole_batch_parser(monkeypatch):
    detail, service, record, issues = await three_findings(monkeypatch)

    async def model(record, **kwargs):
        return reviewed(payload_from(kwargs))

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, issues, evidence_issues=[])
    local = detail.trace_spans[-1]
    candidates = {r["issue_id"]: r for r in json.loads(local.full_input)["findings"]}
    output = receipt(detail)
    bound = output["batch_receipts"][0]
    span = next(s for s in detail.trace_spans if s.id == bound["span_id"])
    span.full_input = span.full_input.replace(qa.INDEPENDENT_SYSTEM, qa.INDEPENDENT_SYSTEM_V6, 1)
    bound["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    assert len(qa._bound_batch_reviews(detail, output["basis_hash"], candidates, bound,
                                     protocol="independent_questions_v6")) == 3
    response = json.loads(span.full_output)
    response["reviews"][1]["support_digest"] += "0"
    span.full_output = json.dumps(response)
    bound["full_output_sha256"] = hashlib.sha256(span.full_output.encode()).hexdigest()
    assert qa._bound_batch_reviews(detail, output["basis_hash"], candidates, bound,
                                   protocol="independent_questions_v6") == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_marker", [0, None, True, "1", -1])
async def test_503_cache_ignores_forged_receipt_timeout_and_requires_typed_evidence(
    monkeypatch, timeout_marker
):
    detail, service, record = await independent_case(monkeypatch)
    provider, _ = await task_service()
    provider._llm._settings = replace(provider._llm._settings, llm_max_retries=0,
        backup_llm_api_key="", backup_llm_model="")
    service._settings = replace(service._settings, run_llm_max_calls=24,
        run_llm_max_tokens=80000, llm_max_output_tokens=1600, llm_max_retries=0)
    service._llm = provider._llm
    record.llm_budget = None
    detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service))
    calls = []

    async def post(url, request, headers):
        batch = payload_from({"user": request["messages"][1]["content"]})
        calls.append(batch)
        if len(calls) == 1:
            return httpx.Response(503, text="Controlled offline unavailable provider")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": reviewed(batch)}}]})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    local = detail.trace_spans[-1]
    candidates = {r["issue_id"]: r for r in json.loads(local.full_input)["findings"]}
    span = next(s for s in detail.trace_spans
                if s.id == output["batch_receipts"][0]["span_id"])
    assert span.status == "error" and span.metadata["llm_transport_attempts"] == 1
    assert span.metadata["llm_timeout_attempts"] == 0
    before = qa._cache(detail, output["basis_hash"], candidates)
    assert before[3] == set() and before[4][0]["status"] == "unavailable"
    assert len(calls) == budget.calls == 1

    # marker=0 is the exact production regression: only the receipt is changed.
    # Other markers check that missing, boolean, string and negative metadata
    # cannot supply the positive integer evidence emitted by the real adapter.
    output["batch_receipts"][0]["status"] = "timeout"
    local.full_output = json.dumps(output)
    if timeout_marker is None:
        span.metadata.pop("llm_timeout_attempts")
    elif timeout_marker != 0:
        span.metadata["llm_timeout_attempts"] = timeout_marker
    rebuilt = qa._cache(detail, output["basis_hash"], candidates)
    assert rebuilt[0] == {} and rebuilt[1] == before[1] and rebuilt[2] == before[2]
    assert rebuilt[3] == set()
    assert rebuilt[4][0]["status"] == "unavailable"
    assert rebuilt[4][0]["timeout_attempts"] == 0
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(calls) == budget.calls == 2
    assert receipt(detail)["timeout_issue_ids"] == []
    assert receipt(detail)["unresolved_timeout_issue_ids"] == []
    assert receipt(detail)["model_execution"] == "completed"
