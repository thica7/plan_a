"""Capacity expressions must retain their exact unit, conditions and polarity."""

import pytest

from packages.agents.writer.subquestion_premises import _counts


@pytest.mark.parametrize(
    "text",
    [
        "最多只能使用两个 collections",
        "最多只能提供两个 containers",
        "最多可使用三个集合",
        "至多可提供四个容器",
    ],
)
def test_explicit_chinese_capacity_modifier_is_recognized(text):
    assert _counts(text, upper=True)


@pytest.mark.parametrize(
    "text",
    [
        "并非最多只能使用两个 collections",
        "如果升级，最多只能使用两个 collections",
        "建议最多只能使用两个 collections",
        "最多只能使用两个工作日，collections 不限数量",
    ],
)
def test_conditional_negated_and_wrong_unit_text_does_not_supply_a_capacity(text):
    assert not _counts(text, upper=True)


def test_three_conditional_tasks_keep_every_required_source_review_check():
    from types import SimpleNamespace

    from test_capability_alignment import fact

    from packages.agents.writer.question_repair import repair_review_batches
    from packages.research.evidence.operations import (
        operation_binding,
        operation_observations,
        structured_operations,
    )
    from packages.research.evidence.report_claims import (
        ReportClaim,
        required_claim_checks,
        required_operation_checks,
    )

    facts, claims = [], []
    for i, (action, phrase) in enumerate(
        [
            ("edit", "edit documents"),
            ("comment", "comment on documents"),
            ("read", "read documents"),
        ]
    ):
        quote = f"Members can {phrase} only on paid plans."
        original = fact(
            "Example Product",
            quote,
            slot=str(i),
            qualifiers={"operations": structured_operations(quote, [quote], "Example Product")},
        )
        op = next(o for o in operation_observations(original) if o["operation"] == action)
        facts.append(original)
        claims.append(
            ReportClaim(
                id=f"c{i}",
                text=quote,
                kind="fact",
                competitor=original.competitor,
                dimension="feature",
                fact_ids=(original.id,),
                source_ids=(original.source_id,),
                operation_binding=operation_binding(op),
            )
        )
    view = SimpleNamespace(facts=facts, sources=[])
    assert all(
        len(required_claim_checks(c)) + len(required_operation_checks(c.operation_binding)) == 7
        for c in claims
    )
    legacy, omitted = repair_review_batches(claims, view, [], max_bytes=14000)
    assert len(legacy) == 2 and omitted
    batches, omitted = repair_review_batches(claims, view, [], max_bytes=14000, max_batches=3)
    assert not omitted
    assert [[row["id"] for row in b["claims"]] for b in batches] == [["c0"], ["c1"], ["c2"]]
