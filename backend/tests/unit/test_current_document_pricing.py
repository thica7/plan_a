from packages.business_intel.entity_resolver import is_trusted_url_for_competitor
from packages.research.extraction.pricing_cards import rendered_price_cards
from packages.research.models import CapturedPage


def page(text, title, url):
    return CapturedPage(candidate_id='official', requested_url=url, final_url=url,
                        title=title, text=text, content_hash='public-capture', status='ok')


def test_coda_migration_is_scoped_to_docs_not_other_superhuman_products():
    assert is_trusted_url_for_competitor('Coda', 'https://superhuman.com/plans/docs?source=coda.io')
    assert is_trusted_url_for_competitor('Coda', 'https://help.superhuman.com/hc/en-us/articles/46210173956109-Share-your-doc')
    assert not is_trusted_url_for_competitor('Coda', 'https://superhuman.com/plans/mail')
    assert not is_trusted_url_for_competitor('Coda', 'https://help.superhuman.com/hc/en-us/articles/46005744375437')
    assert not is_trusted_url_for_competitor('Coda', 'https://superhuman.com.evil.test/plans/docs')


def test_docs_cards_bind_explicit_currency_maker_and_both_billing_intervals():
    text = 'Pro\n$12 USD / month\nper Doc Maker, billed annually\n$15 when billed monthly\nBusiness\n$33 USD / month\nper Doc Maker, billed annually\n$40 when billed monthly\n'
    rows = rendered_price_cards('Coda', page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs'))
    assert [(r['tier_name'], r['qualifiers']['amount'], r['billing_cycle']) for r in rows] == [('Pro', 12, 'annual'), ('Pro', 15, 'monthly'), ('Business', 33, 'annual'), ('Business', 40, 'monthly')]
    assert all(r['qualifiers']['currency'] == 'USD' and r['qualifiers']['amount_basis'] == 'doc_maker' and r['qualifiers']['amount_period'] == 'monthly' for r in rows)
    assert all(r['source_quote'] in text for r in rows)
    assert all(r['qualifiers']['tax_scope'] == 'unknown' for r in rows)


def test_same_brand_mail_page_cannot_be_attributed_to_coda():
    p = page('Pro\n$12 USD / month', 'Superhuman Mail | Pricing & Plans', 'https://superhuman.com/plans/mail')
    assert rendered_price_cards('Coda', p) == []


def test_confluence_plan_card_keeps_unit_without_guessing_currency_or_toggle():
    text = 'Monthly\nAnnually\nStandard\n$6.70\nper user / month\nPremium\n$13.20\nper user / month'
    rows = rendered_price_cards('Confluence', page(text, 'Confluence Pricing', 'https://www.atlassian.com/software/confluence/pricing'))
    assert [(r['tier_name'], r['qualifiers']['amount']) for r in rows] == [('Standard', 6.7), ('Premium', 13.2)]
    assert all(r['qualifiers']['amount_basis'] == 'user' and r['qualifiers']['billing_interval'] == 'unknown' and 'currency' not in r['qualifiers'] for r in rows)


def test_wrapped_doc_maker_labels_and_plan_subtitles_are_preserved():
    text = 'Pro\n\n$12 USD / month\n\nper \nDoc Maker\n, billed annually\n\n$15 when billed monthly\n'
    rows = rendered_price_cards('Coda', page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs'))
    assert [r['billing_cycle'] for r in rows] == ['annual', 'monthly']
    assert all(r['qualifiers']['amount_basis'] == 'doc_maker' for r in rows)


def test_confluence_public_layout_binds_amount_after_short_subtitle():
    text = 'Free\nFree forever for 10 users\n$0\nStart free trial\nStandard\nEverything you need to get started\n$5.42\nper user / month\nPremium\nConnect work across teams\n$10.44\nper user / month'
    rows = rendered_price_cards('Confluence', page(text, 'Confluence Pricing', 'https://www.atlassian.com/software/confluence/pricing'))
    assert [(r['tier_name'], r['qualifiers']['amount']) for r in rows] == [('Free', 0), ('Standard', 5.42), ('Premium', 10.44)]
    assert all(r['source_quote'] in text for r in rows)


def test_comparison_table_and_sticky_footer_do_not_add_unqualified_duplicate_prices():
    text = 'Pro\n$12 USD / month\nper Doc Maker, billed annually\n$15 when billed monthly\nSee all features and compare plans\nGrammarly\n$15/mo per Maker on monthly\nPro\n$12 USD\n/month\n$15 when billed monthly'
    rows = rendered_price_cards('Coda', page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs'))
    assert len(rows) == 2


def test_migrated_pricing_precedes_old_product_docs_for_bounded_capture():
    from packages.research.discovery import trusted_registry_candidates
    from packages.research.models import ResearchBrief

    candidates = trusted_registry_candidates(ResearchBrief(
        run_id='price-priority', topic='文档协作定价', competitor='Coda',
        dimension='pricing', homepage_hint='https://coda.io',
    ))
    assert candidates[0].url == 'https://superhuman.com/plans/docs'


def test_curated_document_order_precedes_homepage_changelog():
    from packages.research.discovery import trusted_registry_candidates
    from packages.research.models import ResearchBrief
    candidates = trusted_registry_candidates(ResearchBrief(run_id='docs-first', topic='文档协作', competitor='Coda',
        dimension='feature', product_category='文档', homepage_hint='https://coda.io'))
    assert [c.url for c in candidates[:2]] == [
        'https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors',
        'https://help.superhuman.com/hc/en-us/articles/47804378033677-Share-folders-and-the-docs-within']


def test_public_document_browser_retry_is_explicit_and_scoped_to_curated_pages():
    from packages.business_intel.entity_resolver import trusted_source_candidates
    sources = trusted_source_candidates('Coda', 'feature')
    public_urls = {s.url for s in sources if s.source_kind == 'public_document'}
    assert public_urls == {
        'https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors',
        'https://help.superhuman.com/hc/en-us/articles/47804378033677-Share-folders-and-the-docs-within',
        'https://help.superhuman.com/hc/en-us/articles/46210367411469-Comment-on-docs',
        'https://help.superhuman.com/hc/en-us/articles/46210173956109-Share-your-doc',
        'https://help.superhuman.com/hc/en-us/articles/46210170717965-Control-sharing-of-docs-and-Packs',
    }


def test_verified_docs_source_retains_coda_identity_after_brand_migration():
    from packages.research.evidence.admission import competitor_identity_problem
    from packages.schema.models import RawSource
    source = RawSource(id='migrated-docs', competitor='Coda', dimension='pricing',
        source_type='webpage_verified', title='Superhuman Docs | Pricing & Plans',
        url='https://superhuman.com/plans/docs', snippet='Pro $12 USD per Doc Maker, billed annually.',
        content_hash='verified-migrated-page', confidence=.9)
    assert competitor_identity_problem(source) is None
    assert competitor_identity_problem(source.model_copy(update={
        'url': 'https://superhuman.com/plans/mail', 'title': 'Superhuman Mail | Pricing & Plans',
    })) is not None


def test_docs_page_mail_section_cannot_create_admitted_coda_price():
    from packages.research.extraction import extract_page
    from packages.research.evidence.admission import admit_evidence_items
    from packages.research.models import ResearchBrief

    text = ('Superhuman Docs\nPro\n$12 USD / month\nper Doc Maker, billed annually\n'
            'Superhuman Mail\nPro\n$30 USD / month\nper user / month')
    captured = page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs')
    captured.quality_score = 1
    captured.source_material_level = 'full_source'
    brief = ResearchBrief(run_id='mixed-price', topic='文档定价', competitor='Coda', dimension='pricing', product_name='Coda')
    extraction = extract_page(brief, captured)
    items = admit_evidence_items([extraction], captured_pages=[captured], brief=brief)
    prices = next(item for item in items if item.field == 'price_rows')
    assert prices.status == 'accepted'
    assert [r['qualifiers']['amount'] for r in prices.value] == [12]


def test_shared_brand_navigation_keeps_following_docs_section():
    text = ('Superhuman Mail\nSuperhuman Go\nSuperhuman Docs\nPro\n'
            '$12 USD / month\nper Doc Maker, billed annually\n$15 when billed monthly')
    rows = rendered_price_cards('Coda', page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs'))
    assert [r['qualifiers']['amount'] for r in rows] == [12, 15]


def test_mail_currency_note_does_not_supply_docs_currency_or_quote():
    from packages.research.extraction import extract_page
    from packages.research.evidence.admission import admit_evidence_items
    from packages.research.models import ResearchBrief
    text = ('Superhuman Mail\nPrices in USD\nPro\n$30 / month\nper user / month\n'
            'Superhuman Docs\nPro\n$12 / month\nper Doc Maker, billed annually')
    captured = page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs')
    captured.quality_score = 1
    captured.source_material_level = 'full_source'
    brief = ResearchBrief(run_id='mixed-currency', topic='文档定价', competitor='Coda', dimension='pricing', product_name='Coda')
    items = admit_evidence_items([extract_page(brief, captured)], captured_pages=[captured], brief=brief)
    rows = next(item.value for item in items if item.field == 'price_rows' and item.status == 'accepted')
    assert len(rows) == 1
    assert 'currency' not in rows[0]['qualifiers']
    assert 'Mail' not in rows[0]['source_quote'] and '$30' not in rows[0]['source_quote']


def test_docs_currency_note_is_preserved_within_its_own_section():
    text = 'Superhuman Mail\nPrices in EUR\nSuperhuman Docs\nPrices in USD\nPro\n$12 / month\nper Doc Maker, billed annually'
    rows = rendered_price_cards('Coda', page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs'))
    assert len(rows) == 1 and rows[0]['qualifiers']['currency'] == 'USD'
    assert 'EUR' not in rows[0]['source_quote']


def test_short_free_card_does_not_reject_other_fully_bound_docs_prices():
    from packages.research.extraction import extract_page
    from packages.research.evidence.admission import admit_evidence_items
    from packages.research.models import ResearchBrief
    text = ('Free\n\n$0 USD\n\nGet Superhuman Free\nFree includes:\nCollaborative docs\n'
            'Pro\n$12 USD / month\nper Doc Maker, billed annually\n$15 when billed monthly')
    captured = page(text, 'Superhuman Docs | Pricing & Plans', 'https://superhuman.com/plans/docs')
    captured.quality_score = 1
    captured.source_material_level = 'full_source'
    brief = ResearchBrief(run_id='short-free', topic='文档定价', competitor='Coda', dimension='pricing', product_name='Coda')
    items = admit_evidence_items([extract_page(brief, captured)], captured_pages=[captured], brief=brief)
    item = next(item for item in items if item.field == 'price_rows')
    assert item.status == 'accepted', item.rejection_reason
    assert [r['qualifiers']['amount'] for r in item.value] == [0, 12, 15]
