from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from test_run_evidence_snapshot import make_detail

# isort: split
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.admission import (
    admit_evidence_items,
    raw_sources_from_research_result,
)
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.extraction import extract_page
from packages.research.models import CapturedPage, EvidenceItem, ResearchBrief, SourceCandidate
from packages.research.pipeline import run_research_pipeline
from packages.skills.registry import SkillRegistry
from packages.tools import evidence_fetch
from packages.tools.fetch_page import FetchPageResult

SUBSCRIPTION = (
    "Acme Pro subscription price USD 20 per month; plan: Pro; seat_type: named_user; "
    "tax included; market: US."
)
DEVICE = (
    "Acme device price CNY 3999 one-time; model: Pocket 2; capacity: 256 GB; "
    "condition: new; tax included; market: CN."
)


def brief_for(*, device=False):
    return ResearchBrief(
        run_id="structured-price-local",
        topic="Acme pricing",
        competitor="Acme",
        dimension="pricing",
        product_name="Acme" if device else "",
        homepage_hint="https://acme.example",
        product_market="CN" if device else "US",
        include_trusted_sources=False,
        include_homepage_candidates=False,
        max_repair_rounds=0,
        target_source_count=1,
    )


def page_for(text, *, url="https://acme.example/pricing"):
    return CapturedPage(
        candidate_id="local",
        requested_url=url,
        final_url=url,
        status="ok",
        title="Acme pricing",
        text=text,
        content_hash="local",
        quality_score=0.95,
    )


async def local_chain(monkeypatch, text, *, device=False, final_url=None, source_date=None):
    brief = brief_for(device=device)
    candidate = SourceCandidate(
        title="Acme pricing",
        url="https://acme.example/pricing",
        origin="manual",
        competitor="Acme",
        dimension="pricing",
        confidence=0.95,
        date=source_date,
    )

    async def basic(url, **kwargs):
        return FetchPageResult(
            url=final_url or url,
            ok=True,
            title="Acme pricing",
            text=text,
            content_hash="local-body",
            status_code=200,
        )

    async def forbid(*args, **kwargs):
        raise AssertionError("No browser, search, or model call is permitted")

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr(evidence_fetch, "advanced_fetch_page", forbid)

    async def fetch(url):
        return await evidence_fetch.fetch_evidence_page(url, min_text_chars=40)

    result = await run_research_pipeline(
        brief,
        fetch=fetch,
        seed_candidates=[candidate],
    )
    sources = raw_sources_from_research_result(
        brief,
        result,
        batch_sources=[],
        target_source_count=1,
        requires_accepted_evidence=True,
        source_exists=lambda *_: False,
        confidence_for_source=lambda *_: 0.95,
        fallback_snippet=lambda page: page.snippet,
    )
    return result, sources


def writer_context(tmp_path, sources, *, market, report):
    detail = make_detail()
    detail.id = "structured-price-local"
    detail.topic = "Acme pricing"
    detail.plan.competitors = ["Acme"]
    detail.plan.dimensions = ["pricing"]
    from packages.research.evidence.answer_models import AnswerRequirement

    detail.plan.answer_requirements = [
        AnswerRequirement(
            competitor="Acme",
            dimension="pricing",
            intent="current_price",
            market=market,
            as_of=datetime.now(UTC).date(),
        )
    ]
    detail.raw_sources = sources
    detail.report_md = report
    journal = RunJournal(tmp_path / "journal.db")
    journal.save_run(detail)
    detail = journal.load_run(detail.id)
    assert detail.raw_sources[0].metadata == sources[0].metadata
    service = RunService(
        settings=Settings(demo_mode=True, analyst_react_enabled=False),
        skill_registry=SkillRegistry.from_default_path(),
        journal=journal,
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    selected, use = service._writer_segment_evidence(
        record,
        {
            "segment_name": "competitor_deep_dives",
            "segment_competitor": "Acme",
            "dimension": "pricing",
            "allowed_source_ids": [source.id for source in sources],
        },
    )
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=[use],
        payload=service._writer_evidence_artifact_payload(detail),
    )
    assert service._final_qa_producer_verified(record, snapshot)
    return service, record, snapshot, selected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device,text,market,currency,amount",
    [
        (False, SUBSCRIPTION, "US", "USD", 20),
        (True, DEVICE, "CN", "CNY", 3999),
    ],
)
async def test_actual_pricing_chain_can_answer_and_writer_qa_accepts(
    tmp_path,
    monkeypatch,
    device,
    text,
    market,
    currency,
    amount,
):
    result, sources = await local_chain(monkeypatch, text, device=device)
    assert sources
    row = sources[0].metadata["normalized_fields"][0]
    assert isinstance(row["price"], str)
    assert row["qualifiers"]["amount"] == amount
    assert row["qualifiers"]["currency"] == currency
    assert row["qualifiers"]["price_type"] == "official_current"
    assert row["source_quote"] == text
    assert sources[0].metadata["source_material_level"] == "full_source"
    assert sources[0].metadata["market"] == market
    service, record, snapshot, selected = writer_context(
        tmp_path,
        sources,
        market=market,
        report=f"Acme current price {currency} {amount}. [source:{sources[0].id}]",
    )
    assert selected["answer_boundaries"][0]["status"] == "answer"
    assert any(
        fact.field == "price" and fact.qualifiers["amount"] == amount for fact in snapshot.facts
    )
    _, issues, uses = await service._final_qa_evidence(record)
    for use in uses:
        service._validate_evidence_use(record, use)
    assert not [issue for issue in issues if issue.metadata.get("answer_guard_reason")]
    qa_uses = [use for use in record.detail.evidence_consumptions if use.agent == "qa"]
    assert qa_uses and all(use.status == "validated" and use.fact_ids for use in qa_uses)
    assert result.captured_pages[0].metadata.get("verified_at") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,device,final_url,source_date",
    [
        (SUBSCRIPTION.replace("seat_type: named_user; ", ""), False, None, None),
        (SUBSCRIPTION.replace("tax included; ", ""), False, None, None),
        (SUBSCRIPTION.replace("USD ", "$"), False, None, None),
        (SUBSCRIPTION.replace("market: US.", ""), False, None, None),
        (SUBSCRIPTION.replace("per month", "per month and per year"), False, None, None),
        (
            "Acme Pro subscription price USD 20 per month.\n"
            "seat_type: named_user; tax included; market: US.",
            False,
            None,
            None,
        ),
        ("Launch price: " + DEVICE, True, None, None),
        (DEVICE, True, "https://reseller.example/pricing", None),
        (DEVICE, True, None, "2024-01-01"),
        (
            SUBSCRIPTION.replace("seat_type: named_user", "seat_type: Full or Dev"),
            False,
            None,
            None,
        ),
        (SUBSCRIPTION.replace("seat_type: named_user", "Full or Dev seat"), False, None, None),
        (SUBSCRIPTION.replace("tax included", "tax included or excluded"), False, None, None),
        (DEVICE.replace("condition: new", "condition: new or used"), True, None, None),
    ],
)
async def test_actual_chain_withholds_incomplete_or_noncurrent_price(
    tmp_path,
    monkeypatch,
    text,
    device,
    final_url,
    source_date,
):
    _, sources = await local_chain(
        monkeypatch,
        text,
        device=device,
        final_url=final_url,
        source_date=source_date,
    )
    assert sources, "Legacy evidence remains available even when current price is incomplete"
    service, record, _, selected = writer_context(
        tmp_path,
        sources,
        market="CN" if device else "US",
        report=f"Acme current price {'CNY 3999' if device else 'USD 20'}. [source:{sources[0].id}]",
    )
    assert selected["answer_boundaries"][0]["status"] != "answer"
    _, issues, uses = await service._final_qa_evidence(record)
    for use in uses:
        service._validate_evidence_use(record, use)
    assert [issue for issue in issues if issue.metadata.get("answer_guard_reason")]


@pytest.mark.parametrize("device,text", [(False, SUBSCRIPTION), (True, DEVICE)])
@pytest.mark.parametrize("change", ["amount", "currency", "seat", "quote", "tier", "billing"])
@pytest.mark.parametrize("extractor_override", [None, "llm_pricing"])
def test_admission_reparses_rows_and_rejects_forged_fields(
    device,
    text,
    change,
    extractor_override,
):
    page = page_for(text)
    extraction = extract_page(brief_for(device=device), page)
    if extractor_override:
        extraction.extractor_name = extractor_override
    row = extraction.fields["price_rows"][0]
    if change == "quote":
        row["source_quote"] = "Acme fabricated price USD 20 per month; market: US."
    elif change == "tier":
        row["tier_name"] = "Enterprise"
    elif change == "billing":
        row["billing_cycle"] = "annual"
    else:
        row.setdefault("qualifiers", {})[{"seat": "seat_type"}.get(change, change)] = {
            "amount": True,
            "currency": "EUR",
            "seat": "admin",
        }[change]
    items = admit_evidence_items([extraction], captured_pages=[page])
    item = next(item for item in items if item.field == "price_rows")
    assert item.status == "rejected"
    assert "price_row" in item.rejection_reason


def test_normalization_preserves_each_rows_source_conditions_and_input():
    values = []
    for index, seat in enumerate(("named_user", "admin", "named_user")):
        values.append(
            EvidenceItem(
                competitor="Acme" if index < 2 else "Other",
                dimension="pricing",
                field="price_rows",
                value=[
                    {
                        "tier_name": "Pro",
                        "price": "USD 20",
                        "billing_cycle": "monthly",
                        "source_quote": f"Original row {index}",
                        "market": "US",
                        "qualifiers": {"amount": 20, "currency": "USD", "seat_type": seat},
                    }
                ],
                source_candidate_id=f"candidate-{index}",
                captured_page_id=f"page-{index}",
                source_url=f"https://source-{index}.example/pricing",
                quote=f"Original row {index}",
                confidence=0.5 + index / 10,
                status="accepted",
            )
        )
    before = deepcopy([item.model_dump() for item in values])
    rows = normalized_fields_from_evidence_items(values)
    assert len(rows) == 3
    assert [(row.competitor, row.source_url, row.confidence) for row in rows] == [
        (item.competitor, item.source_url, item.confidence) for item in values
    ]
    assert [row.qualifiers["seat_type"] for row in rows] == ["named_user", "admin", "named_user"]
    assert [row.market for row in rows] == ["US"] * 3
    assert [item.model_dump() for item in values] == before


@pytest.mark.parametrize("price", ["USD 0", "USD -20", "USD NaN", "USD 1,2", "$20", "¥20", "20元"])
def test_only_explicit_unambiguous_numeric_money_is_structured(price):
    text = SUBSCRIPTION.replace("USD 20", price)
    result = extract_page(brief_for(), page_for(text))
    structured = [
        row for row in result.fields["price_rows"] if "amount" in row.get("qualifiers", {})
    ]
    assert bool(structured) is (price == "USD 0")
    if structured:
        assert structured[0]["qualifiers"]["amount"] == 0


@pytest.mark.asyncio
async def test_stale_capture_is_not_reverified_as_current(tmp_path, monkeypatch):
    result, _ = await local_chain(monkeypatch, DEVICE, device=True)
    page = result.captured_pages[0]
    page.captured_at = datetime.now(UTC) - timedelta(days=10)
    page.metadata.update(
        {"verified_at": datetime.now(UTC).isoformat(), "source_material_level": "full_source"}
    )
    items = admit_evidence_items(
        result.extractions, captured_pages=[page], candidates=result.candidates, brief=result.brief
    )
    row = next(item for item in items if item.field == "price_rows")
    assert row.status == "accepted"
    assert row.value[0].get("qualifiers", {}).get("price_type") != "official_current"
    assert row.value[0]["qualifiers"]["verification_method"] == "deterministic_body_row_reparse_v1"


@pytest.mark.asyncio
async def test_future_capture_and_forged_page_event_are_not_current(monkeypatch):
    result, _ = await local_chain(monkeypatch, DEVICE, device=True)
    page = result.captured_pages[0]
    page.captured_at = datetime.now(UTC) + timedelta(days=1)
    page.metadata["verified_at"] = datetime.now(UTC).isoformat()
    items = admit_evidence_items(
        result.extractions, captured_pages=[page], candidates=result.candidates, brief=result.brief
    )
    row = next(item for item in items if item.field == "price_rows")
    assert row.value[0]["qualifiers"].get("price_type") != "official_current"


@pytest.mark.asyncio
async def test_dated_capture_cannot_be_hidden_by_invalid_candidate_date(monkeypatch):
    result, _ = await local_chain(monkeypatch, DEVICE, device=True)
    result.captured_pages[0].source_updated_at = "2024-01-01"
    result.candidates[0].last_updated = "not-a-date"
    items = admit_evidence_items(
        result.extractions,
        captured_pages=result.captured_pages,
        candidates=result.candidates,
        brief=result.brief,
    )
    row = next(item for item in items if item.field == "price_rows")
    assert row.value[0]["qualifiers"].get("price_type") != "official_current"


@pytest.mark.asyncio
async def test_arbitrary_page_metadata_cannot_upgrade_material_level(monkeypatch):
    from packages.research.capture import capture_candidate
    from packages.tools.evidence_fetch import EvidenceFetchResult

    candidate = SourceCandidate(
        title="Acme pricing", url="https://acme.example/pricing", origin="manual"
    )

    async def fetch(url):
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Acme pricing",
            text=DEVICE,
            content_hash="summary",
            fetch_method="search_summary",
            quality_score=0.9,
            source_material_level="full_source",
            capture_metadata={
                "source_material_level": "full_source",
                "verified_at": datetime.now(UTC).isoformat(),
            },
        )

    page = await capture_candidate(candidate, fetch)
    assert page.source_material_level == "unknown"
    extraction = extract_page(brief_for(device=True), page)
    item = next(
        item
        for item in admit_evidence_items(
            [extraction],
            captured_pages=[page],
            candidates=[candidate],
            brief=brief_for(device=True),
        )
        if item.field == "price_rows"
    )
    assert item.value[0]["qualifiers"].get("price_type") != "official_current"


@pytest.mark.parametrize("seat", ["Full", "Dev", "Collab"])
def test_explicit_natural_seat_types_remain_distinct(seat):
    text = SUBSCRIPTION.replace("seat_type: named_user", f"{seat} seat per seat")
    extraction = extract_page(brief_for(), page_for(text))
    assert extraction.fields["price_rows"][0]["qualifiers"]["seat_type"] == seat


@pytest.mark.asyncio
@pytest.mark.parametrize("natural_seat,complete", [("Dev", False), ("Full", True)])
async def test_labelled_and_natural_seat_values_must_agree(
    tmp_path, monkeypatch, natural_seat, complete
):
    text = SUBSCRIPTION.replace("seat_type: named_user", f"seat_type: Full; {natural_seat} seat")
    _, sources = await local_chain(monkeypatch, text)
    assert sources
    qualifiers = sources[0].metadata["normalized_fields"][0]["qualifiers"]
    assert qualifiers.get("seat_type") == ("Full" if complete else None)
    service, record, _, selected = writer_context(
        tmp_path,
        sources,
        market="US",
        report=f"Acme current price USD 20. [source:{sources[0].id}]",
    )
    assert (selected["answer_boundaries"][0]["status"] == "answer") is complete
    _, issues, uses = await service._final_qa_evidence(record)
    for use in uses:
        service._validate_evidence_use(record, use)
    assert bool([issue for issue in issues if issue.metadata.get("answer_guard_reason")]) is (
        not complete
    )
    qa_uses = [use for use in record.detail.evidence_consumptions if use.agent == "qa"]
    assert qa_uses and all(use.status == "validated" and use.fact_ids for use in qa_uses)


@pytest.mark.parametrize("tax", ["不含税", "未含税"])
def test_chinese_excluded_tax_is_not_mistaken_for_included(tax):
    extraction = extract_page(brief_for(device=True), page_for(DEVICE.replace("tax included", tax)))
    assert extraction.fields["price_rows"][0]["qualifiers"]["tax_scope"] == "excluded"


@pytest.mark.parametrize("device", [False, True])
def test_display_and_amount_preserve_comma_grouped_price(device):
    text = SUBSCRIPTION.replace("USD 20", "USD 1,000")
    extraction = extract_page(brief_for(device=device), page_for(text))
    row = extraction.fields["price_rows"][0]
    assert "1,000" in row["price"]
    assert row["qualifiers"]["amount"] == 1000
    row["price"] = "USD 1"
    admitted = admit_evidence_items([extraction], captured_pages=[page_for(text)])
    assert next(item for item in admitted if item.field == "price_rows").status == "rejected"


@pytest.mark.parametrize("device", [False, True])
def test_monthly_equivalent_retains_amount_period_and_annual_billing(device):
    text = SUBSCRIPTION.replace("per month", "per month billed annually")
    extraction = extract_page(brief_for(device=device), page_for(text))
    row = extraction.fields["price_rows"][0]
    assert "per month" in row["price"]
    assert row["qualifiers"]["amount_period"] == "monthly"
    assert row["qualifiers"]["billing_interval"] == "annual"
    assert row["qualifiers"]["amount"] == 20


@pytest.mark.asyncio
async def test_source_with_two_explicit_markets_does_not_pick_request_market(monkeypatch):
    _, sources = await local_chain(
        monkeypatch, SUBSCRIPTION + "\n" + SUBSCRIPTION.replace("market: US", "market: CA")
    )
    assert sources
    rows = sources[0].metadata["normalized_fields"]
    assert {row["market"] for row in rows} == {"US", "CA"}
    assert sources[0].metadata["market"] is None


@pytest.mark.parametrize(
    "replacement",
    ["Full seat and Dev seat", "billed monthly or annually", "tax included and tax excluded"],
)
def test_ambiguous_conditions_cannot_supply_complete_row(replacement):
    field, original = (
        ("seat_type", "seat_type: named_user")
        if "seat" in replacement
        else ("billing_interval", "per month")
        if "billed" in replacement
        else ("tax_scope", "tax included")
    )
    text = SUBSCRIPTION.replace(original, replacement)
    row = extract_page(brief_for(), page_for(text)).fields["price_rows"][0]
    assert field not in row.get("qualifiers", {})
    if field == "billing_interval":
        assert row["billing_cycle"] in {"", "unknown"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://acme.example/blog/pricing",
        "https://acme.example/post?pricing=1",
        "https://acme.example/news/pricing",
        "https://acme.example/press/pricing",
    ],
)
async def test_official_host_and_pricing_title_do_not_upgrade_article_urls(monkeypatch, url):
    _, sources = await local_chain(monkeypatch, DEVICE, device=True, final_url=url)
    assert sources
    assert (
        sources[0].metadata["normalized_fields"][0]["qualifiers"].get("price_type")
        != "official_current"
    )


def test_normalization_keeps_legacy_source_alongside_structured_rows():
    structured = EvidenceItem(
        competitor="Acme",
        dimension="pricing",
        field="price_rows",
        value=[
            {
                "price": "USD 20",
                "source_quote": SUBSCRIPTION,
                "qualifiers": {"amount": 20, "currency": "USD"},
            }
        ],
        source_candidate_id="one",
        captured_page_id="one",
        status="accepted",
        source_url="https://acme.example/one",
        confidence=0.8,
    )
    legacy = structured.model_copy(
        update={
            "id": "legacy",
            "field": "price_points",
            "value": ["$30"],
            "captured_page_id": "two",
            "source_url": "https://acme.example/two",
        }
    )
    rows = normalized_fields_from_evidence_items([structured, legacy])
    assert [(row.price, row.source_url) for row in rows] == [
        ("USD 20", "https://acme.example/one"),
        ("$30", "https://acme.example/two"),
    ]


def test_explicitly_excluded_seat_is_not_a_positive_price_condition():
    text = SUBSCRIPTION.replace("seat_type: named_user", "does not include Full seat")
    row = extract_page(brief_for(), page_for(text)).fields["price_rows"][0]
    assert "seat_type" not in row["qualifiers"]


def test_negated_seat_with_article_does_not_supply_seat_type():
    text = SUBSCRIPTION.replace("seat_type: named_user", "not a Full seat")
    row = extract_page(brief_for(), page_for(text)).fields["price_rows"][0]
    assert "seat_type" not in row["qualifiers"]


def test_not_including_tax_does_not_supply_included_tax_scope():
    text = SUBSCRIPTION.replace("tax included", "not including tax")
    row = extract_page(brief_for(), page_for(text)).fields["price_rows"][0]
    assert row["qualifiers"].get("tax_scope") != "included"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original,replacement,missing",
    [
        ("seat_type: named_user", "Full seat is not included", "seat_type"),
        ("seat_type: named_user", "excluding Full seat", "seat_type"),
        ("per month", "not billed monthly", "billing_interval"),
    ],
)
async def test_negated_conditions_stay_missing_through_writer_boundary(
    tmp_path,
    monkeypatch,
    original,
    replacement,
    missing,
):
    text = SUBSCRIPTION.replace(original, replacement)
    _, sources = await local_chain(monkeypatch, text)
    row = sources[0].metadata["normalized_fields"][0]
    assert missing not in row["qualifiers"]
    if missing == "billing_interval":
        assert row["billing_cycle"] == ""
    _, _, _, selected = writer_context(
        tmp_path,
        sources,
        market="US",
        report=f"Acme current price USD 20. [source:{sources[0].id}]",
    )
    assert selected["answer_boundaries"][0]["status"] != "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("date", ["2024/01/01", "January 1, 2024", "2024", "unparseable"])
async def test_any_nonempty_source_date_blocks_current_price(tmp_path, monkeypatch, date):
    _, sources = await local_chain(monkeypatch, SUBSCRIPTION, source_date=date)
    row = sources[0].metadata["normalized_fields"][0]
    assert row["qualifiers"].get("price_type") != "official_current"
    _, _, _, selected = writer_context(
        tmp_path,
        sources,
        market="US",
        report=f"Acme current price USD 20. [source:{sources[0].id}]",
    )
    assert selected["answer_boundaries"][0]["status"] != "answer"


@pytest.mark.asyncio
async def test_renamed_extractor_cannot_stamp_forged_current_amount(monkeypatch):
    result, _ = await local_chain(monkeypatch, SUBSCRIPTION)
    extraction = result.extractions[0]
    extraction.extractor_name = "llm_pricing"
    extraction.fields["price_rows"][0]["qualifiers"]["amount"] = 999
    item = next(
        item
        for item in admit_evidence_items(
            [extraction],
            captured_pages=result.captured_pages,
            candidates=result.candidates,
            brief=result.brief,
        )
        if item.field == "price_rows"
    )
    assert item.status == "rejected"
    assert "verification_method" not in item.value[0]["qualifiers"]


def test_display_numeric_substring_cannot_disagree_with_structured_amount():
    page = page_for(SUBSCRIPTION)
    extraction = extract_page(brief_for(), page)
    extraction.fields["price_rows"][0]["price"] = "USD 2"
    item = next(
        item
        for item in admit_evidence_items(
            [extraction],
            captured_pages=[page],
        )
        if item.field == "price_rows"
    )
    assert item.status == "rejected"


def test_legacy_symbol_price_cannot_reintroduce_negated_billing_interval():
    text = SUBSCRIPTION.replace("USD 20 per month", "$20 not billed monthly")
    row = extract_page(brief_for(), page_for(text)).fields["price_rows"][0]
    assert row["billing_cycle"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original,replacement",
    [
        ("USD 20", "USD 20-30"),
        ("USD 20", "USD 20/30"),
        ("USD 20", "USD 20–30"),
        ("USD 20", "USD 20—30"),
        ("USD 20", "USD 20−30"),
        ("seat_type: named_user", "seat_type: Full and Dev"),
        ("seat_type: named_user", "seat_type: Full/Dev"),
        ("seat_type: named_user", "Full and Dev seat"),
        ("tax included", "tax included and excluded"),
        ("tax included", "tax_scope: included/excluded"),
    ],
)
async def test_numeric_ranges_and_compound_conditions_remain_legacy(
    tmp_path,
    monkeypatch,
    original,
    replacement,
):
    _, sources = await local_chain(monkeypatch, SUBSCRIPTION.replace(original, replacement))
    row = sources[0].metadata["normalized_fields"][0]
    assert row["qualifiers"] == {}
    assert row["tier_name"] == row["billing_cycle"] == ""
    service, record, _, selected = writer_context(
        tmp_path,
        sources,
        market="US",
        report=f"Acme current price USD 20. [source:{sources[0].id}]",
    )
    assert selected["answer_boundaries"][0]["status"] != "answer"
    _, issues, uses = await service._final_qa_evidence(record)
    for use in uses:
        service._validate_evidence_use(record, use)
    assert [issue for issue in issues if issue.metadata.get("answer_guard_reason")]


def test_slash_billing_unit_is_not_a_numeric_range():
    text = SUBSCRIPTION.replace("USD 20 per month", "USD 20/month")
    row = extract_page(brief_for(), page_for(text)).fields["price_rows"][0]
    assert row["qualifiers"]["amount"] == 20
    assert row["qualifiers"]["billing_interval"] == "monthly"


@pytest.mark.asyncio
@pytest.mark.parametrize("operator", ["到", "至"])
async def test_chinese_money_ranges_remain_legacy(tmp_path, monkeypatch, operator):
    text = DEVICE.replace("CNY 3999", f"CNY 3999 {operator} 4999")
    _, sources = await local_chain(monkeypatch, text, device=True)
    row = sources[0].metadata["normalized_fields"][0]
    assert row["qualifiers"] == {}
    assert row["billing_cycle"] == ""
    _, _, _, selected = writer_context(
        tmp_path,
        sources,
        market="CN",
        report=f"Acme current price CNY 3999. [source:{sources[0].id}]",
    )
    assert selected["answer_boundaries"][0]["status"] != "answer"


@pytest.mark.parametrize("cycle", [["monthly"], {"cycle": "monthly"}])
def test_malformed_legacy_cycle_is_rejected_without_exception(cycle):
    page = page_for(SUBSCRIPTION.replace("USD 20", "$20"))
    extraction = extract_page(brief_for(), page)
    extraction.extractor_name = "llm_pricing"
    extraction.fields["price_rows"][0]["billing_cycle"] = cycle
    item = next(
        item
        for item in admit_evidence_items(
            [extraction],
            captured_pages=[page],
        )
        if item.field == "price_rows"
    )
    assert item.status == "rejected"


def test_generic_price_row_limit_also_applies_to_repeated_amounts():
    text = "\n".join(DEVICE.replace("Pocket 2", f"Pocket {index}") for index in range(30))
    rows = extract_page(brief_for(device=True), page_for(text)).fields["price_rows"]
    assert len(rows) == 8


@pytest.mark.parametrize(
    "method,ok,text,expected",
    [
        ("browser", True, DEVICE, "full_source"),
        ("search_summary", True, DEVICE, "unknown"),
        ("browser", False, DEVICE, "unknown"),
        ("browser", True, "", "unknown"),
    ],
)
def test_advanced_fetch_producer_only_marks_successful_body_as_full(method, ok, text, expected):
    from packages.tools.advanced_fetch import AdvancedFetchResult

    result = evidence_fetch._from_advanced_fetch(
        AdvancedFetchResult(
            url="https://acme.example/pricing",
            final_url="https://acme.example/pricing",
            ok=ok,
            title="Acme pricing",
            text=text,
            markdown="",
            fetch_method=method,
        )
    )
    assert result.source_material_level == expected
