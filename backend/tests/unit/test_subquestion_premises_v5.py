"""A source witness proves only the same cap already published by its own fact."""

import hashlib
import json

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response
from test_question_atomic_delivery import atomic_case, supported_review
from test_subquestion_premises_v2 import branch
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic
from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.research.evidence.report_claims import ReportClaim
from packages.research.evidence.snapshot_models import EvidenceFact
from packages.research.evidence.source_spans import source_span_candidates

V5 = "subquestion-premises-v5"
SOURCE = ("Free organizations offer both users all the core features of Password Manager "
          "and secure data sharing in up to two collections.")
PEOPLE_SOURCE = ("Start a Free organization to store and securely share data with one other user. "
                 + SOURCE + " Any user of any plan can be the owner of one Free organization.")
QUESTION = ("Bitwarden: 我们都在 2026 年新建了 Bitwarden 账户，并建立一个 Free organization，"
            "想让包括我在内的 3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？")
PUBLISHED = "Free organization 的共享数据最多可放入 2 个 collections。"


def bound_case(text=PUBLISHED, source=SOURCE, *, kind="fact", qualifiers="{}",
               competitor="Bitwarden"):
    fact = EvidenceFact(id="f", semantic_id="sf", source_id="s", competitor=competitor,
        dimension="feature", field="evidence_terms", value_json=json.dumps([source]),
        quote=source, qualifiers_json=qualifiers, status="supported", confidence=1)
    claim = ReportClaim(id="c", text=text, kind=kind, competitor=competitor, dimension="feature",
        fact_ids=(fact.id,), source_ids=(fact.source_id,),
        source_span_bindings=(source_span_candidates(fact)[0],))
    return claim, fact


def decide(claim, facts, question=QUESTION, *, contract=V5):
    response = json.dumps(dict(version=3, answers=[dict(question_id="q", status="answered",
        resolution="direct", conclusion="no", claim_ids=[claim.id], missing_fields=[],
        reason="Reviewed", subquestions=[branch(question, [claim.id], relation="upper_bound")])]))
    diagnostics = []
    result = parse_answer_coverage(response, [dict(question_id="q", question=question)], {claim.id},
        claims=[claim.model_dump(mode="json")], facts=facts, required_binding_version=3,
        require_subquestions=True, answer_review_contract=contract, diagnostics=diagnostics,
        question_claim_whitelist={"q": {claim.id}})[0]
    return result, diagnostics


@pytest.mark.parametrize("text", [PUBLISHED,
    "Free organization 最多支持在 2 个 collections 中进行安全数据共享。"])
def test_v5_real_rewrites_have_the_same_snapshot_bound_cap(text):
    claim, fact = bound_case(text)
    answer, diagnostics = decide(claim, [fact])
    assert (answer.status, answer.conclusion) == ("answered", "no"), answer
    witnesses = diagnostics[0]["finite_witnesses"]
    if text == PUBLISHED:
        witness = witnesses[0]
        assert witness["published_cap_quote"] == text
        assert witness["source_cap_quote"] == SOURCE
        assert witness["source_span_binding"] == claim.source_span_bindings[0].model_dump(
            mode="json")
        assert decide(claim, [fact], contract="subquestion-premises-v4")[0].status == "unverified"
    assert not coverage_resolution_reasons(answer, [claim.model_dump(mode="json")], facts=[fact],
        require_subquestions=True, answer_review_contract=V5)
    assert coverage_resolution_reasons(answer, [claim.model_dump(mode="json")], facts=[],
        require_subquestions=True, answer_review_contract=V5)


def test_v5_independent_brand_number_and_source_word_number():
    source = "Aster Free organizations support secure data sharing in up to four collections."
    text = "Aster Free organization 的共享数据最多可放入 4 个 collections。"
    claim, fact = bound_case(text, source, competitor="Aster")
    question = "Aster: Free organization用7个collections共享数据，能满足吗？"
    answer, diagnostics = decide(claim, [fact], question)
    assert (answer.status, answer.conclusion) == ("answered", "no"), answer
    witness = diagnostics[0]["finite_witnesses"][0]
    assert (witness["maximum"], witness["required"], witness["unit"]) == (4, 7, "collections")


@pytest.mark.parametrize("published_brand,source_brand,question_brand,has_facts,eligible", [
    ("", "", "Bitwarden", True, True),
    ("Bitwarden", "", "Bitwarden", True, True),
    ("", "Bitwarden", "Bitwarden", True, True),
    ("Bitwarden", "Bitwarden", "Bitwarden", True, True),
    ("", "", None, True, True),
    ("Bitwarden", "", None, True, True),
    ("", "Bitwarden", None, True, True),
    ("Bitwarden", "Bitwarden", None, True, True),
    ("Aster", "", "Bitwarden", True, False),
    ("", "Aster", "Bitwarden", True, False),
    ("Aster", "Aster", "Bitwarden", True, False),
    ("Bitwarden", "Aster", "Bitwarden", True, False),
    ("Aster", "Bitwarden", "Bitwarden", True, False),
    ("", "", "Aster", True, False),
    ("Bitwarden", "Bitwarden", "Aster", True, False),
    ("Bitwarden", "", "Bitwarden", False, False),
    ("", "Bitwarden", "Bitwarden", False, False),
])
def test_v5_brand_omission_preserves_only_the_current_verified_product(
    published_brand, source_brand, question_brand, has_facts, eligible,
):
    text = (published_brand + " " if published_brand else "") + PUBLISHED
    source = (source_brand + " " if source_brand else "") + SOURCE
    claim, fact = bound_case(text, source)
    question = (QUESTION.replace("Bitwarden", question_brand) if question_brand else
                "Free organization用3个collections共享数据，能满足吗？")
    answer, diagnostics = decide(claim, [fact] if has_facts else [], question)
    assert (answer.status, answer.conclusion) == (
        ("answered", "no") if eligible else ("unverified", "unknown")), (answer, diagnostics)
    assert bool(diagnostics[0]["finite_witnesses"]) is eligible


@pytest.mark.parametrize("question,eligible", [
    ("Can Free organization share data in 3 collections?", True),
    ("Could Free organization share data in 3 collections?", True),
    ("Can Bitwarden Free organization share data in 3 collections?", True),
    ("Could Bitwarden Free organization share data in 3 collections?", True),
    ("Can Aster Free organization share data in 3 collections?", False),
    ("Could Aster Free organization share data in 3 collections?", False),
    ("Bitwarden: Can Free organization share data in 3 collections?", True),
    ("Bitwarden: Can Bitwarden Free organization share data in 3 collections?", True),
    ("Bitwarden: Could Aster Free organization share data in 3 collections?", False),
    ("Aster: Can Bitwarden Free organization share data in 3 collections?", False),
    ("Can Bitwarden: Free organization share data in 3 collections?", True),
    ("Could Aster: Free organization share data in 3 collections?", False),
    ("Bitwarden: Can Aster: Free organization share data in 3 collections?", False),
    ("Bitwarden: Aster: Free organization share data in 3 collections?", False),
    ("Can Bitwarden: Could Aster: Free organization share data in 3 collections?", False),
    ("Bitwarden: Bitwarden: Free organization share data in 3 collections?", False),
    ("Bitwarden：Can Aster：Free organization share data in 3 collections?", False),
    ("Aster Free organization用3个collections共享数据，能满足吗？", False),
])
def test_v5_question_verb_is_not_a_product_brand(question, eligible):
    claim, fact = bound_case()
    answer, _ = decide(claim, [fact], question)
    assert (answer.status == "answered") is eligible


@pytest.mark.parametrize("text,source,kind", [
    ("Free organization 的共享仅限与另外 1 位用户（即共 2 位用户）进行。", PEOPLE_SOURCE, "fact"),
    ("Free organization 的共享最多为 2 位用户。", SOURCE, "fact"),
    (PUBLISHED, SOURCE, "inference"),
    (PUBLISHED.replace("2 个", "1 个"), SOURCE, "fact"),
    (PUBLISHED.replace("最多", "最少"), SOURCE, "fact"),
    (PUBLISHED.replace("最多", "可以"), SOURCE, "fact"),
    ("建议" + PUBLISHED, SOURCE, "fact"),
    ("如果管理员允许，" + PUBLISHED, SOURCE, "fact"),
    (PUBLISHED.replace("共享", "编辑"), SOURCE, "fact"),
    (PUBLISHED.replace("Free", "Paid"), SOURCE, "fact"),
    (PUBLISHED, SOURCE.replace("up to two", "at least two"), "fact"),
    (PUBLISHED, "If administrators approve, " + SOURCE, "fact"),
    (PUBLISHED, SOURCE + " This applies only after 2026.", "fact"),
    (PUBLISHED, SOURCE.replace("two collections", "two collections per team"), "fact"),
    (PUBLISHED, SOURCE.replace("two collections", "two collections (active users only)"), "fact"),
    (PUBLISHED, SOURCE.replace("two collections", "two collections (excluding the owner)"), "fact"),
    (PUBLISHED, SOURCE.replace("two collections", "two collections (unknown annotation)"), "fact"),
    (PUBLISHED, SOURCE + " Except administrators may share more.", "fact"),
    (PUBLISHED, SOURCE.replace("Free organizations", "Paid organizations"), "fact"),
    (PUBLISHED, SOURCE.replace("data sharing", "data editing"), "fact"),
    (PUBLISHED, SOURCE.replace("two collections", "two collections at a time"), "fact"),
])
def test_v5_source_cannot_supply_unpublished_or_unqualified_properties(text, source, kind):
    claim, fact = bound_case(text, source, kind=kind)
    answer, diagnostics = decide(claim, [fact])
    assert answer.status == "unverified", (answer, diagnostics)
    assert not diagnostics or not diagnostics[0]["finite_witnesses"]


@pytest.mark.parametrize("field,value", [("quote", "forged"), ("source_path", "value/9"),
    ("start", 1), ("end", 1), ("fact_hash", "0" * 64), ("span_id", "untrusted"),
    ("source_id", "foreign"), ("fact_id", "foreign")])
def test_v5_reconstructs_every_binding_identity_member(field, value):
    claim, fact = bound_case()
    changed = claim.model_copy(update={"source_span_bindings": (
        claim.source_span_bindings[0].model_copy(update={field: value}),)})
    assert decide(changed, [fact])[0].status == "unverified"


@pytest.mark.parametrize("change", [
    "missing_facts", "missing_binding", "parent_changed", "qualifier"])
def test_v5_never_trusts_a_quote_or_receipt_without_its_original_fact(change):
    claim, fact = bound_case()
    facts = [fact]
    if change == "missing_facts":
        facts = []
    elif change == "missing_binding":
        claim = claim.model_copy(update={"source_span_bindings": ()})
    elif change == "parent_changed":
        facts = [fact.model_copy(update={"quote": fact.quote + " changed"})]
    else:
        claim, fact = bound_case(qualifiers=json.dumps({"active_users_only": True}))
        facts = [fact]
    assert decide(claim, facts)[0].status == "unverified"


@pytest.mark.parametrize("qualifiers", [
    {"operations": [{"operation": "share", "effect": "allowed",
                     "operation_quote": "Only active users can share", "prerequisites": []}]},
    {"operations": None},
    {"source_scope": {"operations": None}},
    {"source_scope": {"context": {"plan": "Paid"}}},
])
def test_v5_preserves_unknown_parent_qualifiers_instead_of_ignoring_them(qualifiers):
    claim, fact = bound_case(qualifiers=json.dumps(qualifiers))
    assert decide(claim, [fact])[0].status == "unverified"


def test_v5_published_cap_path_also_rechecks_its_snapshot_identity():
    claim, fact = bound_case("Free organization 最多支持在 2 个 collections 中进行安全数据共享。")
    claim = claim.model_copy(update={"source_span_bindings": ()})
    assert decide(claim, [fact])[0].status == "unverified"


def test_v5_actual_parent_headings_are_preserved_but_unknown_members_still_reject():
    claim, fact = bound_case(source=PEOPLE_SOURCE)
    value = ["Free organizations\n" + PEOPLE_SOURCE, "Password Manager Plans", "Personal plans"]
    fact = fact.model_copy(update={"value_json": json.dumps(value)})
    span = next(s for s in source_span_candidates(fact) if s['quote'] == SOURCE)
    claim = claim.model_copy(update={"source_span_bindings": (
        type(claim.source_span_bindings[0])(**span),)})
    answer, _ = decide(claim, [fact])
    assert answer.status == "answered", answer
    value.append("Only active users qualify")
    fact = fact.model_copy(update={"value_json": json.dumps(value)})
    span = next(s for s in source_span_candidates(fact) if s['quote'] == SOURCE)
    claim = claim.model_copy(update={"source_span_bindings": (
        type(claim.source_span_bindings[0])(**span),)})
    assert decide(claim, [fact])[0].status == "unverified"


def test_v5_system_identity_preserves_all_frozen_contracts():
    expected = {
        "subquestion-premises-v1":
            "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb",
        "subquestion-premises-v2":
            "58946566e4de82459bd322f9a2f879f993b6fd874516037ab44589939fcfb0ae",
        "subquestion-premises-v3":
            "c13e8aebcfa080138e2c20d56c1657152fb5731892f8e3d6a78b2b736fadad9b",
    }
    for contract, checksum in expected.items():
        assert hashlib.sha256(atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN",
            answer_review_contract=contract).encode()).hexdigest() == checksum
    system = atomic.atomic_system(atomic.ANSWER_NAME, "zh-CN", answer_review_contract=V5)
    assert "Server subquestion premises v5." in system
    assert atomic.answer_contract_from_system(system, "zh-CN") == V5


@pytest.mark.asyncio
@pytest.mark.parametrize("source,text,eligible", [
    (SOURCE, PUBLISHED, True),
    (PEOPLE_SOURCE, "Free organization 的共享仅限与另外 1 位用户（即共 2 位用户）进行。", False),
    (SOURCE.replace("two collections", "two collections per team"), PUBLISHED, False),
])
async def test_v5_exact_selected_source_survives_live_parse_render_audit_replay_and_qa(
    monkeypatch, source, text, eligible,
):
    from packages.agents.qa.question_context import question_delivery_complete
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.answer_presentation import question_coverage_lines
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    if eligible:
        import test_question_atomic_delivery as fixture

        original = fixture.research_case

        def actual_parent(texts, **kwargs):
            detail, previous = original(texts, **kwargs)
            fields = detail.raw_sources[0].metadata['normalized_fields'][0]
            fields['evidence_quote'] = PEOPLE_SOURCE
            fields['evidence_terms'] = ["Free organizations\n" + PEOPLE_SOURCE,
                                        "Password Manager Plans", "Personal plans"]
            operation = dict(operation='share', effect='allowed', role=None, object_type=None,
                object_quote=None, access_scope=None, plan='Personal plans',
                missing_fields=['role', 'access_scope'],
                operation_quote=PEOPLE_SOURCE.split('.')[0],
                prerequisites=[dict(kind='plan', quote=PEOPLE_SOURCE)])
            fields['qualifiers'] = dict(operations=[operation], source_scope=dict(
                context=dict(document_section=[1554, 1845], plan=None, role=None,
                             section_path=None),
                operations=[operation]))
            return detail, previous

        monkeypatch.setattr(fixture, 'research_case', actual_parent)

    case = await atomic_case([source], question=QUESTION.replace("Bitwarden", "Example Product"))
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            span = next(s for f in payload["evidence_view"]["facts"]
                        for s in f["source_span_candidates"] if s["quote"] == source)
            response = question_plan_response(payload,
                [dict(text=text, kind="fact", support_refs=[span["support_ref"]])])
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        else:
            assert payload["answer_review_contract"] == V5
            q = payload["questions"][0]
            ids = [c["id"] for c in payload["claims"]]
            response = json.dumps(dict(version=3, answers=[dict(question_id=q["question_id"],
                status="answered", resolution="direct", conclusion="no", claim_ids=ids,
                missing_fields=[], reason="Reviewed",
                subquestions=[branch(q["question"], ids, relation="upper_bound")])]))
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(service, record, selected, view, use,
        packets[0]["questions"], packets, allowed, boundaries, (), answer_review_contract=V5)
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
        available_facts=view.facts, review_version=3)
    assert len(audited) == 1 and audited[0].status == "supported", audited
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await atomic.atomic_answer_coverage(service, record, packets[0]["questions"],
        result["compact"], [a.claim for a in audited if a.status == 'supported'], view, use, (),
        answer_review_contract=V5)
    assert (answers[0].status, answers[0].conclusion) == (
        ("answered", "no") if eligible else ("unverified", "unknown")), answers
    audit = ReportDimensionAudit(competitor=view.competitor, dimension=view.dimension,
        consumption_id=use.id, claims=audited, answer_coverage=answers, answer_binding_version=3,
        claim_review_version=3, answer_review_contract=V5, question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"])
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert tuple(atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view,
        audit=audit)["answers"].values()) == answers
    q = packets[0]["questions"][0]
    if not eligible:
        assert "结论：否" not in record.detail.report_md
        assert _answer_support(record.detail, snapshot, audit, answers[0], q) is None
        return
    assert "结论：否" in record.detail.report_md
    assert question_delivery_complete(service, record.detail, snapshot, audit, q)
    assert _answer_support(record.detail, snapshot, audit, answers[0], q)
    assert "结论：否" not in "\n".join(question_coverage_lines(audit, "zh-CN"))
    damaged = snapshot.model_copy(update={"facts": ()})
    assert _answer_support(record.detail, damaged, audit, answers[0], q) is None
    with pytest.raises(ValueError):
        atomic.replay_atomic_delivery(service, record.detail, damaged, use, view, audit=audit)
