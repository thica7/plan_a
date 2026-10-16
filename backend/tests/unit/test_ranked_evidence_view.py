"""Anonymous ranked evidence selection, including complete observations."""

from datetime import UTC, datetime

import pytest
from test_run_evidence_snapshot import make_detail

from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view


class FixedTime(datetime):
    @classmethod
    def now(cls, tz=None):
        stamp = datetime(2026, 10, 3, tzinfo=UTC)
        return stamp if tz else stamp.replace(tzinfo=None)


def ranked_snapshot(monkeypatch, *, cross_product=False):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = make_detail()
    detail.plan.dimensions = ["feature"]
    detail.plan.competitors = ["Product A", "Product B"] if cross_product else ["Product A"]
    prototype = detail.raw_sources[0]
    detail.raw_sources = []
    rules = [
        ("noise", "Editors can edit documents shared with them.", 650),
        ("relevant", "Guests must sign in before accessing their invited documents.", 800),
    ]
    for index, product in enumerate(detail.plan.competitors):
        source = prototype.model_copy(deep=True)
        source.id = f"source-{index}"
        source.competitor = product
        source.covered_competitors = [product]
        source.dimension = "feature"
        source.title = f"{product} original rules"
        source.metadata.pop("market", None)
        source.metadata["source_material_level"] = "full_source"
        selected_rules = [rules[index]] if cross_product else rules
        source.metadata["normalized_fields"] = [
            dict(
                kind="feature",
                competitor=product,
                dimension="feature",
                slot=key,
                support_level="documented",
                evidence_terms=[quote, key + " original context " * size],
                evidence_quote=quote,
                evidence_item_ids=[key],
                qualifiers={"access": "direct invitation", "account": "signed in"},
                confidence=0.9,
            )
            for key, quote, size in selected_rules
        ]
        detail.raw_sources.append(source)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    requested = {
        fact.evidence_item_ids[0]: fact.id
        for fact in snapshot.facts
        if fact.field == "evidence_terms"
    }
    return snapshot, requested


def one_observation_budget(snapshot, requested):
    singles = [
        select_evidence_view(snapshot, agent="writer", fact_ids=[fact_id], max_bytes=100000)
        for fact_id in requested.values()
    ]
    full = select_evidence_view(
        snapshot, agent="writer", fact_ids=list(requested.values()), max_bytes=100000
    )
    budget = max(view.estimated_bytes for view in singles) + 1024
    assert budget < full.estimated_bytes
    return budget


@pytest.mark.parametrize("cross_product", [False, True])
def test_first_requested_observation_keeps_its_rank_under_the_byte_budget(
    monkeypatch, cross_product
):
    snapshot, requested = ranked_snapshot(monkeypatch, cross_product=cross_product)
    budget = one_observation_budget(snapshot, requested)
    view = select_evidence_view(
        snapshot,
        agent="writer",
        fact_ids=(requested["relevant"], requested["noise"], requested["relevant"]),
        max_bytes=budget,
    )
    assert requested["relevant"] in view.fact_ids
    assert requested["noise"] not in view.fact_ids
    siblings = {fact.id for fact in snapshot.facts if "relevant" in fact.evidence_item_ids}
    assert set(view.fact_ids) == siblings
    originals = {fact.id: fact for fact in snapshot.facts}
    for fact in view.facts:
        assert fact == originals[fact.id]
    assert view.estimated_bytes <= budget
    assert len(view.to_prompt_json().encode("utf-8")) == view.estimated_bytes
    assert "context_budget_exceeded" in {gap.reason for gap in view.gaps}
    assert {fact.source_id for fact in view.facts} <= set(view.source_ids)


def test_request_deduplication_preserves_first_order_and_hash_replay(monkeypatch):
    snapshot, requested = ranked_snapshot(monkeypatch)
    priority = (requested["relevant"], requested["noise"])
    first = select_evidence_view(snapshot, agent="qa", fact_ids=priority, max_bytes=100000)
    replay = select_evidence_view(
        snapshot, agent="qa", fact_ids=(*priority, priority[0]), max_bytes=100000
    )
    reversed_rank = select_evidence_view(
        snapshot, agent="qa", fact_ids=tuple(reversed(priority)), max_bytes=100000
    )
    assert first.dependency_hash == replay.dependency_hash
    assert first.fact_ids == replay.fact_ids
    assert first.dependency_hash != reversed_rank.dependency_hash


def test_reversing_explicit_rank_changes_the_selected_observation(monkeypatch):
    snapshot, requested = ranked_snapshot(monkeypatch)
    budget = one_observation_budget(snapshot, requested)
    first = select_evidence_view(
        snapshot,
        agent="writer",
        fact_ids=[requested["relevant"], requested["noise"]],
        max_bytes=budget,
    )
    second = select_evidence_view(
        snapshot,
        agent="writer",
        fact_ids=[requested["noise"], requested["relevant"]],
        max_bytes=budget,
    )
    assert requested["relevant"] in first.fact_ids
    assert requested["noise"] in second.fact_ids
    assert set(first.fact_ids).isdisjoint(second.fact_ids)


def test_none_retains_default_selection_and_empty_tuple_remains_explicitly_empty(monkeypatch):
    snapshot, requested = ranked_snapshot(monkeypatch)
    before = snapshot.model_dump_json()
    budget = one_observation_budget(snapshot, requested)
    default = select_evidence_view(snapshot, agent="writer", max_bytes=budget)
    no_filter = select_evidence_view(snapshot, agent="writer", fact_ids=None, max_bytes=budget)
    empty = select_evidence_view(snapshot, agent="writer", fact_ids=(), max_bytes=budget)
    assert default == no_filter
    assert requested["noise"] in default.fact_ids
    assert not empty.fact_ids
    assert empty.dependency_hash != default.dependency_hash
    assert snapshot.model_dump_json() == before


def test_requested_rank_does_not_bypass_product_and_source_scope(monkeypatch):
    snapshot, requested = ranked_snapshot(monkeypatch, cross_product=True)
    source_a = next(source.id for source in snapshot.sources if source.competitor == "Product A")
    view = select_evidence_view(
        snapshot,
        agent="writer",
        competitor="Product A",
        source_ids=[source_a],
        fact_ids=[requested["relevant"], requested["noise"]],
        max_bytes=100000,
    )
    assert requested["relevant"] not in view.fact_ids
    assert requested["noise"] in view.fact_ids
    assert {fact.competitor for fact in view.facts} == {"Product A"}
    assert view.source_ids == (source_a,)
