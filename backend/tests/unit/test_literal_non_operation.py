"""An exact non-operation sentence may coexist with operation evidence."""

import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.dimension_writer import operation_claim_selection, parse_claim_drafts
from packages.research.evidence.operations import operation_binding, operation_observations
from packages.research.evidence.report_claims import ReportClaim, audit_report_claims
from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json

EDIT = "Members can edit documents."
LITERAL = "Members may be Custodians."


def fact(fact_id="f1", *, quote=None, value=None, field="evidence_terms"):
    quote = quote if quote is not None else f"{EDIT} {LITERAL}"
    return EvidenceFact(
        id=fact_id,
        semantic_id=f"semantic-{fact_id}",
        source_id="source-original",
        competitor="Example Product",
        dimension="feature",
        field=field,
        value_json=canonical_json(value if value is not None else [quote]),
        quote=quote,
        status="supported",
        confidence=0.9,
    )


def sent_row(original):
    return dict(
        id=original.id,
        source_id=original.source_id,
        competitor=original.competitor,
        dimension=original.dimension,
        field=original.field,
        quote=original.quote,
        value=original.value,
        qualifiers=original.qualifiers,
    )


def draft(original, text=LITERAL, **updates):
    row = dict(
        text=text,
        kind="fact",
        competitor=original.competitor,
        dimension=original.dimension,
        fact_ids=[original.id],
        source_ids=[original.source_id],
    )
    row.update(updates)
    return row


def candidates(original):
    bindings = [operation_binding(row) for row in operation_observations(original)]
    return {row["observation_id"]: row for row in bindings}


def parse(rows, original, *, source_facts=None, sent_ids=None):
    return parse_claim_drafts(
        json.dumps({"claims": rows}),
        candidates(original),
        sent_ids if sent_ids is not None else {original.id},
        "use-anonymous",
        source_facts=source_facts if source_facts is not None else [sent_row(original)],
    )


def test_literal_non_operation_sentence_survives_mixed_fact_parser():
    original = fact()
    assert candidates(original)
    claims, gaps = parse([draft(original)], original)
    assert len(claims) == 1
    assert claims[0].text == LITERAL
    assert claims[0].operation_binding is None
    assert not gaps


def test_literal_non_operation_sentence_survives_operation_target_selection():
    original = fact()
    claim = ReportClaim(id="literal", **draft(original))
    chosen = operation_claim_selection(
        [claim], SimpleNamespace(facts=[original]), ("edit",), {original.id},
        fact_targets={original.id: ["edit"]},
    )
    assert chosen == [claim]


def test_literal_can_come_from_the_original_value_string_not_only_the_quote():
    original = fact(quote=EDIT, value=[EDIT, LITERAL])
    claims, gaps = parse([draft(original)], original)
    assert len(claims) == 1 and not gaps


@pytest.mark.parametrize(
    "source,text",
    [
        (f"{EDIT} Members can create new pages. {LITERAL}", "Members can create"),
        (f"{EDIT} Members may be Custodians only after verification.", "Members may be Custodians"),
        (f"{EDIT} No Members may be Custodians.", LITERAL),
        (f"{EDIT} {LITERAL}", "Custodians."),
    ],
)
def test_literal_exception_cannot_cut_objects_conditions_or_negation(source, text):
    original = fact(quote=source)
    claims, gaps = parse([draft(original, text)], original)
    assert not claims and "operation_binding_required" in gaps


@pytest.mark.parametrize(
    "text",
    [
        "Members may be Custodians only after verification.",
        "Members cannot be Custodians.",
        "Members may be Custodians!",
        "成员可以担任保管人，但需要完成验证。",
    ],
)
def test_complete_literal_sentence_preserves_its_conditions_negation_and_punctuation(text):
    original = fact(quote=f"{EDIT} {text}")
    claims, gaps = parse([draft(original, text)], original)
    assert len(claims) == 1 and claims[0].text == text and not gaps


def test_independent_value_entry_does_not_require_terminal_punctuation():
    text = "Members may be Custodians"
    original = fact(quote=EDIT, value=[EDIT, text])
    claims, gaps = parse([draft(original, text)], original)
    assert len(claims) == 1 and claims[0].text == text and not gaps


@pytest.mark.parametrize(
    "text",
    [
        "Members may be Managers.",
        "成员可以担任保管人。",
        EDIT,
        f"{EDIT} {LITERAL}",
    ],
)
def test_paraphrased_translated_and_operation_assertions_still_need_binding(text):
    original = fact()
    claims, gaps = parse([draft(original, text)], original)
    assert not claims
    assert "operation_binding_required" in gaps


def test_multiple_content_facts_cannot_use_the_literal_exception():
    original, other = fact(), fact("f2")
    claims, gaps = parse(
        [draft(original, fact_ids=[original.id, other.id])], original,
        source_facts=[sent_row(original), sent_row(other)], sent_ids={original.id, other.id},
    )
    assert not claims and "operation_binding_required" in gaps


def test_an_unsent_original_cannot_supply_the_literal_sentence():
    original = fact(quote=EDIT)
    other = fact("not-sent")
    claims, gaps = parse(
        [draft(original)], original, source_facts=[sent_row(original), sent_row(other)],
    )
    assert not claims and "operation_binding_required" in gaps


def test_an_unsent_fact_id_is_still_rejected_even_when_its_text_is_supplied():
    original, other = fact(), fact("not-sent")
    claims, gaps = parse(
        [draft(other)], original, source_facts=[sent_row(original), sent_row(other)],
    )
    assert not claims and "claim_candidate_invalid" in gaps


def test_question_and_qualifier_text_cannot_replace_original_quote_or_value():
    original = fact(quote=EDIT)
    row = sent_row(original)
    row.update(question=LITERAL, qualifiers={"generated_note": LITERAL})
    claims, gaps = parse([draft(original)], original, source_facts=[row])
    assert not claims and "operation_binding_required" in gaps


def test_default_source_facts_keeps_legacy_binding_requirement():
    original = fact()
    claims, gaps = parse_claim_drafts(
        json.dumps({"claims": [draft(original)]}), candidates(original), {original.id}, "legacy-use"
    )
    assert not claims and "operation_binding_required" in gaps


def test_literal_exception_keeps_the_eight_row_limit():
    original = fact()
    claims, gaps = parse([draft(original)] * 9, original)
    assert len(claims) == 8
    assert gaps == {"claim_count_limit_exceeded"}


def test_literal_exception_still_requires_normal_claim_review():
    original = fact()
    claims, gaps = parse([draft(original)], original)
    assert claims and not gaps
    view = SimpleNamespace(facts=[original])
    boundaries = [SimpleNamespace(allowed_fact_ids=[original.id])]
    missing = audit_report_claims(claims, [], view, boundaries)
    assert missing[0].status == "unreviewed"
    rejected = audit_report_claims(
        claims,
        [dict(claim_id=claims[0].id, verdict="unsupported", reason="Not established here.")],
        view,
        boundaries,
    )
    assert rejected[0].status == "rejected"
