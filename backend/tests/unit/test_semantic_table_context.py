"""Original table rows retain only their own verified source table context."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_question_semantic_focus as source_fixtures
from test_writer_question_delivery import service_for

from packages.agents.writer.atomic_question_projection import complete_support_text
from packages.agents.writer.question_atomic_delivery import atomic_question_context
from packages.agents.writer.readable_support import dispatched_support_choices
from packages.research.evidence import admit_evidence_items
from packages.research.evidence.admission import raw_sources_from_research_result
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.extraction import semantic
from packages.research.models import (
    CapturedPage,
    ResearchBrief,
    ResearchQuestion,
    ResearchResult,
    SourceCandidate,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, DecisionBrief

HEADER = '| Principal | Document capability |'
SEPARATOR = '|:---|---:|'
ROW = '| Auditors | Can edit shared documents after sign-in. |'
NOTE = '* Only invited users can edit shared documents.'
source = source_fixtures.source


@pytest.mark.parametrize('tail', ['', '# Other section', '```', NOTE])
def test_mixed_original_table_candidate_is_incomplete_instead_of_crashing(tail):
    mixed = '\n'.join([HEADER, SEPARATOR, tail, ROW])
    assert not complete_support_text(mixed, SimpleNamespace(qualifiers={}))


async def project_original(brief, candidate, page, quote, *, version=None):
    extraction = semantic.semantic_extraction(
        brief, page, {'facts': [{'quote': quote}]}, extractor_version=version,
    )
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate],
    )
    assert items and all(item.status == 'accepted' for item in items)
    normalized = normalized_fields_from_evidence_items(items)
    research = ResearchResult(
        brief=brief, candidates=[candidate], captured_pages=[page], extractions=[extraction],
        evidence_items=items, normalized_fields=normalized,
    )
    sources = raw_sources_from_research_result(
        brief, research, batch_sources=[], target_source_count=1,
        requires_accepted_evidence=True, source_exists=lambda *_: False,
        confidence_for_source=lambda *_: .8, fallback_snippet=lambda capture: capture.text,
    )
    assert len(sources) == 1
    now = datetime.now()
    detail = RunDetail(
        id=brief.run_id, topic=brief.topic, status='running', execution_mode='real',
        created_at=now, updated_at=now, raw_sources=sources,
        plan=AnalysisPlan(topic=brief.topic, competitors=[brief.competitor], dimensions=['feature'],
                          decision_brief=DecisionBrief(decision_question=brief.questions[0].question)),
    )
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    facts = [fact for fact in snapshot.facts if fact.field == 'evidence_terms']
    assert len(facts) == 1 and facts[0].quote == quote
    service, record = service_for(detail)
    _, _, packets = await service._begin_question_evidence_use(
        record, agent='writer', competitor=brief.competitor, dimension='feature',
    )
    view, use, packets = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    payload = atomic_question_context(
        service, record, view, packets, packets[0]['questions'][0],
        {fact.id for fact in facts}, use, generation_projection_version=3,
    )
    choices = dispatched_support_choices(payload, facts, {fact.id for fact in facts})
    return extraction, facts[0], payload, choices


@pytest.mark.asyncio
async def test_frozen_role_row_reaches_actual_writer_support_choices():
    fixture_path = Path(__file__).parent / 'fixtures/semantic_role_table_capture.json'
    fixture = json.loads(fixture_path.read_text())
    capture = fixture['capture']
    candidate = SourceCandidate.model_validate(capture['candidate'])
    page = CapturedPage.model_validate(capture['page'])
    assert hashlib.sha256(page.text.encode()).hexdigest() == capture['body_sha256']
    question = fixture['question']
    brief = ResearchBrief(
        run_id='frozen-table-source', topic='Cloudflare 的功能、权限及计费条件研究',
        competitor=candidate.competitor, dimension='feature', product_category='产品',
        questions=[ResearchQuestion(question_id=question['id'], question=question['question'])],
    )
    original_row = next(line.strip() for line in page.text.splitlines()
                        if line.startswith('| Cache Domain Purge |'))
    legacy_version = 'question-focus-v2:' + semantic.semantic_focus_signature(brief, page)
    legacy, old_fact, old_payload, old_choices = await project_original(
        brief, candidate, page, original_row, version=legacy_version,
    )
    assert original_row == old_payload['evidence_view']['facts'][0]['quote']
    assert original_row not in [choice.get('quote') for choice in old_choices.values()]
    extraction, fact, payload, choices = await project_original(
        brief, candidate, page, original_row,
    )
    assert original_row in [choice['quote'] for choice in choices.values() if 'quote' in choice]
    expected = ['| Role | Description | ', '|---|---|']
    assert fact.qualifiers['table_context'] == expected
    assert payload['evidence_view']['facts'][0]['qualifiers']['table_context'] == expected
    assert extraction.quotes == legacy.quotes
    assert list(extraction.fields) == list(legacy.fields)
    current_value = next(iter(extraction.fields.values()))
    old_value = next(iter(legacy.fields.values()))
    assert current_value['conditions'] == old_value['conditions']
    assert fact.quote == old_fact.quote
    assert fact.source_id == old_fact.source_id
    assert extraction.extractor_version.startswith('question-focus-v3:')
    assert legacy.extractor_version == legacy_version


@pytest.mark.asyncio
async def test_generic_original_table_keeps_header_separator_and_adjacent_notes(source):
    body = '\n'.join([
        HEADER, SEPARATOR, ROW, NOTE, '', '* Unrelated: only owners can delete pages.',
    ])
    brief, candidate, page = source(body, questions=('What can Auditors do to documents?',))
    extraction, fact, _, choices = await project_original(brief, candidate, page, ROW)
    assert fact.qualifiers['table_context'] == [HEADER, SEPARATOR, NOTE]
    assert ROW in [choice.get('quote') for choice in choices.values()]
    value = next(iter(extraction.fields.values()))
    assert NOTE in value['conditions']
    assert '* Unrelated: only owners can delete pages.' not in fact.qualifiers['table_context']


@pytest.mark.asyncio
async def test_generic_table_keeps_preceding_shared_condition_in_actual_writer_payload(source):
    body = '\n'.join([
        NOTE,
        'Permissions are described in the table below.',
        'Review each principal separately.',
        'The table lists document capabilities.',
        HEADER, SEPARATOR, ROW,
    ])
    brief, candidate, page = source(body, questions=('What can Auditors do to documents?',))
    legacy = semantic.semantic_extraction(
        brief, page, {'facts': [{'quote': ROW}]},
        extractor_version='question-focus-v2:' + semantic.semantic_focus_signature(brief, page),
    )
    old_value = next(iter(legacy.fields.values()))
    assert NOTE in old_value['conditions']
    assert NOTE in old_value['evidence_terms']
    extraction, fact, payload, choices = await project_original(brief, candidate, page, ROW)
    value = next(iter(extraction.fields.values()))
    assert value['conditions'] == old_value['conditions']
    assert NOTE in value['evidence_terms']
    assert NOTE in fact.value
    sent = payload['evidence_view']['facts'][0]
    assert NOTE in sent['value']
    assert sent['qualifiers']['table_context'] == [HEADER, SEPARATOR]
    assert ROW in [choice.get('quote') for choice in choices.values()]
    assert extraction.quotes == legacy.quotes


def test_generic_table_keeps_every_adjacent_original_note(source):
    notes = [f'* Supporting detail {index} for shared documents.' for index in range(6)]
    brief, _, page = source('\n'.join([HEADER, SEPARATOR, ROW, *notes]))
    extraction = semantic.semantic_extraction(brief, page, {'facts': [{'quote': ROW}]})
    assert next(iter(extraction.fields.values()))['table_context'] == [HEADER, SEPARATOR, *notes]


def test_generic_table_context_over_budget_rejects_whole_fact_without_truncating(source):
    notes = [f'* Supporting detail {index}: ' + 'Document detail. ' * 10 for index in range(30)]
    brief, _, page = source('\n'.join([HEADER, SEPARATOR, ROW, *notes]))
    extraction = semantic.semantic_extraction(brief, page, {'facts': [{'quote': ROW}]})
    assert not extraction.fields
    assert 'source_condition_context_budget_exceeded' in extraction.metadata[
        'source_condition_gaps'
    ]


@pytest.mark.parametrize('body,selected', [
    (ROW, ROW),
    ('\n'.join([HEADER, '|--|---|', ROW]), ROW),
    ('\n'.join([HEADER, '|---|---|---|', ROW]), ROW),
    ('\n'.join([HEADER, SEPARATOR, '| Other | Can edit | Extra |', ROW]), ROW),
    ('\n'.join([HEADER, SEPARATOR, ROW, '| Other | Can edit | Extra |']), ROW),
    ('\n'.join([HEADER, SEPARATOR, '', ROW]), ROW),
    ('\n'.join([HEADER, SEPARATOR, '# Other section', ROW]), ROW),
    ('\n'.join(['```markdown', HEADER, SEPARATOR, ROW, '```']), ROW),
    ('\n'.join([HEADER, SEPARATOR, ROW, '| Another | Header |', '|---|---|',
                '| Member | Can read documents. |']), ROW),
    ('\n'.join([HEADER, SEPARATOR, ROW, '', HEADER, SEPARATOR, ROW]), ROW),
    ('\n'.join([HEADER, SEPARATOR, ROW]), 'Can edit shared documents after sign-in.'),
])
@pytest.mark.asyncio
async def test_invalid_or_ambiguous_table_context_cannot_offer_selected_row(source, body, selected):
    brief, candidate, page = source(body, questions=('What can Auditors do to documents?',))
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': selected}]})
    assert all(not value.get('table_context') for value in result.fields.values())
    if result.fields and selected.startswith('|'):
        _, _, _, choices = await project_original(brief, candidate, page, selected)
        assert selected not in [choice.get('quote') for choice in choices.values()]


@pytest.mark.parametrize('version', ['question-focus-v1', 'question-focus-v2'])
@pytest.mark.asyncio
async def test_explicit_older_mapping_keeps_its_original_generic_table_behavior(source, version):
    brief, candidate, page = source('\n'.join([HEADER, SEPARATOR, ROW]),
                                    questions=('What can Auditors do to documents?',))
    exact_version = version + ':' + semantic.semantic_focus_signature(brief, page)
    result, fact, _, choices = await project_original(
        brief, candidate, page, ROW, version=exact_version,
    )
    assert result.extractor_version == exact_version
    assert 'table_context' not in fact.qualifiers
    assert ROW not in [choice.get('quote') for choice in choices.values()]


def test_role_column_mapping_keeps_its_original_fields_and_operations(source):
    header = '| Operation | Guests | Members |'
    row = '| Edit shared documents | No | Yes |'
    brief, _, page = source('\n'.join([header, '|---|---|---|', row, NOTE]))
    payload = {'facts': [{'quote': row}]}
    current = semantic.semantic_extraction(brief, page, payload)
    assert next(iter(current.fields.values()))['table_context'] == [header, NOTE]
    for version in ['question-focus-v1', 'question-focus-v2']:
        old = semantic.semantic_extraction(
            brief, page, payload,
            extractor_version=version + ':' + semantic.semantic_focus_signature(brief, page),
        )
        assert current.fields == old.fields
        assert current.quotes == old.quotes


def test_explicit_v2_mapping_keeps_display_quote_recovery():
    from test_collector_quote_mapping import QUOTES, trello_source

    brief, _, page = trello_source()
    version = 'question-focus-v2:' + semantic.semantic_focus_signature(brief, page)
    result = semantic.semantic_extraction(
        brief, page, {'facts': [{'quote': QUOTES[0]}]}, extractor_version=version,
    )
    assert result.extractor_version == version
    assert result.quotes and result.quotes[0].text != QUOTES[0]
    assert result.quotes[0].text in page.text
