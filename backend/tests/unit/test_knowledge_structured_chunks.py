from __future__ import annotations

import pytest

from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalRequest
from packages.knowledge.parsers import parse_document
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import QueryRewriter, RetrievalService


class NoRewrite(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        return []


def test_chinese_sentences_remain_exact_substrings() -> None:
    sentences = ['基础套餐每月29.9元。', '包含权限管理与审计日志。', '仅限中国大陆市场。']
    source = ''.join(sentences)
    pipeline = IngestionPipeline(object(), object(), chunk_size=14, chunk_overlap=0)

    chunks = pipeline._chunk_text(source, 'document-test', 'body-hash', '')

    assert [chunk.text for chunk in chunks] == sentences
    assert all(chunk.text in source for chunk in chunks)


def test_decimal_and_model_dots_do_not_split_sentences() -> None:
    source = 'English 3.5 and V4.1 remain together. Next sentence.'
    pipeline = IngestionPipeline(object(), object(), chunk_size=39, chunk_overlap=0)

    chunks = pipeline._chunk_text(source, 'document-test', 'body-hash', '')

    assert [chunk.text for chunk in chunks] == [
        'English 3.5 and V4.1 remain together.', 'Next sentence.'
    ]


def test_chinese_period_before_ascii_starts_a_new_sentence() -> None:
    source = '基础套餐。Pro plan.'
    pipeline = IngestionPipeline(object(), object(), chunk_size=9, chunk_overlap=0)

    chunks = pipeline._chunk_text(source, 'document-test', 'body-hash', '')

    assert [chunk.text for chunk in chunks] == ['基础套餐。', 'Pro plan.']


def test_heading_metadata_uses_actual_heading_line() -> None:
    source = 'Business plans overview.\n\nBusiness\n\nActual price.'
    pipeline = IngestionPipeline(object(), object(), chunk_size=30, chunk_overlap=0)

    chunks = pipeline._chunk_text(
        source, 'document-test', 'body-hash', '', markdown='## Business',
    )

    assert chunks[0].metadata['structure'] == 'unknown'
    assert chunks[-1].metadata['heading_path'] == [{'level': 2, 'text': 'Business'}]


def test_html_preserves_real_structure_and_drops_navigation() -> None:
    html = b'''<html><head><title>Plans</title></head><body>
      <nav>Products Pricing Login</nav><main><h1>Pricing</h1><h2>Business</h2>
      <p>Monthly plans are available.</p><table><thead><tr><th>Plan</th><th>Price</th></tr></thead>
      <tbody><tr><td>Pro</td><td>29.9/month*</td></tr></tbody></table>
      <p>* Annual billing only.</p></main><footer>Products Pricing Login</footer></body></html>'''

    parsed = parse_document(html, 'text/html', 'https://example.com/plans')

    assert 'Products Pricing Login' not in parsed.text
    assert parsed.text.index('Business') < parsed.text.index('Plan | Price')
    assert 'Pro | 29.9/month*' in parsed.text
    assert '* Annual billing only.' in parsed.text
    assert '# Pricing' in parsed.metadata['markdown']
    assert '## Business' in parsed.metadata['markdown']
    assert parsed.tables[0]['headers'] == ['Plan', 'Price']
    assert parsed.tables[0]['rows'] == [['Pro', '29.9/month*']]


def test_table_without_header_does_not_invent_one() -> None:
    parsed = parse_document(
        b'<main><h2>Rates</h2><table><tr><td>Basic</td><td>29.9</td></tr>'
        b'<tr><td>Pro</td><td>49.9</td></tr></table></main>',
        'text/html', 'https://example.com/rates',
    )

    assert parsed.tables[0]['headers'] == []
    assert parsed.tables[0]['rows'] == [['Basic', '29.9'], ['Pro', '49.9']]
    assert 'Basic | 29.9' in parsed.text
    assert parsed.tables[0]['structure_gap'] == 'missing_header'


def test_main_direct_text_and_tails_are_preserved() -> None:
    parsed = parse_document(
        b'<main>Intro terms <p>Basic plan.</p> Final limitation.</main>',
        'text/html', 'https://example.com/terms',
    )

    assert parsed.text == 'Intro terms\n\nBasic plan.\n\nFinal limitation.'


def test_merged_table_cells_report_structure_gap() -> None:
    parsed = parse_document(
        b'<main><table><tr><th>Plan</th><th>Region</th></tr>'
        b'<tr><td colspan="2">Global plan</td></tr></table></main>',
        'text/html', 'https://example.com/plans',
    )

    assert parsed.tables[0]['rows'] == [['Global plan']]
    assert parsed.tables[0]['structure_gap'] == 'merged_cells'


def test_row_label_th_is_not_promoted_to_column_header() -> None:
    parsed = parse_document(
        b'<main><table><tr><th scope="row">Basic</th><td>29.9</td></tr>'
        b'<tr><th scope="row">Pro</th><td>49.9</td></tr></table></main>',
        'text/html', 'https://example.com/prices',
    )

    assert parsed.tables[0]['headers'] == []
    assert parsed.tables[0]['rows'] == [['Basic', '29.9'], ['Pro', '49.9']]


def test_caption_and_navigation_role_are_handled() -> None:
    parsed = parse_document(
        b'<main><div role="navigation">Products Login</div><h2>Business</h2>'
        b'<table><caption>USD per seat, taxes excluded</caption>'
        b'<tr><th>Plan</th><th>Price</th></tr>'
        b'<tr><td>Pro</td><td>29.9/month</td></tr></table></main>',
        'text/html', 'https://example.com/pricing',
    )

    assert 'Products Login' not in parsed.text
    assert 'USD per seat, taxes excluded' in parsed.text
    assert parsed.tables[0]['caption'] == 'USD per seat, taxes excluded'
    assert parsed.tables[0]['text'] in parsed.text


def test_xhtml_encoding_declaration_does_not_expose_raw_markup() -> None:
    parsed = parse_document(
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        b'<main><h1>Plans</h1><p>Only annual contracts.</p></main>'
        b'</body></html>',
        'text/html', 'https://example.com/plans',
    )

    assert 'Only annual contracts.' in parsed.text
    assert '<main>' not in parsed.text


def test_html_comment_is_skipped_but_its_tail_is_kept() -> None:
    parsed = parse_document(
        b'<main><h1>Prices</h1><!-- hidden note --> Terms apply.'
        b'<p>29.9/month</p></main>',
        'text/html', 'https://example.com/prices',
    )

    assert parsed.text == 'Prices\n\nTerms apply.\n\n29.9/month'
    assert parsed.metadata['markdown'].startswith('# Prices')


def test_sibling_articles_both_survive_without_nested_duplicate() -> None:
    parsed = parse_document(
        b'<article><h2>Basic</h2><p>29.9/month</p></article>'
        b'<article><h2>Pro</h2><p>99/month</p></article>',
        'text/html', 'https://example.com/plans',
    )
    nested = parse_document(
        b'<main><article><h2>Basic</h2><p>29.9/month</p></article></main>',
        'text/html', 'https://example.com/plans',
    )

    assert parsed.text == 'Basic\n\n29.9/month\n\nPro\n\n99/month'
    assert nested.text.count('29.9/month') == 1


def test_hidden_main_does_not_override_visible_main() -> None:
    parsed = parse_document(
        b'<main hidden><p>Old price 99</p></main>'
        b'<main><p>New price 29.9</p></main>',
        'text/html', 'https://example.com/prices',
    )

    assert 'Old price 99' not in parsed.text
    assert parsed.text == 'New price 29.9'


def test_list_item_nested_structure_keeps_table_and_conditions() -> None:
    parsed = parse_document(
        b'<main><ul><li><h2>Pro</h2><p>Annual only</p>'
        b'<table><tr><th>Price</th></tr><tr><td>29.9/month</td></tr></table>'
        b'<p>Tax excluded</p></li></ul></main>',
        'text/html', 'https://example.com/prices',
    )

    assert parsed.text == 'Pro\n\nAnnual only\n\nPrice\n29.9/month\n\nTax excluded'
    assert '## Pro' in parsed.metadata['markdown']
    assert parsed.tables[0]['text'] == 'Price\n29.9/month'
    assert parsed.tables[0]['text'] in parsed.text


@pytest.mark.asyncio
async def test_price_top1_keeps_conditions_and_plan_boundary(tmp_path) -> None:
    parsed = parse_document(
        b'<main><h1>Pricing</h1><h2>Business</h2>'
        b'<p>Only annual contracts.</p>'
        b'<table><caption>USD per seat, taxes excluded</caption>'
        b'<tr><th>Plan</th><th>Price</th></tr>'
        b'<tr><td>Pro</td><td>29.9/month*</td></tr></table>'
        b'<p>* Annual billing only.</p>'
        b'<h2>Personal</h2><p>Single user only.</p></main>',
        'text/html', 'https://example.com/pricing',
    )
    async with KnowledgeRepository(str(tmp_path / 'kb.db')) as repo:
        pipeline = IngestionPipeline(repo, object(), chunk_size=32, chunk_overlap=0)
        doc_id = await pipeline.ingest(DocumentCreate(
            url='https://example.com/pricing', title=parsed.title,
            source_type='manual', text=parsed.text,
            markdown=parsed.metadata['markdown'],
            metadata={**parsed.metadata, 'tables': parsed.tables},
        ))
        stored = await repo.get_document(doc_id)
        chunks = await repo.get_chunks_for_document(doc_id)
        response = await RetrievalService(
            repo, object(), embed_fn=lambda _: [], query_rewriter=NoRewrite(),
        ).retrieve(RetrievalRequest(
            query='29.9', mode='sparse', top_k=1, final_top_k=1,
            enable_query_rewrite=False,
        ))

    assert stored is not None
    assert len(response.hits) == 1
    price_chunk = next(chunk for chunk in chunks if '29.9' in chunk.text)
    assert response.hits[0].chunk_id == price_chunk.id
    assert price_chunk.text in stored.text
    assert 'Only annual contracts.' in response.hits[0].text
    assert 'USD per seat, taxes excluded' in response.hits[0].text
    assert '* Annual billing only.' in response.hits[0].text
    assert 'Personal' not in response.hits[0].text
    assert price_chunk.metadata['heading_path'] == [
        {'level': 1, 'text': 'Pricing'}, {'level': 2, 'text': 'Business'},
    ]
    personal_chunk = next(chunk for chunk in chunks if 'Single user only.' in chunk.text)
    assert 'Annual billing' not in personal_chunk.text
    assert personal_chunk.metadata['heading_path'] == [
        {'level': 1, 'text': 'Pricing'}, {'level': 2, 'text': 'Personal'},
    ]


@pytest.mark.asyncio
async def test_oversized_table_is_atomic_and_metadata_survives_sqlite(tmp_path) -> None:
    parsed = parse_document(
        b'<main><h1>Pricing</h1><table><tr><th>Plan</th><th>Conditions</th></tr>'
        b'<tr><td>Enterprise</td><td>Annual billing applies to all seats; '
        b'priority support and audit history included.</td></tr></table>'
        b'<p>* Taxes excluded.</p></main>',
        'text/html', 'https://example.com/pricing',
    )
    metadata = {**parsed.metadata, 'tables': parsed.tables}
    async with KnowledgeRepository(str(tmp_path / 'kb.db')) as repo:
        pipeline = IngestionPipeline(repo, object(), chunk_size=30, chunk_overlap=0)
        doc_id = await pipeline.ingest(DocumentCreate(
            url='https://example.com/pricing', title=parsed.title,
            source_type='manual', text=parsed.text,
            markdown=parsed.metadata['markdown'], metadata=metadata,
        ))
        stored = await repo.get_document(doc_id)
        chunks = await repo.get_chunks_for_document(doc_id)

    assert stored is not None
    assert stored.url == 'https://example.com/pricing'
    assert any(chunk.metadata.get('structure') == 'table' for chunk in chunks)
    table_chunk = next(chunk for chunk in chunks if chunk.metadata.get('structure') == 'table')
    assert parsed.tables[0]['text'] in table_chunk.text
    assert table_chunk.metadata['overflow'] is True
    assert table_chunk.metadata['overflow_chars'] == len(table_chunk.text) - 30
    assert table_chunk.metadata['heading'] == {'level': 1, 'text': 'Pricing'}
    assert all(chunk.text in stored.text for chunk in chunks)
