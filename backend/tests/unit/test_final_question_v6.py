"""Current QA v6 exercises actual delivery, cache reconstruction and guards offline."""

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from question_review_fixture import review_payload as decode_review_payload
from test_clarification_qa_alignment import clarification, install_review, qa_case
from test_final_question_reconciliation import QUESTION, reviewed, scope_case
from test_independent_final_question_qa import (
    independent_case,
    payload_from,
    receipt,
    traced_model_double,
)
from test_task_delivery_budget import task_service

from packages.agents.qa import independent_question_review as independent
from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.llm.errors import LLMExecutionLimitError
from packages.orchestrator.llm_execution import LLMExecutionMixin
from packages.research.question_scope import research_questions


@pytest.mark.asyncio
async def test_price_permission_and_unmapped_findings_never_share_actual_request(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    provider, _ = await task_service()
    service._settings = replace(
        service._settings,
        writer_task_execution_enabled=True,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
    )
    service._llm = provider._llm
    record.llm_budget = None
    detail.llm_budget_checkpoint = {}
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    detail.plan.decision_brief.decision_question = (
        QUESTION + "\nExample Product: What is the total annual price for 8 users?"
    )
    questions = research_questions(detail, "Example Product", "feature")
    detail.reflections[-1].blocking_gaps = [
        q["question_id"] + ": Answer remains missing." for q in questions
    ] + ["Unscoped historical question."]
    calls = []

    async def post(url, request, headers):
        raw = request["messages"][1]["content"].split("\nJSON:\n", 1)[1]
        payload = json.loads(raw)
        calls.append(payload)
        assert "c" not in payload
        assert len({row["question_id"] for row in payload["findings"]}) == 1
        response = reviewed(decode_review_payload(raw))
        return httpx.Response(200, json={"choices": [{"message": {"content": response}}]})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    await service._real_qa_step(record)
    output = receipt(detail)
    assert output["mode"] == "independent_questions_v7"
    assert {r["question_id"] for b in calls for r in b["findings"]} == {
        *[q["question_id"] for q in questions],
        "unmapped",
    }
    assert [calls[i]["findings"][0]["independent_question_check"] for i in range(2)] == [True, True]
    assert output["planned_issue_ids"] == output["valid_review_issue_ids"]
    spans = [s for s in detail.trace_spans if s.name == "final_question_reconciliation"]
    assert len(spans) == len(calls)
    assert all(s.metadata["llm_transport_attempts"] == 1 for s in spans)
    for bound in output["batch_receipts"]:
        span = next(s for s in spans if s.id == bound["span_id"])
        assert bound["full_input_sha256"] == hashlib.sha256(span.full_input.encode()).hexdigest()
    before = len(calls)
    record.detail = type(detail).model_validate_json(detail.model_dump_json())
    await service._real_qa_step(record)
    assert len(calls) == before


@pytest.mark.asyncio
async def test_canonical_clarification_real_qa_adapter_replays_partial_limitation(monkeypatch):
    service, record, _ = qa_case()
    provider, _ = await task_service()
    service._settings = replace(
        service._settings,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
    )
    service._llm = provider._llm
    record.llm_budget = None
    record.detail.llm_budget_checkpoint = {}
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    requests = []

    async def post(url, payload, headers):
        user = payload["messages"][1]["content"]
        batch = json.loads(user.split("\nJSON:\n", 1)[1])
        requests.append(batch)
        context = batch["findings"][0]
        assert context["server_delivery_type"] == "canonical_request_only_clarification"
        assert context["answer"]["status"] == "partial"
        assert context["answer"]["answer"] in context["visible_answer"]
        assert context["claims"] == context["expected_claim_ids"] == []
        response = json.loads(reviewed(batch, "current_limitation"))
        for row in response["reviews"]:
            row["reason"] = (
                "The full necessary clarification is published; pending user input is explicit."
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(response)}}]}
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    await service._real_qa_step(record)
    audit, question, answer = clarification(record)
    assert answer.status == "partial" and answer.resolution == "clarification"
    output = receipt(record.detail)
    assert output["mode"] == "independent_questions_v7"
    assert output["passed_question_ids"] == [question["question_id"]]
    assert output["question_review_states"][question["question_id"]] == "current_limitation"
    assert not any(
        i.metadata.get("question_id") == question["question_id"] for i in record.detail.qa_findings
    )
    bound = output["batch_receipts"][0]
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    assert span.metadata["llm_transport_attempts"] == 1
    assert bound["full_input_sha256"] == hashlib.sha256(span.full_input.encode()).hexdigest()
    assert bound["full_output_sha256"] == hashlib.sha256(span.full_output.encode()).hexdigest()
    record.detail = type(record.detail).model_validate_json(record.detail.model_dump_json())
    await service._real_qa_step(record)
    assert len(requests) == 1
    assert receipt(record.detail)["passed_question_ids"] == [question["question_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["parent", "extra_assertion"])
async def test_server_type_cannot_excuse_wrong_parent_or_extra_product_assertion(
    monkeypatch, mutation
):
    service, record, _ = qa_case()
    _, question, answer = clarification(record)
    if mutation == "parent":
        record.detail.plan.decision_brief.decision_question = (
            "Example Product: 我们会移除组织成员，数据属于个人，是否可以？ " + question["question"]
        )
    else:
        record.detail.report_md = record.detail.report_md.replace(
            answer.answer, answer.answer + "\n  产品一定会保留所有密码。"
        )
    calls = install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    rows = [r for b in calls for r in b["findings"]]
    assert all(
        r.get("server_delivery_type") != "canonical_request_only_clarification" for r in rows
    )
    assert all(r["diagnostic_only"] for r in rows)
    assert receipt(record.detail)["passed_question_ids"] == []


@pytest.mark.asyncio
async def test_actual_evidence_cap_keeps_complete_context_unsent_and_retryable(monkeypatch):
    detail, service, record = await independent_case(monkeypatch)
    original = service._begin_evidence_use

    def limited(*args, **kwargs):
        view, use = original(*args, **kwargs)
        return view, use.model_copy(update={"max_bytes": 1})

    monkeypatch.setattr(service, "_begin_evidence_use", limited)

    async def forbidden(*args, **kwargs):
        pytest.fail("Whole final context must be unsent under the actual EvidenceUse cap")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(detail)
    assert (
        output["unsent_issue_ids"] == output["resumable_issue_ids"] == output["planned_issue_ids"]
    )
    assert not any(output["attempts_by_issue_id"].values())
    monkeypatch.setattr(service, "_begin_evidence_use", original)

    async def model(record, **kwargs):
        return reviewed(payload_from(kwargs))

    traced_model_double(monkeypatch, service, model)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []


def test_current_reserve_covers_actual_plain_cap_and_preserves_legacy_system():
    assert independent.PROTOCOL == "independent_questions_v7"
    assert independent.TASK_REVIEW_BYTES == 8192
    assert "Decode exact-content sharing first" in independent.INDEPENDENT_SYSTEM_V5
    assert "Decode exact-content sharing first" not in independent.INDEPENDENT_SYSTEM
    assert independent.FINAL_QA_REQUEST_RESERVE == (
        len(independent.INDEPENDENT_SYSTEM.encode())
        + 8192
        + 256
        + independent.MAX_REVIEW_OUTPUT_TOKENS
        + 2
    )


@pytest.mark.asyncio
async def test_existing_smaller_checkpoint_floor_is_preserved_and_full_v6_request_is_unsent():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    budget.delivery_reserves["final_qa:run"] = 12000
    budget.tokens_used = 68000
    service._checkpoint_llm_budget(record, budget)
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert restored.delivery_reserves["final_qa:run"] == 12000
    assert restored.tokens_used == 68000
    assert (restored.max_calls, restored.max_tokens) == (24, 80000)
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        pytest.fail("An old persisted floor cannot fund a larger v6 request")

    service._llm._post_chat_completion = post
    with pytest.raises(LLMExecutionLimitError):
        await service._trace_llm_text(
            record,
            agent="qa",
            subagent=None,
            name="final_question_reconciliation",
            system=independent.INDEPENDENT_SYSTEM,
            user="x" * 8192,
            max_output_tokens=1600,
        )
    assert not requests
    assert restored.delivery_reserves["final_qa:run"] == 12000
    assert restored.tokens_used == 68000 and restored.calls == 0


async def billing_case():
    from claim_review_fixture import supported_review
    from test_incomplete_quote_answers import usage_case
    from test_question_retrieval import replace_snapshot
    from test_writer_question_delivery import service_for

    from packages.agents.writer.dimension_writer import render_dimension_report, review_payload
    from packages.agents.writer.price_answers import server_missing_price_answers
    from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
    from packages.research.evidence.answer_models import AnswerBoundary
    from packages.research.evidence.report_claims import (
        ReportClaim,
        ReportDimensionAudit,
        audit_report_claims,
    )
    from packages.research.evidence.source_spans import source_span_candidates
    from packages.schema.models import DecisionBrief

    detail, snapshot = usage_case()
    snapshot = replace_snapshot(
        detail,
        snapshot,
        sources=tuple(s.model_copy(update={"dimension": "feature"}) for s in snapshot.sources),
        facts=tuple(
            f.model_copy(update={"dimension": "feature", "evidence_item_ids": ("original-0",)})
            for f in snapshot.facts
        ),
    )
    detail.plan.dimensions = ["feature"]
    detail.plan.competitors = ["Example Product"]
    detail.plan.decision_brief = DecisionBrief(
        decision_question=("Example Product Usage plan 本月有2300万次请求，账单准确是多少美元？")
    )
    service, record = service_for(detail, task_execution=True)
    view, use, _ = await service._begin_question_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    segment = service._writer_segment_context(
        record,
        dict(
            segment_name="dimension:Example Product:feature",
            segment_competitor="Example Product",
            dimension="feature",
        ),
        view,
        use,
    )
    boundaries = [AnswerBoundary.model_validate(b) for b in segment["answer_boundaries"]]
    detail.report_answer_boundaries = boundaries
    fact = snapshot.facts[0]
    claim = ReportClaim(
        id="known-billing-rule",
        text=fact.quote,
        kind="fact",
        competitor="Example Product",
        dimension="feature",
        fact_ids=[fact.id],
        source_ids=[fact.source_id],
        source_span_bindings=[source_span_candidates(fact)[0]],
    )
    review = supported_review(review_payload([claim], view, review_version=3)["claims"][0])
    claims = audit_report_claims([claim], [review], view, boundaries, review_version=3)
    assert claims[0].status == "supported", claims[0].rule_reasons
    questions = research_questions(detail, "Example Product", "feature")
    answer = ReportAnswerCoverage(
        **server_missing_price_answers(
            detail, snapshot, questions, "Example Product", claims=[claim]
        )[questions[0]["question_id"]]
    )
    assert answer.claim_ids == (claim.id,) and claim.text in answer.answer
    detail.report_dimension_audits = [
        ReportDimensionAudit(
            competitor="Example Product",
            dimension="feature",
            consumption_id=use.id,
            claims=claims,
            answer_coverage=[answer],
            answer_binding_version=3,
            claim_review_version=3,
        )
    ]
    detail.report_md = render_dimension_report(
        detail, detail.report_dimension_audits, snapshot=snapshot
    )
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(
        record, kind="writer", uses=[use], payload=service._writer_evidence_artifact_payload(detail)
    )
    assert service._final_qa_producer_verified(record, snapshot)
    return service, record, snapshot, claim, use


@pytest.mark.asyncio
@pytest.mark.parametrize("omit_known_rule", [False, True])
async def test_unknown_bill_keeps_known_rules_and_rejects_omitted_rule(
    monkeypatch, omit_known_rule
):
    from packages.agents.writer.dimension_writer import render_dimension_report

    service, record, snapshot, claim, use = await billing_case()
    audit = record.detail.report_dimension_audits[0]
    if omit_known_rule:
        answer = audit.answer_coverage[0]
        audit = audit.model_copy(
            update={
                "answer_coverage": (
                    answer.model_copy(update={"answer": answer.answer.replace(claim.text, "")}),
                )
            }
        )
        record.detail.report_dimension_audits = [audit]
        record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
        service._record_evidence_artifact(
            record,
            kind="writer",
            uses=[use],
            payload=service._writer_evidence_artifact_payload(record.detail),
        )
        assert service._final_qa_producer_verified(record, snapshot)
    calls = install_review(monkeypatch, service)
    result = await reconcile_question_findings(service, record, [], evidence_issues=[])
    row = calls[0]["findings"][0]
    assert row["answer"]["resolution"] == "insufficient"
    assert row["answer"]["claim_ids"] == [claim.id]
    assert audit.answer_coverage[0].conclusion == "unknown"
    assert row["claims"][0]["text"] == claim.text
    assert row["diagnostic_only"] is omit_known_rule
    assert bool(result) is omit_known_rule
    assert audit.answer_coverage[0].status == "partial"
