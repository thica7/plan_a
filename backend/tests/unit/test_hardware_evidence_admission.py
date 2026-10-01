import pytest

from packages.research.evidence.admission import admit_evidence_items, source_quality_problem
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


def test_hardware_spec_table_is_extracted_and_admitted_without_capability_verbs():
    brief = ResearchBrief(run_id='specs', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    page = CapturedPage(candidate_id='specs',
        requested_url='https://www.nintendo.com/us/gaming-systems/switch-2/tech-specs/',
        final_url='https://www.nintendo.com/us/gaming-systems/switch-2/tech-specs/',
        title='Nintendo Switch 2 Tech Specs', status='ok', quality_score=0.8,
        content_hash='specs', text='Nintendo Switch 2 Technical Specs\n'
        'Screen Capacitive touch screen 7.9-inch wide color gamut LCD screen 1920x1080 pixels\n'
        'Storage 256 GB (UFS). A portion of storage is reserved for the system.')
    result = extract_generic_capabilities(brief, page)
    assert any('7.9-inch' in quote.text for quote in result.quotes)
    assert any('256 GB' in quote.text for quote in result.quotes)
    assert all(page.text[q.start_offset:q.end_offset] == q.text for q in result.quotes)
    admitted = admit_evidence_items([result], captured_pages=[page])
    assert admitted
    assert all(item.status == 'accepted' for item in admitted)


def test_hardware_specs_with_unrelated_page_identity_are_not_extracted():
    brief = ResearchBrief(run_id='specs', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    page = CapturedPage(candidate_id='specs', requested_url='https://example.com/specs',
        final_url='https://example.com/specs', title='Other console specifications',
        status='ok', quality_score=0.8, content_hash='other',
        text='Screen Capacitive touch screen 7.9-inch wide color gamut LCD screen. '
             'Storage 256 GB (UFS). A portion of storage is reserved for the system.')
    assert extract_generic_capabilities(brief, page).fields == {}


@pytest.mark.parametrize(('title', 'text'), [
    ('Nintendo Switch 2 versus Steam Deck OLED', 'Steam Deck OLED specifications\n'
     'Screen 7.4-inch OLED touch screen with HDR and wide color gamut.\n'
     'Storage 1 TB NVMe SSD for games and operating system.'),
    ('Nintendo Switch 2 technical specifications',
     'Storage 256 GB external expansion is not available on Nintendo Switch 2.'),
    ('Nintendo Switch 2 technical specifications',
     'Storage 256 GB external expansion is not supported on Nintendo Switch 2.'),
    ('Nintendo Switch 2 technical specifications',
     'Storage 256 GB external expansion is unsupported on Nintendo Switch 2.'),
    ('Nintendo Switch 2 launch',
     'Storage promotion: win a 256 GB memory card when you register for our launch giveaway.'),
    ('Nintendo Switch 2 technical specifications',
     'Storage promotion: win a 256 GB memory card in our giveaway.'),
])
def test_hardware_spec_fallback_rejects_comparison_negation_and_marketing(title, text):
    brief = ResearchBrief(run_id='invalid', topic='掌机功能', competitor='Nintendo Switch 2',
                          dimension='feature', product_category='游戏掌机')
    page = CapturedPage(candidate_id='invalid', requested_url='https://example.com/specs',
        final_url='https://example.com/specs', title=title, status='ok', quality_score=0.8,
        content_hash='invalid', text=text)
    assert extract_generic_capabilities(brief, page).fields == {}


def test_capability_sentence_split_preserves_decimal_specifications():
    brief = ResearchBrief(run_id='decimal', topic='掌机功能', competitor='Steam Deck',
                          dimension='feature', product_category='游戏掌机')
    page = CapturedPage(candidate_id='decimal', requested_url='https://www.steamdeck.com/en/tech',
        final_url='https://www.steamdeck.com/en/tech', title='Steam Deck :: Tech Specs',
        status='ok', quality_score=0.8, content_hash='decimal',
        text='CPU 2.4-3.5GHz GPU 1.6 TFlops FP32) Storage Steam Deck 512GB NVMe SSD '
             'Both include a high-speed microSD card slot.')
    result = extract_generic_capabilities(brief, page)
    assert result.quotes
    assert '1.6 TFlops' in result.quotes[0].text
    quote = result.quotes[0]
    assert page.text[quote.start_offset:quote.end_offset] == quote.text
