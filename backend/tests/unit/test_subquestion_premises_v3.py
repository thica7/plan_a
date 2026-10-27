"""V3 binds a cap's explicit same-fact restatement to its complete action premise."""

import hashlib
import json

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response
from test_question_atomic_delivery import atomic_case, supported_review
from test_subquestion_premises_v2 import V1, V2, branch, parse
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic
from packages.agents.writer.answer_coverage import coverage_resolution_reasons

V3 = "subquestion-premises-v3"
CAP = ("Bitwarden Free 组织允许用户与另外一位用户存储并安全共享数据，"
       "即免费组织最多支持 2 名用户（含所有者）。")
QUESTION = ("Bitwarden: 我们都在 2026 年新建了 Bitwarden 账户，并建立一个 Free organization，"
            "想让包括我在内的 3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？")
QUALIFIED_CAPS = [prefix + "Bitwarden Free 组织允许用户共享数据，即免费组织最多支持 2 名用户。"
                  for prefix in ("仅统计活跃用户，", "每个团队分别计算，",
                                 "以下仅适用于活跃用户，", "针对管理员账户，",
                                 "每个团队分别计算；", "以下仅适用于活跃用户。",
                                 "针对管理员账户\n")]


def decide(question=QUESTION, text=CAP, *, kind="fact", contract=V3):
    return parse(question, [dict(id="cap", kind=kind, text=text)],
                 [branch(question, ["cap"], relation="upper_bound")], contract=contract)


def test_real_published_cap_keeps_no_with_complete_restatement_witness():
    result, diagnostics = decide()
    assert (result.status, result.conclusion) == ("answered", "no"), result.reason
    assert result.answer == CAP
    witness = diagnostics[0]["finite_witnesses"][0]
    assert (witness["unit"], witness["maximum"], witness["required"]) == ("people", 2, 3)
    assert witness["cap_sentence"] == CAP
    assert witness["action_antecedent_quote"] == CAP.split("，即")[0]
    assert witness["cap_clause_quote"] == "免费组织最多支持 2 名用户（含所有者）。"
    assert witness["restatement_quote"] == "即"
    assert not coverage_resolution_reasons(result, [dict(id="cap", kind="fact", text=CAP)],
                                          answer_review_contract=V3)
    assert decide(contract=V2)[0].status == "unverified"


@pytest.mark.parametrize("marker", ["即", "i.e.", "that is"])
def test_restatement_is_product_and_number_independent(marker):
    q = "Aster: Free organization 能让7名用户共享数据吗？"
    text = ("Aster Free organization 允许用户与其他用户共享数据，"
            f"{marker} 免费组织最多支持4名用户。")
    result, diagnostics = decide(q, text)
    assert result.status == "answered", result.reason
    witness = diagnostics[0]["finite_witnesses"][0]
    assert (witness["maximum"], witness["required"], witness["restatement_quote"]) == (
        4, 7, marker)


def test_english_same_population_synonyms_keep_complete_cap_and_action_quotes():
    q = "Aster: Can a Free organization allow 7 people to share data?"
    text = ("Aster Free organization allows users to securely share data with other users, "
            "i.e. Free organization supports at most 4 users (including the owner).")
    result, diagnostics = decide(q, text)
    assert result.status == "answered", result.reason
    witness = diagnostics[0]["finite_witnesses"][0]
    assert witness["cap_sentence"] == text and witness["unit"] == "people"
    assert witness["action_antecedent_quote"] == text.split(", i.e.")[0]


def test_v3_canonical_restores_the_relation_and_keeps_a_missing_peer_unknown():
    first = "Aster: Free organization能让7名用户共享数据吗？"
    q = first + "月费是多少？"
    text = "Aster Free organization 允许用户共享数据，即免费组织最多支持4名用户。"
    claims = [dict(id="cap", kind="fact", text=text)]
    result, diagnostics = parse(q, claims, [branch(first, ["cap"]),
        branch("月费是多少？", [], relation="unresolved", conclusion="unknown")],
        status="partial", resolution="conditional", conclusion="depends", contract=V3)
    assert (result.status, result.conclusion, result.claim_ids) == ("partial", "depends", ("cap",))
    assert result.subquestion_bindings[0].relation == "upper_bound"
    assert result.subquestion_bindings[1].conclusion == "unknown"
    assert diagnostics[0]["adjustments"][0]["kind"] == "relation_restored"


@pytest.mark.parametrize("text", [
    CAP.replace("即", ""),
    CAP.replace("，即", "。即"),
    CAP.replace("，即", "；即"),
    CAP.replace("，即", "，另外的套餐允许编辑，即"),
    CAP.replace("即免费组织", "即 Aster Free organization"),
    CAP.replace("即免费组织", "即付费组织"),
    CAP.replace("即免费组织", "即 Premium organization"),
    CAP.replace("即免费组织", "即免费工作区"),
    CAP.replace("即免费组织", "即免费团队"),
    CAP.replace("组织允许用户", "组织允许访客"),
    CAP.replace("即免费组织", "即管理员的免费组织"),
    CAP.replace("即免费组织", "即访客的免费组织"),
    CAP.replace("即免费组织", "即免费组织 B"),
    CAP.replace("安全共享数据", "编辑文档"),
    CAP.replace("2 名用户", "2 个 collections"),
    "如果管理员批准，" + CAP,
    "建议" + CAP,
    "例如" + CAP,
    "并非" + CAP,
    "尚未核实" + CAP,
    CAP.replace("最多支持", "最少支持"),
    CAP.replace("最多支持", "并非最多支持"),
    CAP.replace("最多支持", "可能最多支持"),
    CAP.replace("允许用户", "允许外部审计员"),
    CAP.replace("与另外一位用户", "与外部审计员"),
    CAP.replace("用户存储", "用户在试用套餐中存储"),
    CAP.replace("（含所有者）", "（仅管理员）"),
    CAP.replace("最多支持", "一次最多支持"),
])
def test_restatement_never_borrows_unknown_or_conflicting_scope(text):
    result, diagnostics = decide(text=text)
    assert result.status == "unverified", (text, result)
    assert not diagnostics or not diagnostics[0]["finite_witnesses"]


@pytest.mark.parametrize("question", [
    QUESTION.replace("3 个人", "2 个人"),
    QUESTION.replace("3 个人", "1 个人"),
    QUESTION.replace("3 个人", "3 个容器"),
    QUESTION.replace("共享密码", "编辑密码"),
    QUESTION.replace("共享密码", "共享密码或编辑文档"),
    QUESTION.replace("Bitwarden", "Aster"),
    QUESTION.replace("Free organization", "Premium organization").replace("免费组织", "付费组织"),
])
def test_restatement_still_requires_strict_same_unit_operation_and_and_semantics(question):
    assert decide(question)[0].status == "unverified"


def test_inference_and_separate_atoms_cannot_supply_the_cap_action_bridge():
    assert decide(kind="inference")[0].status == "unverified"
    claims = [dict(id="action", kind="fact", text=CAP.split("，即")[0] + "。"),
              dict(id="cap", kind="fact", text="免费组织最多支持 2 名用户（含所有者）。")]
    result, _ = parse(QUESTION, claims,
                      [branch(QUESTION, ["action", "cap"], relation="upper_bound")], contract=V3)
    assert result.status == "unverified"


@pytest.mark.parametrize("suffix", [
    "（不含所有者）", "（只统计活跃用户）", "（每个团队分别计算）",
    "，每个团队分别计算", " excluding the owner", " (active users only)",
])
def test_restatement_cap_preserves_the_requested_count_population(suffix):
    text = "Bitwarden Free 组织允许用户共享数据，即免费组织最多支持 2 名用户" + suffix + "。"
    assert decide(text=text)[0].status == "unverified"


@pytest.mark.parametrize("text", QUALIFIED_CAPS)
def test_restatement_requires_the_entire_fact_antecedent_to_match(text):
    result, diagnostics = decide(text=text)
    assert result.status == "unverified", (text, result)
    assert not diagnostics[0]["finite_witnesses"]
    assert decide(text=text, contract=V2)[0].status == "unverified"


def test_v3_transport_has_explicit_identity_and_legacy_systems_are_unchanged():
    frozen = {
        V1: "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb",
        V2: "58946566e4de82459bd322f9a2f879f993b6fd874516037ab44589939fcfb0ae",
    }
    for contract, expected in frozen.items():
        system = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN", answer_review_contract=contract)
        assert hashlib.sha256(system.encode()).hexdigest() == expected
        assert atomic.answer_contract_from_system(system, "zh-CN") == contract
    system = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN", answer_review_contract=V3)
    assert "Server subquestion premises v3." in system
    assert atomic.answer_contract_from_system(system, "zh-CN") == V3
    with pytest.raises(ValueError):
        atomic.answer_contract_from_system(system + "changed", "zh-CN")
    assert decide(contract="subquestion-premises-v99")[0].status == "unverified"


@pytest.mark.asyncio
# Multiline originals are covered above; claim generation rejects newlines earlier.
@pytest.mark.parametrize("cap,eligible", [
    (CAP, True), *[(text, False) for text in QUALIFIED_CAPS if "\n" not in text]])
async def test_v3_real_cap_survives_publication_render_replay_and_tamper_checks(
    monkeypatch, cap, eligible,
):
    from packages.agents.qa.independent_question_review import _question_context
    from packages.agents.qa.question_context import question_delivery_complete
    from packages.agents.qa.question_reconciliation import _answer_support, _basis
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    # The fixture's research product is anonymous; the complete real statement is unchanged.
    case = await atomic_case([cap], question="Example Product: " + QUESTION)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    seen = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append(kwargs["name"])
        if kwargs["name"] == atomic.GENERATION_NAME:
            span = next(s for fact in payload["evidence_view"]["facts"]
                        for s in fact["source_span_candidates"] if s["quote"] == cap)
            response = question_plan_response(payload,
                [dict(text=cap, kind="fact", support_refs=[span["support_ref"]])])
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        else:
            assert kwargs["name"] == atomic.ANSWER_NAME
            assert payload["answer_review_contract"] == V3
            assert kwargs["system"] == atomic.atomic_system(atomic.ANSWER_NAME,
                record.detail.output_language, answer_review_contract=V3)
            question = payload["questions"][0]
            ids = [c["id"] for c in payload["claims"]]
            response = json.dumps(dict(version=3, answers=[dict(
                question_id=question["question_id"], status="answered", resolution="direct",
                conclusion="no", claim_ids=ids, missing_fields=[], reason="Reviewed",
                subquestions=[branch(question["question"], ids, relation="upper_bound")])]))
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service, record, selected, view, use, packets[0]["questions"], packets,
        allowed, boundaries, (), answer_review_contract=V3)
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                                 available_facts=view.facts, review_version=3)
    assert len(audited) == 1 and audited[0].status == "supported", (audited, result["gaps"])
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await atomic.atomic_answer_coverage(
        service, record, packets[0]["questions"], result["compact"],
        [row.claim for row in audited], view, use, (), answer_review_contract=V3)
    assert (answers[0].status, answers[0].conclusion) == (
        ("answered", "no") if eligible else ("unverified", "unknown")), answers
    audit = ReportDimensionAudit(competitor=view.competitor, dimension=view.dimension,
        consumption_id=use.id, claims=audited, answer_coverage=answers,
        answer_binding_version=3, claim_review_version=3, answer_review_contract=V3,
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"])
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert tuple(replay["answers"].values()) == answers
    q = packets[0]["questions"][0]
    complete = question_delivery_complete(service, record.detail, snapshot, audit, q)
    if not eligible:
        assert _answer_support(record.detail, snapshot, audit, answers[0], q) is None
        assert "结论：否" not in record.detail.report_md
        assert seen[-1] == atomic.ANSWER_NAME
        return
    assert complete
    context = _question_context(service, record, snapshot, q, audit,
                                verified=complete, producer_verified=True)
    assert context["publication_matches"] and context["support_verified"]
    assert cap in context["visible_answer"] and "结论：否" in context["visible_answer"]
    assert _answer_support(record.detail, snapshot, audit, answers[0], q)
    assert ReportDimensionAudit.model_validate_json(audit.model_dump_json()) == audit
    original_basis = _basis(service, record, snapshot)
    changed_record = type(record)(**vars(record))
    changed_record.detail = record.detail.model_copy(update={"report_dimension_audits": [
        audit.model_copy(update={"answer_review_contract": V2})]})
    assert _basis(service, changed_record, snapshot) != original_basis
    assert seen[-1] == atomic.ANSWER_NAME
    for mutation in ("receipt_contract", "payload_contract", "witness", "audit_contract"):
        clone = record.detail.model_copy(deep=True)
        target = next(s for s in clone.trace_spans if s.name == "question_atomic_delivery")
        receipt = json.loads(target.full_output)
        dispatch = next(d for d in receipt["dispatches"] if d["name"] == atomic.ANSWER_NAME)
        changed_audit = audit
        if mutation == "receipt_contract":
            receipt["answer_review_contract"] = V2
        elif mutation == "payload_contract":
            span = next(s for s in clone.trace_spans if s.id == dispatch["span_id"])
            system, raw = span.full_input.split("\nJSON:\n", 1)
            payload = json.loads(raw)
            payload["answer_review_contract"] = V2
            span.full_input = system + "\nJSON:\n" + json.dumps(payload)
            dispatch["full_input_sha256"] = atomic.digest(span.full_input)
        elif mutation == "witness":
            witness = dispatch["answer_validation"][0]["finite_witnesses"][0]
            witness["action_antecedent_quote"] = "changed"
        else:
            changed_audit = audit.model_copy(update=dict(answer_review_contract=V2))
        target.full_output = json.dumps(receipt)
        changed_audit = changed_audit.model_copy(
            update=dict(question_atomic_receipt_digest=atomic.digest(receipt)))
        with pytest.raises(ValueError):
            atomic.replay_atomic_delivery(service, clone, snapshot, use, view, audit=changed_audit)
