"""QA8 audits canonical clarification delivery without resolving product facts."""

import copy
import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from test_clarification_qa_alignment import clarification, install_review, qa_case
from test_final_question_reconciliation import reviewed
from test_independent_final_question_qa import context_for, payload_from, receipt
from test_task_delivery_budget import task_service

from packages.agents.qa import independent_question_review as qa
from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.agents.qa.question_review_transport import dumps, final_review_batches
from packages.orchestrator.llm_execution import LLMExecutionMixin
from packages.schema.models import QCIssue, RedoScope, ReflectionRecord

DELIVERY = "canonical_clarification_delivery"
FACTS = "complete_finding_resolution"
V8 = "independent_questions_v8"


def history(record, *, structural=False):
    audit, question, _ = clarification(record)
    return QCIssue(
        id="structural-history" if structural else "factual-history", severity="blocker",
        detected_by="reflector", target_agent="writer", target_competitor=audit.competitor,
        target_subagent=audit.dimension, field_path="answer_coverage",
        problem=question["question_id"] + (
            ": source document missing." if structural else ": product retention is unanswered."),
        metadata={"question_id": question["question_id"]},
        redo_scope=RedoScope(kind="writer_only", rationale="Review complete finding."),
    )


def candidates(detail):
    span = next(s for s in reversed(detail.trace_spans) if s.name == qa.RECEIPT_NAME)
    return {row["issue_id"]: row for row in json.loads(span.full_input)["findings"]}


@pytest.mark.asyncio
async def test_current_delivery_is_separate_and_history_cannot_borrow_its_approval(monkeypatch):
    service, record, _ = qa_case()
    originals = [history(record), history(record, structural=True)]
    before = record.detail.model_dump(mode="json")
    calls = install_review(monkeypatch, service)
    result = await reconcile_question_findings(service, record, originals, evidence_issues=[])
    assert [(i.id, i.severity, i.problem) for i in result] == [
        (i.id, i.severity, i.problem) for i in originals]
    rows = candidates(record.detail)
    current = next(row for row in rows.values() if row.get("independent_question_check"))
    assert current["verification_target"] == DELIVERY
    assert all(rows[i.id]["verification_target"] == FACTS for i in originals)
    assert len(calls) == 2
    assert {row["verification_target"] for row in calls[0]["findings"]} == {DELIVERY}
    assert {row["verification_target"] for row in calls[1]["findings"]} == {FACTS}
    for batch in calls:
        for row in batch["findings"]:
            context = context_for(batch, row)
            assert context["request_context"]["parents"]
            assert context["question"] == current["question"]
            assert context["visible_answer"] == current["visible_answer"]
    output = receipt(record.detail)
    assert output["mode"] == qa.PROTOCOL
    assert output["passed_question_ids"] == [current["question_id"]]
    assert len(output["model_review"]["reviews"]) == 3
    assert output["question_review_states"][current["question_id"]] == "current_limitation"
    for row in rows.values():
        assert row["support_digest"] == service._evidence_artifact_hash(
            {key: value for key, value in row.items() if key != "support_digest"})
    assert output["basis_hash"] == service._evidence_artifact_hash(dict(
        dependencies=qa._basis(service, record, service._final_qa_snapshot(record)),
        protocol=qa.PROTOCOL, candidates=list(rows.values())))
    assert record.detail.report_md == before["report_md"]
    assert record.detail.report_dimension_audits[0].model_dump(mode="json") == before[
        "report_dimension_audits"][0]
    _, _, answer = clarification(record)
    assert (answer.status, answer.conclusion, answer.missing_fields) == (
        "partial", "depends", ("actual_action", "data_ownership"))


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition,fully,gaps", [
    ("keep", True, []), ("current_limitation", False, []),
    ("current_limitation", True, ["A delivery omission remains."]), ("superseded", True, []),
])
async def test_target_never_overrides_a_negative_or_wrong_disposition(
    monkeypatch, disposition, fully, gaps,
):
    service, record, _ = qa_case()
    def mutate(value):
        value["reviews"][0].update(disposition=disposition, finding_fully_addressed=fully,
                                   remaining_gaps=gaps)
    calls = install_review(monkeypatch, service, mutate=mutate)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1
    assert not receipt(record.detail)["passed_question_ids"]
    assert candidates(record.detail).popitem()[1]["verification_target"] == DELIVERY


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["producer", "body", "claim", "parent"])
async def test_noncanonical_or_unverified_clarification_never_receives_delivery_target(
    monkeypatch, mutation,
):
    service, record, _ = qa_case()
    audit, _, answer = clarification(record)
    if mutation == "producer":
        record.detail.evidence_consumptions = []
    elif mutation == "body":
        record.detail.report_md += "\n  Data is always retained."
    elif mutation == "claim":
        record.detail.report_dimension_audits = [audit.model_copy(update={
            "answer_coverage": (answer.model_copy(update={"claim_ids": ("forged",)}),)})]
    else:
        record.detail.plan.decision_brief.decision_question = (
            "Example Product: 数据属于个人；我们会移除组织成员。 " + answer.question)
    install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    rows = candidates(record.detail)
    assert rows and all(row["verification_target"] == FACTS for row in rows.values())
    assert not receipt(record.detail)["passed_question_ids"]


def test_protocol_freezes_old_systems_and_scopes_boolean_to_verification_target():
    assert qa.PROTOCOL == "independent_questions_v9"
    for name, expected in {
        "INDEPENDENT_SYSTEM_V5": "d3b389c339ed353b83560842c33f5f64acd500e2241ce49a40ea9f5a1c7466c5",
        "INDEPENDENT_SYSTEM_V6": "077d6cffe1ace86417e94cb16baa4747ca081d285dc2a3f17ed70c2f931fae43",
        "INDEPENDENT_SYSTEM_V7": "29d1a48473e58ae2f85f487476f33ced368b6b2acde98fb4fd972d85d4244a9d",
    }.items():
        assert hashlib.sha256(getattr(qa, name).encode()).hexdigest() == expected
    assert qa.INDEPENDENT_SYSTEM_V8.startswith("Independent final question QA v8.")
    assert "verification_target" in qa.INDEPENDENT_SYSTEM
    assert "assigned verification target" in qa.INDEPENDENT_SYSTEM
    assert "Pending user inputs are not delivery omissions" in qa.INDEPENDENT_SYSTEM
    assert qa.FINAL_QA_REQUEST_RESERVE == (
        len(qa.INDEPENDENT_SYSTEM.encode()) + 14000 + 256 + 1600 + 2)


@pytest.mark.asyncio
async def test_explicit_legacy_keeps_its_original_wire_and_affirmative_semantics(monkeypatch):
    service, record, _ = qa_case()
    install_review(monkeypatch, service)
    await reconcile_question_findings(service, record, [history(record)], evidence_issues=[])
    rows = candidates(record.detail)
    original_rows = [{k: v for k, v in row.items() if k != "verification_target"}
                     for row in rows.values()]
    legacy, omitted = final_review_batches(original_rows, "legacy", max_bytes=8192,
                                           max_batches=6, protocol="independent_questions_v7")
    assert not omitted and len(legacy) == 1
    current = next(row for row in rows.values() if row.get("independent_question_check"))
    old = next(row for row in rows.values() if not row.get("independent_question_check"))
    decision = qa._batch_response(reviewed({"basis_hash": "legacy", "findings": [old]},
                                           "current_limitation"), "legacy", {old["issue_id"]: old},
                                  protocol="independent_questions_v7").reviews[old["issue_id"]]
    assert qa._affirmative(decision, old, protocol="independent_questions_v7")
    assert qa._affirmative(decision, old, protocol="independent_questions_v6")
    assert not qa._affirmative(decision, old)
    assert not qa._affirmative(decision, {**current, "issue_id": "forged-history"})
    # Explicit legacy cache replay binds its original target-free payload and SYS.
    local = next(s for s in reversed(record.detail.trace_spans) if s.name == qa.RECEIPT_NAME)
    bound = copy.deepcopy(receipt(record.detail)["batch_receipts"][0])
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    span.full_input = qa.INDEPENDENT_SYSTEM_V7 + "\n\n\nJSON:\n" + dumps(legacy[0])
    span.full_output = reviewed({"basis_hash": "legacy", "findings": original_rows},
                                "current_limitation")
    bound.update(issue_ids=[r["issue_id"] for r in original_rows],
        full_input_sha256=hashlib.sha256(span.full_input.encode()).hexdigest(),
        full_output_sha256=hashlib.sha256(span.full_output.encode()).hexdigest())
    local.metadata["basis_hash"] = "legacy"
    local.full_output = json.dumps(dict(mode="independent_questions_v7", batch_receipts=[bound]))
    old_candidates = {r["issue_id"]: r for r in original_rows}
    assert len(qa._cache(record.detail, "legacy", old_candidates,
                         protocol="independent_questions_v7")[0]) == 2
    assert qa._cache(record.detail, "legacy", old_candidates)[0] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["target", "unknown_target", "missing_target", "mode7",
                                    "system7", "mixed_batch"])
async def test_target_and_protocol_cannot_be_rehashed_into_a_valid_transport(monkeypatch, tamper):
    service, record, _ = qa_case()
    install_review(monkeypatch, service)
    await reconcile_question_findings(service, record, [history(record)], evidence_issues=[])
    output = receipt(record.detail)
    rows = candidates(record.detail)
    bound = copy.deepcopy(output["batch_receipts"][0])
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    payload = json.loads(span.full_input.split("\nJSON:\n", 1)[1])
    if tamper == "system7":
        span.full_input = span.full_input.replace(qa.INDEPENDENT_SYSTEM, qa.INDEPENDENT_SYSTEM_V7)
    elif tamper == "mode7":
        assert qa._bound_batch_reviews(record.detail, output["basis_hash"], rows, bound,
                                       protocol="independent_questions_v7") == {}
        return
    else:
        if tamper == "target":
            payload["findings"][0]["verification_target"] = FACTS
        elif tamper == "unknown_target":
            payload["findings"][0]["verification_target"] = "approve_everything"
        elif tamper == "missing_target":
            payload["findings"][0].pop("verification_target")
        else:
            payload["findings"].append(rows["factual-history"])
            bound["issue_ids"].append("factual-history")
        span.full_input = qa.INDEPENDENT_SYSTEM + "\n\n\nJSON:\n" + dumps(payload)
    bound["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    assert qa._bound_batch_reviews(record.detail, output["basis_hash"], rows, bound) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [1, 2, 3])
async def test_target_split_keeps_initial_history_before_format_retry_and_pending(
    monkeypatch, window,
):
    service, record, _ = qa_case()
    original = history(record)
    assert qa.MAX_REVIEW_BATCHES == 6 and qa.MAX_ATTEMPTS_PER_FINDING == 2
    monkeypatch.setattr(qa, "MAX_REVIEW_BATCHES", window)
    def mutate(value):
        if len(calls) == 1:
            value["reviews"][0]["support_digest"] += "0"
    calls = install_review(monkeypatch, service, mutate=mutate)
    result = await reconcile_question_findings(service, record, [original], evidence_issues=[])
    output = receipt(record.detail)
    _, question, _ = clarification(record)
    current_id = "final-question-" + question["question_id"]
    dispatched = [[row["issue_id"] for row in batch["findings"]] for batch in calls]
    assert dispatched == [[current_id], [original.id], [current_id]][:window]
    assert output["attempts_by_issue_id"][current_id] == (2 if window == 3 else 1)
    assert output["unsent_issue_ids"] == ([original.id] if window == 1 else [])
    assert original in result
    assert output["passed_question_ids"] == ([question["question_id"]] if window == 3 else [])


@pytest.mark.asyncio
async def test_real_adapter_full_qa_preserves_partial_history_budget_and_cache(monkeypatch):
    service, record, _ = qa_case()
    audit, question, answer = clarification(record)
    record.detail.reflections = [ReflectionRecord(iteration=1, gate_status="block", blocking_gaps=[
        question["question_id"] + ": product retention is unanswered.",
        question["question_id"] + ": source document missing.",
    ])]
    # Reflections are Writer upstream inputs. Commit the fixture producer only
    # after its complete input state exists, as the real Writer does.
    service._record_evidence_artifact(record, kind="writer",
        uses=[u for u in record.detail.evidence_consumptions if u.agent == "writer"],
        payload=service._writer_evidence_artifact_payload(record.detail))
    assert service._final_qa_producer_verified(record, service._final_qa_snapshot(record))
    provider, _ = await task_service()
    service._llm = provider._llm
    service._settings = replace(service._settings, run_llm_max_calls=24,
        run_llm_max_tokens=80000, llm_max_output_tokens=1600, llm_max_retries=0)
    record.llm_budget = None
    record.detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    previous_calls = budget.calls
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    monkeypatch.setattr(service, "_trace_llm_text",
                        LLMExecutionMixin._trace_llm_text.__get__(service))
    requests = []
    async def post(url, payload, headers):
        assert payload["messages"][0]["content"] == qa.INDEPENDENT_SYSTEM
        user = payload["messages"][1]["content"]
        assert len(user.encode()) <= 8192
        batch = payload_from({"user": user})
        requests.append(batch)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": reviewed(batch, "current_limitation")}}]})
    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    body = record.detail.report_md
    await service._real_qa_step(record)
    output = receipt(record.detail)
    assert output["mode"] == qa.PROTOCOL
    assert len(requests) == 2, {
        "rows": [(r["verification_target"], r["support_verified"], r["diagnostic_only"])
                 for r in candidates(record.detail).values()],
        "issues": [(i.detected_by, i.metadata.get("evidence_reason"),
                    i.metadata.get("claim_audit_reason")) for i in record.detail.qa_findings
                   if i.detected_by == "citation"],
    }
    assert output["passed_question_ids"] == [question["question_id"]]
    assert any(i.detected_by == "reflector" and i.severity == "blocker"
               for i in record.detail.qa_findings)
    assert record.detail.report_md == body
    assert record.detail.report_dimension_audits[0].answer_coverage == (answer,)
    spans = [s for s in record.detail.trace_spans if s.name == "final_question_reconciliation"]
    assert all(s.metadata["llm_max_output_tokens"] == 1600 for s in spans)
    charged = sum(len(s.full_input.encode()) + 256 + 1600 for s in spans)
    assert budget.tokens_used == charged and budget.calls == previous_calls + 2
    assert (budget.max_calls, budget.max_tokens) == (24, 80000)
    service._checkpoint_llm_budget(record, budget)
    record.detail = type(record.detail).model_validate_json(record.detail.model_dump_json())
    record.llm_budget = None
    await service._real_qa_step(record)
    assert len(requests) == 2
    restored = service._run_llm_budget(record)
    assert restored.tokens_used == charged and restored.calls == previous_calls + 2
    assert record.detail.report_dimension_audits[0].answer_coverage[0].status == "partial"
