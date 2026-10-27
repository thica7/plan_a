"""V4 finite live-language repairs preserve frozen v1-v3 interpretation."""

import hashlib
import json

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response
from test_question_atomic_delivery import atomic_case, supported_review
from test_subquestion_premises_v2 import V1, V2, branch, parse
from test_subquestion_premises_v3 import QUESTION, V3
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic

V4 = "subquestion-premises-v4"
LIVE_CAP = ("Bitwarden 免费组织（Free organization）仅支持与另外 1 名用户存储并安全共享数据，"
            "即免费组织最多容纳 2 名用户。")
LIVE_PERMISSION = ("Observer 在已启用投票的看板上被允许对卡片投票，仅表示该操作被许可；"
                   "该许可本身并不蕴含 Observer 必须对每张卡片投票的义务。")
DUTY_SPLICE = ("Observer 在已启用投票的看板上被允许对卡片投票，仅表示该操作被许可；"
               "该许可本身并不蕴含强制投票要求而Observer 必须对每张卡片投票的义务来自管理员规定。")
PERMISSION_QUESTION = ("B 允许投票，是否意味着他必须给每张卡片投票？ "
                       "请将可以执行的操作、启用条件与是否存在强制义务分别说明。")


def decide(text=LIVE_CAP, question=QUESTION, *, contract=V4, kind="fact", relation="upper_bound"):
    return parse(question, [dict(id="c", kind=kind, text=text)],
                 [branch(question, ["c"], relation=relation)], contract=contract)


def permission(text=LIVE_PERMISSION, *, contract=V4):
    return decide(text, PERMISSION_QUESTION, contract=contract, kind="inference",
                  relation="permission_entailment")


def test_actual_live_cap_has_a_complete_v4_witness_and_v3_stays_unknown():
    result, diagnostics = decide()
    assert (result.status, result.conclusion) == ("answered", "no"), result.reason
    witness = diagnostics[0]["finite_witnesses"][0]
    assert witness["cap_sentence"] == LIVE_CAP
    assert witness["action_antecedent_quote"] == LIVE_CAP.split("，即")[0]
    assert witness["peer_count"] == 1 and witness["maximum"] == 2
    assert witness["organization_alias_quote"] == "（Free organization）"
    assert decide(contract=V3)[0].status == "unverified"


@pytest.mark.parametrize("alias", ["(Free organization)", "（免费组织）", "(free organizations)"])
def test_known_equivalent_identity_aliases_are_consumed_in_full(alias):
    text = LIVE_CAP.replace("（Free organization）", alias)
    assert decide(text)[0].status == "answered"


@pytest.mark.parametrize("marker", ["即", "i.e.", "that is"])
def test_new_peer_form_checks_independent_brand_and_numbers(marker):
    text = ("Aster 免费组织(Free organization)仅支持与另外 4 名用户存储并安全共享数据，"
            f"{marker} 免费组织最多容纳 5 名用户。")
    q = "Aster: Free organization 能让包括我在内的 7 个人共享数据吗？"
    result, diagnostics = decide(text, q)
    assert result.status == "answered", result.reason
    witness = diagnostics[0]["finite_witnesses"][0]
    assert (witness["peer_count"], witness["maximum"], witness["required"]) == (4, 5, 7)


@pytest.mark.parametrize("text", [
    LIVE_CAP.replace("另外 1", "另外 2"),
    LIVE_CAP.replace("另外 1", "另外 5"),
    LIVE_CAP.replace("最多容纳 2", "最多容纳 1"),
    LIVE_CAP.replace("（Free organization）", "（Paid organization）"),
    LIVE_CAP.replace("（Free organization）", "（Free workspace）"),
    LIVE_CAP.replace("（Free organization）", "（Free organization；仅活跃用户）"),
    LIVE_CAP.replace("（Free organization）", "（Free organization / Premium organization）"),
    LIVE_CAP.replace("（Free organization）", "（不含所有者）"),
    LIVE_CAP.replace("（Free organization）", "（每个团队分别计算）"),
    LIVE_CAP.replace("（Free organization）", "（未知人口）"),
    LIVE_CAP.replace("（Free organization）", "（Free organization)"),
    LIVE_CAP.replace("（Free organization）", "(Aster Free organization)"),
    LIVE_CAP.replace("仅支持与另外", "仅支持与另外的管理员及"),
    LIVE_CAP.replace("1 名用户", "1 名活跃用户"),
    LIVE_CAP.replace("1 名用户", "1 名访客"),
    LIVE_CAP.replace("最多容纳 2 名用户", "最多容纳 2 名用户（不含所有者）"),
    LIVE_CAP.replace("最多容纳 2 名用户", "最多容纳 2 名用户（每组分别计算）"),
    LIVE_CAP.replace("最多容纳", "一次最多容纳"),
    LIVE_CAP.replace("存储并安全共享数据", "编辑数据"),
    LIVE_CAP.replace("即免费组织", "即付费组织"),
    LIVE_CAP.replace("即免费组织", "即 Aster Free organization"),
    LIVE_CAP.replace("，即", "。即"),
    "仅统计活跃用户，" + LIVE_CAP,
    "每个团队分别计算；" + LIVE_CAP,
    "以下仅适用于活跃用户。" + LIVE_CAP,
    "针对管理员账户，" + LIVE_CAP,
    "如果管理员批准，" + LIVE_CAP,
    "建议" + LIVE_CAP,
    "并非" + LIVE_CAP,
])
def test_peer_alias_repair_never_launders_unknown_or_conflicting_population(text):
    result, diagnostics = decide(text)
    assert result.status == "unverified", (text, result)
    assert not diagnostics or not diagnostics[0]["finite_witnesses"]


def test_v4_checks_explicit_peer_arithmetic_in_the_existing_permission_form():
    text = ("Bitwarden Free 组织允许用户与另外五位用户存储并安全共享数据，"
            "即免费组织最多支持 2 名用户（含所有者）。")
    assert decide(text)[0].status == "unverified"
    assert decide(text, contract=V3)[0].status == "answered"


@pytest.mark.parametrize("question", [
    QUESTION.replace("3 个人", "2 个人"),
    QUESTION.replace("3 个人", "3 个容器"),
    QUESTION.replace("共享密码", "共享密码或编辑文档"),
    QUESTION.replace("共享密码", "编辑密码"),
    QUESTION.replace("Bitwarden", "Aster"),
])
def test_v4_keeps_the_same_unit_strict_excess_action_and_branch_boundaries(question):
    assert decide(question=question)[0].status == "unverified"


def test_actual_live_permission_has_only_a_finite_denied_entailment_witness():
    result, diagnostics = permission()
    assert (result.status, result.conclusion) == ("answered", "no"), result.reason
    witness = diagnostics[0]["finite_witnesses"][0]
    assert witness["denied_entailment_quotes"] == [
        "并不蕴含 Observer 必须对每张卡片投票的义务"]
    assert witness["permission_quote"] == LIVE_PERMISSION
    assert permission(contract=V3)[0].status == "unverified"


@pytest.mark.parametrize("denial", ["并不构成", "并不意味", "并不推出", "并不蕴含"])
def test_v4_keeps_existing_finite_permission_denial_synonyms(denial):
    assert permission(LIVE_PERMISSION.replace("并不蕴含", denial))[0].status == "answered"


@pytest.mark.parametrize("text", [
    LIVE_PERMISSION + "Observer 必须遵守另外规定的投票义务。",
    LIVE_PERMISSION.replace("的义务。", "的义务，但 Observer 必须按管理员要求投票。"),
    LIVE_PERMISSION.replace("的义务。", "的义务但 Observer 必须按管理员要求投票。"),
    LIVE_PERMISSION.replace("的义务。", "的义务，Observer must vote when instructed."),
    LIVE_PERMISSION.replace("的义务。", "的义务；Observer 必须按管理员要求投票。"),
    LIVE_PERMISSION.replace("投票的义务。", "投票但必须导出看板的义务。"),
    LIVE_PERMISSION.replace("投票的义务。", "投票且必须下载附件的义务。"),
    LIVE_PERMISSION.replace("必须对每张卡片投票", "必须下载附件"),
    LIVE_PERMISSION.replace("并不蕴含", "无法确认是否蕴含"),
])
def test_v4_never_erases_true_duties_or_changes_the_denied_operation(text):
    result, _ = permission(text)
    assert result.status == "unverified", (text, result)


@pytest.mark.parametrize("text", [
    DUTY_SPLICE,
    LIVE_PERMISSION.replace("并不蕴含 Observer", "并不蕴含管理员要求而Observer"),
    LIVE_PERMISSION.replace("的义务。", "的义务来自管理员规定。"),
    LIVE_PERMISSION.replace("的义务。", "的义务属于管理员规定。"),
    LIVE_PERMISSION.replace("必须对每张卡片投票", "必须接受管理员要求并投票"),
    LIVE_PERMISSION.replace("必须对每张卡片投票", "必须在管理员规定下对每张卡片投票"),
    LIVE_PERMISSION.replace("并不蕴含 Observer", "并不蕴含上述要求而Observer"),
])
def test_v4_denial_fragment_must_consume_a_complete_single_duty(text):
    result, diagnostics = permission(text)
    assert result.status == "unverified", (text, result)
    assert not diagnostics[0]["finite_witnesses"]


def test_v3_greedy_same_clause_failure_remains_frozen_only_in_v3():
    text = LIVE_PERMISSION.replace("并不蕴含", "并不意味").replace(
        "的义务。", "的义务，但 Observer 必须按管理员要求投票。")
    assert permission(text, contract=V3)[0].status == "answered"
    assert permission(text)[0].status == "unverified"


def test_v4_identity_does_not_change_frozen_systems_and_rejects_unknown_contracts():
    frozen = {
        V1: "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb",
        V2: "58946566e4de82459bd322f9a2f879f993b6fd874516037ab44589939fcfb0ae",
        V3: "c13e8aebcfa080138e2c20d56c1657152fb5731892f8e3d6a78b2b736fadad9b",
    }
    for contract, expected in frozen.items():
        system = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN", answer_review_contract=contract)
        assert hashlib.sha256(system.encode()).hexdigest() == expected
        assert atomic.answer_contract_from_system(system, "zh-CN") == contract
    system = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN", answer_review_contract=V4)
    assert "Server subquestion premises v4." in system
    assert atomic.answer_contract_from_system(system, "zh-CN") == V4
    for changed in (system + "changed", system.replace("premises v4.", "premises v99.")):
        with pytest.raises(ValueError):
            atomic.answer_contract_from_system(changed, "zh-CN")
    assert decide(contract="subquestion-premises-v99")[0].status == "unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("text,question,kind,relation,eligible", [
    (LIVE_CAP, QUESTION, "fact", "upper_bound", True),
    (LIVE_PERMISSION, PERMISSION_QUESTION, "inference", "permission_entailment", True),
    (LIVE_CAP.replace("另外 1", "另外 5"), QUESTION, "fact", "upper_bound", False),
    (LIVE_PERMISSION.replace("的义务。", "的义务，但 Observer 必须按管理员要求投票。"),
     PERMISSION_QUESTION, "inference", "permission_entailment", False),
    (DUTY_SPLICE, PERMISSION_QUESTION, "inference", "permission_entailment", False),
])
async def test_v4_real_texts_reach_live_coverage_render_replay_and_qa_support(
    monkeypatch, text, question, kind, relation, eligible,
):
    from packages.agents.qa.independent_question_review import _question_context
    from packages.agents.qa.question_context import question_delivery_complete
    from packages.agents.qa.question_reconciliation import _answer_support, _basis
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    case = await atomic_case([text], question="Example Product: " + question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    seen = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append(kwargs["name"])
        if kwargs["name"] == atomic.GENERATION_NAME:
            span = next(s for fact in payload["evidence_view"]["facts"]
                        for s in fact["source_span_candidates"] if s["quote"] == text)
            response = question_plan_response(payload,
                [dict(text=text, kind=kind, support_refs=[span["support_ref"]])])
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        else:
            assert kwargs["name"] == atomic.ANSWER_NAME
            assert payload["answer_review_contract"] == V4
            assert kwargs["system"] == atomic.atomic_system(atomic.ANSWER_NAME,
                record.detail.output_language, answer_review_contract=V4)
            q = payload["questions"][0]
            ids = [c["id"] for c in payload["claims"]]
            response = json.dumps(dict(version=3, answers=[dict(
                question_id=q["question_id"], status="answered", resolution="direct",
                conclusion="no", claim_ids=ids, missing_fields=[], reason="Reviewed",
                subquestions=[branch(q["question"], ids, relation=relation)])]))
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service, record, selected, view, use, packets[0]["questions"], packets,
        allowed, boundaries, (), answer_review_contract=V4)
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                                 available_facts=view.facts, review_version=3)
    assert len(audited) == 1 and audited[0].status == "supported", (audited, result["gaps"])
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await atomic.atomic_answer_coverage(
        service, record, packets[0]["questions"], result["compact"],
        [item.claim for item in audited if item.status == 'supported'], view, use, (),
        answer_review_contract=V4)
    assert (answers[0].status, answers[0].conclusion) == (
        ("answered", "no") if eligible else ("unverified", "unknown")), answers
    audit = ReportDimensionAudit(competitor=view.competitor, dimension=view.dimension,
        consumption_id=use.id, claims=audited, answer_coverage=answers, answer_binding_version=3,
        claim_review_version=3, answer_review_contract=V4, question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"])
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert tuple(replay["answers"].values()) == answers
    q = packets[0]["questions"][0]
    if not eligible:
        assert "结论：否" not in record.detail.report_md
        assert _answer_support(record.detail, snapshot, audit, answers[0], q) is None
        return
    complete = question_delivery_complete(service, record.detail, snapshot, audit, q)
    assert complete
    context = _question_context(service, record, snapshot, q, audit,
                                verified=complete, producer_verified=True)
    assert context["publication_matches"] and context["support_verified"]
    assert text in context["visible_answer"] and "结论：否" in context["visible_answer"]
    assert _answer_support(record.detail, snapshot, audit, answers[0], q)
    assert ReportDimensionAudit.model_validate_json(audit.model_dump_json()) == audit
    old_basis = _basis(service, record, snapshot)
    prior = record.detail.report_dimension_audits
    record.detail.report_dimension_audits = [
        audit.model_copy(update={"answer_review_contract": V3})]
    assert _basis(service, record, snapshot) != old_basis
    record.detail.report_dimension_audits = prior
    receipt_span = next(s for s in record.detail.trace_spans
                        if s.name == "question_atomic_delivery")
    for mutation in ("receipt_contract", "witness", "audit_contract", "payload_contract"):
        clone = record.detail.model_copy(deep=True)
        target = next(s for s in clone.trace_spans if s.id == receipt_span.id)
        receipt = json.loads(target.full_output)
        dispatch = next(d for d in receipt["dispatches"] if d["name"] == atomic.ANSWER_NAME)
        changed_audit = audit
        if mutation == "receipt_contract":
            receipt["answer_review_contract"] = V3
        elif mutation == "witness":
            dispatch["answer_validation"][0]["finite_witnesses"][0]["claim_id"] = "foreign"
        elif mutation == "payload_contract":
            span = next(s for s in clone.trace_spans if s.id == dispatch["span_id"])
            system, raw = span.full_input.split("\nJSON:\n", 1)
            body = json.loads(raw)
            body["answer_review_contract"] = V3
            span.full_input = system + "\nJSON:\n" + json.dumps(body)
            dispatch["full_input_sha256"] = atomic.digest(span.full_input)
        else:
            changed_audit = audit.model_copy(update={"answer_review_contract": V3})
        target.full_output = json.dumps(receipt)
        changed_audit = changed_audit.model_copy(
            update={"question_atomic_receipt_digest": atomic.digest(receipt)})
        with pytest.raises(ValueError):
            atomic.replay_atomic_delivery(service, clone, snapshot, use, view, audit=changed_audit)
