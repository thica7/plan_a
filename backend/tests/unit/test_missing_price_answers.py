from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from test_question_retrieval import replace_snapshot, research_case

from packages.research.evidence.snapshot_models import EvidenceFact, EvidenceGap, canonical_json

QUESTION = "Example Product：截至 2026-10-16，Pro 套餐在中国的含税人民币月费准确是多少？"
AS_OF = datetime(2026, 10, 16, 12, tzinfo=UTC)


def api():
    try:
        return importlib.import_module(
            "packages.agents.writer.price_answers"
        ).server_missing_price_answers
    except ModuleNotFoundError:
        pytest.fail("server missing-price answer is not implemented")


def price_case(*, money=True, **scope):
    detail, snapshot = research_case(["Merge requests require review before publishing."])
    detail.created_at = AS_OF
    detail.updated_at = AS_OF + timedelta(days=30)
    source = snapshot.sources[0].model_copy(
        update={
            "dimension": "pricing",
            "market": "CN",
            "last_verified_at": AS_OF,
            "source_published_at": AS_OF,
            "source_updated_at": None,
            "source_fetched_at": AS_OF,
        }
    )
    qualifiers = {
        "price_type": "official_current",
        "price_basis": "subscription",
        "plan": "Pro",
        "seat_type": "per_user",
        "billing_interval": "monthly",
        "tax_scope": "tax_included",
    }
    qualifiers.update(scope)
    price = EvidenceFact(
        id="current-price",
        semantic_id="current-price",
        evidence_item_ids=("original-price",),
        source_id=source.id,
        competitor="Example Product",
        dimension="pricing",
        field="price",
        value_json=canonical_json({"amount": 99, "currency": "CNY"}),
        market="CN",
        qualifiers_json=canonical_json(qualifiers),
        quote="Pro costs CNY 99 monthly including tax.",
        status="supported",
        confidence=0.9,
    )
    if money:
        snapshot = replace_snapshot(detail, snapshot, sources=(source,), facts=(price,))
    else:
        snapshot = replace_snapshot(
            detail,
            snapshot,
            sources=(source,),
            facts=tuple(
                fact.model_copy(update={"dimension": "pricing", "market": "CN"})
                for fact in snapshot.facts
            ),
        )
    return detail, snapshot, price


def answer(detail, snapshot, question=QUESTION):
    return api()(
        detail, snapshot, [{"question_id": "q-price", "question": question}], "Example Product"
    )


def test_feature_only_material_generates_explicit_snapshot_bound_missing_price_answer():
    detail, snapshot, _ = price_case(money=False)
    before = snapshot.model_dump_json()
    result = answer(detail, snapshot)
    row = result["q-price"]
    assert row["question_id"] == "q-price" and row["question"] == QUESTION
    assert row["status"] == "answered"
    assert row["resolution"] == "insufficient" and row["conclusion"] == "unknown"
    assert row["claim_ids"] == row["evidence_spans"] == ()
    assert "本次已准入资料不足以核实" in row["answer"]
    assert "2026-10-16" in row["answer"]
    assert {"amount", "currency", "current_price"} <= set(row["missing_fields"])
    assert row["basis_snapshot_id"] == snapshot.id
    assert snapshot.model_dump_json() == before


def test_explicit_chinese_quote_date_is_preserved_instead_of_the_run_date():
    detail, snapshot, _ = price_case(money=False)
    detail.created_at = AS_OF + timedelta(days=1)
    question = QUESTION.replace('2026-10-16', '2026 年 10 月 16 日')
    row = answer(detail, snapshot, question)['q-price']
    assert '2026-10-16' in row['answer'] and '2026-10-17' not in row['answer']


def test_invalid_explicit_chinese_quote_date_is_not_replaced_by_the_run_date():
    detail, snapshot, _ = price_case(money=False)
    assert answer(detail, snapshot, QUESTION.replace('2026-10-16', '2026 年 2 月 30 日')) == {}


def test_complete_matching_quote_is_checked_even_if_writer_did_not_select_it():
    detail, snapshot, _ = price_case()
    detail.evidence_consumptions = []
    assert answer(detail, snapshot) == {}


@pytest.mark.parametrize('background', ['团队会在 2027-11-09 举行活动，', 'Event date: 2027-11-09. '])
def test_background_date_does_not_replace_the_current_quote_date(background):
    detail, snapshot, _ = price_case()
    question = background + 'Example Product Pro 套餐在中国当前含税人民币月费准确是多少？'
    assert answer(detail, snapshot, question) == {}


@pytest.mark.parametrize(
    "change,missing",
    [
        ({"currency": "USD"}, "currency"),
        ({"billing_interval": "annual"}, "billing_interval"),
        ({"tax_scope": "unknown", "price_scope": "listed_unit"}, "tax_scope"),
        ({"tax_scope": "tax_excluded"}, "tax_scope"),
        ({"plan": "Enterprise"}, "plan"),
    ],
)
def test_wrong_currency_cycle_tax_or_plan_does_not_fill_the_requested_quote(change, missing):
    currency = change.get("currency", "CNY")
    detail, snapshot, price = price_case(**{k: v for k, v in change.items() if k != "currency"})
    price = price.model_copy(
        update={"value_json": canonical_json({"amount": 99, "currency": currency})}
    )
    snapshot = replace_snapshot(detail, snapshot, facts=(price,))
    row = answer(detail, snapshot)["q-price"]
    assert missing in row["missing_fields"]


@pytest.mark.parametrize(
    "change,source_change",
    [
        ({"competitor": "Other Product"}, {}),
        ({"market": "US"}, {"market": "US"}),
        ({"status": "signal"}, {}),
        ({}, {"last_verified_at": AS_OF - timedelta(days=8)}),
        ({}, {"role": "historical_report"}),
    ],
)
def test_other_product_market_unsupported_stale_or_historical_prices_do_not_count(
    change, source_change
):
    detail, snapshot, price = price_case()
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=(price.model_copy(update=change),),
        sources=(snapshot.sources[0].model_copy(update=source_change),),
    )
    assert answer(detail, snapshot)["q-price"]["resolution"] == "insufficient"


def test_matching_price_on_feature_dimension_is_still_checked_in_full_snapshot():
    detail, snapshot, price = price_case()
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=(price.model_copy(update={"dimension": "feature"}),),
        sources=(snapshot.sources[0].model_copy(update={"dimension": "feature"}),),
    )
    assert answer(detail, snapshot) == {}


@pytest.mark.parametrize(
    "question",
    [
        "Example Product 的 Pro 套餐支持自定义合并规则吗？",
        "Example Product 的 Pro 套餐按月还是按年计费？",
        "Example Product: How does monthly billing work in China?",
        "Example Product 当前价格是多少？",
        "Example Product 的 Pro 套餐在中国的含税人民币月费是多少？截至 2026-99-99。",
    ],
)
def test_features_billing_mechanisms_or_unknown_quote_scope_are_not_auto_answered(question):
    detail, snapshot, _ = price_case(money=False)
    assert answer(detail, snapshot, question) == {}


def test_english_scope_and_case_are_generic():
    detail, snapshot, _ = price_case()
    question = (
        "Example Product: What is the exact current tax-inclusive monthly price "
        "of the pro plan in China in CNY?"
    )
    assert answer(detail, snapshot, question) == {}


def test_missing_explicit_date_uses_created_at_and_is_stable_when_updated_at_changes():
    detail, snapshot, _ = price_case()
    question = "Example Product：Pro 套餐在中国的当前含税人民币月费准确是多少？"
    assert answer(detail, snapshot, question) == {}
    detail.updated_at = AS_OF + timedelta(days=365)
    assert answer(detail, snapshot, question) == {}


@pytest.mark.parametrize("scope", ["workspace_id", "project_id", "id"])
def test_foreign_snapshot_scope_is_rejected(scope):
    detail, snapshot, _ = price_case(money=False)
    setattr(detail, scope, "foreign")
    with pytest.raises(ValueError, match="scope|identity"):
        answer(detail, snapshot)


def test_mutated_old_and_dirty_snapshots_are_rejected():
    detail, snapshot, _ = price_case(money=False)
    with pytest.raises(ValueError, match="hash|snapshot"):
        answer(detail, snapshot.model_copy(update={"facts": ()}))
    old = snapshot
    snapshot = replace_snapshot(detail, snapshot, facts=())
    with pytest.raises(ValueError, match="current|snapshot"):
        answer(detail, old)
    detail.evidence_inputs_dirty = True
    with pytest.raises(ValueError, match="accepted|dirty"):
        answer(detail, snapshot)


def test_capacity_omission_cannot_be_misrepresented_as_confirmed_missing_price():
    detail, snapshot, _ = price_case(money=False)
    gap = EvidenceGap(
        id="capacity",
        reason="context_budget_exceeded",
        competitor="Example Product",
        dimension="pricing",
    )
    snapshot = replace_snapshot(detail, snapshot, gaps=(gap,))
    assert answer(detail, snapshot) == {}


def test_a_large_complete_snapshot_does_not_omit_a_matching_current_quote():
    detail, snapshot, price = price_case()
    unrelated = [
        price.model_copy(
            update={
                "id": f"irrelevant-{number}",
                "semantic_id": f"irrelevant-{number}",
                "field": "evidence_terms",
                "value_json": canonical_json(["Long original. " * 300]),
                "quote": "Long original. " * 300,
                "qualifiers_json": "{}",
            }
        )
        for number in range(90)
    ]
    snapshot = replace_snapshot(detail, snapshot, facts=(*unrelated, price))
    assert answer(detail, snapshot) == {}


def test_missing_fields_do_not_report_verified_matching_plan_or_cycle_as_absent():
    detail, snapshot, price = price_case()
    price = price.model_copy(
        update={"value_json": canonical_json({"amount": 99, "currency": "USD"})}
    )
    snapshot = replace_snapshot(detail, snapshot, facts=(price,))
    missing = answer(detail, snapshot)["q-price"]["missing_fields"]
    assert "currency" in missing
    assert "plan" not in missing and "billing_interval" not in missing
