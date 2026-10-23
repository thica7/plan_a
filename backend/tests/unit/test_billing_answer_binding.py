"""Billing premises must replay published claims, not merely a snapshot receipt."""

import pytest
from test_incomplete_quote_answers import usage_case
from test_question_retrieval import replace_snapshot

from packages.agents.writer.price_answers import server_missing_price_answers
from packages.research.evidence.report_claims import ReportClaim
from packages.research.evidence.source_spans import ReportSourceSpanBinding, source_span_candidates

QUESTION = {
    "question_id": "bill",
    "question": "Example Product Usage plan 本月有2300万次请求，账单准确是多少美元？",
}


def billing_claim(snapshot):
    original = snapshot.facts[0]
    span = source_span_candidates(original)[0]
    return ReportClaim(
        id="published-cpu-rule",
        kind="fact",
        competitor="Example Product",
        dimension="pricing",
        text="Usage plan 的账单取决于 CPU 时间和请求总量。",
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
        source_span_bindings=(ReportSourceSpanBinding(**span),),
    )


def result(detail, snapshot, **kwargs):
    return server_missing_price_answers(detail, snapshot, [QUESTION], "Example Product", **kwargs)[
        "bill"
    ]


def test_snapshot_only_gap_cannot_publish_an_unbound_cpu_product_assertion():
    detail, snapshot = usage_case()
    row = result(detail, snapshot)
    assert row["resolution"] == "insufficient" and row["status"] == "partial"
    assert "cpu_usage" in row["missing_fields"]
    assert "已准入计费规则包含 CPU 时间计费" not in row["answer"]
    assert row["claim_ids"] == row["evidence_spans"] == ()


def test_supported_published_cpu_premise_keeps_exact_claim_and_full_text():
    detail, snapshot = usage_case()
    claim = billing_claim(snapshot)
    row = result(detail, snapshot, claims=(claim,))
    assert row["claim_ids"] == (claim.id,)
    assert row["evidence_spans"] == ({"claim_id": claim.id, "quote": claim.text},)
    assert claim.text in row["answer"]
    assert row["status"] == "partial" and row["resolution"] == "insufficient"
    assert row["conclusion"] == "unknown" and "cpu_usage" in row["missing_fields"]


@pytest.mark.parametrize(
    "change", ["no_span", "tamper", "source", "plan", "unrelated", "condition"]
)
def test_unreplayable_or_inapplicable_published_claim_cannot_supply_cpu_premise(change):
    detail, snapshot = usage_case()
    claim = billing_claim(snapshot)
    if change == "no_span":
        claim = claim.model_copy(update={"source_span_bindings": ()})
    elif change == "tamper":
        span = claim.source_span_bindings[0].model_copy(update={"quote": "CPU time is free."})
        claim = claim.model_copy(update={"source_span_bindings": (span,)})
    elif change == "source":
        claim = claim.model_copy(update={"source_ids": ("another-source",)})
    elif change == "plan":
        claim = claim.model_copy(update={"text": claim.text.replace("Usage", "Enterprise")})
    elif change == "unrelated":
        claim = claim.model_copy(update={"text": "Usage plan 允许读取计费设置。"})
    else:
        original = snapshot.facts[0]
        changed = original.model_copy(
            update={"quote": original.quote + " Only account owners are billed."}
        )
        snapshot = replace_snapshot(detail, snapshot, facts=(changed,))
    row = result(detail, snapshot, claims=(claim,))
    assert not row["claim_ids"] and not row["evidence_spans"]
    assert claim.text not in row["answer"]


def test_billing_claim_api_uses_reportclaim_objects():
    detail, snapshot = usage_case()
    with pytest.raises(TypeError, match="ReportClaim"):
        result(detail, snapshot, claims=(billing_claim(snapshot).model_dump(mode="json"),))


def test_one_missing_cpu_input_needs_only_one_complete_published_premise():
    detail, snapshot = usage_case()
    first = billing_claim(snapshot)
    another = first.model_copy(update={"id": "another-published-cpu-rule"})
    row = result(detail, snapshot, claims=(first, another))
    assert len(row["claim_ids"]) == len(row["evidence_spans"]) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Standard usage model CPU time is billed.",
        "Standard 用量模式的 CPU 时间包含超额计费项目。",
    ],
)
def test_exact_named_usage_row_is_a_published_cpu_premise_without_borrowing_its_intro(text):
    from test_answer_publication_recovery import QUESTION as TABLE_QUESTION
    from test_answer_publication_recovery import table_case

    detail, snapshot = table_case()
    original = snapshot.facts[0].model_copy(update={"dimension": "feature"})
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=(original,),
        sources=(snapshot.sources[0].model_copy(update={"dimension": "feature"}),),
    )
    claim = ReportClaim(
        id="published-table-cpu",
        kind="fact",
        competitor="Example Product",
        dimension="feature",
        text=text,
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
        source_span_bindings=(ReportSourceSpanBinding(**source_span_candidates(original)[0]),),
    )
    assert "Users on" not in claim.source_span_bindings[0].quote
    row = server_missing_price_answers(
        detail,
        snapshot,
        [{"question_id": "bill", "question": TABLE_QUESTION}],
        "Example Product",
        claims=(claim,),
    )["bill"]
    assert row["claim_ids"] == (claim.id,)
    assert claim.text in row["answer"] and row["resolution"] == "insufficient"


@pytest.mark.parametrize(
    "change",
    [
        "other_service",
        "other_mode",
        "other_product",
        "no_header",
        "wrong_column",
        "request_unit",
        "missing_footnote",
        "scope_omitted",
        "time_omitted",
        "parent_only",
    ],
)
def test_published_cpu_row_keeps_its_own_complete_scope_cell_and_context(change):
    from test_answer_publication_recovery import INTRO, QUESTION, TABLE_ROW, table_case

    from packages.research.evidence.snapshot_models import canonical_json

    intro = INTRO.replace("Compute Paid", "Storage Paid") if change == "other_service" else INTRO
    quote = TABLE_ROW
    if change == "other_mode":
        intro, quote = intro.replace("Standard", "Legacy"), quote.replace("Standard", "Legacy")
    if change == "request_unit":
        quote = quote.replace(
            "+$0.03 per additional million CPU milliseconds", "$0.03 per million requests"
        )
    detail, snapshot = table_case(row=quote, intro=intro)
    original = snapshot.facts[0].model_copy(update={"dimension": "feature"})
    qualifiers = original.qualifiers
    if change == "no_header":
        qualifiers["table_context"] = []
    elif change == "wrong_column":
        qualifiers["table_context"] = [
            qualifiers["table_context"][0].replace("CPU time", "Requests")
        ]
    elif change == "missing_footnote":
        qualifiers["table_context"] = [
            qualifiers["table_context"][0].replace("CPU time", "CPU time*")
        ]
    original = original.model_copy(update={"qualifiers_json": canonical_json(qualifiers)})
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=(original,),
        sources=(snapshot.sources[0].model_copy(update={"dimension": "feature"}),),
    )
    span = next(
        row
        for row in source_span_candidates(original)
        if row["quote"] == (intro if change == "parent_only" else quote)
    )
    text = "Standard usage model CPU time is billed."
    if change == "scope_omitted":
        text = "CPU time is billed."
    elif change == "time_omitted":
        text = "Standard usage model CPU requests are billed."
    claim = ReportClaim(
        id="published-cpu",
        kind="fact",
        competitor=("Other Product" if change == "other_product" else "Example Product"),
        dimension="feature",
        text=text,
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
        source_span_bindings=(ReportSourceSpanBinding(**span),),
    )
    row = server_missing_price_answers(
        detail,
        snapshot,
        [{"question_id": "bill", "question": QUESTION}],
        "Example Product",
        claims=(claim,),
    )["bill"]
    assert not row["claim_ids"] and not row["evidence_spans"]
    assert text not in row["answer"]
