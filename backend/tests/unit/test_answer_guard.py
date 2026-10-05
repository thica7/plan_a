from __future__ import annotations

import importlib
import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

# isort: split
from packages.research.evidence.snapshot_models import (
    EvidenceConflict,
    EvidenceFact,
    EvidenceSource,
    StageEvidenceView,
    canonical_json,
)

AS_OF = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def api():
    try:
        models = importlib.import_module("packages.research.evidence.answer_models")
        guard = importlib.import_module("packages.research.evidence.answer_guard")
    except ModuleNotFoundError as error:
        raise AssertionError(f"answer boundary API is not implemented: {error.name}") from error
    return models, guard.evaluate_answer_boundary


def source(source_id="source-a", **changes):
    values = dict(
        id=source_id,
        semantic_id=source_id,
        competitor="Product A",
        dimension="pricing",
        source_type="official_page",
        title="Original pricing",
        content_hash="source-hash",
        material_level="full_source",
        market="CN",
        confidence=0.9,
        source_published_at=datetime(2026, 10, 1, tzinfo=UTC),
        source_fetched_at=NOW,
        last_verified_at=NOW,
        extracted_at=NOW,
        payload_json="{}",
    )
    return EvidenceSource(**(values | changes))


def fact(fact_id="price-a", *, value=None, qualifiers=None, **changes):
    values = dict(
        id=fact_id,
        semantic_id=fact_id,
        evidence_item_ids=(f"item-{fact_id}",),
        source_id="source-a",
        competitor="Product A",
        dimension="pricing",
        field="price",
        value_json=canonical_json(
            value if value is not None else {"amount": 99, "currency": "CNY"}
        ),
        market="CN",
        qualifiers_json=canonical_json(qualifiers if qualifiers is not None else device_scope()),
        quote="The exact original evidence passage.",
        status="supported",
        confidence=0.9,
    )
    return EvidenceFact(**(values | changes))


def device_scope(**changes):
    return (
        dict(
            price_type="official_current",
            price_basis="device",
            billing_interval="one_time",
            tax_scope="tax_included",
            model="Model A",
            capacity="256GB",
            condition="new",
            observed_at="2026-10-05T12:00:00Z",
            shipping_scope="included",
            offer_conditions="No restrictions",
        )
        | changes
    )


def view(*facts, sources=None, conflicts=()):
    sources = (source(),) if sources is None else tuple(sources)
    return StageEvidenceView(
        agent="writer",
        run_id="run-a",
        workspace_id="workspace-a",
        snapshot_id="snapshot-a",
        snapshot_version=1,
        content_hash="snapshot-hash",
        source_ids=tuple(item.id for item in sources),
        fact_ids=tuple(item.id for item in facts),
        sources=sources,
        facts=tuple(facts),
        conflicts=tuple(conflicts),
        dependency_hash="dependency-hash",
    )


def requirement(intent="current_price", *, context=None, **changes):
    models, _ = api()
    return models.AnswerRequirement(
        **(
            dict(
                competitor="Product A",
                dimension="pricing",
                intent=intent,
                market="CN",
                as_of=AS_OF,
                context_json=canonical_json(context or {}),
            )
            | changes
        )
    )


def evaluate(evidence, intent="current_price", **changes):
    _, guard = api()
    return guard(evidence, requirement(intent, **changes))


def decision(boundary, fact_id="price-a"):
    return next(item for item in boundary.fact_decisions if item.fact_id == fact_id)


def test_dynamic_import_exposes_boundary_api():
    models, guard = api()
    assert callable(guard)
    assert models.AnswerRequirement and models.AnswerBoundary and models.FactDecision


@pytest.mark.parametrize("amount", [0, 99, 99.5])
def test_complete_structured_current_price_including_zero_is_answerable(amount):
    boundary = evaluate(view(fact(value={"amount": amount, "currency": "CNY"})))
    assert boundary.status == "answer"
    assert boundary.allowed_fact_ids == ("price-a",)
    assert boundary.withheld_fact_ids == boundary.missing_fields == ()
    assert decision(boundary).allowed


def test_missing_amount_retains_mechanism_and_does_not_treat_nonempty_search_as_complete():
    mechanism = fact("mechanism", field="model_type", value="subscription", qualifiers={})
    price = fact(value="CNY 99 / month", qualifiers={})
    boundary = evaluate(view(price, mechanism))
    assert boundary.status == "partial"
    assert boundary.allowed_fact_ids == ("mechanism",)
    assert "amount" in boundary.missing_fields
    assert "missing_entity_price" in decision(boundary).reasons
    method = evaluate(view(price, mechanism), "source_guidance")
    assert method.status in {"answer", "partial"}
    assert method.allowed_fact_ids == ("mechanism",)


def test_source_guidance_without_complete_package_matrix_is_answerable():
    mechanism = fact("method", field="enterprise_condition", value="Check official terms")
    boundary = evaluate(view(mechanism), "source_guidance")
    assert boundary.status == "answer"
    assert boundary.allowed_fact_ids == ("method",)


def test_source_guidance_with_original_source_but_no_extracted_facts_is_partial():
    boundary = evaluate(view(), "source_guidance")
    assert boundary.status == "partial"
    assert boundary.allowed_fact_ids == ()
    assert "structured_facts" in boundary.missing_fields
    assert evaluate(view(sources=[source(material_level="summary")]), "source_guidance").status == (
        "insufficient"
    )


@pytest.mark.parametrize("price_type", ["official_launch", "historical", "unknown"])
def test_old_publication_price_is_never_promoted_by_a_fresh_fetch(price_type):
    original = source(source_published_at=datetime(2023, 1, 1, tzinfo=UTC))
    price = fact(qualifiers=device_scope(price_type=price_type))
    boundary = evaluate(view(price, sources=[original]))
    assert boundary.status == "insufficient"
    assert boundary.allowed_fact_ids == ()
    assert "price_type" in boundary.missing_fields


@pytest.mark.parametrize("price_type", [[], {}])
def test_json_container_price_type_is_withheld_without_crashing_guard(price_type):
    boundary = evaluate(view(fact(qualifiers=device_scope(price_type=price_type))))
    assert boundary.allowed_fact_ids == ()
    assert "price_type" in boundary.missing_fields


@pytest.mark.parametrize(
    "fact_changes,source_changes,reason",
    [
        ({"market": "US"}, {}, "market_mismatch"),
        ({"market": None}, {}, "market_missing"),
        ({}, {"market": None}, "market_missing"),
        ({}, {"market": "US"}, "market_mismatch"),
        ({"competitor": "Product A Pro"}, {}, "competitor_mismatch"),
        ({}, {"competitor": "Product B"}, "competitor_mismatch"),
        ({"dimension": "features"}, {}, "dimension_mismatch"),
        ({}, {"dimension": "features"}, "dimension_mismatch"),
    ],
)
def test_each_fact_and_original_source_must_match_requested_scope(
    fact_changes, source_changes, reason
):
    boundary = evaluate(view(fact(**fact_changes), sources=[source(**source_changes)]))
    assert boundary.allowed_fact_ids == ()
    assert reason in decision(boundary).reasons


def test_price_market_is_a_required_research_condition():
    boundary = evaluate(view(fact()), market=None)
    assert boundary.status == "clarify"
    assert "market" in boundary.clarification_fields
    assert boundary.allowed_fact_ids == ()


@pytest.mark.parametrize(
    "dates,reason",
    [
        ({"last_verified_at": None}, "unverified_price"),
        ({"last_verified_at": datetime(2026, 9, 27, tzinfo=UTC)}, "stale_price"),
        ({"last_verified_at": datetime(2026, 10, 6, tzinfo=UTC)}, "future_source_date"),
        ({"source_published_at": datetime(2026, 10, 6, tzinfo=UTC)}, "future_source_date"),
        ({"source_updated_at": datetime(2026, 10, 6, tzinfo=UTC)}, "future_source_date"),
        ({"source_fetched_at": datetime(2026, 10, 6, tzinfo=UTC)}, "future_source_date"),
    ],
)
def test_future_and_stale_dates_reject_prices_and_fetch_cannot_supply_verification(dates, reason):
    boundary = evaluate(view(fact(), sources=[source(**dates)]))
    assert boundary.allowed_fact_ids == ()
    assert reason in decision(boundary).reasons


def test_fact_verification_date_is_valid_evidence_but_future_fact_dates_are_not():
    qualifiers = device_scope(verified_at="2026-10-05")
    evidence = view(fact(qualifiers=qualifiers), sources=[source(last_verified_at=None)])
    assert evaluate(evidence).status == "answer"
    future = fact(qualifiers=device_scope(verified_at="2026-10-06"))
    assert "future_fact_date" in decision(evaluate(view(future))).reasons


@pytest.mark.parametrize(
    "date_key", ["published_at", "updated_at", "observed_at", "effective_date"]
)
def test_future_fact_dates_also_withhold_ordinary_supported_facts(date_key):
    ordinary = fact(
        "method", field="model_type", value="subscription", qualifiers={date_key: "2026-10-06"}
    )
    boundary = evaluate(view(ordinary), "facts")
    assert boundary.allowed_fact_ids == ()
    assert "future_fact_date" in decision(boundary, "method").reasons


def test_future_date_in_structured_value_cannot_be_hidden_by_current_source_verification():
    qualifiers = device_scope()
    qualifiers.pop("observed_at")
    price = fact(
        value={"amount": 99, "currency": "CNY", "observed_at": "2026-10-06"}, qualifiers=qualifiers
    )
    boundary = evaluate(view(price))
    assert boundary.allowed_fact_ids == ()
    assert "future_fact_date" in decision(boundary).reasons


def test_time_window_without_timezone_needs_clarification():
    price = fact(qualifiers=device_scope(channel="Store A"))
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05T10:00:00", window_end="2026-10-05T16:00:00"
    )
    boundary = evaluate(view(price), "price_comparison", context=context)
    assert boundary.status == "clarify"
    assert {"window_start", "window_end"} <= set(boundary.clarification_fields)


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_unvalidated_projection_cannot_become_a_price(amount):
    projected = fact().model_copy(
        update={"value_json": json.dumps({"amount": amount, "currency": "CNY"})}
    )
    boundary = evaluate(view(projected))
    assert boundary.allowed_fact_ids == ()
    assert "amount" in boundary.missing_fields


@pytest.mark.parametrize("amount", [True, -1, "unknown", "99", None])
def test_invalid_amounts_cannot_be_guessed_or_coerced(amount):
    boundary = evaluate(view(fact(value={"amount": amount, "currency": "CNY"})))
    assert boundary.allowed_fact_ids == ()
    assert "amount" in boundary.missing_fields
    assert "missing_entity_price" in decision(boundary).reasons


@pytest.mark.parametrize("currency", ["cny", "CN", "unknown", None])
def test_currency_requires_an_uppercase_three_letter_code(currency):
    boundary = evaluate(view(fact(value={"amount": 99, "currency": currency})))
    assert boundary.allowed_fact_ids == ()
    assert "currency" in boundary.missing_fields


def test_structured_aliases_work_but_request_plan_cannot_supply_source_seat_or_plan():
    qualifiers = dict(
        price_type="official_current",
        price_basis="subscription",
        tax_scope="tax_excluded",
        tier_name="Pro",
        billing_cycle="monthly",
        seat_type="per_user",
    )
    price = fact(qualifiers=qualifiers, value={"amount": 0, "currency": "CNY"})
    assert evaluate(view(price)).status == "answer"
    missing_plan = qualifiers.copy()
    missing_plan.pop("tier_name")
    missing_plan.pop("seat_type")
    boundary = evaluate(view(fact(qualifiers=missing_plan)), context={"plan": "Pro"})
    assert boundary.allowed_fact_ids == ()
    assert {"plan", "seat_type"} <= set(boundary.missing_fields)
    unit_alias = fact(value={"amount": 99}, unit="USD")
    assert evaluate(view(unit_alias)).status == "answer"
    missing_cycle = fact(
        value={"amount": 99}, unit="USD", qualifiers=device_scope() | {"billing_interval": None}
    )
    assert "billing_interval" in evaluate(view(missing_cycle)).missing_fields


@pytest.mark.parametrize("missing", ["tax_scope", "condition", "capacity", "model"])
def test_required_price_conditions_cannot_be_omitted(missing):
    qualifiers = device_scope()
    qualifiers.pop(missing)
    boundary = evaluate(view(fact(qualifiers=qualifiers)))
    assert boundary.allowed_fact_ids == ()
    assert missing in boundary.missing_fields


@pytest.mark.parametrize("field", ["tax_scope", "model", "seat_type"])
def test_boolean_price_conditions_do_not_count_as_explicit_scope(field):
    qualifiers = device_scope(**{field: True})
    if field == "seat_type":
        qualifiers.update(price_basis="subscription", plan="Pro")
    boundary = evaluate(view(fact(qualifiers=qualifiers)))
    assert boundary.allowed_fact_ids == ()
    assert field in boundary.missing_fields


def test_conflicting_structured_amounts_are_withheld():
    price = fact(qualifiers=device_scope(amount=79))
    boundary = evaluate(view(price))
    assert boundary.allowed_fact_ids == ()
    assert "structured_field_conflict" in decision(boundary).reasons


def test_channel_offer_preserves_explicit_offer_conditions():
    qualifiers = device_scope(price_type="channel_offer", channel="Store A")
    qualifiers.pop("offer_conditions")
    boundary = evaluate(view(fact(qualifiers=qualifiers)))
    assert "offer_conditions" in boundary.missing_fields
    complete = fact(qualifiers=qualifiers | {"offer_conditions": "No membership required"})
    evidence = view(complete)
    before = evidence.model_dump_json()
    assert evaluate(evidence).status == "answer"
    assert evidence.model_dump_json() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("channel", True),
        ("channel", ["Store A"]),
        ("channel", {"name": "Store A"}),
        ("offer_conditions", False),
        ("offer_conditions", True),
        ("offer_conditions", ["none"]),
        ("offer_conditions", {"terms": "none"}),
    ],
)
def test_channel_offer_channel_and_conditions_require_explicit_text(field, value):
    qualifiers = device_scope(price_type="channel_offer", channel="Store A")
    qualifiers[field] = value
    boundary = evaluate(view(fact(qualifiers=qualifiers)))
    assert boundary.allowed_fact_ids == ()
    assert field in boundary.missing_fields


def test_explicit_official_listed_unit_with_unknown_tax_retains_amount_as_partial():
    price = fact(qualifiers=device_scope(price_scope="listed_unit", tax_scope="unknown"))
    boundary = evaluate(view(price))
    assert boundary.allowed_fact_ids == ("price-a",)
    assert boundary.status == "partial"
    assert "tax_scope" in boundary.missing_fields
    assert "tax_scope" in decision(boundary).missing_fields


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {
            "price_scope": "listed_unit",
            "price_type": "channel_offer",
            "channel": "Store A",
            "offer_conditions": "No restrictions",
        },
    ],
)
def test_unknown_tax_without_narrow_official_listed_scope_withholds_amount(scope):
    price = fact(qualifiers=device_scope(tax_scope="unknown") | scope)
    boundary = evaluate(view(price))
    assert boundary.allowed_fact_ids == ()
    assert "tax_scope" in boundary.missing_fields


def comparison_context(**changes):
    return (
        dict(
            channels=["Store A", "Store B"],
            window_start="2026-10-01",
            window_end="2026-10-05",
            capacity="256GB",
            condition="new",
            currency="CNY",
        )
        | changes
    )


def test_price_comparison_clarifies_missing_scope_even_when_retrieval_is_nonempty():
    boundary = evaluate(view(fact()), "price_comparison", context={})
    assert boundary.status == "clarify"
    assert {"channels", "window_start", "window_end", "capacity", "condition", "currency"} <= set(
        boundary.clarification_fields
    )


def test_price_comparison_never_shrinks_the_expected_channel_set():
    first = fact(qualifiers=device_scope(channel="Store A"))
    boundary = evaluate(view(first), "price_comparison", context=comparison_context())
    assert boundary.status == "partial"
    assert boundary.allowed_fact_ids == ("price-a",)
    assert "observations.Store B" in boundary.missing_fields
    second = fact("price-b", qualifiers=device_scope(channel="Store B"))
    complete = evaluate(view(second, first), "price_comparison", context=comparison_context())
    assert complete.status == "answer"
    assert complete.missing_fields == ()
    assert "average" not in complete.model_dump_json()


def test_comparison_official_channel_observation_requires_explicit_offer_conditions():
    qualifiers = device_scope(channel="Store A")
    qualifiers.pop("offer_conditions", None)
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05T10:00:00Z", window_end="2026-10-05T16:00:00Z"
    )
    boundary = evaluate(view(fact(qualifiers=qualifiers)), "price_comparison", context=context)
    assert boundary.allowed_fact_ids == ()
    assert boundary.status == "insufficient"
    assert "offer_conditions" in decision(boundary).missing_fields
    assert "observations.Store A" in boundary.missing_fields


@pytest.mark.parametrize("offer_conditions", ["none", "no restrictions"])
def test_comparison_official_channel_can_explicitly_record_no_offer_restrictions(offer_conditions):
    price = fact(qualifiers=device_scope(channel="Store A", offer_conditions=offer_conditions))
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05T10:00:00Z", window_end="2026-10-05T16:00:00Z"
    )
    boundary = evaluate(view(price), "price_comparison", context=context)
    assert boundary.status == "answer"
    assert boundary.allowed_fact_ids == ("price-a",)


@pytest.mark.parametrize("offer_conditions", [True, False, ["none"], {"terms": "none"}])
def test_comparison_offer_conditions_require_text_not_boolean_or_container(offer_conditions):
    price = fact(qualifiers=device_scope(channel="Store A", offer_conditions=offer_conditions))
    boundary = evaluate(
        view(price), "price_comparison", context=comparison_context(channels=["Store A"])
    )
    assert boundary.allowed_fact_ids == ()
    assert "offer_conditions" in boundary.missing_fields


@pytest.mark.parametrize(
    "qualifiers,missing",
    [
        (device_scope(channel="Store A", capacity="128GB"), "capacity"),
        (device_scope(channel="Store A", condition="used"), "condition"),
        (device_scope(channel="Store A", observed_at="2026-09-30T12:00:00Z"), "window"),
    ],
)
def test_comparison_observations_must_share_capacity_condition_and_window(qualifiers, missing):
    boundary = evaluate(
        view(fact(qualifiers=qualifiers)), "price_comparison", context=comparison_context()
    )
    assert boundary.allowed_fact_ids == ()
    assert "observations.Store A" in boundary.missing_fields
    assert missing in decision(boundary).missing_fields


@pytest.mark.parametrize("observed_at", ["2026-10-05T18:00:00Z", "2026-10-05T12:00:00+08:00"])
def test_comparison_time_windows_preserve_hours_and_timezone_offsets(observed_at):
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05T10:00:00Z", window_end="2026-10-05T16:00:00Z"
    )
    price = fact(qualifiers=device_scope(channel="Store A", observed_at=observed_at))
    boundary = evaluate(view(price), "price_comparison", context=context)
    assert boundary.allowed_fact_ids == ()
    assert "window" in decision(boundary).missing_fields
    assert "observations.Store A" in boundary.missing_fields


def test_comparison_accepts_window_inside_observation_in_another_timezone():
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05T10:00:00Z", window_end="2026-10-05T16:00:00Z"
    )
    price = fact(
        qualifiers=device_scope(channel="Store A", observed_at="2026-10-05T20:00:00+08:00")
    )
    assert evaluate(view(price), "price_comparison", context=context).status == "answer"


def test_comparison_cannot_replace_observation_time_with_verification_time():
    qualifiers = device_scope(channel="Store A")
    qualifiers.pop("observed_at")
    boundary = evaluate(
        view(fact(qualifiers=qualifiers)),
        "price_comparison",
        context=comparison_context(channels=["Store A"]),
    )
    assert boundary.allowed_fact_ids == ()
    assert "observed_at" in boundary.missing_fields


def test_date_only_observation_cannot_fill_a_window_with_hours():
    price = fact(qualifiers=device_scope(channel="Store A", observed_at="2026-10-05"))
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05T10:00:00Z", window_end="2026-10-05T16:00:00Z"
    )
    assert (
        "observed_at" in evaluate(view(price), "price_comparison", context=context).missing_fields
    )


def test_lowercase_timestamp_separator_still_requires_precise_observation_time():
    price = fact(qualifiers=device_scope(channel="Store A", observed_at="2026-10-05"))
    context = comparison_context(
        channels=["Store A"], window_start="2026-10-05t00:00:00Z", window_end="2026-10-05t16:00:00Z"
    )
    boundary = evaluate(view(price), "price_comparison", context=context)
    assert boundary.allowed_fact_ids == ()
    assert "observed_at" in boundary.missing_fields


def test_whitespace_trimmed_date_only_window_remains_a_full_day_window():
    price = fact(qualifiers=device_scope(channel="Store A", observed_at="2026-10-05"))
    context = comparison_context(
        channels=["Store A"], window_start=" 2026-10-05 ", window_end="\t2026-10-05\t"
    )
    boundary = evaluate(view(price), "price_comparison", context=context)
    assert boundary.status == "answer"
    assert boundary.allowed_fact_ids == ("price-a",)


def test_comparison_requires_common_currency_and_explicit_shipping_scope():
    context = comparison_context(channels=["Store A", "Store B"])
    first = fact(qualifiers=device_scope(channel="Store A"))
    other_currency = fact(
        "price-b",
        value={"amount": 99, "currency": "USD"},
        qualifiers=device_scope(channel="Store B"),
    )
    boundary = evaluate(view(first, other_currency), "price_comparison", context=context)
    assert boundary.allowed_fact_ids == ("price-a",)
    assert "observations.Store B" in boundary.missing_fields
    context.pop("currency")
    assert (
        "currency"
        in evaluate(view(first), "price_comparison", context=context).clarification_fields
    )
    no_shipping = device_scope(channel="Store A")
    no_shipping.pop("shipping_scope")
    boundary = evaluate(
        view(fact(qualifiers=no_shipping)),
        "price_comparison",
        context=comparison_context(channels=["Store A"]),
    )
    assert boundary.allowed_fact_ids == ()
    assert "shipping_scope" in boundary.missing_fields


@pytest.mark.parametrize("evidence_eligibility", [None, "members_only"])
def test_request_discount_eligibility_must_be_evidenced_not_injected(evidence_eligibility):
    price = fact(
        qualifiers=device_scope(channel="Store A", discount_eligibility=evidence_eligibility)
    )
    context = comparison_context(channels=["Store A"], discount_eligibility="all_buyers")
    boundary = evaluate(view(price), "price_comparison", context=context)
    assert boundary.allowed_fact_ids == ()
    assert "discount_eligibility" in boundary.missing_fields
    matching = fact(qualifiers=device_scope(channel="Store A", discount_eligibility="all_buyers"))
    assert evaluate(view(matching), "price_comparison", context=context).status == "answer"


def test_only_package_fee_cannot_prove_total_cost_or_cover_external_fees():
    package = fact(
        qualifiers=dict(
            price_type="official_current",
            price_basis="subscription",
            plan="Pro",
            seat_type="per_user",
            billing_interval="monthly",
            tax_scope="included",
        )
    )
    context = dict(
        reporting_period="2026-09",
        currency="CNY",
        required_components=["subscription", "payment_settlement", "external_app"],
    )
    boundary = evaluate(view(package), "total_cost", context=context)
    assert boundary.status == "partial"
    assert boundary.allowed_fact_ids == ("price-a",)
    assert {
        "cost_component.subscription",
        "cost_component.payment_settlement",
        "cost_component.external_app",
    } <= set(boundary.missing_fields)


def test_total_cost_requires_records_for_every_applicable_component_and_matching_period():
    context = dict(
        reporting_period="2026-09",
        currency="CNY",
        required_components=["subscription", "external_app"],
    )
    records = [
        fact(
            name,
            field="charge",
            value={"amount": amount, "currency": "CNY"},
            qualifiers={
                "cost_component": name,
                "charge_id": f"charge-{name}",
                "reporting_period": "2026-09",
            },
        )
        for name, amount in [("subscription", 99), ("external_app", 0)]
    ]
    boundary = evaluate(view(*records), "total_cost", context=context)
    assert boundary.status == "answer"
    assert boundary.missing_fields == ()
    wrong = records[0].model_copy(
        update={
            "qualifiers_json": canonical_json(
                {
                    "cost_component": "subscription",
                    "charge_id": "charge-subscription",
                    "reporting_period": "2026-08",
                }
            )
        }
    )
    boundary = evaluate(view(wrong, records[1]), "total_cost", context=context)
    assert "cost_component.subscription" in boundary.missing_fields
    assert "subscription" in boundary.withheld_fact_ids


@pytest.mark.parametrize("missing", ["cost_component", "charge_id", "reporting_period"])
def test_cost_records_need_evidence_component_charge_identity_and_reporting_period(missing):
    context = dict(reporting_period="2026-09", currency="CNY", required_components=["external_app"])
    qualifiers = dict(
        cost_component="external_app", charge_id="charge-app", reporting_period="2026-09"
    )
    qualifiers.pop(missing)
    record = fact("charge", field="cost_component", qualifiers=qualifiers)
    boundary = evaluate(view(record), "total_cost", context=context)
    assert boundary.allowed_fact_ids == ()
    assert missing in boundary.missing_fields


def test_total_cost_missing_applicable_set_requests_clarification():
    mechanism = fact("mechanism", field="model_type", value="subscription", qualifiers={})
    boundary = evaluate(view(mechanism), "total_cost")
    assert boundary.status == "clarify"
    assert {"reporting_period", "currency", "required_components"} <= set(
        boundary.clarification_fields
    )


def test_actual_snapshot_price_field_can_hold_scoped_cost_records():
    from test_run_evidence_snapshot import make_detail

    # isort: split
    from packages.research.evidence.snapshot import seal_snapshot

    detail = make_detail(price={"amount": 99, "currency": "CNY"})
    raw = detail.raw_sources[0]
    raw.metadata["source_material_level"] = "full_source"
    row = raw.metadata["normalized_fields"][0]
    row["qualifiers"] = dict(
        cost_component="external_app", charge_id="charge-app", reporting_period="2026-09"
    )
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert "price" in {item.field for item in snapshot.facts}
    boundary = evaluate(
        view(*snapshot.facts, sources=snapshot.sources),
        "total_cost",
        context=dict(
            reporting_period="2026-09", currency="CNY", required_components=["external_app"]
        ),
    )
    assert boundary.status == "answer"
    assert boundary.missing_fields == ()


def compliance_context():
    return dict(
        industry="healthcare",
        jurisdiction="US",
        compliance_standard="HIPAA",
        intended_use="patient_records",
    )


def test_nonempty_notes_evidence_requires_compliance_clarification():
    notes = fact("notes", field="support_level", value="supported", qualifiers={})
    boundary = evaluate(view(notes), "compliance")
    assert boundary.status == "clarify"
    assert set(boundary.clarification_fields) == set(compliance_context())
    assert boundary.allowed_fact_ids == ("notes",)


def test_notes_with_request_conditions_do_not_prove_compliance():
    notes = fact("notes", field="support_level", value="supported", qualifiers={})
    boundary = evaluate(view(notes), "compliance", context=compliance_context())
    assert boundary.status == "partial"
    assert "compliance_evidence" in boundary.missing_fields
    scoped = fact(
        "certification", field="compliance", value="certified", qualifiers=compliance_context()
    )
    assert evaluate(view(scoped), "compliance", context=compliance_context()).status == "answer"


def test_actual_snapshot_support_level_with_explicit_compliance_claim_can_answer():
    from test_run_evidence_snapshot import make_detail

    # isort: split
    from packages.research.evidence.snapshot import seal_snapshot

    detail = make_detail()
    raw = detail.raw_sources[0]
    raw.dimension = "feature"
    raw.metadata.update(
        source_material_level="full_source",
        normalized_fields=[
            dict(
                kind="feature",
                dimension="feature",
                competitor="Product A",
                slot="compliance",
                support_level="supported",
                evidence_quote="Original scoped certification evidence.",
                evidence_item_ids=["certification-evidence"],
                market="CN",
                qualifiers=compliance_context() | {"claim_kind": "compliance"},
            )
        ],
    )
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert "support_level" in {item.field for item in snapshot.facts}
    boundary = evaluate(
        view(*snapshot.facts, sources=snapshot.sources),
        "compliance",
        context=compliance_context(),
        dimension="feature",
    )
    assert boundary.status == "answer"
    assert boundary.missing_fields == ()


@pytest.mark.parametrize(
    "fact_changes,source_changes,reason",
    [
        ({"source_id": "missing-source"}, {}, "source_missing"),
        ({"status": "signal"}, {}, "unsupported_status"),
        ({"status": "unknown"}, {}, "unsupported_status"),
        ({"quote": " "}, {}, "evidence_quote_missing"),
        ({"evidence_item_ids": ()}, {}, "evidence_item_ids_missing"),
        ({}, {"material_level": "summary"}, "non_original_source"),
        ({}, {"role": "historical_report"}, "non_original_source"),
        ({}, {"source_type": "web_search_result"}, "non_original_source"),
        ({}, {"status": "inactive"}, "source_inactive"),
    ],
)
def test_unpaired_signal_summary_historical_and_unquoted_facts_are_withheld(
    fact_changes, source_changes, reason
):
    boundary = evaluate(view(fact(**fact_changes), sources=[source(**source_changes)]), "facts")
    assert boundary.allowed_fact_ids == ()
    assert reason in decision(boundary).reasons


def test_conflicted_fact_is_withheld_even_if_marked_supported():
    conflict = EvidenceConflict(
        id="conflict-a",
        competitor="Product A",
        dimension="pricing",
        field="price",
        fact_ids=("price-a", "not-in-view"),
        source_ids=("source-a", "not-in-view"),
    )
    boundary = evaluate(view(fact(), conflicts=[conflict]))
    assert boundary.allowed_fact_ids == ()
    assert "unresolved_conflict" in decision(boundary).reasons


def test_fact_and_source_must_belong_to_the_declared_view_selection():
    evidence = view(fact()).model_copy(update={"source_ids": (), "fact_ids": ()})
    boundary = evaluate(evidence)
    assert boundary.allowed_fact_ids == ()
    assert {"fact_not_in_view", "source_not_in_view"} <= set(decision(boundary).reasons)


def test_models_are_frozen_json_safe_and_do_not_share_mutable_context():
    models, _ = api()
    req = requirement(context={"options": [{"plan": "Pro"}]})
    req.context["options"][0]["plan"] = "changed"
    assert req.context == {"options": [{"plan": "Pro"}]}
    assert req.context_json == '{"options":[{"plan":"Pro"}]}'
    with pytest.raises(ValidationError):
        req.intent = "facts"
    with pytest.raises(ValidationError):
        models.AnswerRequirement(competitor="A", dimension="B", as_of=AS_OF, extra="x")
    with pytest.raises(ValidationError):
        models.AnswerRequirement(competitor="A", dimension="B", as_of=AS_OF, context_json="[]")
    with pytest.raises(ValidationError):
        models.AnswerRequirement(competitor="A", dimension="B")
    boundary = evaluate(view(fact()))
    assert json.loads(boundary.model_dump_json())["requirement"]["as_of"] == "2026-10-05"
    with pytest.raises(ValidationError):
        boundary.status = "partial"


def test_readonly_boundary_is_deterministic_across_evidence_order():
    first = fact("z-price")
    second = fact("a-method", field="model_type", value="one_time")
    evidence = view(first, second)
    before = evidence.model_dump_json()
    result = evaluate(evidence)
    other = evaluate(view(second, first))
    assert result.model_dump_json() == other.model_dump_json()
    assert result.view_source_ids == ("source-a",)
    assert result.view_fact_ids == ("a-method", "z-price")
    assert result.allowed_fact_ids == ("a-method", "z-price")
    assert tuple(item.fact_id for item in result.fact_decisions) == ("a-method", "z-price")
    assert evidence.model_dump_json() == before
