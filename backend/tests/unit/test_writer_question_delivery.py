"""Anonymous regressions for question originals and independently reviewed answers."""

import json
from datetime import UTC, datetime

from claim_review_fixture import expand_prompt_payload, question_plan_response

import pytest
from claim_review_fixture import sent_source_span_id, supported_review
from pydantic import HttpUrl, TypeAdapter
from test_missing_price_answers import answer, price_case
from test_question_retrieval import replace_snapshot, research_case
from test_source_exception_closure import AUTH, facts, item, reasons

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.agents.writer.price_answers import _request
from packages.agents.writer.question_retrieval import retrieve_question_facts
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json
from packages.schema.models import DecisionBrief
from packages.skills.registry import SkillRegistry


def selection(question_id="q", **updates):
    return dict(question_id=question_id, status="answered", claim_ids=["c"],
                resolution="direct", conclusion="no", missing_fields=[],
                reason="The complete published restriction addresses the request.") | updates


def parse(text, question, **updates):
    claims = [{"id": "c", "text": text}]
    return parse_answer_coverage(
        json.dumps({"version": 2, "answers": [selection(**updates)]}),
        [{"question_id": "q", "question": question}], {"c"}, claims=claims, require_v2=True,
    )[0], claims


@pytest.mark.parametrize("text", [
    "访客账户没有自己的私人区域，且只能访问由账户所有者选择的一个容器。",
    "来宾账户没有自己的私人区域，且仅能访问由账户所有者选择的一个容器。",
])
def test_complete_chinese_negative_and_limited_assertions_keep_v2_binding(text):
    record, claims = parse(text, "访客能访问两个容器，或者拥有自己的私人区域吗？")
    assert record.status == "answered", record.reason
    assert record.answer == text and record.binding_version == 2
    assert not coverage_resolution_reasons(record, claims, require_v2=True)
    persisted = ReportAnswerCoverage.model_validate_json(record.model_dump_json())
    assert persisted == record
    for changed in (text.replace("没有", "拥有"), text.replace("一个", "两个"),
                    text.replace("访客", "管理员").replace("来宾", "管理员")):
        assert "answer_selection_binding_invalid" in coverage_resolution_reasons(
            persisted.model_copy(update={"answer": changed}), claims, require_v2=True)


def test_specific_guard_reason_survives_parser_and_roles_do_not_cross_sentences():
    record, _ = parse("编辑者没有自己的文档。访客只能访问文件夹。", "访客能访问文档吗？")
    assert record.status == "unverified" and not record.claim_ids
    assert "question_role_mismatch" in record.reason
    invalid, _ = parse("访客没有自己的文档。", "访客能访问文档吗？", claim_ids=["unknown"])
    assert invalid.status == "unverified" and not invalid.answer


AUTH_ZH = (
    "对于通过 SSO with trusted devices 使用受信任设备且没有主密码的成员账户，"
    "从组织中移除这些成员会消除对其 Example Product 账户的所有访问，"
    "除非账户恢复为其分配了主密码，并且在移除前使用该主密码至少登录一次。"
)


def test_account_qualified_chinese_auth_outcome_preserves_all_prerequisites():
    originals = facts(item(AUTH, "auth"))
    assert not reasons(AUTH_ZH, originals)
    for changed in (
        AUTH_ZH.replace("并且", "或者"),
        AUTH_ZH.replace("且没有主密码", ""),
        AUTH_ZH.replace("成员账户", "用户账户"),
        AUTH_ZH.replace("从组织中移除这些成员", "从文件夹中移除这些成员"),
        AUTH_ZH.replace("消除对其", "不会消除对其"),
        AUTH_ZH.replace("会消除对其", "不消除对其"),
        AUTH_ZH.replace("在移除前使用该主密码至少登录一次", "在移除后使用该主密码至少登录一次"),
        AUTH_ZH.replace("账户恢复为其分配了主密码", "账户恢复可能可用"),
    ):
        assert reasons(changed, originals), changed


CORE = [
    "Organizations own all collections. Personally-owned items remain in a member's personal vault.",
    "Members can move personally-owned vault items into organization-owned collections. "
    "Centralized ownership assigns those items to the organization; remaining personal items belong to members.",
    "Deleting an account is permanent and will delete all associated vault data.",
]


def lifecycle_case(product="Example Product"):
    questions = (f"{product}：Free 套餐允许保存密码吗？\n"
                 f"{product}：我们准备把离职同事“删掉”，他保存的那些密码之后还会留下吗？")
    background = [f"{plan} plan users can store passwords. " + "Plan background details. " * 42
                  for plan in ("Free", "Families", "Enterprise")]
    removal = ("If you don't want to permanently delete account data, consider removing the member "
               "from the organization. Removing a user does not delete their account. "
               "Users can still access any personally-owned items if they know their master password.")
    detail, _ = research_case([*background, *CORE, removal, AUTH], question=questions)
    detail.topic = "账户生命周期调研"
    detail.created_at = datetime.now(UTC)
    detail.updated_at = detail.created_at
    detail.plan.competitors = [product]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=questions)
    for source in detail.raw_sources:
        source.competitor = product
        source.covered_competitors = [product]
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
        for field in source.metadata["normalized_fields"]:
            field["competitor"] = product
    return detail, seal_snapshot(detail, phase="analysis", canonical_documents={})


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["Example Product", "Other Suite"])
async def test_lifecycle_core_originals_precede_plan_background_without_auth_substitution(product):
    detail, snapshot = lifecycle_case(product)
    before = snapshot.model_dump_json()
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, product, "feature", mode="lexical")
    picked = {fact.quote for fact in snapshot.facts if fact.id in selected}
    assert set(CORE) <= picked, diagnostic
    assert AUTH not in picked
    assert any(quote.startswith("Free plan") for quote in picked)
    assert len(selected) <= 8 and diagnostic["selected_original_bytes"] <= 14000
    assert snapshot.model_dump_json() == before
    assert not diagnostic["questions"][1]["missing_core_fact_ids"]


@pytest.mark.asyncio
async def test_lifecycle_capacity_gap_keeps_whole_originals(monkeypatch):
    from packages.agents.writer import question_retrieval

    detail, snapshot = lifecycle_case()
    monkeypatch.setattr(question_retrieval, "EXCEPTION_CLOSURE_MAX_BYTES", 2000)
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical")
    assert diagnostic["questions"][1]["missing_core_fact_ids"]
    assert diagnostic["selected_original_bytes"] <= 2000
    assert all(fact.quote in CORE for fact in snapshot.facts if fact.id in selected)


def service_for(detail):
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    return service, record


@pytest.mark.asyncio
async def test_real_writer_prompt_keeps_lifecycle_originals_and_final_qa_retains_gap(monkeypatch):
    detail, _ = lifecycle_case()
    service, record = service_for(detail)
    prompts = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_writer":
            prompts.append(payload)
            originals = payload["evidence_view"]["facts"]
            assert set(CORE) <= {fact["quote"] for fact in originals}
            return question_plan_response(payload, [dict(text=fact["quote"], kind="fact",
                competitor="Example Product", dimension="feature", fact_ids=[fact["id"]],
                source_ids=[fact["source_id"]]) for fact in originals if fact["quote"] in CORE])
        if kwargs["name"] == "dimension_claim_review":
            return json.dumps({"reviews": [supported_review(claim) for claim in payload["claims"]]})
        assert kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}
        return json.dumps({"version": 3, "answers": [dict(question_id=q["question_id"],
            status="unverified", resolution="unresolved", conclusion="unknown", claim_ids=[],
            missing_fields=["actual_action", "data_ownership"],
            reason="The action and ownership need clarification before concluding retention.")
            for q in payload["questions"]]})

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert prompts
    audit = detail.report_dimension_audits[0]
    saved = type(audit).model_validate_json(audit.model_dump_json())
    assert len(saved.answer_coverage) == 2
    use = next(use for use in detail.evidence_consumptions if use.id == audit.consumption_id)
    snapshot = current_snapshot(detail)
    assert set(CORE) <= {fact.quote for fact in snapshot.facts if fact.id in use.fact_ids}
    assert any(issue.metadata.get("claim_audit_reason") == "answer_coverage_incomplete"
               for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True))


@pytest.mark.asyncio
async def test_chinese_answer_flows_through_writer_review_saved_record_and_final_qa(monkeypatch):
    question = "Example Product：访客能访问两个容器，或者拥有自己的私人区域吗？"
    text = "访客账户没有自己的私人区域，且只能访问由账户所有者选择的一个容器。"
    detail, _ = research_case([text], question=question)
    detail.created_at = datetime.now(UTC)
    detail.updated_at = detail.created_at
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs["name"])
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_writer":
            fact = payload["evidence_view"]["facts"][0]
            assert fact["quote"] == text
            return question_plan_response(payload, [dict(text=text, kind="fact", competitor="Example Product",
                dimension="feature", fact_ids=[fact["id"]], source_ids=[fact["source_id"]])])
        if kwargs["name"] == "dimension_claim_review":
            return json.dumps({"reviews": [supported_review(claim) for claim in payload["claims"]]})
        assert kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}
        return json.dumps({"version": 3, "answers": [dict(question_id=q["question_id"],
            status="answered", resolution="direct", conclusion="no", missing_fields=[],
            claim_ids=[claim["id"] for claim in payload["claims"]], reason="The restriction answers both clauses.")
            for q in payload["questions"]]})

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    saved = type(audit).model_validate_json(audit.model_dump_json())
    result = saved.answer_coverage[0]
    assert result.status == "answered" and result.conclusion == "no", result.reason
    assert result.binding_version == 3 and result.answer == text
    assert {"dimension_answer_coverage", "dimension_answer_review"} <= set(calls)
    snapshot = current_snapshot(detail)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)


@pytest.mark.parametrize('purchase', ['准备购买', '准备买'])
def test_purchase_duration_product_currency_and_tax_are_request_conditions(purchase):
    detail, snapshot, _ = price_case(money=False)
    question = (f"Example Product：我们有300名员工，{purchase} Example Product Unified Access 和 Device Trust 一年。"
                "请给出精确的人民币含税总价。")
    parsed = _request(detail, {"question": question}, "Example Product")
    assert parsed[2]["plan"] == "Unified Access + Device Trust"
    assert parsed[2]["duration_months"] == 12
    assert parsed[2]["currency"] == "CNY" and parsed[2]["tax_scope"] == "tax_included"
    assert "billing_interval" not in parsed[2] and "seats" not in parsed[2]
    row = answer(detail, snapshot, question)["q-price"]
    assert row["status"] == "partial" and row["resolution"] == "insufficient"
    assert "plan" not in row["missing_fields"] and "billing_interval" in row["missing_fields"]
    assert all(value in row["answer"] for value in ("Unified Access", "Device Trust", "12个月", "含税", "人民币"))
    assert "付费席位" in row["answer"]
    assert "官网没有" not in row["answer"] and "销售" not in row["answer"]


def test_explicit_purchased_plan_with_admitted_matching_price_is_not_missing_a_sku():
    detail, snapshot, _ = price_case()
    assert answer(detail, snapshot,
        "Example Product：准备购买 Pro 套餐，在中国的含税人民币月费准确是多少？") == {}


def billing_original():
    quote = "| Standard | 12 million included +$0.42 per million requests | 20 million included +$0.03 per million CPU milliseconds |"
    conditions = [
        "By default, users have access to the Compute Free plan. The Compute Free plan includes limited usage. "
        "Read more about the Free plan limits. "
        "The Compute Paid plan has a minimum account charge of $13 USD per month.",
        "Users on the Compute Paid plan have access to the Standard usage model. "
        "Compute Enterprise accounts are billed based on the usage model specified in their contract. "
        "To switch to the Standard usage model, contact your Account Manager.",
    ]
    table = ["| Usage model | Requests | CPU time |", "* CPU time is only billed when the function runs."]
    return quote, conditions, table


def test_cpu_table_applicability_keeps_adjacent_free_branch_and_specific_gap():
    detail, snapshot, _ = price_case(money=False)
    quote, conditions, table = billing_original()
    fact = EvidenceFact(id="cpu-original", semantic_id="cpu-original", source_id=snapshot.sources[0].id,
        competitor="Example Product", dimension="pricing", field="evidence_terms", quote=quote,
        value_json=canonical_json([quote, *conditions, *table]), qualifiers_json=canonical_json({"conditions": conditions,
            "table_context": table}), status="supported", confidence=.9)
    snapshot = replace_snapshot(detail, snapshot, facts=(fact,))
    question = "Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？"
    row = answer(detail, snapshot, question)["q-price"]
    assert "cpu_usage" in row["missing_fields"], row
    assert "CPU 总用量" in row["answer"] and "完整用量" in row["answer"]
    assert snapshot.facts[0].qualifiers["conditions"] == conditions
    assert "Free plan" in snapshot.facts[0].qualifiers["conditions"][0]


@pytest.mark.asyncio
async def test_role_background_and_bill_original_reach_real_writer_and_replay_cpu_gap(monkeypatch):
    guest = "访客账户没有自己的私人区域，且只能访问由账户所有者选择的一个容器。"
    quote, conditions, table = billing_original()
    questions = ("Example Product：访客能访问两个容器，或者拥有自己的私人区域吗？\n"
                 "Example Product：Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？")
    background = [f"Guests can format style {index} in shared documents. "
                  + "General guest role background. " * 14 for index in range(44)]
    detail, _ = research_case([guest, *background, quote], question=questions)
    detail.created_at = datetime.now(UTC)
    detail.updated_at = detail.created_at
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=questions)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    field = detail.raw_sources[-1].metadata["normalized_fields"][0]
    field["evidence_terms"] = [quote, *conditions, *table]
    field["qualifiers"] = {"conditions": conditions, "table_context": table}
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    target = next(fact for fact in snapshot.facts if fact.field == "evidence_terms" and fact.quote == quote)
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical")
    assert target.id in selected and diagnostic["selected_original_bytes"] <= 14000
    service, record = service_for(detail)
    prompts = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_writer":
            prompts.append(payload)
            rows = payload["evidence_view"]["facts"]
            bill = next(row for row in rows if row["id"] == target.id)
            def resolve(value):
                if isinstance(value, dict) and set(value) == {'text_ref'}:
                    return payload['text_sets'][value['text_ref']]
                if isinstance(value, dict):
                    return {key: resolve(child) for key, child in value.items()}
                if isinstance(value, list):
                    return [resolve(child) for child in value]
                return value
            bill = resolve(bill)
            assert bill["quote"] == quote
            assert bill["qualifiers"]["conditions"] == conditions
            assert bill["qualifiers"]["table_context"] == table
            assert set([quote, *conditions, *table]) <= set(bill["value"])
            fact = next(row for row in rows if row["quote"] == guest)
            return question_plan_response(payload, [dict(text=guest, kind="fact", competitor="Example Product",
                dimension="feature", fact_ids=[fact["id"]], source_ids=[fact["source_id"]])])
        if kwargs["name"] == "dimension_claim_review":
            return json.dumps({"reviews": [supported_review(claim) for claim in payload["claims"]]})
        assert kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}
        assert len(payload["questions"]) == 1  # The other answer is an exact local snapshot replay.
        return json.dumps({"version": 3, "answers": [dict(question_id=q["question_id"],
            status="answered", resolution="direct", conclusion="no", missing_fields=[],
            claim_ids=[claim["id"] for claim in payload["claims"]], reason="The complete restriction answers this request.")
            for q in payload["questions"]]})

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert prompts
    audit = detail.report_dimension_audits[0]
    audit = type(audit).model_validate_json(audit.model_dump_json())
    answers = audit.answer_coverage
    assert [row.status for row in answers] == ["answered", "partial"]
    assert answers[1].resolution == "insufficient" and "cpu_usage" in answers[1].missing_fields
    assert "CPU 总用量" in answers[1].answer and "完整用量" in answers[1].answer
    use = next(use for use in detail.evidence_consumptions if use.id == audit.consumption_id)
    assert target.id in use.fact_ids and target.id in use.requested_fact_ids
    snapshot = current_snapshot(detail)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    changed = answers[1].model_copy(update={"answer": answers[1].answer.replace("CPU 总用量", "无需 CPU 用量")})
    detail.report_dimension_audits = [audit.model_copy(update={"answer_coverage": (answers[0], changed)})]
    assert any(issue.metadata.get("claim_audit_reason") == "answer_coverage_incomplete"
               for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True))


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', [14000, 2000])
async def test_four_independent_lifecycle_originals_share_total_writer_budget(monkeypatch, budget):
    from packages.agents.writer import question_retrieval

    core = [
        'Organizations own all collections.',
        "Personally-owned items remain in a member's personal vault.",
        'Administrators centralize organization ownership when selected items are transferred from a member.',
        'Deleting the individual user account is permanent. Deleting an account will delete all associated vault data including stored passwords.',
    ]
    question = 'Example Product：把离职同事“删掉”后，他保存的密码还会留下吗？'
    background = [f'Plan {index}: passwords are retained when members are removed. Background policy details.'
                  for index in range(3)]
    detail, _ = research_case([*background, *core], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    monkeypatch.setattr(question_retrieval, 'EXCEPTION_CLOSURE_MAX_BYTES', budget)
    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda *_: None)
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, 'Example Product', 'feature', mode='lexical')
    originals = {fact.id: fact.quote for fact in snapshot.facts if fact.field == 'evidence_terms'}
    assert diagnostic['selected_original_bytes'] <= budget and len(selected) <= 8
    if budget == 2000:
        assert diagnostic['questions'][0]['missing_core_fact_ids']
        assert not set(core) <= {originals[key] for key in selected}
    service, record = service_for(detail)
    prompts = []

    async def model(_record, **kwargs):
        assert kwargs['name'] == 'dimension_claim_writer'
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        prompts.append(payload)
        quotes = {fact['quote'] for fact in payload['evidence_view']['facts']}
        if budget == 14000:
            assert set(core) <= quotes
        else:
            assert 'question_core_context_budget_exceeded' in payload['upstream_context_gaps']
            assert not set(core) <= quotes
        return question_plan_response(payload, [])

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    assert prompts
    audit = detail.report_dimension_audits[0]
    saved = type(audit).model_validate_json(audit.model_dump_json())
    if budget == 14000:
        assert set(core) <= {originals[key] for key in selected}
        assert not diagnostic['questions'][0]['missing_core_fact_ids']
        assert 'question_core_context_budget_exceeded' not in saved.gaps
    else:
        assert 'question_core_context_budget_exceeded' in saved.gaps
    clarification = saved.answer_coverage[0]
    assert clarification.status == 'partial' and clarification.resolution == 'clarification'
    assert clarification.conclusion == 'depends' and clarification.binding_version == 3
    assert clarification.missing_fields == ('actual_action', 'data_ownership')
    assert not clarification.claim_ids and not clarification.evidence_spans
    assert clarification.basis_snapshot_id is None
    assert clarification.answer == ('请确认具体操作：您准备移除成员，还是永久删除账户或数据？ '
                                    '请确认数据归属：相关数据属于个人，还是组织？')
    issues = audit_dimension_claims(service, record, current_snapshot(detail), producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for issue in issues) == (budget == 2000)


PAID_SEAT_QUESTION = (
    'Example Product：我们有300名员工，实际付费席位250个，准备购买 Unified Access 和 Device Trust 一年，'
    '请给出精确的人民币含税总价。'
)


def test_explicit_paid_seats_remain_a_request_condition_separate_from_employees():
    detail, snapshot, _ = price_case(money=False)
    before = snapshot.model_dump_json()
    context = _request(detail, {'question': PAID_SEAT_QUESTION}, 'Example Product')[2]
    assert context['employee_count'] == 300 and context['billable_seats'] == 250
    assert context['duration_months'] == 12 and 'billing_interval' not in context
    row = answer(detail, snapshot, PAID_SEAT_QUESTION)['q-price']
    assert 'billable_seats' not in row['missing_fields']
    assert '实际付费席位 250个' in row['answer']
    assert row['resolution'] == 'insufficient' and row['conclusion'] == 'unknown'
    assert not row['claim_ids'] and snapshot.model_dump_json() == before


@pytest.mark.asyncio
async def test_writer_persists_given_paid_seats_without_facts_and_replays_partial_gap(monkeypatch):
    detail, _ = research_case([], question=PAID_SEAT_QUESTION)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=PAID_SEAT_QUESTION)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)

    async def forbidden(*args, **kwargs):
        pytest.fail('Explicit request conditions and a verified snapshot gap need no model call.')

    monkeypatch.setattr(service, '_trace_llm_text', forbidden)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    saved = type(audit).model_validate_json(audit.model_dump_json())
    row = saved.answer_coverage[0]
    assert row.status == 'partial' and row.resolution == 'insufficient'
    assert 'billable_seats' not in row.missing_fields
    assert '实际付费席位 250个' in row.answer and row.answer in detail.report_md
    assert row.basis_snapshot_id == snapshot.id and not snapshot.facts
    assert not row.claim_ids and not row.evidence_spans
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert not issues
    forged = row.model_copy(update={'status': 'answered'})
    detail.report_dimension_audits = [saved.model_copy(update={'answer_coverage': (forged,)})]
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for issue in issues)


@pytest.mark.asyncio
@pytest.mark.parametrize('different_condition', [False, True])
async def test_only_complete_identical_sent_originals_close_redundant_core_ids(monkeypatch, different_condition):
    from packages.agents.writer import question_retrieval

    conclusion = ('Deleting an account will delete all associated vault data. '
                  'Members cannot retain their personal vault items after account deletion.')
    rule = ("Organizations own all collections. Personally-owned items remain in a member's personal vault. "
            'Administrators centralize organization ownership when selected items are transferred from a member. '
            + conclusion + ' ')
    quote = rule + '\n\n' + 'Background policy details. ' * 80
    extra = ' Account deletion is delayed for 30 days when a legal hold is active.'
    quotes = [quote, quote, quote + extra if different_condition else quote]
    question = 'Example Product：把自己的账户永久删掉后，之前保存的密码还会留下吗？'
    detail, _ = research_case(quotes, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for index, source in enumerate(detail.raw_sources):
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
        source.metadata['normalized_fields'][0]['slot'] = (
            f'distinct-original-{index}' if different_condition else 'same-original')
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda *_: None)
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, 'Example Product', 'feature', mode='lexical')
    originals = {fact.id: fact for fact in snapshot.facts if fact.field == 'evidence_terms'}
    missing = diagnostic['questions'][0]['missing_core_fact_ids']
    # Exact equivalent originals consume one slot; a different condition still needs its own.
    assert len(selected) == (2 if different_condition else 1)
    assert diagnostic['selected_original_bytes'] <= 14000
    if different_condition:
        assert missing and all(extra in originals[key].quote for key in missing)
        assert all(extra not in originals[key].quote for key in selected)
    else:
        assert not missing
    service, record = service_for(detail)
    calls = []

    async def model(_record, **kwargs):
        calls.append(kwargs['name'])
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            fact = payload['evidence_view']['facts'][0]
            assert fact['quote'] == quote
            return question_plan_response(payload, [dict(text=conclusion, kind='fact', competitor='Example Product',
                dimension='feature', fact_ids=[fact['id']], source_ids=[fact['source_id']],
                source_span_ids=[sent_source_span_id(fact, conclusion)])])
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(claim) for claim in payload['claims']]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        return json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'], status='answered',
            resolution='direct', conclusion='no', claim_ids=[claim['id'] for claim in payload['claims']],
            missing_fields=[], reason='The complete original records the account deletion outcome.')
            for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    assert calls == ['dimension_claim_writer', 'dimension_claim_review',
                     'dimension_answer_coverage', 'dimension_answer_review']
    audit = detail.report_dimension_audits[0]
    saved = type(audit).model_validate_json(audit.model_dump_json())
    detail.report_dimension_audits = [saved]
    assert saved.answer_coverage[0].status == 'answered'
    assert saved.answer_coverage[0].binding_version == 3
    issues = audit_dimension_claims(service, record, current_snapshot(detail), producer_verified=True)
    if different_condition:
        assert 'question_core_context_budget_exceeded' in saved.gaps
        assert any(issue.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for issue in issues)
    else:
        assert 'question_core_context_budget_exceeded' not in saved.gaps
        assert not issues


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', [14000, 3000])
async def test_fourth_different_lifecycle_condition_reaches_prompt_or_retains_capacity_gap(monkeypatch, budget):
    from packages.agents.writer import question_retrieval

    conclusion = ('Deleting an account will delete all associated vault data. '
                  'Members cannot retain their personal vault items after account deletion.')
    rule = ("Organizations own all collections. Personally-owned items remain in a member's personal vault. "
            'Administrators centralize organization ownership when selected items are transferred from a member. '
            + conclusion)
    hold = rule + ' Account deletion is delayed for 30 days when a legal hold is active.'
    core = [rule + ' Confirmation is required.', rule + ' Recovery is unavailable.',
            rule + ' Backups expire after 7 days.', hold]
    background = ('Removing members and deleting credentials can affect retention and ownership. '
                  'Passwords remain subject to the policy.')
    question = 'Example Product：把自己的账户永久删掉后，之前保存的密码还会留下吗？'
    detail, _ = research_case([background + f' Note {index}.' for index in range(3)] + core,
                              question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda *_: None)
    monkeypatch.setattr(question_retrieval, 'EXCEPTION_CLOSURE_MAX_BYTES', budget)
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, 'Example Product', 'feature', mode='lexical')
    originals = {fact.id: fact for fact in snapshot.facts if fact.field == 'evidence_terms'}
    hold_id = next(key for key, fact in originals.items() if fact.quote == hold)
    assert len(selected) <= 8 and diagnostic['selected_original_bytes'] <= budget
    service, record = service_for(detail)
    calls = []

    async def model(_record, **kwargs):
        calls.append(kwargs['name'])
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            rows = payload['evidence_view']['facts']
            if budget == 14000:
                assert hold_id in {row['id'] for row in rows}
                fact = next(row for row in rows if row['id'] == hold_id)
                assert fact['quote'] == hold
                text = hold
            else:
                assert hold_id not in {row['id'] for row in rows}
                assert 'question_core_context_budget_exceeded' in payload['upstream_context_gaps']
                fact = next(row for row in rows if row['quote'] in core)
                text = conclusion
            return question_plan_response(payload, [dict(text=text, kind='fact', competitor='Example Product',
                dimension='feature', fact_ids=[fact['id']], source_ids=[fact['source_id']],
                source_span_ids=[sent_source_span_id(fact, text)])])
        if kwargs['name'] == 'dimension_claim_review':
            if budget == 14000:
                text = payload['claims'][0]['text']
                if isinstance(text, dict):
                    payload['claims'][0]['text'] = payload['text_sets'][text['text_ref']]
                assert payload['claims'][0]['text'] == hold
            return json.dumps({'reviews': [supported_review(claim) for claim in payload['claims']]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        return json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'], status='answered',
            resolution='conditional' if budget == 14000 else 'direct',
            conclusion='depends' if budget == 14000 else 'no',
            claim_ids=[claim['id'] for claim in payload['claims']], missing_fields=[],
            reason='The complete published text records the applicable original conditions.')
            for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    assert calls == ['dimension_claim_writer', 'dimension_claim_review',
                     'dimension_answer_coverage', 'dimension_answer_review']
    audit = detail.report_dimension_audits[0]
    saved = type(audit).model_validate_json(audit.model_dump_json())
    detail.report_dimension_audits = [saved]
    answer = saved.answer_coverage[0]
    assert answer.status == 'answered' and answer.binding_version == 3
    assert hold_id in diagnostic['questions'][0]['core_fact_ids']
    issues = audit_dimension_claims(service, record, current_snapshot(detail), producer_verified=True)
    if budget == 14000:
        assert hold_id in selected and not diagnostic['questions'][0]['missing_core_fact_ids']
        assert answer.answer == hold and answer.conclusion == 'depends'
        assert [(span.claim_id, span.quote) for span in answer.evidence_spans] == [(answer.claim_ids[0], hold)]
        assert 'question_core_context_budget_exceeded' not in saved.gaps
        assert not issues
    else:
        assert hold_id in diagnostic['questions'][0]['missing_core_fact_ids']
        assert 'question_core_context_budget_exceeded' in saved.gaps
        assert any(issue.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for issue in issues)
