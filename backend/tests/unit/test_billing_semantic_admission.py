"""Anonymous original billing observations survive the actual evidence gates."""

import hashlib
from datetime import datetime

import pytest
import test_question_semantic_focus as source_fixtures
from test_billing_rule_context import source_table

from packages.research.evidence import admit_evidence_items
from packages.research.evidence.admission import (
    raw_source_from_capture, raw_sources_from_research_result, source_quality_problem,
)
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.extraction import semantic
from packages.research.models import ResearchResult
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


BILLING_QUESTION = 'What are the Usage billing rules for requests and CPU time?'
source = source_fixtures.source


def extract(source, body, quote, *, question=BILLING_QUESTION, headings=()):
    brief, candidate, page = source(body, questions=(question,), headings=headings)
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]})
    return brief, candidate, page, result


@pytest.mark.parametrize('quote', [
    'The Usage plan has a minimum account charge of $13 USD per month.',
    'CPU time is only billed when the function runs.',
    'Requests to static assets are free and unlimited.',
    'Your bill depends on request count and CPU time.',
])
def test_source_billing_signals_pass_extraction_and_native_quality(source, quote):
    brief, candidate, page, result = extract(source, quote, quote)
    assert result.fields, 'An actual billing rule was lost before admission.'
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)
    raw = raw_source_from_capture(brief, candidate, page, confidence=.8, snippet=quote)
    assert source_quality_problem(raw) is None


def test_complete_rate_table_and_all_notes_reach_the_sealed_feature_snapshot(source):
    body, header, row, notes = source_table()
    brief, candidate, page, extraction = extract(source, body, row)
    assert extraction.fields
    value = next(iter(extraction.fields.values()))
    assert value['table_context'] == [header, *notes]
    assert all(term in '\n'.join(value['evidence_terms']) for term in [header, *notes])
    items = admit_evidence_items([extraction], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)
    normalized = normalized_fields_from_evidence_items(items)
    research = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page],
        extractions=[extraction], evidence_items=items, normalized_fields=normalized)
    sources = raw_sources_from_research_result(brief, research, batch_sources=[],
        target_source_count=1, requires_accepted_evidence=True,
        source_exists=lambda *_: False, confidence_for_source=lambda *_: .8,
        fallback_snippet=lambda capture: capture.text)
    assert len(sources) == 1, 'An admitted billing observation was dropped by native quality.'
    now = datetime.now()
    detail = RunDetail(id=brief.run_id, topic=brief.topic, status='running', execution_mode='real',
        created_at=now, updated_at=now, raw_sources=sources,
        plan=AnalysisPlan(topic=brief.topic, competitors=[brief.competitor], dimensions=['feature']))
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    facts = [fact for fact in snapshot.facts if fact.field == 'evidence_terms']
    assert facts and all(fact.dimension == 'feature' for fact in facts)
    assert any(fact.qualifiers.get('table_context') == [header, *notes] for fact in facts)
    assert not any(fact.field in {'price', 'amount', 'current_price'} for fact in snapshot.facts)


def test_four_column_rate_table_keeps_all_numbered_notes_and_stops_at_worked_example(source):
    header = '|  | Requests1, 2, 3, 4 | Duration | CPU time |'
    free = '| Free | 90,000/day | No charge | 12 ms/request |'
    row = ('| Usage | 14 million included per month +$0.44 per million | No charge | '
           '40 million CPU milliseconds included per month +$0.04 per million CPU milliseconds |')
    notes = [
        '1 Requests to static assets are free and unlimited.',
        '2 Upgraded connections count as the initial request.\nMessages do not count as new requests.',
        '3 Some cache lookups are excluded from request counts.',
        '4 CPU time is only billed when a function runs (on a cache miss or bypass).',
    ]
    body = 'Billing\nFunctions\n' + header + '\n|---|---|---|---|\n' + free + '\n' + row + '\n'
    body += '\n'.join(notes) + '\nExample 1\n| Estimated costs | $8.00 |'
    *_, result = extract(source, body, row, headings=[(1, 'Billing'), (2, 'Functions')])
    assert result.fields
    value = next(iter(result.fields.values()))
    assert value['table_context'] == [header, *notes]
    assert not any('Estimated costs' in term or 'Example 1' in term
                   for term in value['evidence_terms'])


def test_nearest_verified_service_section_does_not_mix_sibling_restrictions(source):
    quote = 'CPU time is only billed when the function runs.'
    unrelated = '\n'.join(f'Storage tier {index} requires a separate license.' for index in range(13))
    body = 'Billing\nService rules\nStorage service\n' + unrelated + '\nUsage service\n' + quote
    brief, candidate, page, result = extract(source, body, quote, headings=[
        (1, 'Billing'), (2, 'Service rules'), (3, 'Storage service'), (3, 'Usage service')])
    assert result.fields
    field = next(iter(result.fields.values()))
    assert all('Storage tier' not in term for term in field['evidence_terms'])
    assert field['document_section'][0] == body.index('Usage service')
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)


def test_no_heading_billing_rule_uses_contiguous_local_context_not_entire_page(source):
    quote = 'CPU time is only billed when the function runs.'
    other = '\n'.join(f'Archive tier {index} requires an independent storage subscription.'
                      for index in range(13))
    body = quote + '\n\n' + other
    *_, result = extract(source, body, quote)
    assert result.fields
    assert all('Archive tier' not in term for value in result.fields.values()
               for term in value['evidence_terms'])
    assert not result.metadata['source_condition_gaps']


@pytest.mark.parametrize('change', ['missing_note', 'duplicate_note', 'wrong_columns', 'unmeasured_header'])
def test_incomplete_rate_table_is_rejected_instead_of_accepted_as_bare_money(source, change):
    body, _, row, notes = source_table()
    if change == 'missing_note':
        body = body.replace(notes[0] + '\n', '')
    elif change == 'duplicate_note':
        body = body.replace(notes[0], notes[0] + '\n' + notes[0])
    elif change == 'wrong_columns':
        body = body.replace('|---|---|---|', '|---|---|')
    else:
        body = body.replace('| Plan | Requests1, 2 | CPU time* |', '| Plan | Label1, 2 | Other* |')
    *_, result = extract(source, body, row)
    assert not result.fields


@pytest.mark.parametrize('change', ['units', 'footnote', 'source', 'offset', 'focus', 'headings'])
def test_rate_table_admission_replays_original_context_and_authorized_focus(source, change):
    body, _, row, _ = source_table()
    brief, candidate, page, result = extract(source, body, row, headings=[(1, 'Billing')])
    assert result.fields
    if change == 'units':
        page.text = page.text.replace('CPU time*', 'CPU seconds*')
    elif change == 'footnote':
        page.text = page.text.replace('initial connection.', 'entire session.')
    elif change == 'source':
        result.quotes[0].source_url = 'https://foreign.example.test/rates'
    elif change == 'offset':
        result.quotes[0].start_offset += 1
    elif change == 'focus':
        result.metadata['active_question_ids'] = ['unapproved']
    else:
        page.metadata['document_headings'] = [(2, 'Billing')]
    page.content_hash = hashlib.sha256(page.text.encode()).hexdigest()
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'rejected' for item in items)


@pytest.mark.parametrize('change', ['outside_body', 'outside_heading_level'])
def test_focus_signature_binds_complete_body_and_verified_headings_outside_model_window(source, change):
    quote = 'The Usage plan has a minimum account charge of $13 USD per month.'
    body = 'Billing\nUsage service\n' + quote + '\nAppendix\n' + 'Archived note.\n' * 1200
    body += 'Other service\nStorage requests are only billed in the destination region.'
    brief, _, page = source(body, questions=('What minimum account charge applies to Usage billing?',), headings=[
        (1, 'Billing'), (2, 'Usage service'), (2, 'Appendix'), (2, 'Other service')])
    before = semantic.semantic_focus_signature(brief, page)
    window = semantic.semantic_body_window(brief, page)
    if change == 'outside_body':
        page.text = page.text.replace('destination region.', 'origin region.')
        page.content_hash = hashlib.sha256(page.text.encode()).hexdigest()
    else:
        page.metadata['document_headings'][-1] = (3, 'Other service')
    assert semantic.semantic_body_window(brief, page) == window
    assert semantic.semantic_focus_signature(brief, page) != before


def test_official_worked_example_does_not_become_users_actual_bill(source):
    quote = 'Example 7: 15 million requests and 7 ms of CPU time per request cost $8.'
    brief, candidate, page, result = extract(source, quote, quote,
        question='What is my exact bill this month for 1500 million requests?')
    assert result.fields
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)
    normalized = normalized_fields_from_evidence_items(items)
    assert normalized and all(item.kind == 'feature' for item in normalized)
    assert all('1500' not in str(item.model_dump()) for item in normalized)
    assert all(not {'price', 'amount', 'currency'} & item.model_dump().keys() for item in normalized)


@pytest.mark.parametrize('question', ['Can guests edit shared pages?', 'Which features are available?',
    'Can guests edit the pricing page?', 'What exact permissions do editors have on billing pages?'])
def test_active_feature_question_cannot_use_billing_money_exception(source, question):
    quote = 'The Usage plan has a minimum account charge of $13 USD per month.'
    *_, result = extract(source, quote, quote, question=question)
    assert not result.fields


def test_inactive_billing_question_does_not_grant_money_extraction(source):
    quote = 'The Usage plan has a minimum account charge of $13 USD per month.'
    brief, _, page = source(quote, questions=('Can guests edit shared pages?', BILLING_QUESTION))
    brief.metadata['active_question_ids'] = ['q0']
    assert not semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]}).fields


@pytest.mark.parametrize('placement', ['same_section', 'parent_section', 'no_heading'])
def test_table_retains_applicable_local_and_parent_intro_subscription_conditions(source, placement):
    condition = 'These Usage rates are only available to verified enterprise subscribers.'
    header = '| Plan | Requests | CPU time |'
    row = '| Usage | $0.42 per million requests | $0.03 per million CPU milliseconds |'
    table = header + '\n|---|---|---|\n' + row
    body = ('Billing\nUsage service\n' + condition + '\n' + table if placement == 'same_section'
            else 'Billing\n' + condition + '\nUsage service\n' + table)
    headings = [(1, 'Billing'), (2, 'Usage service')]
    if placement == 'no_heading':
        body, headings = condition + '\n' + table, []
    brief, candidate, page, result = extract(source, body, row,
        headings=headings)
    assert result.fields and condition in next(iter(result.fields.values()))['conditions']
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)


@pytest.mark.parametrize('change', ['markdown_ref', 'implicit_cpu_unit'])
def test_unsupported_markdown_ref_and_implicit_conflicting_unit_cannot_enter_admission(source, change):
    header = '| Plan | Requests[^1] | CPU time |' if change == 'markdown_ref' else '| Plan | Requests | CPU seconds |'
    row = ('| Usage | $0.42 per million requests | $0.03 per million CPU milliseconds |'
           if change == 'markdown_ref' else '| Usage | $0.42 per million requests | $0.03 per million milliseconds |')
    body = header + '\n|---|---|---|\n' + row
    if change == 'markdown_ref':
        body += '\n[^1]: Only inbound requests are billed.'
    brief, candidate, page, result = extract(source, body, row)
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert not any(item.status == 'accepted' for item in items)


@pytest.mark.parametrize('placement', ['same_section', 'parent_section', 'no_heading'])
def test_full_source_intro_keeps_adjacent_exception_sentences_without_keyword_guessing(source, placement):
    intro = ('These Usage rates are only available to enterprise subscribers.\n'
             'Trial subscriptions are excluded.')
    header = '| Plan | Requests | CPU time |'
    row = '| Usage | $0.42 per million requests | $0.03 per million CPU milliseconds |'
    table = header + '\n|---|---|---|\n' + row
    if placement == 'same_section':
        body = 'Billing\nUsage service\n' + intro + '\n' + table
    elif placement == 'parent_section':
        body = 'Billing\n' + intro + '\nUsage service\n' + table
    else:
        body = intro + '\n' + table
    headings = [] if placement == 'no_heading' else [(1, 'Billing'), (2, 'Usage service')]
    brief, candidate, page, result = extract(source, body, row, headings=headings)
    assert result.fields and intro in next(iter(result.fields.values()))['conditions']
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)


def test_overlong_contiguous_intro_is_rejected_instead_of_pruning_its_exception(source):
    intro = 'These Usage rates are only available to enterprise subscribers.\n'
    intro += 'Trial subscriptions are excluded from this entitlement.\n' * 30
    header = '| Plan | Requests | CPU time |'
    row = '| Usage | $0.42 per million requests | $0.03 per million CPU milliseconds |'
    body = 'Billing\n' + intro + '\nUsage service\n' + header + '\n|---|---|---|\n' + row
    *_, result = extract(source, body, row, headings=[(1, 'Billing'), (2, 'Usage service')])
    assert not result.fields
