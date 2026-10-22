"""Only published supports are proof; unpublished exceptions may only restrict."""

import json
from types import SimpleNamespace

from test_answer_coverage import fact

from packages.agents.writer.answer_coverage import answer_review_payload
from packages.research.evidence.report_claims import ReportClaim
from packages.research.evidence.source_spans import source_span_candidates


def test_exact_support_and_kind_exclude_unpublished_parent_facts():
    original = fact(1, "Guests can access one vault. Guests have no Private vault.")
    original = original.model_copy(
        update={
            "value_json": json.dumps(
                ["Guests can access one vault.", "Guests have no Private vault."]
            )
        }
    )
    span = next(
        s for s in source_span_candidates(original) if s["quote"] == "Guests can access one vault."
    )
    claim = ReportClaim(
        id="c",
        text=span["quote"],
        kind="inference",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
        source_span_bindings=[span],
    )
    payload = answer_review_payload(
        [], [claim], SimpleNamespace(facts=[original], competitor=original.competitor)
    )
    assert payload["claims"][0]["kind"] == "inference"
    assert "no Private vault" not in str(payload)
    assert payload["published_supports"][0]["quote"] == span["quote"]
    assert payload["published_supports"][0]["claim_id"] == "c"


def test_unpublished_retained_copy_is_restrictive_context_only():
    original = fact(
        1, "If you allow members to keep a copy, they can retain downloaded files after removal."
    )
    payload = answer_review_payload(
        [],
        [],
        SimpleNamespace(facts=[original], competitor=original.competitor),
        additional_fact_ids={original.id},
    )
    assert not payload["claims"] and not payload["published_supports"]
    assert payload["restrictive_source_context"][0]["source_exceptions"]
    assert payload["restrictive_source_context"][0]["purpose"] == "reject_or_qualify_only"


def test_operation_support_does_not_restore_unpublished_parent_sentence():
    from packages.research.evidence.operations import operation_binding, operation_observations

    original = fact(1, "Guests can edit boards. Guests have no Private vault.")
    bound = operation_binding(operation_observations(original)[0])
    claim = ReportClaim(
        id="c",
        text="Guests can edit boards.",
        kind="fact",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
        operation_binding=bound,
    )
    payload = answer_review_payload(
        [], [claim], SimpleNamespace(facts=[original], competitor=original.competitor)
    )
    assert "no Private vault" not in str(payload)
    assert payload["published_supports"][0]["quote"] == bound["operation_quote"]
