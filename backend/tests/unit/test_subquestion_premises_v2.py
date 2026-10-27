"""Finite v2 decisions keep legacy transports and public answer DTOs unchanged."""

import json

import pytest

from packages.agents.writer import question_atomic_delivery as atomic
from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

V1 = "subquestion-premises-v1"
V2 = "subquestion-premises-v2"


def branch(text, ids, *, relation="explicit_negative", conclusion="no"):
    return dict(question_quote=text, claim_ids=ids, relation=relation, conclusion=conclusion)


def parse(
    question,
    claims,
    branches,
    *,
    contract=V2,
    status="answered",
    resolution="direct",
    conclusion="no",
    fields=(),
    selected_ids=None,
):
    diagnostics = []
    response = json.dumps(
        dict(
            version=3,
            answers=[
                dict(
                    question_id="q",
                    status=status,
                    resolution=resolution,
                    conclusion=conclusion,
                    claim_ids=[c["id"] for c in claims] if selected_ids is None else selected_ids,
                    missing_fields=list(fields),
                    reason="Reviewed",
                    subquestions=branches,
                )
            ],
        )
    )
    result = parse_answer_coverage(
        response,
        [dict(question_id="q", question=question)],
        {c["id"] for c in claims},
        claims=claims,
        required_binding_version=3,
        require_subquestions=True,
        answer_review_contract=contract,
        diagnostics=diagnostics,
    )[0]
    return result, diagnostics


def test_actual_answer_system_selects_contract_and_preserves_old_system():
    old = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN")
    new = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN", answer_review_contract=V2)
    assert old != new
    assert atomic.answer_contract_from_system(old, "zh-CN") == V1
    assert atomic.answer_contract_from_system(new, "zh-CN") == V2
    with pytest.raises(ValueError):
        atomic.answer_contract_from_system(new + "changed", "zh-CN")


def test_cap_real_complete_sentence_has_independent_witness_and_legacy_stays_unverified():
    question = "Free organization 中3个人用3个collections共享密码，能满足吗？"
    claims = [
        dict(
            id="cap",
            kind="fact",
            text="Free organization 最多支持在 2 个 collections 中进行安全数据共享。",
        )
    ]
    b = [branch(question, ["cap"], relation="upper_bound")]
    result, diagnostics = parse(question, claims, b)
    assert result.status == "answered" and result.conclusion == "no"
    witness = diagnostics[0]["finite_witnesses"][0]
    assert (witness["kind"], witness["unit"], witness["maximum"], witness["required"]) == (
        "upper_bound",
        "collections",
        2,
        3,
    )
    assert not coverage_resolution_reasons(result, claims, answer_review_contract=V2)
    assert parse(question, claims, b, contract=V1)[0].status == "unverified"
    assert ReportAnswerCoverage.model_validate_json(result.model_dump_json()) == result


def test_mislabeled_permission_has_explicit_finite_adjustment_not_universal_no_duty():
    question = "B允许投票，是否意味着他必须给每张卡片投票？"
    claims = [
        dict(
            id="permission",
            kind="inference",
            text=("Observer 在已启用投票的看板上被允许投票，仅表示拥有投票权限，"
                  "并不构成必须投票的强制义务。"),
        )
    ]
    result, diagnostics = parse(question, claims, [branch(question, ["permission"])])
    assert result.status == "answered"
    assert result.subquestion_bindings[0].relation == "permission_entailment"
    adjustment = next(a for a in diagnostics[0]["adjustments"] if a["kind"] == "relation_restored")
    assert adjustment["original_relation"] == "explicit_negative"
    assert adjustment["applied_relation"] == "permission_entailment"
    assert (
        parse(question, claims, [branch(question, ["permission"])], contract=V1)[0].status
        == "unverified"
    )
    actual = "他是否必须给每张卡片投票？"
    assert parse(actual, claims, [branch(actual, ["permission"])])[0].status == "unverified"


def test_single_vault_cap_and_one_separator_reconstruct_without_changing_public_schema():
    question = "访客已被确认。他能同时加入两个共享保险库，或者拥有自己的Private vault吗？"
    claims = [
        dict(
            id="cap",
            kind="fact",
            text="访客一次只能被邀请加入一个保险库，但可以先移除再加入另一个保险库。",
        ),
        dict(id="private", kind="fact", text="访客没有自己的Private vault。"),
    ]
    b = [
        branch("访客已被确认。他能同时加入两个共享保险库", ["cap"]),
        branch("或者拥有自己的Private vault吗？", ["private"]),
    ]
    result, diagnostics = parse(question, claims, b)
    assert result.status == "answered"
    assert result.subquestion_bindings[0].question_quote.endswith("，")
    assert result.subquestion_bindings[0].relation == "upper_bound"
    assert {a["kind"] for a in diagnostics[0]["adjustments"]} == {
        "separator_restored",
        "relation_restored",
    }
    assert parse(question, claims, b, contract=V1)[0].status == "unverified"


def test_invalid_clarification_keeps_independently_valid_peer_and_unknown_gap():
    question = "仅依据所给页面，逐项回答：能否在Workspace统一设为Observer；成员计费是多少？"
    claims = [
        dict(
            id="rule",
            kind="fact",
            text="无法在Workspace层级将用户统一设置为Observer，每位Observer按看板设置。",
        )
    ]
    b = [
        branch("仅依据所给页面，逐项回答：能否在Workspace统一设为Observer；", ["rule"]),
        branch("成员计费是多少？", [], relation="unresolved", conclusion="unknown"),
    ]
    result, diagnostics = parse(
        question,
        claims,
        b,
        status="partial",
        resolution="clarification",
        conclusion="depends",
        fields=["data_ownership"],
    )
    assert (result.status, result.resolution, result.conclusion) == (
        "partial",
        "conditional",
        "depends",
    )
    assert result.claim_ids == ("rule",) and result.missing_fields == ()
    assert [b.conclusion for b in result.subquestion_bindings] == ["no", "unknown"]
    assert any(a["kind"] == "invalid_clarification_omitted" for a in diagnostics[0]["adjustments"])


@pytest.mark.parametrize(
    "text",
    [
        "Free organization 最少支持在2个collections中共享。",
        "Free organization 并非最多支持在2个collections中共享。",
        "如果管理员批准，Free organization 最多支持在2个collections中共享。",
        "建议Free organization 最多支持在2个collections中共享。",
        "Paid organization 最多支持在2个collections中共享。",
        "不能认定Free organization 最多支持在2个collections中共享。",
        "Free organization 可能最多支持在2个collections中共享。",
        "It is unconfirmed that Free organization supports at most 2 collections for sharing.",
    ],
)
def test_finite_cap_does_not_launder_minimum_negation_condition_advice_or_other_plan(text):
    q = "Free organization能用3个collections共享吗？"
    result, _ = parse(q, [dict(id="c", text=text, kind="fact")], [branch(q, ["c"])])
    assert result.status == "unverified"


@pytest.mark.parametrize(
    "question",
    [
        "Free organization能用2个collections共享吗？",
        "Free organization能用3个人共享吗？",
    ],
)
def test_cap_requires_strict_same_unit_excess(question):
    claims = [dict(id="c", text="Free organization 最多支持在2个collections中共享。", kind="fact")]
    assert (
        parse(question, claims, [branch(question, ["c"], relation="upper_bound")])[0].status
        == "unverified"
    )


def test_true_page_object_is_not_removed_by_source_instruction_handling():
    q = "仅依据所给页面，逐项回答：访客能编辑页面吗？"
    claims = [dict(id="c", kind="fact", text="访客不能编辑看板。")]
    assert parse(q, claims, [branch(q, ["c"])])[0].status == "unverified"


@pytest.mark.parametrize(
    "left,right",
    [
        ("访客能访问两个保险库", "或者拥有自己的Private vault吗？"),
        ("访客能同时访问两个保险库", "者拥有自己的Private vault吗？"),
    ],
)
def test_partition_restoration_never_restores_words_or_conditions(left, right):
    q = "访客能同时访问两个保险库，或者拥有自己的Private vault吗？"
    claims = [dict(id="c", text="访客不能访问保险库或拥有自己的Private vault。", kind="fact")]
    assert parse(q, claims, [branch(left, ["c"]), branch(right, ["c"])])[0].status == "unverified"


@pytest.mark.parametrize("parent_bad_id", [False, True])
def test_bad_branch_reference_is_removed_without_erasing_valid_peer(parent_bad_id):
    q = "访客能下载附件吗？能导出看板吗？"
    claims = [dict(id="yes", text="访客可以下载附件。", kind="fact")]
    result, diagnostics = parse(
        q,
        claims,
        [
            branch("访客能下载附件吗？", ["yes"], relation="direct", conclusion="yes"),
            branch("能导出看板吗？", ["unpublished"]),
        ],
        conclusion="depends",
        selected_ids=["yes", "unpublished"] if parent_bad_id else None,
    )
    assert result.status == "partial" and result.claim_ids == ("yes",)
    assert result.subquestion_bindings[-1].claim_ids == ()
    assert result.subquestion_bindings[-1].conclusion == "unknown"
    assert any(a["kind"] == "branch_demoted" for a in diagnostics[0]["adjustments"])


@pytest.mark.parametrize(
    "question,text",
    [
        (
            "Free organization能用3个collections或拥有一个Private vault吗？",
            "Free organization最多支持在2个collections中共享。",
        ),
        (
            "Free organization不能用3个collections共享吗？",
            "Free organization最多支持在2个collections中共享。",
        ),
        ("Workspace A能用3个collections共享吗？", "Workspace B最多支持在2个collections中共享。"),
        (
            "Free organization能用3个collections共享吗？",
            "例如Free organization最多支持在2个collections中共享。",
        ),
        (
            "Free organization能用3个collections共享吗？",
            "‘Free organization最多支持在2个collections中共享。’",
        ),
        (
            "Free organization能用3个collections共享吗？",
            "Free organization不只是最多支持在2个collections中共享。",
        ),
    ],
)
def test_finite_witness_rejects_unresolved_or_outer_negation_named_scope_and_examples(
    question, text
):
    result, _ = parse(
        question,
        [dict(id="c", kind="fact", text=text)],
        [branch(question, ["c"], relation="upper_bound")],
    )
    assert result.status == "unverified"


def test_permission_witness_does_not_bind_an_unrelated_action():
    q = "B允许导出，是否意味着他必须给每张卡片投票？"
    claims = [dict(id="c", kind="fact", text="Observer可以投票。")]
    assert (
        parse(q, claims, [branch(q, ["c"], relation="permission_entailment")])[0].status
        == "unverified"
    )


def test_borrowed_peer_claim_is_demoted_locally_using_current_question_whitelist():
    q = "访客能下载附件吗？能导出看板吗？"
    claims = [
        dict(id="yes", text="访客可以下载附件。", kind="fact"),
        dict(id="borrowed", text="访客不能导出看板。", kind="fact"),
    ]
    response = json.dumps(
        dict(
            version=3,
            answers=[
                dict(
                    question_id="q",
                    status="answered",
                    resolution="direct",
                    conclusion="depends",
                    missing_fields=[],
                    reason="Reviewed",
                    claim_ids=["yes", "borrowed"],
                    subquestions=[
                        branch("访客能下载附件吗？", ["yes"], relation="direct", conclusion="yes"),
                        branch("能导出看板吗？", ["borrowed"]),
                    ],
                )
            ],
        )
    )
    row = parse_answer_coverage(
        response,
        [dict(question_id="q", question=q)],
        {"yes", "borrowed"},
        claims=claims,
        required_binding_version=3,
        require_subquestions=True,
        answer_review_contract=V2,
        question_claim_whitelist={"q": {"yes"}},
    )[0]
    assert row.status == "partial" and row.claim_ids == ("yes",)
    assert row.subquestion_bindings[-1].conclusion == "unknown"


@pytest.mark.parametrize(
    "question,text",
    [
        ("访客能同时删除两个共享保险库吗？", "访客一次只能被邀请加入一个保险库。"),
        (
            "Free organization能编辑3个collections吗？",
            "Free organization最多支持在2个collections中共享。",
        ),
    ],
)
def test_count_cap_cannot_change_the_bound_operation(question, text):
    assert (
        parse(
            question,
            [dict(id="c", kind="fact", text=text)],
            [branch(question, ["c"], relation="upper_bound")],
        )[0].status
        == "unverified"
    )


@pytest.mark.asyncio
async def test_v2_complete_transport_render_replay_and_downgrade_rejection(monkeypatch):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.qa.independent_question_review import _question_context
    from packages.agents.qa.question_context import question_delivery_complete
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    cap = "Free organization 最多支持在 2 个 collections 中进行安全数据共享。"
    case = await atomic_case(
        [cap], question="Example Product: Free organization能用3个collections共享吗？"
    )
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    seen = []
    original_preflight = atomic._current_request_preflight

    def checked_preflight(service, record, scope, question_ids, request, **kwargs):
        for name, _, system, user, _ in (request, *kwargs.get("future_requests", ())):
            if name == atomic.ANSWER_NAME:
                assert system == atomic.atomic_system(name, record.detail.output_language,
                                                      answer_review_contract=V2)
                payload = expand_prompt_payload(json.loads(user.split("\nJSON:\n", 1)[1]))
                assert payload["answer_review_contract"] == V2
        return original_preflight(service, record, scope, question_ids, request, **kwargs)

    monkeypatch.setattr(atomic, "_current_request_preflight", checked_preflight)

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append(kwargs["name"])
        if kwargs["name"] == atomic.GENERATION_NAME:
            span = next(
                s
                for fact in payload["evidence_view"]["facts"]
                for s in fact.get("source_span_candidates", [])
                if s["quote"] == cap
            )
            output = question_plan_response(
                payload, [dict(text=cap, kind="fact", support_refs=[span["support_ref"]])]
            )
        elif kwargs["name"] == atomic.REVIEW_NAME:
            output = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        else:
            q = payload["questions"][0]
            ids = [c["id"] for c in payload["claims"]]
            output = json.dumps(
                dict(
                    version=3,
                    answers=[
                        dict(
                            question_id=q["question_id"],
                            status="answered",
                            resolution="direct",
                            conclusion="no",
                            claim_ids=ids,
                            reason="Reviewed",
                            missing_fields=[],
                            subquestions=[branch(q["question"], ids)],
                        )
                    ],
                )
            )
        return append_response(service, record, kwargs, output)

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
        answer_review_contract=V2,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert len(audited) == 1 and audited[0].status == "supported"
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await atomic.atomic_answer_coverage(
        service,
        record,
        packets[0]["questions"],
        result["compact"],
        [c.claim for c in audited],
        view,
        use,
        (),
        answer_review_contract=V2,
    )
    assert answers[0].status == "answered" and answers[0].conclusion == "no"
    audit = ReportDimensionAudit(
        competitor=view.competitor,
        dimension=view.dimension,
        consumption_id=use.id,
        claims=audited,
        answer_coverage=answers,
        answer_binding_version=3,
        claim_review_version=3,
        answer_review_contract=V2,
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"],
    )
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert tuple(replay["answers"].values()) == answers
    q = packets[0]["questions"][0]
    complete = question_delivery_complete(service, record.detail, snapshot, audit, q)
    assert complete
    context = _question_context(
        service, record, snapshot, q, audit, verified=complete, producer_verified=True
    )
    assert context["publication_matches"] and context["support_verified"]
    assert cap in context["visible_answer"] and "结论：否" in context["visible_answer"]
    assert seen == [atomic.GENERATION_NAME, atomic.REVIEW_NAME, atomic.ANSWER_NAME]
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    for mutation in ("contract", "validation", "witness", "audit_contract"):
        clone = record.detail.model_copy(deep=True)
        target = next(s for s in clone.trace_spans if s.id == receipt_span.id)
        receipt = json.loads(target.full_output)
        dispatch = next(d for d in receipt["dispatches"] if d["name"] == atomic.ANSWER_NAME)
        changed_audit = audit
        if mutation == "contract":
            receipt.pop("answer_review_contract")
        elif mutation == "validation":
            dispatch.pop("answer_validation")
        elif mutation == "witness":
            dispatch["answer_validation"][0]["finite_witnesses"][0]["maximum"] = 99
        else:
            changed_audit = audit.model_copy(update=dict(answer_review_contract=V1))
        target.full_output = json.dumps(receipt)
        changed_audit = changed_audit.model_copy(
            update=dict(question_atomic_receipt_digest=atomic.digest(receipt))
        )
        with pytest.raises(ValueError):
            atomic.replay_atomic_delivery(service, clone, snapshot, use, view, audit=changed_audit)


@pytest.mark.parametrize(
    "conclusion,relation",
    [
        ("unknown", "unresolved"),
        ("yes", "unresolved"),
        ("no", "unresolved"),
        ("unknown", "direct"),
    ],
)
def test_unresolved_branch_cannot_publish_its_claims(conclusion, relation):
    question = "访客能下载附件吗？能导出看板吗？"
    claims = [
        dict(id="download", kind="fact", text="访客可以下载附件。"),
        dict(id="unrelated", kind="fact", text="访客可以投票。"),
    ]
    row, _ = parse(
        question,
        claims,
        [
            branch("访客能下载附件吗？", ["download"], relation="direct", conclusion="yes"),
            branch("能导出看板吗？", ["unrelated"], relation=relation, conclusion=conclusion),
        ],
        status="partial",
        conclusion="depends",
    )
    assert (row.status, row.resolution, row.conclusion) == ("partial", "conditional", "depends")
    assert row.claim_ids == ("download",) and row.answer == claims[0]["text"]
    assert [span.claim_id for span in row.evidence_spans] == ["download"]
    assert row.subquestion_bindings[-1].claim_ids == ()
    assert row.subquestion_bindings[-1].conclusion == "unknown"
    assert row.subquestion_bindings[-1].relation == "unresolved"


def test_clearing_unknown_branch_keeps_id_selected_by_an_independent_valid_branch():
    question = "访客能下载附件吗？能导出看板吗？"
    claims = [dict(id="download", kind="fact", text="访客可以下载附件。")]
    row, _ = parse(
        question,
        claims,
        [
            branch("访客能下载附件吗？", ["download"], relation="direct", conclusion="yes"),
            branch("能导出看板吗？", ["download"], relation="unresolved", conclusion="unknown"),
        ],
        status="partial",
        conclusion="depends",
    )
    assert row.status == "partial" and row.claim_ids == ("download",)
    assert row.subquestion_bindings[0].claim_ids == ("download",)
    assert row.subquestion_bindings[1].claim_ids == ()


def test_all_unknown_with_claims_stays_unverified_without_an_answer():
    question = "访客能导出看板吗？"
    claims = [dict(id="unrelated", kind="fact", text="访客可以投票。")]
    row, _ = parse(
        question,
        claims,
        [
            branch(question, ["unrelated"], relation="unresolved", conclusion="unknown"),
        ],
        status="partial",
        conclusion="depends",
    )
    assert row.status == "unverified" and not row.answer and not row.claim_ids


@pytest.mark.asyncio
async def test_unknown_branch_claim_is_absent_from_production_answer_and_qa(monkeypatch):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.qa.independent_question_review import _question_context
    from packages.agents.qa.question_context import question_delivery_complete
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    texts = ["访客可以下载附件。", "访客可以导出附件。"]
    case = await atomic_case(texts, question="Example Product：访客能下载附件，能导出看板吗？")
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    seen = []

    async def model(record, **kwargs):
        seen.append(kwargs["name"])
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            atoms = [
                dict(text=s["quote"], kind="fact", support_refs=[s["support_ref"]])
                for fact in payload["evidence_view"]["facts"]
                for s in fact.get("source_span_candidates", [])
            ]
            output = question_plan_response(payload, atoms)
        elif kwargs["name"] == atomic.REVIEW_NAME:
            output = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        else:
            assert kwargs["name"] == atomic.ANSWER_NAME
            q = payload["questions"][0]
            ids = {c["text"]: c["id"] for c in payload["claims"]}
            output = json.dumps(
                dict(
                    version=3,
                    answers=[
                        dict(
                            question_id=q["question_id"],
                            status="partial",
                            resolution="conditional",
                            conclusion="depends",
                            claim_ids=[ids[t] for t in texts],
                            missing_fields=[],
                            reason="Reviewed",
                            subquestions=[
                                branch(
                                    q["question"][: -len("能导出看板吗？")],
                                    [ids[texts[0]]],
                                    relation="direct",
                                    conclusion="yes",
                                ),
                                branch(
                                    "能导出看板吗？",
                                    [ids[texts[1]]],
                                    relation="unresolved",
                                    conclusion="unknown",
                                ),
                            ],
                        )
                    ],
                )
            )
        return append_response(service, record, kwargs, output)

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
        answer_review_contract=V2,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert len(audited) == 2 and all(c.status == "supported" for c in audited)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await atomic.atomic_answer_coverage(
        service,
        record,
        packets[0]["questions"],
        result["compact"],
        [c.claim for c in audited],
        view,
        use,
        (),
        answer_review_contract=V2,
    )
    answer = answers[0]
    assert answer.status == "partial" and answer.answer == texts[0]
    assert texts[1] not in answer.answer and answer.subquestion_bindings[-1].claim_ids == ()
    audit = ReportDimensionAudit(
        competitor=view.competitor,
        dimension=view.dimension,
        consumption_id=use.id,
        claims=audited,
        answer_coverage=answers,
        answer_binding_version=3,
        claim_review_version=3,
        answer_review_contract=V2,
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"],
    )
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert tuple(replay["answers"].values()) == answers
    assert replay["reviews"] == result["reviews"]
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    producer_verified = service._final_qa_producer_verified(record, snapshot)
    assert producer_verified
    q = packets[0]["questions"][0]
    complete = question_delivery_complete(service, record.detail, snapshot, audit, q)
    support = _answer_support(record.detail, snapshot, audit, answer, q)
    context = _question_context(
        service, record, snapshot, q, audit, verified=complete, producer_verified=producer_verified
    )
    assert support is not None and [c.text for c in support] == texts[:1]
    assert context["publication_matches"] and context["support_verified"]
    assert texts[0] in context["visible_answer"] and texts[1] not in context["visible_answer"]
    assert "结论：尚不能确定" in context["visible_answer"]
    assert [c["text"] for c in context["claims"]] == texts[:1]
    assert seen == [
        atomic.GENERATION_NAME,
        atomic.REVIEW_NAME,
        atomic.REVIEW_NAME,
        atomic.ANSWER_NAME,
    ]


@pytest.mark.parametrize("export_text", ["查看者可以导出看板。", "访客可以导出文档。"])
def test_branch_scope_cannot_borrow_role_or_object_from_a_valid_peer(export_text):
    from packages.agents.writer.answer_presentation import answer_decision_lines

    question = "访客是否可以下载文档？访客是否可以导出看板？"
    claims = [
        dict(id="download", kind="fact", text="访客可以下载文档。"),
        dict(id="export", kind="fact", text=export_text),
    ]
    row, diagnostics = parse(
        question,
        claims,
        [
            branch("访客是否可以下载文档？", ["download"], relation="direct", conclusion="yes"),
            branch("访客是否可以导出看板？", ["export"], relation="direct", conclusion="yes"),
        ],
        conclusion="yes",
    )
    assert (row.status, row.resolution, row.conclusion) == ("partial", "conditional", "depends")
    assert row.claim_ids == ("download",) and row.answer == claims[0]["text"]
    assert row.subquestion_bindings[0].claim_ids == ("download",)
    invalid = row.subquestion_bindings[1]
    assert (invalid.claim_ids, invalid.conclusion, invalid.relation) == (
        (), "unknown", "unresolved"
    )
    assert any(a["kind"] == "branch_demoted" for a in diagnostics[0]["adjustments"])
    visible = "\n".join(answer_decision_lines(row, "zh-CN", claims=claims,
                                             answer_review_contract=V2))
    assert "访客是否可以导出看板？ — 结论：尚不能确定" in visible
    assert "访客是否可以导出看板？ — 结论：是" not in visible


def test_same_role_and_object_branches_remain_answered():
    question = "访客是否可以下载文档？访客是否可以导出看板？"
    claims = [
        dict(id="download", kind="fact", text="访客可以下载文档。"),
        dict(id="export", kind="fact", text="访客可以导出看板。"),
    ]
    row, diagnostics = parse(
        question,
        claims,
        [
            branch("访客是否可以下载文档？", ["download"], relation="direct", conclusion="yes"),
            branch("访客是否可以导出看板？", ["export"], relation="direct", conclusion="yes"),
        ],
        conclusion="yes",
    )
    assert row.status == "answered" and row.conclusion == "yes"
    assert row.claim_ids == ("download", "export")
    assert diagnostics[0]["adjustments"] == []
