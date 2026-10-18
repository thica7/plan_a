"""Billing signals and complete table context use only source text and offsets."""

import importlib

import pytest


def api():
    try:
        return importlib.import_module('packages.research.extraction.billing_rules')
    except ModuleNotFoundError:
        pytest.fail('Shared source-bound billing rules are missing.')


@pytest.mark.parametrize('quote', [
    'The Usage plan has a minimum account charge of $13 USD per month.',
    'CPU time is only billed when the function runs.',
    'Requests to static assets are free and unlimited.',
    'Your bill depends on request count and CPU time.',
    'Enterprise pricing is tailored to your needs. Contact sales for a quote.',
    '| Usage | 12 million included per month +$0.42 per additional million | '
    '20 million CPU milliseconds included per month +$0.03 per additional million CPU milliseconds |',
])
def test_actual_billing_rule_is_a_shared_quality_signal(quote):
    assert api().billing_rule_text_signal(quote)


@pytest.mark.parametrize('quote', [
    '$13',
    'Users can paste $13 into a comment.',
    'The price button opens the settings page.',
    'CPU time is measured in milliseconds.',
    'Members may quote the feature guide.',
])
def test_currency_or_feature_terms_alone_do_not_establish_a_billing_rule(quote):
    assert not api().billing_rule_text_signal(quote)


@pytest.mark.parametrize('question,expected', [
    ('本月账单准确是多少美元？', True),
    ('请给出精确人民币含税总价。', True),
    ('How does billing work?', True),
    ('Can guests edit a page?', False),
    ('Can members quote a feature guide?', False),
    ('Can guests edit the pricing page?', False),
    ('What exact permissions do editors have on billing pages?', False),
    ('Can guests edit the pricing page, and how much is the monthly fee?', True),
])
def test_question_scope_is_distinct_from_source_support(question, expected):
    assert api().is_billing_question(question) is expected


def source_table():
    header = '| Plan | Requests1, 2 | CPU time* |'
    row = '| Usage | 12 million included +$0.42 per million | 20 million CPU milliseconds included +$0.03 per million |'
    notes = [
        '1 Only inbound requests are billed.',
        '2 An upgrade connection is charged as a request,\nrepresenting the initial connection.\nMessages do not count as requests.',
        '* CPU time is only billed when the function runs.',
    ]
    body = 'Billing\n' + header + '\n|---|---|---|\n' + row + '\n' + '\n'.join(notes) + '\n\nOther service\n9 Storage requests have a different rate.'
    return body, header, row, notes


def test_numbered_star_and_wrapped_footnotes_stay_with_the_complete_original_header():
    body, header, row, notes = source_table()
    start = body.index(row)
    context = api().billing_table_context(body, start, start + len(row), (0, len(body)))
    assert context == [header, *notes]
    assert all(text in body for text in context)
    assert 'Storage' not in '\n'.join(context)


@pytest.mark.parametrize('change', ['partial_row', 'missing_note', 'wrong_columns', 'outside_scope'])
def test_incomplete_or_foreign_table_context_is_not_repaired_by_guessing(change):
    body, _, row, _ = source_table()
    if change == 'missing_note':
        body = body.replace('1 Only inbound requests are billed.\n', '')
    if change == 'wrong_columns':
        body = body.replace('|---|---|---|', '|---|---|')
    start = body.index(row)
    end = start + len(row) - (5 if change == 'partial_row' else 0)
    bounds = (start, len(body)) if change == 'outside_scope' else (0, len(body))
    assert api().billing_table_context(body, start, end, bounds) == []


def test_selected_rate_cells_bind_their_own_footnotes_not_only_header_markers():
    header = '| Plan | Requests | CPU time |'
    row = '| Usage | $0.42 per million* | $0.03 per million CPU milliseconds† |'
    notes = ['* Only inbound requests are billed.',
             '† CPU time is only billed when the function runs.\nIdle waiting time is excluded.']
    body = header + '\n|---|---|---|\n' + row + '\n' + '\n'.join(notes)
    start = body.index(row)
    assert api().billing_table_context(body, start, start + len(row)) == [header, *notes]


@pytest.mark.parametrize('marker', ['[1]', '(1)', '¹', '<sup>1</sup>', '{1}', '[^1]'])
def test_unimplemented_note_markers_do_not_silently_lose_restrictions(marker):
    header = '| Plan | Requests | CPU time |'
    row = f'| Usage | $0.42 per million{marker} | $0.03 per million CPU milliseconds |'
    body = header + '\n|---|---|---|\n' + row + '\n1 Only inbound requests are billed.'
    start = body.index(row)
    assert api().billing_table_context(body, start, start + len(row)) == []


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'foreign_note', 'malformed_preceding_row'])
def test_rate_cell_note_integrity_and_all_table_columns_are_replayed(change):
    header = '| Plan | Requests | CPU time |'
    row = '| Usage | $0.42 per million* | $0.03 per million CPU milliseconds |'
    note = '* Only inbound requests are billed.'
    prior = '| Starter | Free requests | Free CPU time |\n'
    if change == 'malformed_preceding_row':
        prior = '| Starter | Free requests |\n'
    body = header + '\n|---|---|---|\n' + prior + row + '\n'
    if change != 'missing':
        body += note + ('\n' + note if change == 'duplicate' else '')
    if change == 'foreign_note':
        body += '\n† Storage requires a separate subscription.'
    start = body.index(row)
    assert api().billing_table_context(body, start, start + len(row)) == []


@pytest.mark.parametrize('header,row', [
    ('| Plan | Requests | CPU seconds |', '| Usage | $0.42 per million requests | $0.03 per million CPU milliseconds |'),
    ('| Plan | Requests | CPU milliseconds |', '| Usage | $0.42 per million requests | $0.03 per million CPU seconds |'),
    ('| Plan | Requests | CPU time |', '| Usage | $0.42 per million CPU milliseconds | $0.03 per million CPU milliseconds |'),
    ('| Plan | Requests | CPU time |', '| Usage | $0.42 per million requests | $0.03 per million requests |'),
    ('| Plan | Requests | CPU seconds |', '| Usage | $0.42 per million requests | $0.03 per million milliseconds |'),
])
def test_explicit_measured_unit_conflicts_do_not_create_a_rate_binding(header, row):
    body = header + '\n|---|---|---|\n' + row
    start = body.index(row)
    assert api().billing_table_context(body, start, start + len(row)) == []


def test_free_cpu_limit_per_request_remains_a_cpu_duration_column():
    header = '| Plan | Requests | CPU time |'
    row = '| Free | 90,000/day | 12 ms/request |'
    body = header + '\n|---|---|---|\n' + row
    start = body.index(row)
    assert api().billing_table_context(body, start, start + len(row)) == [header]


def test_header_note_marker_does_not_hide_an_explicit_rate_unit_conflict():
    header = '| Plan | Requests1 | CPU time |'
    row = '| Usage | $0.42 per million CPU milliseconds | $0.03 per million CPU milliseconds |'
    body = header + '\n|---|---|---|\n' + row + '\n1 Only inbound requests are billed.'
    start = body.index(row)
    assert api().billing_table_context(body, start, start + len(row)) == []
