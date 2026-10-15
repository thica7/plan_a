from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from test_run_evidence_snapshot import make_detail, make_document, with_document

from packages.research.evidence.snapshot import seal_snapshot

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def distributed_detail(*, dimensions=("feature",), observations=8):
    detail = make_detail()
    detail.plan.competitors = ["Coda", "Confluence", "Notion"]
    detail.plan.dimensions = list(dimensions)
    prototype = detail.raw_sources[0]
    detail.raw_sources = []
    for product in detail.plan.competitors:
        for dimension in dimensions:
            source = prototype.model_copy(deep=True)
            source.id = f"source-{product}-{dimension}"
            source.competitor = product
            source.covered_competitors = [product]
            source.dimension = dimension
            source.title = f"{product} official {dimension}"
            source.url = f"https://{product.lower()}.example/{dimension}"
            source.metadata["normalized_fields"] = []
            source.metadata.pop("market", None)  # Prototype pricing classification is not feature evidence.
            source.metadata["source_material_level"] = "full_source"
            for number in range(observations if product == "Coda" else 2):
                quote = f"{product} observation {number}: People can comment on shared pages. Requires membership in the workspace."
                common = dict(kind=dimension, competitor=product, dimension=dimension, confidence=.9, evidence_item_ids=[f"item-{product}-{dimension}-{number}"], qualifiers={"plan": "paid"})
                if dimension == "feature":
                    row = dict(common, slot=f"capability_{number}", support_level="documented", evidence_terms=[quote], evidence_quote=quote)
                else:
                    row = dict(common, tier_name=f"Plan {number}", price="10 USD", billing_cycle="monthly", source_quote=quote, unit="USD", market="US")
                source.metadata["normalized_fields"].append(row)
            detail.raw_sources.append(source)
    return detail


class FixedTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def test_evidence_projection_finishes_before_a_stage_deadline():
    import os
    import subprocess
    import sys
    program = '''
from test_stage_evidence_views import distributed_detail
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view
detail = distributed_detail(observations=16)
for source in detail.raw_sources:
    source.metadata['normalized_fields'] = [dict(source.metadata['normalized_fields'][0],
        slot='capability_' + str(number), evidence_item_ids=['item-' + str(number)],
        evidence_quote='People can comment on shared pages. ' + ('Workspace editors synchronize content while invited members review draft changes. ' * 8) + str(number),
        evidence_terms=['People can comment on shared pages. ' + ('Workspace editors synchronize content while invited members review draft changes. ' * 8) + str(number)])
        for number in range(16)]
snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
view = select_evidence_view(snapshot, agent='reflector', max_bytes=98304)
assert {fact.competitor for fact in view.facts} == set(detail.plan.competitors)
assert len(view.to_prompt_json().encode()) <= 98304
'''
    subprocess.run([sys.executable, '-c', program], check=True, timeout=20,
                   env={**os.environ, 'PYTHONPATH': 'backend:backend/tests/unit'},
                   capture_output=True, text=True)


def view_api(monkeypatch):
    from packages.research.evidence import views

    monkeypatch.setattr(views, "datetime", FixedTime)
    return views.select_evidence_view


def test_global_budget_represents_each_product_before_more_observations(monkeypatch):
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(distributed_detail(), phase="analysis", canonical_documents={})
    view = select(snapshot, agent="writer", max_bytes=8192)
    assert {fact.competitor for fact in view.facts} == {"Coda", "Confluence", "Notion"}
    assert view.estimated_bytes <= 8192


def test_global_budget_distributes_by_product_and_dimension(monkeypatch):
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(distributed_detail(dimensions=("feature", "pricing")), phase="analysis", canonical_documents={})
    # Six complete branch observations need the standard-depth budget.
    view = select(snapshot, agent="comparator", max_bytes=16384)
    assert {(fact.competitor, fact.dimension) for fact in view.facts} == {
        (product, dimension) for product in ("Coda", "Confluence", "Notion") for dimension in ("feature", "pricing")
    }


@pytest.mark.parametrize("product, budget, products", [
    ("Notion", 4120, ["Coda", "Notion"]),
    ("Confluence", 5850, ["Coda", "Confluence", "Notion"]),
])
def test_source_header_cost_does_not_starve_other_products(monkeypatch, product, budget, products):
    detail = distributed_detail(observations=2)
    detail.plan.competitors = products
    original = next(s for s in detail.raw_sources if s.competitor == product)
    first = original.model_copy(deep=True)
    first.id = f"{product.lower()}-short-quote"
    first.title = f"{product} official documentation " + "long page title " * 40
    first.metadata["normalized_fields"] = first.metadata["normalized_fields"][:1]
    second = original.model_copy(deep=True)
    second.id = f"{product.lower()}-alternative"
    second.title = f"{product} help"
    second.url = f"https://{product.lower()}.example/alternate"
    second.metadata["normalized_fields"] = second.metadata["normalized_fields"][1:]
    row = second.metadata["normalized_fields"][0]
    row["evidence_quote"] += " The editor supports collaborative discussion inside the document."
    row["evidence_terms"] = [row["evidence_quote"]]
    detail.raw_sources = [s for s in detail.raw_sources if s.competitor in products and s.competitor != product] + [first, second]
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = view_api(monkeypatch)(snapshot, agent="writer", max_bytes=budget)
    assert {fact.competitor for fact in view.facts} == set(products)
    assert view.estimated_bytes <= budget


def test_selected_observation_keeps_its_terms_and_conditions_together(monkeypatch):
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(distributed_detail(), phase="analysis", canonical_documents={})
    view = select(snapshot, agent="writer", max_bytes=8192)
    for item_id in {item for fact in view.facts for item in fact.evidence_item_ids}:
        available = {fact.id for fact in snapshot.facts if item_id in fact.evidence_item_ids}
        selected = {fact.id for fact in view.facts if item_id in fact.evidence_item_ids}
        assert selected == available
    omitted = {(fact.competitor, fact.dimension) for fact in snapshot.facts if fact.id not in view.fact_ids}
    assert omitted <= {(gap.competitor, gap.dimension) for gap in view.gaps if gap.reason == "context_budget_exceeded"}


def test_repeated_quote_is_stored_once_in_self_contained_prompt(monkeypatch):
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(distributed_detail(observations=1), phase="analysis", canonical_documents={})
    view = select(snapshot, agent="analyst", competitor="Coda", max_bytes=8192)
    payload = json.loads(view.to_prompt_json())
    quoted = payload.get("quoted_evidence", {})
    for fact in payload["facts"]:
        original = next(item for item in view.facts if item.id == fact["id"])
        assert (fact.get("quote") or quoted.get(fact.get("quote_ref"))) == original.quote
        if "quote_ref" in fact:
            assert quoted[fact["quote_ref"]] == original.quote
    quote = view.facts[0].quote
    assert view.to_prompt_json().count(quote) == 1


def test_view_exact_scope_typed_values_and_fresh_projection(monkeypatch) -> None:
    select = view_api(monkeypatch)
    detail = make_detail(price={"amount": 3999, "tax_included": True, "options": [256]})
    source = detail.raw_sources[0]
    row = source.metadata["normalized_fields"][0]
    row["qualifiers"] = {"tax_included": True, "capacity": 256}
    source.metadata.update(
        full_text="PRIVATE_BODY", html="PRIVATE_HTML", instructions="PRIVATE_RULE"
    )
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    before = snapshot.model_dump_json()
    view = select(snapshot, agent="analyst", competitor=" product a ", dimension="pricing")
    assert view.snapshot_id == snapshot.id
    price = next(fact for fact in view.facts if fact.field == "price")
    assert price.value["amount"] == 3999
    assert price.evidence_item_ids == ("item-product-a-price",)
    assert price.quote == row["source_quote"]
    assert price.source_id in view.source_ids
    price.value["options"].append(512)
    view.sources[0].to_raw_source().metadata["normalized_fields"][0]["price"] = "mutated"
    assert snapshot.model_dump_json() == before
    assert "PRIVATE_" not in view.to_prompt_json()
    wrong = select(snapshot, agent="analyst", competitor="Product A Pro", dimension="pricing")
    assert wrong.source_ids == () and wrong.fact_ids == ()
    assert "source_not_in_snapshot" in {
        gap.reason for gap in select(snapshot, agent="qa", source_ids=["missing"]).gaps
    }


@pytest.mark.parametrize(
    "agent",
    ["planner", "collector", "collect_qa", "analyst", "comparator", "reflector", "writer", "qa"],
)
def test_named_stage_views_keep_paired_facts_and_source_identity(monkeypatch, agent) -> None:
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(make_detail(), phase="analysis", canonical_documents={})
    view = select(snapshot, agent=agent, source_ids=[snapshot.sources[0].id])
    assert view.facts
    assert all(
        fact.source_id in view.source_ids and fact.quote and fact.evidence_item_ids
        for fact in view.facts
    )
    parsed = json.loads(view.to_prompt_json())
    assert parsed["snapshot_id"] == snapshot.id
    assert len(view.to_prompt_json().encode("utf-8")) == view.estimated_bytes
    assert view.estimated_tokens == view.estimated_bytes + 256
    assert parsed["token_estimation_method"] == "utf8_bytes_plus_256"


@pytest.mark.parametrize(
    "dates,reason",
    [
        ({"last_verified_at": "2026-09-01T00:00:00+00:00"}, "stale_evidence"),
        ({"last_verified_at": "2026-10-04T00:00:00+00:00"}, "future_source_date"),
        ({"last_verified_at": None}, "source_date_missing"),
    ],
)
def test_invalid_original_dates_downgrade_supported_facts(monkeypatch, dates, reason) -> None:
    select = view_api(monkeypatch)
    detail = make_detail()
    detail.raw_sources[0].metadata.update(dates)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = select(snapshot, agent="analyst")
    assert view.facts and all(fact.status == "signal" for fact in view.facts)
    assert reason in {gap.reason for gap in view.gaps}
    assert view.sources[0].last_verified_at == snapshot.sources[0].last_verified_at


def test_date_precedence_and_seven_thirty_day_rules(monkeypatch) -> None:
    select = view_api(monkeypatch)
    detail = make_detail()
    raw = detail.raw_sources[0]
    raw.metadata.update(
        last_verified_at=None,
        source_updated_at="2026-09-20T00:00:00+00:00",
        source_published_at="2026-10-02T00:00:00+00:00",
        fetched_at=NOW.isoformat(),
    )
    price = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert all(fact.status == "signal" for fact in select(price, agent="writer").facts)
    raw.dimension = "feature"
    raw.metadata["normalized_fields"] = [
        dict(
            kind="feature",
            dimension="feature",
            competitor="Product A",
            slot="support",
            support_level="supported",
            evidence_quote="Feature has source support",
            evidence_item_ids=["feature-id"],
            confidence=0.8,
        )
    ]
    feature = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert all(fact.status == "supported" for fact in select(feature, agent="analyst").facts)


def test_historical_summary_remains_advisory(monkeypatch) -> None:
    select = view_api(monkeypatch)
    detail = with_document(make_detail())
    doc = make_document(
        source_role="historical_report", metadata={"source_material_level": "summary"}
    )
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={doc.id: doc})
    view = select(snapshot, agent="planner")
    assert view.sources[0].role == "historical_report"
    assert all(fact.status == "signal" for fact in view.facts)
    assert "historical_evidence_advisory" in {gap.reason for gap in view.gaps}


@pytest.mark.parametrize(
    "source_type,level,advisory",
    [
        ("report", "historical_report", "historical_evidence_advisory"),
        ("webpage_verified", "summary", "summary_evidence_advisory"),
        ("webpage_verified", "search_summary", "summary_evidence_advisory"),
    ],
)
@pytest.mark.parametrize(
    "verified,date_gap",
    [
        (None, "source_date_missing"),
        ("2099-01-01T00:00:00+00:00", "future_source_date"),
        ("2020-01-01T00:00:00+00:00", "stale_evidence"),
    ],
)
def test_advisory_material_keeps_independent_date_gap(
    monkeypatch, source_type, level, advisory, verified, date_gap
) -> None:
    select = view_api(monkeypatch)
    detail = make_detail()
    detail.raw_sources[0].source_type = source_type
    detail.raw_sources[0].metadata.update(source_material_level=level, last_verified_at=verified)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    before = snapshot.model_dump_json()

    view = select(snapshot, agent="writer")

    assert view.facts and all(fact.status == "signal" for fact in view.facts)
    assert {advisory, date_gap} <= {gap.reason for gap in view.gaps}
    assert view.sources[0].last_verified_at == snapshot.sources[0].last_verified_at
    assert view.sources[0].source_fetched_at is None
    assert snapshot.model_dump_json() == before


@pytest.mark.parametrize("max_bytes", [8192, 16384, 24576])
def test_budget_omits_whole_quotes_and_values_and_reports_gap(monkeypatch, max_bytes) -> None:
    select = view_api(monkeypatch)
    detail = make_detail(price={"options": ["a" * max_bytes]})
    detail.raw_sources[0].metadata["normalized_fields"][0]["source_quote"] = "证据" * max_bytes
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = select(snapshot, agent="writer", max_bytes=max_bytes)
    assert not view.facts and not view.sources
    assert "context_budget_exceeded" in {gap.reason for gap in view.gaps}
    assert len(view.to_prompt_json().encode("utf-8")) <= max_bytes
    assert json.loads(view.to_prompt_json())


def test_selected_source_payload_cannot_smuggle_unselected_quote(monkeypatch) -> None:
    select = view_api(monkeypatch)
    detail = make_detail()
    row = dict(detail.raw_sources[0].metadata["normalized_fields"][0])
    row.update(
        price="huge-other-observation",
        source_quote="HUGE_UNSELECTED_" * 2000,
        evidence_item_ids=["other-observation"],
    )
    detail.raw_sources[0].metadata["normalized_fields"].append(row)
    # Different tiers make the giant observation independent of the small conflict-free row.
    row["tier_name"] = "Enterprise"
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = select(snapshot, agent="writer", max_bytes=8192)
    assert view.facts and view.sources
    assert "HUGE_UNSELECTED_" not in view.to_prompt_json()
    assert "HUGE_UNSELECTED_" not in view.sources[0].payload_json
    selected_values = {fact.value_json for fact in view.facts}
    for selected_source in view.sources:
        projected = selected_source.to_raw_source().metadata["normalized_fields"]
        assert not any(row.get("price") == "huge-other-observation" for row in projected)
    assert selected_values


def test_source_projection_preserves_separate_units_and_markets(monkeypatch) -> None:
    select = view_api(monkeypatch)
    detail = make_detail(price=3999)
    row = dict(detail.raw_sources[0].metadata["normalized_fields"][0])
    row.update(unit="USD", market="US")
    detail.raw_sources[0].metadata["normalized_fields"].append(row)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})

    view = select(snapshot, agent="analyst", max_bytes=16384)

    prices = [fact for fact in view.facts if fact.field == "price"]
    assert {(fact.unit, fact.market) for fact in prices} == {("CNY", "CN"), ("USD", "US")}
    projected = view.sources[0].to_raw_source().metadata["normalized_fields"]
    assert {(row["unit"], row["market"]) for row in projected} == {("CNY", "CN"), ("USD", "US")}
    assert all(
        row["price"] == 3999
        and row["source_quote"] == prices[0].quote
        and row["evidence_item_ids"] == list(prices[0].evidence_item_ids)
        for row in projected
    )


def test_conflict_positions_and_quotes_are_selected_as_a_complete_group(monkeypatch) -> None:
    select = view_api(monkeypatch)
    detail = make_detail()
    other = make_detail(price="4299 CNY").raw_sources[0]
    other.id = "other-price"
    detail.raw_sources.append(other)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = select(snapshot, agent="comparator", max_bytes=16384)
    assert view.conflicts
    for conflict in view.conflicts:
        assert set(conflict.fact_ids) <= set(view.fact_ids)
        assert set(conflict.source_ids) <= set(view.source_ids)


def test_page_local_capability_ordinals_do_not_create_cross_page_conflicts():
    detail = distributed_detail(observations=1)
    other = detail.raw_sources[0].model_copy(deep=True)
    other.id = 'coda-another-page'
    other.metadata['normalized_fields'][0]['evidence_terms'] = ['You can organize documents in a page tree.']
    other.metadata['normalized_fields'][0]['evidence_quote'] = 'You can organize documents in a page tree.'
    detail.raw_sources.append(other)
    assert not seal_snapshot(detail, phase='analysis', canonical_documents={}).conflicts


def test_shared_capability_precedes_shorter_unrelated_feature(monkeypatch):
    select = view_api(monkeypatch)
    detail = distributed_detail(observations=1)
    for source in detail.raw_sources:
        row = source.metadata['normalized_fields'][0]
        row.update(evidence_terms=[f'{source.competitor} users can comment on shared documents and resolve discussion threads.'],
                   evidence_quote=f'{source.competitor} users can comment on shared documents and resolve discussion threads.')
    source = detail.raw_sources[0]
    noise = dict(source.metadata['normalized_fields'][0], slot='capability_9',
                 evidence_item_ids=['item-unrelated'], evidence_quote='You can set the table row height.',
                 evidence_terms=['You can set the table row height.'])
    source.metadata['normalized_fields'].append(noise)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    view = select(snapshot, agent='writer', competitor='Coda', dimension='feature', max_bytes=4000)
    assert any(f.field == 'evidence_terms' and 'resolve discussion' in f.quote for f in view.facts)


def test_confidence_priority_does_not_starve_first_product_coverage(monkeypatch):
    select = view_api(monkeypatch)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Coda', 'Notion']
    detail.raw_sources = [source for source in detail.raw_sources if source.competitor in detail.plan.competitors]
    expensive = detail.raw_sources[0].model_copy(deep=True)
    expensive.id = 'coda-expensive'
    expensive.title = 'Coda official documentation ' + 'long page title ' * 40
    expensive.metadata['normalized_fields'][0]['confidence'] = .99
    detail.raw_sources.append(expensive)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    # Include the omission diagnostics for the still-unselected observations.
    view = select(snapshot, agent='writer', max_bytes=4100)
    assert {fact.competitor for fact in view.facts} == {'Coda', 'Notion'}


def test_requested_fact_keeps_the_whole_observation_and_conditions(monkeypatch):
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(distributed_detail(observations=1), phase='analysis', canonical_documents={})
    status = next(fact for fact in snapshot.facts if fact.competitor == 'Coda' and fact.field == 'support_level')
    view = select(snapshot, agent='comparator', fact_ids=[status.id], max_bytes=8192)
    assert {fact.competitor for fact in view.facts} == {'Coda'}
    assert any(fact.field == 'evidence_terms' and 'Requires membership' in str(fact.value) for fact in view.facts)
    replay = select(snapshot, agent='comparator', fact_ids=[status.id], max_bytes=8192)
    assert replay.dependency_hash == view.dependency_hash


def test_requested_fact_filter_does_not_conceal_price_conflict(monkeypatch):
    select = view_api(monkeypatch)
    detail = make_detail()
    other = make_detail(price='4299 CNY').raw_sources[0]
    other.id = 'conflicting-price'
    detail.raw_sources.append(other)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    selected = next(fact for fact in snapshot.facts if fact.field == 'price' and fact.source_id != other.id)
    view = select(snapshot, agent='comparator', fact_ids=[selected.id], max_bytes=8192)
    assert any(gap.reason == 'conflict_context_incomplete' for gap in view.gaps)
    assert next(fact for fact in view.facts if fact.id == selected.id).status == 'unknown'


def test_tiny_budget_and_unknown_agent_are_explicit_errors(monkeypatch) -> None:
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(make_detail(), phase="analysis", canonical_documents={})
    with pytest.raises(ValueError, match="budget"):
        select(snapshot, agent="analyst", max_bytes=1)
    with pytest.raises(ValueError, match="agent"):
        select(snapshot, agent="unknown")
