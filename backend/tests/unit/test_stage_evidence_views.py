from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from test_run_evidence_snapshot import make_detail, make_document, with_document

from packages.research.evidence.snapshot import seal_snapshot

NOW = datetime(2026, 10, 3, tzinfo=UTC)


class FixedTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def view_api(monkeypatch):
    from packages.research.evidence import views

    monkeypatch.setattr(views, "datetime", FixedTime)
    return views.select_evidence_view


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


def test_tiny_budget_and_unknown_agent_are_explicit_errors(monkeypatch) -> None:
    select = view_api(monkeypatch)
    snapshot = seal_snapshot(make_detail(), phase="analysis", canonical_documents={})
    with pytest.raises(ValueError, match="budget"):
        select(snapshot, agent="analyst", max_bytes=1)
    with pytest.raises(ValueError, match="agent"):
        select(snapshot, agent="unknown")
