"""Readable short references preserve complete, dispatched source identities."""

import copy
import importlib
import json
from types import SimpleNamespace

import pytest
from test_literal_non_operation import fact

from packages.agents.writer import dimension_writer as writer
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.source_spans import source_span_candidates


def payload_for(originals):
    return dict(
        segment_competitor="Example Product",
        dimension="feature",
        evidence_view=dict(
            facts=[
                dict(
                    id=original.id,
                    source_id=original.source_id,
                    competitor=original.competitor,
                    dimension=original.dimension,
                    field=original.field,
                    quote=original.quote,
                    value=original.value,
                    qualifiers={k: v for k, v in original.qualifiers.items() if k != "operations"},
                    source_span_candidates=[
                        dict(support_ref=f"s{index + 1}", quote=original.quote)
                    ],
                )
                for index, original in enumerate(originals)
            ]
        ),
    )


def module():
    assert importlib.util.find_spec("packages.agents.writer.readable_support") is not None, (
        "Readable references need one resolver shared by parsing and the dispatched whitelist"
    )
    return importlib.import_module("packages.agents.writer.readable_support")


def test_short_context_shows_complete_quote_instead_of_coordinates():
    original = fact(quote="Guests do not have private vaults and can access only one shared vault.")
    payload, _ = writer.compact_dimension_context(
        dict(segment_competitor=original.competitor, dimension="feature"),
        SimpleNamespace(facts=[original]),
        {original.id},
        questions=[dict(question_id="q", question="Do guests have private vaults?")],
    )
    assert payload["evidence_view"]["facts"][0]["source_span_candidates"] == [
        dict(support_ref="s1", quote=original.quote)
    ]


def test_readable_quote_round_trip_restores_every_exact_binding_field():
    original = fact(quote="Guests do not have private vaults.")
    payload = payload_for([original])
    catalog = writer._support_ref_catalog(payload, [original], {original.id})
    assert catalog == {
        "s1": dict(
            competitor=original.competitor,
            dimension=original.dimension,
            fact_ids=[original.id],
            source_ids=[original.source_id],
            source_span_ids=[source_span_candidates(original)[0]["span_id"]],
        )
    }
    whitelist = module().dispatched_span_candidates(payload, [original], {original.id})
    claims, gaps, _ = writer.parse_question_claim_plans(
        json.dumps(
            dict(
                question_plans=[
                    dict(
                        question_id="q",
                        atoms=[dict(text=original.quote, kind="fact", support_refs=["s1"])],
                        missing_fields=[],
                    )
                ]
            )
        ),
        [dict(question_id="q", question="Do guests have private vaults?")],
        {},
        {original.id},
        "readable-test",
        support_refs=catalog,
        source_facts=[original],
        span_candidates=whitelist,
    )
    assert not gaps and len(claims) == 1
    assert (
        claims[0].source_span_bindings[0].model_dump(mode="json")
        == source_span_candidates(original)[0]
    )


@pytest.mark.parametrize(
    "change",
    [
        "text",
        "substring",
        "cross_fact",
        "original_quote",
        "original_value",
        "original_qualifiers",
        "duplicate_ref",
        "duplicate_invalid_ref",
        "extra_coordinate",
        "unknown_ref",
        "empty_quote",
        "non_string_quote",
    ],
)
def test_tampered_readable_reference_cannot_enter_catalog_or_whitelist(change):
    original = fact(quote="Guests do not have private vaults.")
    other = fact("other", quote="Organizations own all collections.")
    payload = payload_for([original])
    row = payload["evidence_view"]["facts"][0]
    candidate = row["source_span_candidates"][0]
    if change == "text":
        candidate["quote"] = "Guests have private vaults."
    elif change == "substring":
        candidate["quote"] = "private vaults"
    elif change == "cross_fact":
        candidate["quote"] = other.quote
    elif change == "original_quote":
        original = original.model_copy(update={"quote": "Changed original."})
    elif change == "original_value":
        original = original.model_copy(update={"value_json": canonical_json(["Changed value."])})
    elif change == "original_qualifiers":
        original = original.model_copy(
            update={"qualifiers_json": canonical_json({"plan": "Enterprise"})}
        )
    elif change == "duplicate_ref":
        row["source_span_candidates"].append(copy.deepcopy(candidate))
    elif change == "duplicate_invalid_ref":
        row["source_span_candidates"].append(dict(candidate, quote="Unrelated text."))
    elif change == "extra_coordinate":
        candidate["start"] = 0
    elif change == "unknown_ref":
        candidate["support_ref"] = "invented"
    elif change == "empty_quote":
        candidate["quote"] = ""
    else:
        candidate["quote"] = [original.quote]
    assert not writer._support_ref_catalog(payload, [original, other], {original.id})
    assert not module().dispatched_span_candidates(payload, [original, other], {original.id})


def test_incomplete_condition_list_cannot_be_readable_support():
    original = fact(
        quote=(
            "Guests can access a vault only when all of the following are true:\n"
            "- An owner confirms the invitation.\n- The guest accepts the invitation."
        )
    )
    payload = payload_for([original])
    payload["evidence_view"]["facts"][0]["source_span_candidates"][0]["quote"] = (
        original.quote.split("\n")[0]
    )
    assert not writer._support_ref_catalog(payload, [original], {original.id})
    assert not module().dispatched_span_candidates(payload, [original], {original.id})


def test_repeated_same_text_uses_canonical_candidate_path():
    original = fact(
        quote="Guests do not have private vaults.",
        value=["Guests do not have private vaults.", "Guests do not have private vaults."],
    )
    payload = payload_for([original])
    spans = module().dispatched_span_candidates(payload, [original], {original.id})
    assert list(spans.values()) == list(source_span_candidates(original))
    assert len(spans) == 1 and next(iter(spans.values()))["source_path"] == "quote"


def test_ambiguous_legal_candidates_are_rejected_if_canonical_generator_changes(monkeypatch):
    original = fact(quote="Guests do not have private vaults.")
    choices = list(source_span_candidates(original))
    choices.append(dict(choices[0], span_id="another-span", source_path="value/0"))
    monkeypatch.setattr(
        "packages.research.evidence.source_spans.source_span_candidates", lambda _: tuple(choices)
    )
    payload = payload_for([original])
    assert not writer._support_ref_catalog(payload, [original], {original.id})
    assert not module().dispatched_span_candidates(payload, [original], {original.id})


@pytest.mark.parametrize("annotated", [False, True])
def test_legacy_coordinate_reference_still_restores_exact_binding(annotated):
    original = fact(quote="Organizations own all collections.")
    span = source_span_candidates(original)[0]
    payload = payload_for([original])
    legacy = {key: span[key] for key in ("span_id", "source_path", "start", "end")}
    if annotated:
        legacy["support_ref"] = "s1"
    payload["evidence_view"]["facts"][0]["source_span_candidates"] = [legacy]
    assert module().dispatched_span_candidates(payload, [original], {original.id}) == {
        span["span_id"]: span
    }
    assert bool(writer._support_ref_catalog(payload, [original], {original.id})) is annotated
