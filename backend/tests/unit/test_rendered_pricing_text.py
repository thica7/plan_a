import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "third_party/webfetch_v2"))

import pytest
from webfetch_v2.extract import score_quality  # noqa: E402
from webfetch_v2.fetcher import _select_browser_text  # noqa: E402


def test_pricing_render_keeps_plan_and_seat_context_even_when_extractor_is_long():
    visible = (
        "Professional\nMonthly\nAnnual\nFull seat\n$16/mo\nDev seat\n$12/mo\n" + "Features. " * 20
    )
    extracted = "The product provides collaboration features. " * 20
    assert (
        _select_browser_text("https://example.com/pricing", "Plans", visible, extracted) == visible
    )


def test_product_article_still_uses_existing_clean_text_selection():
    visible = "Navigation " + "Product supports collaboration. " * 10
    extracted = "Product supports collaboration. " * 10
    assert (
        _select_browser_text("https://example.com/docs", "Guide", visible, extracted) == extracted
    )


def test_advanced_article_extractor_preserves_paragraphs_and_headings():
    from webfetch_v2.extract import extract_best_content
    body = ('<article><h1>Product collaboration</h1><h2>Comments</h2>'
            '<p>People can leave comments in shared documents and reply to feedback.</p>'
            '<h2>Access rules</h2><p>Requires edit or comment access.</p></article>')
    result = extract_best_content(body, 'Product collaboration', status_code=200)
    assert '\n' in result.text
    assert (2, 'Comments') in result.extraction.headings
    assert (2, 'Access rules') in result.extraction.headings


def test_advanced_clean_extraction_restores_roles_at_original_unique_blocks(monkeypatch):
    from webfetch_v2 import extract
    team = 'On the team level, you can assign owner, admin, member, or guest roles.'
    workspace = 'On the workspace level, you can assign full access, comment-only, or read-only roles.'
    body = ('<article><h1>Roles and permissions</h1><h2>Team roles</h2>'
            f'<p>{team}</p><h2>Workspace roles</h2><p>{workspace}</p>'
            '<table><tr><th>Permission</th><th>Full access</th><th>Read-only</th></tr>'
            '<tr><td>View content</td><td>✅</td><td>✅</td></tr></table></article>')
    captured = f'{team}\n{workspace}\n| Permission | Full access | Read-only |\n| View content | ✅ | ✅ |'
    monkeypatch.setattr(extract, '_raw_extraction_candidates',
                        lambda _body: [('trafilatura', captured, None)])
    result = extract.extract_best_content(body, 'Roles and permissions', status_code=200)
    assert result.text == f'Team roles\n{team}\nWorkspace roles\n{captured.split(chr(10), 1)[1]}'
    assert '| View content | ✅ | ✅ |' in result.text


@pytest.mark.parametrize('captured', [
    'The original content block appears in two different places.\n'
    'The original content block appears in two different places.',
    'A different content block does not locate the missing section.',
])
def test_advanced_extraction_does_not_guess_missing_heading_positions(monkeypatch, captured):
    from webfetch_v2 import extract
    body = ('<article><h2>Workspace roles</h2>'
            '<p>The original content block appears in two different places.</p></article>')
    monkeypatch.setattr(extract, '_raw_extraction_candidates',
                        lambda _body: [('trafilatura', captured, None)])
    assert extract.extract_best_content(body, 'Guide').text == captured


def test_advanced_extraction_does_not_restore_navigation_headings(monkeypatch):
    from webfetch_v2 import extract
    captured = 'Members can create and edit documents within the workspace.'
    body = f'<nav><h2>Navigation</h2><p>{captured}</p></nav><article><p>{captured}</p></article>'
    monkeypatch.setattr(extract, '_raw_extraction_candidates',
                        lambda _body: [('trafilatura', captured, None)])
    assert extract.extract_best_content(body, 'Guide').text == captured


def test_equal_quality_prefers_clean_table_over_longer_navigation_text(monkeypatch):
    from webfetch_v2 import extract
    clean = ('Members can view and comment on documents within their workspace.\n' * 25
             + '| Permission | Full access | Read-only |\n| View content | ✅ | ✅ |')
    noisy = 'Navigation\nLog in\nPricing\nSupport\n' + clean.replace(' | ', '\n')
    noisy += '\nMore navigation links and footers.' * 20
    monkeypatch.setattr(extract, '_raw_extraction_candidates', lambda _body: [
        ('trafilatura', clean, None), ('body_text', noisy, None)])
    result = extract.extract_best_content('<article></article>', 'Product permissions', status_code=200)
    assert result.extraction.method == 'trafilatura'
    assert '| View content | ✅ | ✅ |' in result.text


def test_clean_extractor_priority_does_not_override_higher_quality_body(monkeypatch):
    from webfetch_v2 import extract
    clean = 'Product page.'
    body = 'Members can view and edit shared documents with their workspace.\n' * 25
    monkeypatch.setattr(extract, '_raw_extraction_candidates', lambda _body: [
        ('trafilatura', clean, None), ('body_text', body, None)])
    assert extract.extract_best_content('<article></article>', 'Guide', status_code=200).extraction.method == 'body_text'


def test_missing_optional_html_parser_does_not_guess_section_scope(monkeypatch):
    from webfetch_v2 import extract
    captured = 'Members can create and edit documents within the workspace.'
    monkeypatch.setattr(extract, 'BeautifulSoup', None)
    monkeypatch.setattr(extract, '_raw_extraction_candidates',
                        lambda _body: [('trafilatura', captured, None)])
    assert extract.extract_best_content(f'<h2>Roles</h2><p>{captured}</p>', 'Guide').text == captured


def test_public_pricing_navigation_login_link_is_not_an_auth_wall():
    quality = score_quality(
        "Figma Pricing",
        "Products\nLog in\nProfessional\nFull seat\n$16/mo\n" + "Public features. " * 100,
        status_code=200,
    )
    assert not quality.looks_like_login


@pytest.mark.parametrize(
    "title,text",
    [
        ("Sign in - Product", "Choose an account and continue. " * 50),
        ("Workspace", "Please sign in to continue. " * 50),
        ("Workspace", "Login required to access this page. " * 50),
        ("登录", "请先登录后继续。" * 50),
    ],
)
def test_actual_auth_wall_is_still_detected(title, text):
    assert score_quality(title, text, status_code=200).looks_like_login


def test_brand_header_does_not_hide_actual_login_form():
    text = (
        "Acme\nWelcome back\nSign in\nEmail address\nPassword\n"
        "Continue with Google\nForgot your password?\n"
        + "Marketing copy. " * 40
    )
    assert score_quality("Acme Workspace", text, status_code=200).looks_like_login


def test_navigation_and_newsletter_email_are_not_a_login_form():
    text = (
        "Products\nLog in\nProfessional\nSubscribe with your email address\n"
        + "Public features. " * 100
    )
    assert not score_quality("Figma Pricing", text, status_code=200).looks_like_login


def test_first_navigation_login_link_is_not_an_auth_form():
    text = "Log in\nProducts\nProfessional\nFull seat\n$16/mo\n" + "Public features. " * 100
    assert not score_quality("Figma Pricing", text, status_code=200).looks_like_login


def test_captured_checked_billing_control_is_not_an_unselected_label():
    from packages.tools.fetch_page import _pricing_controls
    controls=_pricing_controls('<main><input name="billingInterval" type="radio" value="month"><input name="billingInterval" type="radio" value="year" checked></main>')
    assert len(controls)==1 and controls[0]['interval']=='annual'
    assert _pricing_controls('<input name="billingInterval" value="month"><input name="billingInterval" value="year">')==()


def test_price_card_binds_selected_interval_and_preserves_html_evidence():
    from packages.tools.fetch_page import _pricing_controls
    from packages.research.models import CapturedPage
    from packages.research.extraction.pricing_cards import rendered_price_cards
    controls=_pricing_controls('<input name="billingInterval" type="radio" value="year" checked>')
    page=CapturedPage(candidate_id='price-ui',requested_url='https://www.notion.com/pricing',final_url='https://www.notion.com/pricing',status='ok',title='Notion Pricing',text='Price in USD\nPlus\n$10\nper member / month',content_hash='pricing-ui-fixture',metadata={'pricing_controls':controls})
    row=rendered_price_cards('Notion',page)[0]
    assert row['qualifiers']['billing_interval']=='annual'
    assert 'checked' in row['qualifiers']['billing_selection_evidence']['html']
    ambiguous=page.model_copy(update={'metadata':{'pricing_controls':[*controls,*_pricing_controls('<input name="billingInterval" value="month" checked>')]}})
    assert rendered_price_cards('Notion',ambiguous)[0]['qualifiers']['billing_interval']=='unknown'


def test_notions_selected_control_does_not_set_another_products_interval():
    from packages.tools.fetch_page import _pricing_controls
    from packages.research.models import CapturedPage
    from packages.research.extraction.pricing_cards import rendered_price_cards
    page=CapturedPage(candidate_id='scope',requested_url='https://www.atlassian.com/software/confluence/pricing',final_url='https://www.atlassian.com/software/confluence/pricing',status='ok',title='Confluence Pricing',text='Standard\nEverything you need to get started\n$5.42\nper user / month',content_hash='scope',metadata={'pricing_controls':_pricing_controls('<input name="billingInterval" value="year" checked>')})
    assert rendered_price_cards('Confluence',page)[0]['qualifiers']['billing_interval']=='unknown'


def test_confluence_visible_price_matches_same_product_structured_offer_and_controls():
    import json
    from packages.tools.fetch_page import _pricing_controls
    from packages.research.models import CapturedPage
    from packages.research.extraction.pricing_cards import rendered_price_cards
    offer={'@type':'Product','name':'Confluence','offers':[{'name':'Standard','priceSpecification':{'price':'5.42','priceCurrency':'USD','billingDuration':'P1M','referenceQuantity':{'value':1,'unitText':'user'},'eligibleQuantity':{'value':300,'unitText':'user'}}}]}
    control='<input name="billing" id="MONTHLY" type="radio" checked><input id="unit-count" type="number" value="300">'
    page=CapturedPage(candidate_id='quote',requested_url='https://www.atlassian.com/software/confluence/pricing',final_url='https://www.atlassian.com/software/confluence/pricing',status='ok',title='Confluence Pricing',text='Standard\nEverything you need to get started\n$5.42\nper user / month',content_hash='quote',metadata={'pricing_controls':_pricing_controls(control),'pricing_offer_json':[json.dumps(offer)]})
    row=rendered_price_cards('Confluence',page)[0]
    assert row['qualifiers']['currency']=='USD'
    assert row['qualifiers']['billing_interval']=='monthly'
    assert row['qualifiers']['quoted_user_count']==300
    assert row['qualifiers']['amount_basis']=='user'
    changed=json.loads(json.dumps(offer));changed['name']='Jira'
    wrong=page.model_copy(update={'metadata':{**page.metadata,'pricing_offer_json':[json.dumps(changed)]}})
    assert 'currency' not in rendered_price_cards('Confluence',wrong)[0]['qualifiers']
    changed['name']='Confluence';changed['offers'][0]['priceSpecification']['price']='9.99'
    mismatch=page.model_copy(update={'metadata':{**page.metadata,'pricing_offer_json':[json.dumps(changed)]}})
    assert 'currency' not in rendered_price_cards('Confluence',mismatch)[0]['qualifiers']


def test_malformed_structured_offers_do_not_crash_or_create_currency():
    import json
    from packages.research.models import CapturedPage
    from packages.research.extraction.pricing_cards import rendered_price_cards
    for raw in [json.dumps({'@graph':42}),json.dumps({'@type':'Product','name':'Confluence','offers':'invalid'}),json.dumps({'@type':'Product','name':'Confluence','offers':[{'name':'Standard','priceSpecification':42}]})]:
        page=CapturedPage(candidate_id='malformed',requested_url='https://www.atlassian.com/software/confluence/pricing',final_url='https://www.atlassian.com/software/confluence/pricing',status='ok',title='Confluence Pricing',text='Standard\nEverything you need to get started\n$5.42\nper user / month',content_hash='malformed',metadata={'pricing_offer_json':[raw]})
        assert 'currency' not in rendered_price_cards('Confluence',page)[0]['qualifiers']


def test_hidden_billing_input_does_not_create_selected_interval():
    from packages.tools.fetch_page import _pricing_controls
    assert _pricing_controls('<div hidden><input name="billingInterval" value="year" checked></div>')==()
    assert _pricing_controls('<div aria-hidden="true"><input name="billing" id="MONTHLY" checked></div>')==()


def test_matching_json_ld_amount_does_not_hide_conflicting_billing_or_unit():
    import json
    from packages.tools.fetch_page import _pricing_controls
    from packages.research.models import CapturedPage
    from packages.research.extraction.pricing_cards import rendered_price_cards
    for control,period,unit in [('<input name="billing" id="ANNUAL" checked>','P1Y','user'),('<input name="billing" id="MONTHLY" checked>','P1M','site')]:
        spec={'price':'5.42','priceCurrency':'USD','billingDuration':period,'referenceQuantity':{'value':1,'unitText':unit}}
        product={'@type':'Product','name':'Confluence','offers':[{'name':'Standard','priceSpecification':spec}]}
        page=CapturedPage(candidate_id='condition-conflict',requested_url='https://www.atlassian.com/software/confluence/pricing',final_url='https://www.atlassian.com/software/confluence/pricing',status='ok',title='Confluence Pricing',text='Standard\nEverything you need to get started\n$5.42\nper user / month',content_hash='condition-conflict',metadata={'pricing_controls':_pricing_controls(control),'pricing_offer_json':[json.dumps(product)]})
        row=rendered_price_cards('Confluence',page)[0]
        assert 'currency' not in row['qualifiers']
        assert row['qualifiers'].get('price_condition_conflict')
