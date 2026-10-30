"""Delivery regressions: exact missing-price answers remain visible and authenticated."""

import json
from types import SimpleNamespace

import pytest
from claim_review_fixture import question_plan_response
from test_incomplete_quote_answers import usage_case
from test_question_atomic_delivery import atomic_case

from packages.agents.writer.answer_presentation import question_coverage_lines
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.report_claims import ReportDimensionAudit

POLICY = "complete-predicates-v1"


@pytest.mark.asyncio
async def test_authority_task_keeps_complete_role_list_with_same_permission_wording():
    from packages.agents.writer import question_atomic_delivery as atomic

    source = (
        "Please note that only Workspace admins and board admins can change "
        "a board member’s status to reviewer."
    )
    case = await atomic_case(
        [source], question=("Example Product：谁有权将看板现有成员的权限状态改为 reviewer？")
    )
    service, record, _, _, view, use, packets, _, allowed = case
    payload = atomic.atomic_question_context(
        service,
        record,
        view,
        packets,
        packets[0]["questions"][0],
        allowed,
        use,
        generation_projection_version=5,
    )
    payload["delivery_policy"] = POLICY
    text = "只有 Workspace 管理员和看板管理员才能将看板成员的权限状态改为 reviewer。"
    response = question_plan_response(
        payload,
        [
            {
                "text": text,
                "kind": "fact",
                "support_refs": ["s1"],
            }
        ],
    )
    claims, _, _ = atomic.parse_atomic_generation(response, payload, view, use)
    assert [c.text for c in claims] == [text]
    assert claims[0].source_span_bindings[0].quote == source
    # The old source contract still rejects the old operation classification.
    legacy = dict(payload)
    legacy.pop("delivery_policy")
    assert atomic.parse_atomic_generation(response, legacy, view, use)[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["not_who", "missing_actor", "extra_action", "wrong_source"])
async def test_authority_exception_cannot_authorize_another_task_actor_or_action(change):
    from packages.agents.writer import question_atomic_delivery as atomic

    source = "Only Project owners and board admins can change a board member’s status to reviewer."
    question = (
        "Example Product：谁有权将看板现有成员的权限状态改为 reviewer？"
        if change != "not_who"
        else "Example Product：能将看板成员的权限状态改为 reviewer 吗？"
    )
    if change == "wrong_source":
        source = (
            "Only Project owners and board admins can change a board member’s status to editor."
        )
    case = await atomic_case([source], question=question)
    service, record, _, _, view, use, packets, _, allowed = case
    payload = atomic.atomic_question_context(
        service,
        record,
        view,
        packets,
        packets[0]["questions"][0],
        allowed,
        use,
        generation_projection_version=5,
        delivery_policy=POLICY,
    )
    text = "只有项目所有者和看板管理员才能将看板成员的权限状态改为 reviewer。"
    if change == "missing_actor":
        text = "只有看板管理员才能将看板成员的权限状态改为 reviewer。"
    elif change == "extra_action":
        text = text[:-1] + "并授予整个工作区的编辑权限。"
    response = question_plan_response(
        payload, [{"text": text, "kind": "fact", "support_refs": ["s1"]}]
    )
    assert atomic.parse_atomic_generation(response, payload, view, use)[0] == []


@pytest.mark.parametrize(
    "source,text,rejected",
    [
        ("Sharing is available with one other user.", "组织最多容纳 2 名用户。", True),
        ("Data sharing is available in up to two collections.", "组织最多容纳 2 名用户。", True),
        (
            "Data sharing is available in up to two collections.",
            "组织共享上限为 2 个 collections。",
            False,
        ),
        ("Organizations support up to two users.", "组织最多容纳 2 名用户。", False),
    ],
)
def test_numeric_modal_rejection_is_unit_local_and_never_establishes_support(
    source, text, rejected
):
    from packages.agents.writer.complete_predicates import unsupported_numeric_restriction

    assert unsupported_numeric_restriction(text, [source]) is rejected


def test_complete_predicate_review_rejects_maximum_invented_from_nonexclusive_count():
    from claim_review_fixture import supported_review
    from test_atomic_claim_review import selected_payload

    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    payload = selected_payload(
        ["Start a Basic organization to store and securely share data with one other user."]
    )
    payload["review_projection_version"] = 3
    payload["delivery_policy"] = POLICY
    payload["claims"][0]["text"] = "Basic organization 最多容纳 2 名用户。"
    row = supported_review(payload["claims"][0])
    row["support_witnesses"] = [
        {"support_index": 0, "quote": payload["claims"][0]["support_quotes"][0]}
    ]
    response = json.dumps({"reviews": [row]})
    legacy = dict(payload)
    legacy.pop("delivery_policy")
    assert (
        len(
            parse_atomic_reviews(
                response,
                [SimpleNamespace(id="download")],
                payload=legacy,
                review_projection_version=3,
            )
        )
        == 1
    )
    assert (
        parse_atomic_reviews(
            response, [SimpleNamespace(id="download")], payload=payload, review_projection_version=3
        )
        == []
    )


def test_quote_limitation_keeps_reviewed_non_cpu_rule_without_inventing_the_total():
    from test_incomplete_quote_answers import rule_case
    from test_literal_non_operation import draft
    from test_source_span_binding import spans

    from packages.agents.writer.price_answers import server_missing_price_answers
    from packages.research.evidence.report_claims import ReportClaim

    detail, snapshot = rule_case(
        "The Usage plan includes a monthly request allowance; usage above it is billed separately."
    )
    original = snapshot.facts[0]
    claim = ReportClaim(
        id="billing-rule",
        **draft(original, original.quote),
        source_span_bindings=[spans(original)[0]],
    )
    question = {
        "question_id": "q-price",
        "question": "Example Product Usage plan 本月有2300万次请求，账单准确是多少美元？",
    }
    row = server_missing_price_answers(
        detail,
        snapshot,
        [question],
        "Example Product",
        claims=[claim],
        delivery_policy=POLICY,
        question_claim_whitelist={"q-price": {claim.id}},
    )["q-price"]
    assert claim.text in row["answer"] and row["claim_ids"] == (claim.id,)
    assert "完整用量明细" in row["answer"]
    assert row["conclusion"] == "unknown" and row["resolution"] == "insufficient"
    other_task = server_missing_price_answers(
        detail,
        snapshot,
        [question],
        "Example Product",
        claims=[claim],
        delivery_policy=POLICY,
        question_claim_whitelist={"q-other-sku": {claim.id}},
    )["q-price"]
    assert claim.text not in other_task["answer"] and other_task["claim_ids"] == ()


@pytest.mark.asyncio
async def test_new_authority_admission_survives_actual_review_answer_and_strict_replay(monkeypatch):
    from claim_review_fixture import answer_response, expand_prompt_payload
    from test_question_atomic_delivery import supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import audit_report_claims

    source = (
        "Please note that only Project owners and board admins can change "
        "a board member’s status to reviewer."
    )
    text = "只有项目所有者和看板管理员才能将看板成员的权限状态改为 reviewer。"
    case = await atomic_case(
        [source], question="Example Product：谁有权将看板成员权限状态改为 reviewer？"
    )
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries

    async def model(record, **kwargs):
        body = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n")[1]))
        assert body["delivery_policy"] == POLICY
        if kwargs["name"] == atomic.GENERATION_NAME:
            response = question_plan_response(
                body, [{"text": text, "kind": "fact", "support_refs": ["s1"]}]
            )
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = json.dumps({"reviews": [supported_review(body["claims"][0])]})
        else:
            response = answer_response(
                body,
                {
                    "version": 3,
                    "answers": [
                        {
                            "question_id": body["questions"][0]["question_id"],
                            "status": "answered",
                            "claim_ids": [c["id"] for c in body["claims"]],
                            "resolution": "direct",
                            "conclusion": "yes",
                            "missing_fields": [],
                            "reason": "Complete role list.",
                        }
                    ],
                },
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
        delivery_policy=POLICY,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
        authority_claim_ids=result["authority_claim_ids"],
    )
    assert len(audited) == 1 and audited[0].status == "supported", audited
    assert (
        audit_report_claims(
            result["claims"],
            result["reviews"],
            view,
            boundaries,
            available_facts=view.facts,
            review_version=3,
        )[0].status
        == "rejected"
    )
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
    assert rows[0].status == "answered", rows
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
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay["authority_claim_ids"] == {audited[0].claim.id}
    assert replay["answers"][rows[0].question_id] == rows[0]
    from packages.agents.writer.answer_presentation import answer_decision_lines

    visible = "\n".join(
        answer_decision_lines(
            rows[0],
            "zh-CN",
            claims=[r.claim.model_dump(mode="json") for r in audited],
            answer_review_contract="subquestion-premises-v6",
            facts=view.facts,
            decision_review=replay["decision_review"][rows[0].question_id],
        )
    )
    assert "结论：是" not in visible and text in visible


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [POLICY, None])
async def test_reviewed_billing_classification_answers_label_non_entailment_instead_of_unknown(
    monkeypatch, policy
):
    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import audit_report_claims

    source = "A Reviewer can be a billable Workspace member, or a non-billable single-board guest."
    text = (
        "看板上的 Reviewer 可以是可计费的 Workspace 成员或不可计费的单板访客，"
        "因此仅凭 Reviewer 标签无法确定他一定免费或一定计费。"
    )
    question = "Example Product：只凭看板上的 Reviewer 标签，能否确定他一定免费或一定计费？"
    case = await atomic_case([source], question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries

    async def model(record, **kwargs):
        body = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n")[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            response = question_plan_response(
                body, [{"text": text, "kind": "fact", "support_refs": ["s1"]}]
            )
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = json.dumps({"reviews": [supported_review(body["claims"][0])]})
        else:
            q = body["questions"][0]
            ids = [c["id"] for c in body["claims"]]
            response = json.dumps(
                {
                    "version": 3,
                    "answers": [
                        {
                            "question_id": q["question_id"],
                            "status": "answered",
                            "claim_ids": ids,
                            "resolution": "direct",
                            "conclusion": "no",
                            "missing_fields": [],
                            "reason": "Label alone cannot distinguish the billing alternatives.",
                            "subquestions": [
                                {
                                    "question_quote": q["question"],
                                    "claim_ids": ids,
                                    "conclusion": "no",
                                    "relation": "classification_non_entailment",
                                }
                            ],
                        }
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
        delivery_policy=policy,
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
    if policy is None:
        assert rows[0].status == "unverified"
        return
    assert rows[0].status == "answered" and rows[0].conclusion == "no", rows
    assert text == rows[0].answer
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["answers"][rows[0].question_id] == rows[0]


def quote_audit():
    detail, snapshot = usage_case()
    from packages.agents.writer.price_answers import server_missing_price_answers

    row = ReportAnswerCoverage(
        **server_missing_price_answers(
            detail,
            snapshot,
            [
                {
                    "question_id": "q-price",
                    "question": ("Example Product Usage plan 本月有2300万次请求，"
                                 "账单准确是多少美元？"),
                }
            ],
            "Example Product",
            delivery_policy=POLICY,
        )["q-price"]
    )
    audit = ReportDimensionAudit(
        competitor="Example Product",
        dimension="pricing",
        consumption_id="price-use",
        claims=(),
        answer_coverage=(row,),
        claim_review_version=3,
        answer_binding_version=3,
        answer_review_contract="subquestion-premises-v6",
    )
    return detail, snapshot, audit, row


def test_snapshot_rebuilt_price_limitation_is_visible_under_atomic_answer_contract():
    detail, _, audit, row = quote_audit()
    lines = "\n".join(
        question_coverage_lines(
            audit,
            "zh-CN",
            detail=detail,
            decision_reviews={},
        )
    )
    assert row.answer in lines
    assert "CPU 总用量" in lines and "部分回答" in lines
    assert "本次已审核证据尚未完整覆盖此问题。" not in lines


def test_old_price_record_keeps_its_previous_rendering_contract():
    detail, snapshot, audit, _ = quote_audit()
    from packages.agents.writer.price_answers import server_missing_price_answers

    original = audit.answer_coverage[0]
    row = ReportAnswerCoverage(
        **server_missing_price_answers(
            detail,
            snapshot,
            [
                {
                    "question_id": original.question_id,
                    "question": original.question,
                }
            ],
            audit.competitor,
        )[original.question_id]
    )
    audit = audit.model_copy(update={"answer_coverage": (row,)})
    lines = "\n".join(question_coverage_lines(audit, "zh-CN", detail=detail, decision_reviews={}))
    assert row.answer not in lines
    assert "本次已审核证据尚未完整覆盖此问题。" in lines


@pytest.mark.parametrize("change", ["no_contrast", "other_label", "conditional", "actual_person"])
def test_classification_relation_requires_explicit_same_label_contrast(change):
    from packages.agents.writer.complete_predicates import classification_non_entailment

    question = "只凭 Reviewer 标签，能否确定他一定免费或一定计费？"
    source = "A Reviewer can be a billable member, or a non-billable guest."
    if change == "no_contrast":
        source = "A Reviewer can be a billable member."
    elif change == "other_label":
        source = source.replace("Reviewer", "Editor")
    elif change == "conditional":
        source = "If approved, " + source
    else:
        question = "这个 Reviewer 是否一定免费？"
    binding = SimpleNamespace(question_quote=question, conclusion="no")
    claim = {
        "kind": "fact",
        "text": "Reviewer 可以是可计费成员或不可计费访客，"
        "因此仅凭 Reviewer 标签无法确定他一定免费或一定计费。",
        "source_span_bindings": [{"quote": source}],
    }
    assert not classification_non_entailment(binding, [claim])


@pytest.mark.parametrize("change", ["text", "fields", "snapshot", "claims"])
def test_price_limitation_publication_rejects_unreconstructable_or_tampered_record(change):
    detail, _, audit, row = quote_audit()
    updates = {
        "text": {"answer": row.answer + " 所有用户免费。"},
        "fields": {"missing_fields": ()},
        "snapshot": {"basis_snapshot_id": "another-snapshot"},
        "claims": {"claim_ids": ("invented",)},
    }[change]
    row = row.model_copy(update=updates)
    audit = audit.model_copy(update={"answer_coverage": (row,)})
    lines = "\n".join(
        question_coverage_lines(
            audit,
            "zh-CN",
            detail=detail,
            decision_reviews={},
        )
    )
    assert row.answer not in lines
    assert "本次已审核证据尚未完整覆盖此问题。" in lines
