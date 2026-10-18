"""Anonymous service boundaries, ordered heading recovery and exact source replay."""

import pytest
import test_question_semantic_focus as source_fixtures

from packages.research.evidence import admit_evidence_items
from packages.research.extraction import semantic

source = source_fixtures.source

MINIMUM = 'The Compute Paid plan has a minimum account charge of $13 USD per month.'
ROW = ('| Standard | 12 million included +$0.42 per million requests | '
       '20 million CPU milliseconds included +$0.03 per million CPU milliseconds |')
HEADER = '| Plan | Requests1 | CPU time |'
NOTE = '1 Only inbound requests are billed; failed requests are excluded.'
COMPUTE = ('Compute\nUsers on Compute Paid can use the Standard usage model.\n'
           + HEADER + '\n|---|---|---|\n' + ROW + '\n' + NOTE + '\n')
LOGS = ('Compute Logs\nCompute Logs are included in Compute Paid.\n'
        '| Plan | Requests |\n|---|---|\n| Logs | $0.71 per million requests |\n')
ARCHIVE = ('Archive\n| Class | Storage |\n|---|---|\n'
           '| Standard storage | $0.20 per GB-month |')
HEADINGS = [(1, 'Pricing'), (2, 'Compute'), (2, 'Compute Logs'), (2, 'Archive')]


def service_source(source, *, question='What is the monthly billing for Compute Paid Standard?',
                   archive=ARCHIVE, headings=HEADINGS, questions=None):
    body = 'Pricing\n' + MINIMUM + '\n' + COMPUTE + LOGS + archive
    return source(body, questions=questions or (question,), headings=headings)


def test_repeated_heading_uses_later_anchor_instead_of_erasing_all_headings(source):
    body = 'Pricing\nCompute\nFootnotes\nOnly inbound requests are billed.\nArchive\nFootnotes\n'
    _, _, page = source(body, headings=[(1, 'Pricing'), (2, 'Compute'),
                                        (3, 'Footnotes'), (2, 'Archive')])
    assert semantic._verified_headings(body, page) == [
        (body.index(title), level, title) for level, title in
        [(1, 'Pricing'), (2, 'Compute'), (3, 'Footnotes'), (2, 'Archive')]]


@pytest.mark.parametrize('questions', [None, (
    'What is the monthly billing for Compute Paid Standard?', 'Which CPU costs apply?')])
def test_short_page_selects_complete_service_before_whole_page_returns(source, questions):
    brief, candidate, page = service_source(source, questions=questions)
    start, window = semantic._semantic_window(brief, page)
    assert start == 0 and window == 'Pricing\n' + MINIMUM + '\n' + COMPUTE
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': ROW}, {'quote': MINIMUM}]})
    assert len(result.fields) == 2
    value = next(value for value in result.fields.values() if value.get('table_context'))
    assert value['table_context'] == [HEADER, NOTE]
    assert MINIMUM in '\n'.join(value['conditions'])
    assert all(item.status == 'accepted' for item in admit_evidence_items(
        [result], brief=brief, captured_pages=[page], candidates=[candidate]))


def test_full_service_title_beats_its_prefix(source):
    brief, _, page = service_source(source, question='What is the monthly billing for Compute Logs?')
    assert semantic.semantic_body_window(brief, page) == LOGS


def test_long_foreign_service_cannot_win_with_more_billing_rules(source):
    archive = ARCHIVE + '\n' + '\n'.join(
        f'Standard storage request class {index} costs $0.20 per million requests.' for index in range(240))
    brief, _, page = service_source(source, archive=archive)
    assert semantic.semantic_body_window(brief, page) == 'Pricing\n' + MINIMUM + '\n' + COMPUTE


@pytest.mark.parametrize('question', ['What is the monthly billing for Missing Service?',
                                    'What is the monthly billing for Compute and Archive?'])
def test_unknown_or_multiple_services_do_not_fall_back_to_density(source, question):
    brief, _, page = service_source(source, question=question)
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': ROW}]})
    assert not semantic.semantic_body_window(brief, page)
    assert not result.fields
    assert 'source_billing_service_scope_unresolved' in result.metadata['source_condition_gaps']


def test_missing_child_heading_preserves_complete_known_parent_subtree(source):
    headings = [*HEADINGS[:2], (3, 'Worked scenarios'), *HEADINGS[2:]]
    brief, _, page = service_source(source, headings=headings)
    assert semantic.semantic_body_window(brief, page) == 'Pricing\n' + MINIMUM + '\n' + COMPUTE


def test_missing_peer_heading_cannot_assign_later_subsection_to_previous_service(source):
    quote = 'CPU time is only billed when the function runs.'
    body = 'Pricing\nArchive\nStorage costs $0.20 per GB-month.\nCompute billing\n' + quote + '\nOther\nRequests cost $1 per million.'
    brief, _, page = source(body, questions=('What is the Compute billing fee?',), headings=[
        (1, 'Pricing'), (2, 'Archive'), (2, 'Missing Compute'),
        (3, 'Compute billing'), (2, 'Other')])
    assert semantic._billing_condition_context(body, page, body.index(quote),
                                                body.index(quote) + len(quote)) is None
    assert not semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]}).fields


def test_missing_peer_cannot_remove_service_selection_constraint(source):
    other = 'Requests cost $2 per million requests.'
    body = 'Pricing\nCompute\nRequests cost $1 per million requests.\nOther\n' + other
    brief, _, page = source(body, questions=('What is the monthly billing for Compute?',), headings=[
        (1, 'Pricing'), (2, 'Compute'), (2, 'Missing peer'), (2, 'Other')])
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': other}]})
    assert semantic._semantic_window(brief, page) == (0, '')
    assert not result.fields
    assert 'source_billing_service_scope_unresolved' in result.metadata['source_condition_gaps']


def test_service_without_billing_rules_still_requires_explicit_service_selection(source):
    quote = 'Requests cost $1 per million requests.'
    body = 'Pricing\nCompute\n' + quote + '\nArchive\nArchive files are retained.'
    brief, _, page = source(body, questions=('What is the monthly billing for Missing Service?',), headings=[
        (1, 'Pricing'), (2, 'Compute'), (2, 'Archive')])
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]})
    assert semantic._semantic_window(brief, page) == (0, '')
    assert not result.fields
    assert 'source_billing_service_scope_unresolved' in result.metadata['source_condition_gaps']


def test_mixed_questions_do_not_apply_billing_service_selection_to_role_page(source):
    quote = 'Members can edit shared pages on all plans.'
    body = 'Roles\nAccount roles\n' + quote + '\nResource roles\nGuests can comment on shared pages.'
    brief, _, page = source(body, questions=(
        'Can members edit shared pages?', 'What is the monthly billing for Compute?'),
        headings=[(1, 'Roles'), (2, 'Account roles'), (2, 'Resource roles')])
    assert semantic._billing_service_scope(brief, body, page) is None
    assert semantic.semantic_body_window(brief, page)
    assert semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]}).fields


@pytest.mark.parametrize('archive_heading_present', [False, True])
def test_missing_first_child_cannot_turn_sibling_rules_into_ancestor_intro(source, archive_heading_present):
    restriction = 'Archive rates require a separate storage subscription.'
    quote = 'Requests cost $1 per million requests.'
    body = ('Pricing\n' + ('Archive\n' if archive_heading_present else '') + restriction
            + '\nCompute\n' + quote + '\nOther\nStorage costs $2 per GB-month.')
    brief, candidate, page = source(body, questions=('What is the monthly billing for Compute?',),
        headings=[(1, 'Pricing'), (2, 'Archive'), (2, 'Compute'), (2, 'Other')])
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]})
    if archive_heading_present:
        assert result.fields
        assert not any(restriction in term for value in result.fields.values()
                       for term in value['conditions'])
        assert all(item.status == 'accepted' for item in admit_evidence_items(
            [result], brief=brief, captured_pages=[page], candidates=[candidate]))
    else:
        assert semantic._billing_condition_context(
            body, page, body.index(quote), body.index(quote) + len(quote)) is None
        assert not result.fields
        assert 'source_billing_service_scope_unresolved' in result.metadata['source_condition_gaps']


def test_residual_duplicate_ambiguity_cannot_hide_later_restriction(source):
    body = 'Pricing\nCompute\nFootnotes\nOnly subscribers are billed.\nFootnotes\nUnless excluded, requests are billed.\nArchive\nStorage costs $0.20 per GB-month.'
    brief, _, page = source(body, questions=('What is the Compute billing fee?',), headings=[
        (1, 'Pricing'), (2, 'Compute'), (3, 'Footnotes'), (2, 'Archive')])
    assert not semantic.semantic_body_window(brief, page)


@pytest.mark.parametrize('headings', [
    [(1, 'Pricing'), (2, 'Archive'), (2, 'Compute')],
    [(1, 'Pricing'), (2, 'Compute'), (2, 'Compute')],
    [(1, 'Pricing'), ('2', 'Compute')],
])
def test_invalid_order_or_metadata_does_not_create_a_service_scope(source, headings):
    brief, _, page = service_source(source, headings=headings)
    assert not semantic._verified_headings(page.text, page)
    assert not semantic.semantic_body_window(brief, page)


def test_missing_metadata_boundaries_change_focus_identity_even_outside_window(source):
    brief, _, page = service_source(source)
    before = semantic.semantic_focus_signature(brief, page)
    page.metadata['document_headings'].append((2, 'Absent footer'))
    assert semantic.semantic_focus_signature(brief, page) != before


def test_unique_missing_bullet_is_restored_as_exact_full_original_line(source):
    quote = 'The Compute Paid plan has a minimum account charge of $13 USD per month.'
    body = 'Pricing\n- ' + quote
    brief, candidate, page = source(body, questions=('What minimum account billing charge applies?',),
                                    headings=[(1, 'Pricing')])
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]})
    assert [item.text for item in result.quotes] == ['- ' + quote]
    assert all(item.status == 'accepted' for item in admit_evidence_items(
        [result], brief=brief, captured_pages=[page], candidates=[candidate]))


def test_substantive_missing_prefix_is_not_restored(source):
    quote = 'The Compute Paid plan has a minimum account charge of $13 USD per month.'
    brief, _, page = source('Only verified subscribers: ' + quote,
                            questions=('What minimum account billing charge applies?',))
    assert not semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]}).fields
