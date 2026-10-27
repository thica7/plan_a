"""QA9 keeps current child scope, complete plaintext and historical replay."""

import copy
import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from test_answer_presentation import prepared
from test_clarification_qa_alignment import install_review, qa_case
from test_final_question_reconciliation import reviewed
from test_final_question_v8 import candidates, history
from test_independent_final_question_qa import context_for, payload_from, receipt
from test_task_delivery_budget import task_service

from packages.agents.qa import independent_question_review as qa
from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.agents.qa.question_review_transport import dumps, final_review_batches
from packages.orchestrator.llm_execution import LLMExecutionMixin
from packages.research.question_scope import question_request_context, research_questions

V9 = "independent_questions_v9"
V8 = "independent_questions_v8"


def test_versioned_systems_caps_and_actual_request_reserve():
    assert qa.PROTOCOL == V9
    for version, digest in {
        5: "d3b389c339ed353b83560842c33f5f64acd500e2241ce49a40ea9f5a1c7466c5",
        6: "077d6cffe1ace86417e94cb16baa4747ca081d285dc2a3f17ed70c2f931fae43",
        7: "29d1a48473e58ae2f85f487476f33ced368b6b2acde98fb4fd972d85d4244a9d",
        8: "1c493c5a733f1406fcd8c19dd8246d0a87bf9d56ed2a79bd9f2846216ec067ec",
    }.items():
        assert (
            hashlib.sha256(getattr(qa, f"INDEPENDENT_SYSTEM_V{version}").encode()).hexdigest()
            == digest
        )
        assert qa.review_byte_limit(f"independent_questions_v{version}") == 8192
    assert qa.TASK_REVIEW_BYTES == 8192
    assert qa.review_byte_limit(V9) == 14000
    assert qa.INDEPENDENT_SYSTEM == qa.INDEPENDENT_SYSTEM_V9
    assert "current_question" in qa.INDEPENDENT_SYSTEM
    assert "historical_finding" in qa.INDEPENDENT_SYSTEM
    assert "800" in qa.INDEPENDENT_SYSTEM
    assert (
        qa.FINAL_QA_REQUEST_RESERVE == len(qa.INDEPENDENT_SYSTEM.encode()) + 14000 + 256 + 1600 + 2
    )


@pytest.mark.asyncio
async def test_current_and_historical_scopes_are_server_owned_and_do_not_clear_facts(monkeypatch):
    service, record, _ = qa_case()
    originals = [history(record), history(record, structural=True)]
    install_review(monkeypatch, service)
    result = await reconcile_question_findings(service, record, originals, evidence_issues=[])
    rows = candidates(record.detail)
    current = next(r for r in rows.values() if r.get("independent_question_check"))
    assert current["review_scope"] == {"kind": "current_question"}
    assert all(rows[i.id]["review_scope"] == {"kind": "historical_finding"} for i in originals)
    assert all(i in result for i in originals)
    output = receipt(record.detail)
    parent = next(iter(output["parent_review_states"].values()))
    assert parent["delivery_complete"] is True
    assert parent["factual_resolution"] == "partial"
    assert parent["unresolved_fact_question_ids"] == [current["question_id"]]
    assert parent["child_fact_states"][current["question_id"]]["status"] == "partial"


def test_parent_aggregation_uses_all_canonical_children_and_unique_bindings():
    service, record, _ = qa_case()
    detail = record.detail
    detail.plan.decision_brief.decision_question = (
        "Example Product Premium: Given Observer A AND B, can A vote? Can A download and export?"
    )
    product, dimension = "Example Product", "feature"
    questions = research_questions(detail, product, dimension)
    context = question_request_context(detail, product, dimension, questions)
    assert len(questions) == 2 and len(context["parents"]) == 1
    first, second = [q["question_id"] for q in questions]
    current = [
        dict(
            question_id=first,
            issue_id="final-question-" + first,
            answer=dict(status="answered", conclusion="yes", resolution="direct"),
        )
    ]
    states = qa._parent_review_states(
        detail, current, {current[0]["issue_id"]}, {current[0]["issue_id"]}
    )
    parent = states[context["parents"][0]["parent_id"]]
    assert parent["expected_question_ids"] == [first, second]
    assert parent["passed_question_ids"] == [first]
    assert parent["pending_question_ids"] == [second]
    assert parent["delivery_complete"] is False
    assert parent["factual_resolution"] == "partial"
    assert parent["unresolved_fact_question_ids"] == [second]
    # An ambiguous original cannot be promoted to a fabricated parent.
    detail.plan.decision_brief.decision_question = (
        "Example Product Premium: Can A vote?\nExample Product Basic: Can A vote?"
    )
    ambiguous = research_questions(detail, product, dimension)
    assert ambiguous
    states = qa._parent_review_states(detail, [], set(), set())
    assert all(
        "Can A vote?" not in state["parent_text"] or len(state["expected_question_ids"]) == 1
        for state in states.values()
    )
    # Explicitly shared exact child is unbound when it occurs in two parents.
    detail.plan.decision_brief.decision_question = (
        "Example Product Premium: Given Observer A? Can A vote?\n"
        "Example Product Basic: Given Member B? Can A vote?"
    )
    q = next(
        q for q in research_questions(detail, product, dimension) if q["question"] == "Can A vote?"
    )
    assert (
        q["question_id"]
        in question_request_context(detail, product, dimension, [q])["unbound_question_ids"]
    )
    assert all(
        q["question_id"] not in state["expected_question_ids"]
        for state in qa._parent_review_states(detail, [], set(), set()).values()
    )


def test_unbound_canonical_child_cannot_hide_behind_passed_bound_siblings():
    _, record, _ = qa_case()
    detail = record.detail
    detail.plan.decision_brief.decision_question = (
        "Example Product Premium: Given Observer A? Can A vote?\n"
        "Example Product Basic: Given Member B? Can A vote?"
    )
    questions = research_questions(detail, "Example Product", "feature")
    context = question_request_context(detail, "Example Product", "feature", questions)
    bound_ids = {binding["question_id"] for binding in context["bindings"]}
    rows = [
        dict(
            question_id=qid,
            issue_id="final-question-" + qid,
            answer=dict(status="answered", conclusion="yes", resolution="direct"),
        )
        for qid in bound_ids
    ]
    passed = {row["issue_id"] for row in rows}
    states = qa._parent_review_states(detail, rows, passed, passed)
    assert states and context["unbound_question_ids"]
    for state in states.values():
        assert state["delivery_complete"] is False
        assert state["factual_resolution"] == "partial"
        assert state["unbound_question_ids"] == context["unbound_question_ids"]
        assert not set(state["unbound_question_ids"]) & set(state["expected_question_ids"])


@pytest.mark.asyncio
async def test_full_current_scope_keeps_parent_assumptions_and_all_child_atoms(monkeypatch):
    service, record, _ = qa_case()
    parent = (
        "Example Product Premium: Given Observer A AND B, can A vote? Can A download and export?"
    )
    record.detail.plan.decision_brief.decision_question = parent
    calls = install_review(monkeypatch, service)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    for batch in calls:
        for row in batch["findings"]:
            context = context_for(batch, row)
            assert context["request_context"]["parents"][0]["text"] == parent
            assert row["review_scope"] == {"kind": "current_question"}
    assert {context_for(b, r)["question"] for b in calls for r in b["findings"]} == {
        q["question"] for q in research_questions(record.detail, "Example Product", "feature")
    }
    assert "every atomic" in qa.INDEPENDENT_SYSTEM
    assert "siblings" in qa.INDEPENDENT_SYSTEM
    assert "hypothetical" in qa.INDEPENDENT_SYSTEM


def row_at_bytes(target):
    row = dict(
        issue_id="item",
        question_id="question",
        question="Can A download AND export?",
        independent_question_check=True,
        answer={"claim_ids": []},
        expected_claim_ids=[],
        support_digest="0" * 64,
        verification_target="complete_finding_resolution",
        review_scope={"kind": "current_question"},
        visible_answer="",
    )
    base = len(("\nJSON:\n" + dumps(dict(version=1, basis_hash="basis", findings=[row]))).encode())
    row["visible_answer"] = "中" * ((target - base) // 3) + "x" * ((target - base) % 3)
    return row


def test_plaintext_14000_boundary_and_legacy_8192_are_independent():
    row = row_at_bytes(14000)
    batches, omitted = final_review_batches(
        [row], "basis", max_bytes=qa.review_byte_limit(V9), max_batches=6, protocol=V9
    )
    assert not omitted and batches[0]["findings"] == [row]
    assert len(("\nJSON:\n" + dumps(batches[0])).encode()) == 14000
    assert final_review_batches(
        [dict(row, visible_answer=row["visible_answer"] + "x")],
        "basis",
        max_bytes=14000,
        max_batches=6,
        protocol=V9,
    ) == ([], ["item"])
    assert final_review_batches(
        [row], "basis", max_bytes=qa.review_byte_limit(V8), max_batches=6, protocol=V8
    ) == ([], ["item"])


@pytest.mark.asyncio
async def test_narrow_final_qa_evidence_allowance_keeps_old_credentials(monkeypatch):
    service, record, _ = qa_case()
    record.detail.plan.research_depth = "quick"
    old_view, old_use = service._begin_evidence_use(record, agent="qa", source_ids=[])
    view, use = service._begin_evidence_use(
        record, agent="qa", source_ids=[], qa_review_protocol=V9
    )
    assert old_use.max_bytes == 8192
    assert use.max_bytes == 14000
    assert old_view.fact_ids == view.fact_ids
    service._validate_evidence_use(record, old_use)
    service._validate_evidence_use(record, use)
    calls = []
    original = service._begin_evidence_use

    def observe(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_begin_evidence_use", observe)
    install_review(monkeypatch, service)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert calls and all(c["qa_review_protocol"] == V9 for c in calls)


@pytest.mark.asyncio
async def test_explicit_v8_replay_binds_its_old_system_cap_and_cache(monkeypatch):
    service, record, _ = qa_case()
    install_review(monkeypatch, service)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    rows = candidates(record.detail)
    old_rows = {
        key: {k: v for k, v in row.items() if k != "review_scope"} for key, row in rows.items()
    }
    output = receipt(record.detail)
    bound = copy.deepcopy(output["batch_receipts"][0])
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    batches, omitted = final_review_batches(
        list(old_rows.values()), "old-basis", max_bytes=8192, max_batches=1, protocol=V8
    )
    assert not omitted
    span.full_input = qa.INDEPENDENT_SYSTEM_V8 + "\n\n\nJSON:\n" + dumps(batches[0])
    span.full_output = reviewed(batches[0], "current_limitation")
    bound.update(
        full_input_sha256=hashlib.sha256(span.full_input.encode()).hexdigest(),
        full_output_sha256=hashlib.sha256(span.full_output.encode()).hexdigest(),
    )
    local = record.detail.trace_spans[-1]
    local.metadata["basis_hash"] = "old-basis"
    local.full_output = json.dumps(dict(mode=V8, batch_receipts=[bound]))
    cached = qa._cache(record.detail, "old-basis", old_rows, protocol=V8)
    assert set(cached[0]) == set(old_rows)
    assert qa._affirmative(
        next(iter(cached[0].values())), next(iter(old_rows.values())), protocol=V8
    )
    assert qa._cache(record.detail, "old-basis", rows)[0] == {}
    span.full_input = span.full_input.replace(qa.INDEPENDENT_SYSTEM_V8, qa.INDEPENDENT_SYSTEM)
    bound["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    assert qa._bound_batch_reviews(record.detail, "old-basis", old_rows, bound, protocol=V8) == {}


@pytest.mark.asyncio
async def test_fresh_budget_uses_actual_sys9_14000_and_restored_limits_stay_exact():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    assert budget.delivery_reserves["final_qa:run"] == qa.FINAL_QA_REQUEST_RESERVE
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    budget.tokens_used = budget.max_tokens - qa.FINAL_QA_REQUEST_RESERVE
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    service._llm._post_chat_completion = post
    await LLMExecutionMixin._trace_llm_text(
        service,
        record,
        agent="qa",
        subagent=None,
        name="final_question_reconciliation",
        system=qa.INDEPENDENT_SYSTEM,
        user="x" * 14000,
        max_output_tokens=1600,
    )
    assert len(requests) == 1 and budget.tokens_used == budget.max_tokens == 80000
    record.llm_budget = None
    checkpoint = {
        "calls": 10,
        "repairs": 2,
        "tokens_charged": 30000,
        "cost_charged_usd": 0.0123,
        "delivery_limit:final_qa:run": 15250,
        "delivery_call_limit:final_qa:run": 1,
        "delivery_calls:final_qa:run": 1,
        "delivery_charged:final_qa:run": 7000,
        "delivery_finished:final_qa:run": True,
    }
    record.detail.llm_budget_checkpoint = checkpoint
    restored = service._run_llm_budget(record)
    assert (restored.calls, restored.repairs, restored.tokens_used, restored.cost_used_usd) == (
        10,
        2,
        30000,
        0.0123,
    )
    assert restored.delivery_reserves["final_qa:run"] == 15250
    assert restored.delivery_call_reserves["final_qa:run"] == 1
    assert restored.delivery_calls["final_qa:run"] == 1
    assert restored.delivery_charged["final_qa:run"] == 7000
    assert "final_qa:run" in restored.delivery_finished
    assert (restored.max_calls, restored.max_tokens) == (24, 80000)


def multiple_claim_case():
    service, record, _, audit = prepared(selected_inference=True)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    record.detail.plan.research_depth = "quick"
    from packages.agents.writer.answer_coverage import parse_answer_coverage
    from packages.agents.writer.dimension_writer import render_dimension_report

    snapshot = service._current_evidence_snapshot(record)
    question = research_questions(record.detail, audit.competitor, audit.dimension)[0]
    claims = [row.claim.model_dump(mode="json") for row in audit.claims]
    ids = [row["id"] for row in claims]
    response = json.dumps(
        dict(
            version=3,
            answers=[
                dict(
                    question_id=question["question_id"],
                    status="answered",
                    resolution="direct",
                    conclusion="yes",
                    claim_ids=ids,
                    missing_fields=[],
                    reason="Reviewed",
                    subquestions=[
                        dict(
                            question_quote=question["question"],
                            claim_ids=ids,
                            conclusion="yes",
                            relation="direct",
                        )
                    ],
                )
            ],
        )
    )
    answers = parse_answer_coverage(
        response,
        [question],
        set(ids),
        claims=claims,
        required_binding_version=3,
        facts=snapshot.facts,
        require_subquestions=True,
        answer_review_contract="subquestion-premises-v3",
    )
    audit = audit.model_copy(
        update=dict(answer_coverage=answers, answer_review_contract="subquestion-premises-v3")
    )
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    for use in record.detail.evidence_consumptions:
        service._validate_evidence_use(record, use)
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=record.detail.evidence_consumptions,
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    assert service._final_qa_producer_verified(record, snapshot)
    return service, record, audit


@pytest.mark.asyncio
async def test_actual_multiple_claim_context_keeps_complete_publication_sources_and_atoms(
    monkeypatch,
):
    service, record, audit = multiple_claim_case()
    from test_independent_final_question_qa import traced_model_double

    calls = []

    async def model(record, **kwargs):
        batch = payload_from(kwargs)
        calls.append(kwargs)
        row = batch["findings"][0]
        context = context_for(batch, row)
        assert row["diagnostic_only"] is False
        assert len(context["claims"]) == 2
        assert context["claims"] == [c.claim.model_dump(mode="json") for c in audit.claims]
        assert context["answer"]["claim_ids"] == list(audit.answer_coverage[0].claim_ids)
        assert context["visible_answer"] and all(
            c.claim.text in context["visible_answer"] for c in audit.claims
        )
        assert len(kwargs["user"].encode()) <= 14000
        return reviewed(batch)

    traced_model_double(monkeypatch, service, model)
    assert await qa.review_current_questions(service, record, [], evidence_issues=[]) == []
    assert len(calls) == 1
    parent = next(iter(receipt(record.detail)["parent_review_states"].values()))
    assert parent["delivery_complete"] is True and parent["factual_resolution"] == "resolved"


@pytest.mark.parametrize("length", [800, 801, 837, 868])
def test_v9_preserves_model_reason_and_rejects_oversize_rows_without_rewriting(length):
    row = row_at_bytes(1000)
    raw = json.loads(reviewed({"basis_hash": "basis", "findings": [row]}))
    raw["reviews"][0]["reason"] = "中" * length
    response = json.dumps(raw)
    parsed = qa._batch_response(response, "basis", {row["issue_id"]: row})
    assert parsed.invalid_issue_ids == ([] if length == 800 else [row["issue_id"]])
    assert parsed.missing_issue_ids == []
    if length == 800:
        assert parsed.reviews[row["issue_id"]].reason == "中" * 800
    assert json.loads(response)["reviews"][0]["reason"] == "中" * length


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["historical_finding", "invalid", None])
async def test_scope_tampering_cannot_be_rehashed_into_a_bound_review(monkeypatch, kind):
    service, record, _ = qa_case()
    install_review(monkeypatch, service)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    rows = candidates(record.detail)
    bound = copy.deepcopy(output["batch_receipts"][0])
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    wire = json.loads(span.full_input.split("\nJSON:\n", 1)[1])
    if kind:
        wire["findings"][0]["review_scope"] = {"kind": kind}
    else:
        wire["findings"][0].pop("review_scope")
    span.full_input = qa.INDEPENDENT_SYSTEM + "\n\n\nJSON:\n" + dumps(wire)
    bound["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    assert qa._bound_batch_reviews(record.detail, output["basis_hash"], rows, bound) == {}
