"""Spec-review regressions for quote applicability and complete classification rules."""

import json
from types import SimpleNamespace

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response
from test_incomplete_quote_answers import rule_case
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic
from packages.agents.writer.answer_presentation import question_coverage_lines
from packages.agents.writer.complete_predicates import (
    DELIVERY_POLICY,
    classification_non_entailment,
)
from packages.agents.writer.dimension_writer import DimensionWriterMixin
from packages.agents.writer.price_answers import server_missing_price_answers
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims


def test_complete_request_scope_missing_price_is_visible_only_under_new_policy():
    detail, snapshot = rule_case("The Usage plan includes a monthly request allowance.")
    question = {
        "question_id": "q-price",
        "question": "Example Product 在美国购买 Usage plan，按月、美元、含税，当前准确报价是多少？",
    }
    for policy in (DELIVERY_POLICY, None):
        row = ReportAnswerCoverage(
            **server_missing_price_answers(
                detail, snapshot, [question], "Example Product", delivery_policy=policy
            )["q-price"]
        )
        audit = ReportDimensionAudit(
            competitor="Example Product",
            dimension="pricing",
            consumption_id="quote-use",
            claim_review_version=3,
            answer_binding_version=3,
            answer_review_contract="subquestion-premises-v6",
            answer_coverage=(row,),
        )
        visible = "\n".join(
            question_coverage_lines(audit, "zh-CN", detail=detail, decision_reviews={})
        )
        assert row.resolution == "insufficient" and row.conclusion == "unknown"
        assert (row.answer in visible) == (policy is not None)


async def quote_transport_case(monkeypatch, source, question):
    case = await atomic_case([source], question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    calls = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n")[1]))
        calls.append(kwargs["name"])
        if kwargs["name"] == atomic.GENERATION_NAME:
            ref = next(
                span["support_ref"]
                for fact in payload["evidence_view"]["facts"]
                for span in fact["source_span_candidates"]
                if span["quote"] == source
            )
            result = question_plan_response(
                payload, [dict(text=source, kind="fact", support_refs=[ref])]
            )
        elif kwargs["name"] == atomic.REVIEW_NAME:
            result = json.dumps({"reviews": [supported_review(payload["claims"][0])]})
        else:
            result = json.dumps(
                {
                    "version": 3,
                    "answers": [
                        dict(
                            question_id=q["question_id"],
                            status="unverified",
                            claim_ids=[],
                            resolution="unresolved",
                            conclusion="unknown",
                            missing_fields=[],
                        reason="The rule does not establish the requested exact total.",
                        )
                        for q in payload["questions"]
                    ],
                    "task_decisions": [],
                }
            )
        return append_response(service, record, kwargs, result)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        answer_review_contract="subquestion-premises-v6",
        delivery_policy=DELIVERY_POLICY,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert len(audited) == 1 and audited[0].status == "supported", audited
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    rows, _, _ = await DimensionWriterMixin._dimension_question_coverage(
        service, record, packets[0]["questions"], result["compact"], audited, view, use, ()
    )
    audit = ReportDimensionAudit(
        competitor=view.competitor,
        dimension=view.dimension,
        consumption_id=use.id,
        claims=audited,
        answer_coverage=rows,
        answer_binding_version=3,
        claim_review_version=3,
        answer_review_contract="subquestion-premises-v6",
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"],
    )
    record.detail.report_dimension_audits = [audit]
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    visible = "\n".join(
        question_coverage_lines(
            audit, "zh-CN", detail=record.detail, decision_reviews=replay["decision_review"]
        )
    )
    assert atomic.ANSWER_NAME in calls
    return rows[0], visible


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,question,applicable",
    [
        (
            "The Enterprise plan includes a monthly request allowance; "
            "usage above it is billed separately.",
            "Example Product Free plan 本月2300万次请求，账单准确是多少美元？",
            False,
        ),
        (
            "The Usage plan includes a monthly request allowance; "
            "usage above it is billed separately.",
            "Example Product 在美国购买 Usage plan，按月、美元、含税，当前准确报价是多少？",
            True,
        ),
        (
            "The Standard usage model bill depends on request count.",
            "Example Product Free plan 的 Legacy 用量模式，本月账单准确是多少美元？",
            False,
        ),
        (
            "The Standard usage model bill depends on request count.",
            "Example Product Free plan 的 Standard 用量模式，本月账单准确是多少美元？",
            True,
        ),
    ],
)
async def test_quote_fallback_uses_actual_task_and_applicable_plan_or_mode(
    monkeypatch, source, question, applicable
):
    row, visible = await quote_transport_case(monkeypatch, source, question)
    assert row.resolution == "insufficient" and row.conclusion == "unknown"
    assert (source in row.answer) == applicable
    assert (source in visible) == applicable
    assert row.answer in visible


@pytest.mark.parametrize("source_plan,applicable", [("Free", True), ("Enterprise", False)])
def test_quote_rule_scope_inherits_only_the_uniquely_bound_parent_plan(source_plan, applicable):
    from test_literal_non_operation import draft
    from test_source_span_binding import spans

    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.question_scope import research_questions
    from packages.schema.models import DecisionBrief

    source = f"The {source_plan} plan includes a monthly request allowance."
    detail, snapshot = rule_case(source)
    detail.plan.decision_brief = DecisionBrief(
        decision_question=(
            "Example Product Free plan 已部署，可以继续讨论吗？ 本月账单准确是多少美元？"
        )
    )
    question = research_questions(detail, "Example Product", "feature")[-1]
    original = snapshot.facts[0]
    claim = ReportClaim(
        id="plan-rule", **draft(original, source), source_span_bindings=[spans(original)[0]]
    )
    row = server_missing_price_answers(
        detail,
        snapshot,
        [question],
        "Example Product",
        claims=[claim],
        delivery_policy=DELIVERY_POLICY,
        question_claim_whitelist={question["question_id"]: {claim.id}},
    )[question["question_id"]]
    assert (source in row["answer"]) == applicable
    assert "plan" not in row["missing_fields"]


CLASSIFICATION_TEXT = (
    "Reviewer 可以是可计费的 Workspace 成员或不可计费的单板访客，"
    "因此仅凭 Reviewer 标签无法确定他一定免费或一定计费。"
)
CLASSIFICATION_QUESTION = (
    "Example Product：只凭看板上的 Reviewer 标签，能否确定他一定免费或一定计费？"
)


@pytest.mark.parametrize(
    "source,eligible",
    [
        (
            "A Reviewer can be a billable Workspace member, or a non-billable single-board guest.",
            True,
        ),
        (
            "A Reviewer can be a billable Workspace member, or a non-billable single-board guest "
            "when approved.",
            False,
        ),
        (
            "A Reviewer can be a billable Workspace member, or a non-billable single-board guest "
            "provided the contract permits it.",
            False,
        ),
        (
            "A Reviewer can be a billable Workspace member. "
            "An Editor can be an employee or a non-billable single-board guest.",
            False,
        ),
        (
            'The following is a false example: "A Reviewer can be a billable Workspace member, '
            'or a non-billable single-board guest."',
            False,
        ),
        (
            "There are no limits to how many reviewers you can have on a board, and a Reviewer "
            "can be a billable\u00a0Workspace\u00a0member, or\nmulti-board guest\n, "
            "or a non-billable "
            "single-board guest.",
            True,
        ),
    ],
)
def test_classification_requires_a_complete_unconditional_same_label_rule(source, eligible):
    binding = SimpleNamespace(question_quote=CLASSIFICATION_QUESTION, conclusion="no")
    claim = dict(text=CLASSIFICATION_TEXT, kind="fact", source_span_bindings=[dict(quote=source)])
    assert classification_non_entailment(binding, [claim]) == eligible


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,text",
    [
        (
            "A Reviewer can be a billable Workspace member, or a non-billable single-board guest "
            "when approved.",
            "获批准时，" + CLASSIFICATION_TEXT,
        ),
        (
            "A Reviewer can be a billable Workspace member, or a non-billable single-board guest "
            "provided the contract permits it.",
            "合同允许时，" + CLASSIFICATION_TEXT,
        ),
        (
            "A Reviewer can be a billable Workspace member. "
            "An Editor can be an employee or a non-billable single-board guest.",
            "Reviewer 可以是可计费的 Workspace 成员；Editor 可以是员工或不可计费的单板访客，"
            "因此仅凭 Reviewer 标签无法确定他一定免费或一定计费。",
        ),
    ],
)
async def test_wrong_classification_cannot_become_no_through_independent_answer_and_replay(
    monkeypatch, source, text
):
    case = await atomic_case([source], question=CLASSIFICATION_QUESTION)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n")[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            ref = next(
                s["support_ref"]
                for f in payload["evidence_view"]["facts"]
                for s in f["source_span_candidates"]
                if s["quote"] == source
            )
            response = question_plan_response(
                payload, [dict(text=text, kind="fact", support_refs=[ref])]
            )
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = json.dumps({"reviews": [supported_review(payload["claims"][0])]})
        else:
            q = payload["questions"][0]
            ids = [c["id"] for c in payload["claims"]]
            response = json.dumps(
                {
                    "version": 3,
                    "answers": [
                        dict(
                            question_id=q["question_id"],
                            status="answered",
                            claim_ids=ids,
                            resolution="direct",
                            conclusion="no",
                            missing_fields=[],
                            reason="Candidate contrast.",
                            subquestions=[
                                dict(
                                    question_quote=q["question"],
                                    claim_ids=ids,
                                    conclusion="no",
                                    relation="classification_non_entailment",
                                )
                            ],
                        )
                    ],
                    "task_decisions": [],
                }
            )
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        answer_review_contract="subquestion-premises-v6",
        delivery_policy=DELIVERY_POLICY,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert len(audited) == 1 and audited[0].status == "supported", audited
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    rows, _, _ = await atomic.atomic_answer_coverage(
        service,
        record,
        packets[0]["questions"],
        result["compact"],
        [r.claim for r in audited],
        view,
        use,
        (),
        answer_review_contract="subquestion-premises-v6",
        audited=audited,
    )
    assert rows[0].status != "answered" and rows[0].conclusion != "no", rows
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["answers"][rows[0].question_id] == rows[0]
