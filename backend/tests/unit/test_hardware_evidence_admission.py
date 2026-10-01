from packages.research.evidence.admission import source_quality_problem
from packages.research.extraction.feature import extract_generic_capabilities
from packages.research.models import CapturedPage, ResearchBrief
from packages.schema.models import RawSource


def source(snippet):
    return RawSource(id='hardware-source', competitor='Nintendo Switch 2',
        dimension='feature', source_type='webpage_verified',
        title='Nintendo Switch 2 specifications',
        url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        snippet=snippet, content_hash='hardware', confidence=0.84)


def test_concrete_hardware_specs_are_admitted_without_api_keywords():
    assert source_quality_problem(source(
        'Nintendo Switch 2: 7.9-inch LCD screen, 1080p resolution and 256 GB storage.'
    )) is None


def test_hardware_marketing_or_navigation_is_not_a_concrete_fact():
    assert source_quality_problem(source(
        'Nintendo Switch 2: Explore games. Shop now. Search. Support. All new screen.'
    )) is not None


def test_hardware_identity_mismatch_still_rejected():
    unrelated = source('Another console has a 7.9-inch LCD screen and 256 GB storage.')
    unrelated.title = 'Another console specifications'
    unrelated.url = 'https://example.com/specifications'
    assert source_quality_problem(unrelated) is not None


def test_navigation_support_and_features_labels_are_not_capabilities():
    brief = ResearchBrief(run_id='shell', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    page = CapturedPage(candidate_id='shell',
        requested_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        final_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        title='Nintendo Switch 2', status='ok', quality_score=0.8, content_hash='shell',
        text='Nintendo Switch 2 features How to buy Accessories Games Technical specs '
             'Getting started Frequently Asked Questions Careers Privacy policy '
             'Order details Shipping info Refunds and returns Community guidelines')
    result = extract_generic_capabilities(brief, page)
    assert result.fields == {}
    assert result.missing_fields == ['product_capabilities']


def test_product_fact_survives_navigation_on_the_same_line():
    brief = ResearchBrief(run_id='mixed', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    fact = 'Nintendo Switch 2 supports 256 GB external storage'
    page = CapturedPage(candidate_id='mixed',
        requested_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        final_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        title='Nintendo Switch 2', status='ok', quality_score=0.8, content_hash='mixed',
        text=f'{fact} How to buy Privacy policy Shipping info')
    result = extract_generic_capabilities(brief, page)
    assert result.fields
    assert result.quotes[0].text == fact
    assert source_quality_problem(source(result.quotes[0].text)) is None


def test_product_fact_survives_header_and_footer_with_exact_quote_offsets():
    brief = ResearchBrief(run_id='mixed', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    fact = 'Nintendo Switch 2 supports 256 GB external storage'
    page = CapturedPage(candidate_id='mixed',
        requested_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        final_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        title='Nintendo Switch 2', status='ok', quality_score=0.8, content_hash='mixed',
        text=f'  Skip to main content {fact} Privacy policy Shipping info')
    result = extract_generic_capabilities(brief, page)
    assert result.fields
    quote = result.quotes[0]
    assert quote.text == fact
    assert page.text[quote.start_offset:quote.end_offset] == quote.text


def test_navigation_product_title_does_not_hide_later_product_fact():
    brief = ResearchBrief(run_id='mixed', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    fact = 'Nintendo Switch 2 supports 256 GB external storage'
    page = CapturedPage(candidate_id='mixed',
        requested_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        final_url='https://www.nintendo.com/us/gaming-systems/switch-2/',
        title='Nintendo Switch 2', status='ok', quality_score=0.8, content_hash='mixed',
        text=f'Skip to main content Nintendo Switch 2 How to buy {fact} '
             'Privacy policy Shipping info')
    result = extract_generic_capabilities(brief, page)
    assert result.fields
    quote = result.quotes[0]
    assert quote.text == fact
    assert page.text[quote.start_offset:quote.end_offset] == quote.text
