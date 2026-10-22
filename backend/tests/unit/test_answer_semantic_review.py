"""The final answer selection is checked independently of its first proposal."""
import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.dimension_writer import DimensionWriterMixin
from packages.research.evidence.report_claims import ReportClaim

QUESTION = {"question_id": "q", "question": "Can three people use the Basic workspace?"}


def selected(*, conclusion="yes", status="answered", ids=None, resolution="direct", version=2):
    return json.dumps({"version": version, "answers": [{
        "question_id": "q", "status": status, "claim_ids": ["limit"] if ids is None else ids,
        "resolution": resolution, "conclusion": conclusion, "missing_fields": [],
        "reason": "Check the published limit against the requested group.",
    }]})


class Reviewer(DimensionWriterMixin):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def _evidence_live_record(self, record):
        return record

    def _current_evidence_snapshot(self, record):
        return object()

    async def _dimension_call_with_gaps(self, record, gaps, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        return response, gaps

    def _validate_evidence_use(self, record, use):
        pass

    def _validate_dimension_upstream(self, record, compact):
        pass


async def check(monkeypatch, responses, *, facts=(), compact=None):
    monkeypatch.setattr(
        "packages.agents.writer.price_answers.server_missing_price_answers", lambda *args: {}
    )
    responses = [json.dumps(dict(json.loads(value), version=3)) if isinstance(value, str) and value.startswith('{')
                 else value for value in responses]
    if len(responses) > 1 and isinstance(responses[1], str) and responses[1].startswith('{'):
        response = json.loads(responses[1])
        for row in response['answers']:
            row['subquestions'] = [dict(question_quote=QUESTION['question'], claim_ids=row['claim_ids'],
                conclusion=row['conclusion'], relation='upper_bound' if row['conclusion'] == 'no' else 'direct')]
        responses[1] = json.dumps(response)
    reviewer = Reviewer(responses)
    claim = ReportClaim(id="limit", text="Only two people can use a Basic workspace.",
                        competitor="Example", dimension="feature", kind="fact",
                        fact_ids=("f1",), source_ids=("s1",))
    record = SimpleNamespace(detail=SimpleNamespace(output_language="en"))
    view = SimpleNamespace(competitor="Example", dimension="feature", facts=facts)
    result = await reviewer._dimension_question_coverage(
        record, [QUESTION], compact or {}, [SimpleNamespace(claim=claim, status="supported")],
        view, SimpleNamespace(max_bytes=12000), (),
    )
    return reviewer, result


@pytest.mark.asyncio
async def test_second_review_sees_sent_but_unpublished_exception_without_publishing_it(monkeypatch):
    from packages.research.evidence.snapshot_models import EvidenceFact

    quotes = [
        'Only two people can use a Basic workspace.',
        'If you allow members to keep a copy, they can retain downloaded files after removal.',
        'An unrelated capability has different limits.',
    ]
    facts = tuple(EvidenceFact(
        id=f'f{index}', semantic_id=f'rule-{index}', source_id=f's{index}',
        competitor='Example', dimension='feature', field='evidence_terms',
        value_json=json.dumps([quote]), quote=quote, status='supported', confidence=.9,
    ) for index, quote in enumerate(quotes, 1))
    reviewer, (answers, _, _) = await check(
        monkeypatch, [selected(), selected(status='partial', conclusion='depends',
                                        resolution='conditional')],
        facts=facts, compact={'evidence_view': {'facts': [{'id': 'f1'}, {'id': 'f2'}]}},
    )
    payloads = [json.loads(call['user'].split('\nJSON:\n')[1]) for call in reviewer.calls]
    assert 'facts' not in payloads[0]
    assert {fact['fact_id'] for fact in payloads[1]['published_supports']} == {'f1'}
    assert payloads[1]['restrictive_source_context'][0]['source_exceptions'][0]['quote'] == quotes[1]
    assert [claim['id'] for claim in payloads[1]['claims']] == ['limit']
    assert answers[0].claim_ids == ('limit',) and quotes[1] not in answers[0].answer


@pytest.mark.asyncio
async def test_reviewer_corrects_a_proposed_yes_using_only_published_limits(monkeypatch):
    reviewer, (answers, _, sizes) = await check(
        monkeypatch, [selected(conclusion="yes"), selected(conclusion="no")]
    )
    assert [call['name'] for call in reviewer.calls] == [
        'dimension_answer_coverage', 'dimension_answer_review',
    ]
    assert answers[0].conclusion == 'no' and answers[0].status == 'answered'
    assert answers[0].answer == 'Only two people can use a Basic workspace.'
    assert len(sizes) == 2
    second = json.loads(reviewer.calls[1]['user'].split('\nJSON:\n')[1])
    assert second['proposed_answers'][0]['conclusion'] == 'yes'
    assert second['claims'][0]['text'] == answers[0].answer
    assert second['proposed_answers'][0]['proposed_reason'] == 'Check the published limit against the requested group.'


@pytest.mark.asyncio
@pytest.mark.parametrize('second', [None, 'not JSON', selected(ids=['not-published'])])
async def test_failed_second_review_cannot_keep_the_first_answered_proposal(monkeypatch, second):
    reviewer, (answers, gaps, _) = await check(monkeypatch, [selected(), second])
    assert len(reviewer.calls) == 2
    assert answers[0].status == 'unverified' and not answers[0].claim_ids
    assert 'answer_coverage_incomplete' in gaps


@pytest.mark.asyncio
async def test_second_review_can_reject_incomplete_clarification_without_hiding_known_claims(monkeypatch):
    _, (answers, _, _) = await check(monkeypatch, [selected(), selected(
        status='partial', resolution='conditional', conclusion='depends',
    )])
    assert answers[0].status == 'partial'
    assert answers[0].conclusion == 'depends'
    assert answers[0].claim_ids == ('limit',)


@pytest.mark.parametrize('conclusion,label', [
    ('yes', '结论：是'), ('no', '结论：否'), ('depends', '结论：需按条件判断'),
])
def test_report_renders_the_reviewed_decision_beside_its_complete_claim(conclusion, label):
    from test_stage_evidence_views import distributed_detail
    from packages.agents.writer.answer_coverage import parse_answer_coverage
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import AuditedReportClaim, ReportDimensionAudit

    detail = distributed_detail(observations=1)
    detail.plan.dimensions = ['feature']
    product = detail.plan.competitors[0]
    claim = ReportClaim(id='limit', text='Only two people can use a Basic workspace.',
                        competitor=product, dimension='feature', kind='fact',
                        fact_ids=('f1',), source_ids=(detail.raw_sources[0].id,))
    answers = parse_answer_coverage(
        selected(conclusion=conclusion), [QUESTION], {'limit'},
        claims=[claim.model_dump(mode='json')], require_v2=True,
    )
    audit = ReportDimensionAudit(
        competitor=product, dimension='feature', consumption_id='use',
        claims=(AuditedReportClaim(claim=claim, status='supported'),),
        answer_coverage=answers, answer_binding_version=2,
    )
    report = render_dimension_report(detail, [audit])
    assert label in report and claim.text in report
    assert answers[0].evidence_spans[0].quote == claim.text


@pytest.mark.parametrize('text', [
    'Basic workspace has a maximum of 2 people.',
    'Basic workspace includes up to 2 people.',
    'Basic 工作区最多包含2名成员。',
    'Basic 工作区的上限为两名成员。',
])
def test_complete_numeric_caps_can_support_a_reviewed_negative_decision(text):
    from packages.agents.writer.answer_coverage import parse_answer_coverage, coverage_resolution_reasons
    claims = [{'id': 'limit', 'text': text}]
    result = parse_answer_coverage(selected(conclusion='no'), [QUESTION], {'limit'},
                                   claims=claims, require_v2=True)[0]
    assert result.status == 'answered'
    assert result.answer == text and result.conclusion == 'no'
    assert not coverage_resolution_reasons(result, claims, require_v2=True)


@pytest.mark.parametrize('text', [
    'Example: Basic workspace has a maximum of 2 people.',
    'We recommend Basic workspace has a maximum of 2 people.',
    'Basic workspace has a maximum of 2.',
    '建议 Basic 工作区最多包含2名成员。',
    '“Basic workspace has a maximum of 2 people.”',
])
def test_suggested_quoted_and_incomplete_caps_do_not_supply_a_new_assertion(text):
    from packages.agents.writer.answer_coverage import parse_answer_coverage
    result = parse_answer_coverage(selected(conclusion='no'), [QUESTION], {'limit'},
                                   claims=[{'id': 'limit', 'text': text}], require_v2=True)[0]
    assert result.status == 'unverified'
