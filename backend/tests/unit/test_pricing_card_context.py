from copy import deepcopy

import pytest

from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.evidence.admission import admit_evidence_items
from packages.research.extraction import extract_page
from packages.research.models import CapturedPage, ResearchBrief


def extract(text, title="Figma Pricing", competitor="Figma"):
    brief = ResearchBrief(
        run_id="cards",
        topic="设计交付",
        competitor=competitor,
        dimension="pricing",
        product_name=competitor,
        product_category="设计软件",
    )
    page = CapturedPage(
        candidate_id="pricing",
        requested_url="https://www.figma.com/pricing/",
        final_url="https://www.figma.com/pricing/",
        title=title,
        text=text,
        markdown=text,
        content_hash="cards",
        status="ok",
        quality_score=1,
    )
    return extract_page(brief, page)


def test_rendered_cards_bind_plan_and_seat_without_guessing_active_billing_toggle():
    text = "Prices in USD\nProfessional\nMonthly\nAnnual\nFull seat\n$16/mo\nDev seat\n$12/mo"
    rows = extract(text).fields["price_rows"]
    assert len(rows) == 2
    assert [row["tier_name"] for row in rows] == ["Professional", "Professional"]
    assert [row["qualifiers"]["seat_type"] for row in rows] == ["Full", "Dev"]
    assert all(row["qualifiers"]["currency"] == "USD" for row in rows)
    assert all(row["qualifiers"]["billing_interval"] == "unknown" for row in rows)
    assert all(row["qualifiers"]["tax_scope"] == "unknown" for row in rows)
    assert all(row["source_quote"] in text for row in rows)


def test_explicit_annual_billing_is_preserved_as_different_from_amount_period():
    rows = extract("Prices in USD\nOrganization\nBilled annually\nFull seat\n$55/mo").fields[
        "price_rows"
    ]
    assert rows[0]["qualifiers"]["billing_interval"] == "annual"
    assert rows[0]["qualifiers"]["amount_period"] == "monthly"


def test_price_cards_require_an_unambiguous_product_page_identity():
    result = extract("Professional\nFull seat\n$16/mo", title="Figma vs Another Product Pricing")
    assert not result.fields["price_rows"]


def test_invoice_and_shipping_amounts_do_not_become_card_prices():
    result = extract(
        "Prices in USD\nProfessional\nFull seat\nShipping costs $5.\n"
        "Minimum invoice threshold is $2."
    )
    assert not result.fields["price_rows"]


def test_explicit_amount_currency_is_not_overridden_by_page_currency():
    rows = extract("Prices in USD\nProfessional\nFull seat\nEUR 16/mo").fields["price_rows"]
    assert rows[0]["qualifiers"]["currency"] == "EUR"


def test_symbol_without_explicit_currency_does_not_guess_usd():
    rows = extract("Professional\nFull seat\n$16/mo").fields["price_rows"]
    assert "currency" not in rows[0]["qualifiers"]


def test_local_currency_symbol_is_not_overridden_by_global_note():
    rows = extract("Prices in USD\nProfessional\nFull seat\n€16/mo").fields["price_rows"]
    assert rows[0]["qualifiers"]["currency"] == "EUR"


def test_rendered_notion_layout_preserves_footnotes_and_display_period():
    text = (
        "Price in\nUSD\nFree\n$0\nper member / month\nPlus*\n$10\nper member / month\n"
        "Business\nRecommended\n$20\nper member / month"
    )
    rows = extract(text, title="Notion Pricing", competitor="Notion").fields["price_rows"]
    assert [row["tier_name"] for row in rows] == ["Free", "Plus", "Business"]
    assert [row["qualifiers"]["amount"] for row in rows] == [0, 10, 20]
    assert all(row["qualifiers"]["currency"] == "USD" for row in rows)
    assert all(row["qualifiers"]["amount_period"] == "monthly" for row in rows)
    assert all(row["qualifiers"]["amount_basis"] == "member" for row in rows)
    assert all(row["qualifiers"]["billing_interval"] == "unknown" for row in rows)
    assert all(row["source_quote"] in text for row in rows)


def card_chain():
    brief = ResearchBrief(
        run_id="cards",
        topic="设计交付",
        competitor="Figma",
        dimension="pricing",
        product_name="Figma",
    )
    text = "Prices in USD\nProfessional\nBilled annually\nFull seat\n$16/mo\nDev seat\n$12/mo"
    page = CapturedPage(
        candidate_id="pricing",
        requested_url="https://www.figma.com/pricing/",
        final_url="https://www.figma.com/pricing/",
        title="Figma Pricing",
        text=text,
        content_hash="cards",
        status="ok",
        quality_score=1,
        source_material_level="full_source",
    )
    return brief, page, extract_page(brief, page)


def test_rendered_cards_pass_capture_reparse_admission_and_product_coverage():
    brief, page, extraction = card_chain()
    items = admit_evidence_items([extraction], captured_pages=[page], brief=brief)
    price_rows = next(item for item in items if item.field == "price_rows")
    assert price_rows.status == "accepted", price_rows.rejection_reason
    assert price_rows.value[0]["qualifiers"]["tax_scope"] == "unknown"
    assert evaluate_coverage_contract(
        brief, candidates=[], pages=[page], evidence_items=items, ledger=[]
    ).passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("seat_type", "Dev"),
        ("currency", "EUR"),
        ("billing_interval", "monthly"),
        ("price_type", "official_current"),
        ("verified_at", "2099-01-01"),
    ],
)
def test_rendered_card_conditions_cannot_be_forged(field, value):
    brief, page, extraction = card_chain()
    altered = deepcopy(extraction)
    altered.fields["price_rows"][0]["qualifiers"][field] = value
    items = admit_evidence_items([altered], captured_pages=[page], brief=brief)
    assert next(item for item in items if item.field == "price_rows").status == "rejected"
