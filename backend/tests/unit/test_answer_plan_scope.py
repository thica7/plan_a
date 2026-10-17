"""A named inclusion is not proof of an exhaustive plan or required upgrade."""

import pytest

from packages.agents.writer.answer_coverage import coverage_resolution_reasons
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage


def check(body, text):
    record = ReportAnswerCoverage(question_id='q', question='Can Basic use Answer Panel?',
        status='answered', answer=body, resolution='direct', conclusion='no',
        claim_ids=('c',), evidence_spans=({'claim_id': 'c', 'quote': text},), reason='Reviewed.')
    return coverage_resolution_reasons(record, [{'id': 'c', 'text': text}])


@pytest.mark.parametrize('body', [
    'No. Only the Summit plan includes Answer Panel.',
    '不能。Answer Panel 仅包含在 Summit 套餐中。',
    '不能，需要升级到 Summit 套餐。',
])
def test_inclusion_does_not_establish_exclusivity_or_a_required_upgrade(body):
    reasons = check(body, 'Answer Panel is included in the Summit plan.')
    assert 'answer_plan_exclusivity_unverified' in reasons


def test_explicit_exclusive_plan_can_support_the_same_named_plan_in_another_language():
    assert not check('不能。Answer Panel 仅在 Summit 套餐中提供。',
                     'Answer Panel is only available on the Summit plan.')


def test_another_exclusive_plan_cannot_be_borrowed():
    assert 'answer_plan_exclusivity_unverified' in check(
        'Only the Summit plan includes Answer Panel.',
        'Answer Panel is only available on the Launch plan.')


def test_a_direct_no_does_not_require_an_upgrade_recommendation():
    assert not check('No. Basic does not include Answer Panel.',
                     'Basic does not include Answer Panel; Summit includes it.')


@pytest.mark.parametrize('text', [
    'You do not need to upgrade to the Summit plan.',
    '不需要升级到 Summit 套餐。',
    'Answer Panel is not only available on the Summit plan.',
])
def test_negated_plan_operator_cannot_ground_a_new_exclusive_plan(text):
    assert 'answer_plan_exclusivity_unverified' in check(
        'Answer Panel 仅在 Summit 套餐中提供。', text)


@pytest.mark.parametrize('body', ['不能，仅 Summit 可用，必须升级 Summit。', '只有 Summit 版可用。'])
def test_bare_or_edition_plan_name_cannot_bypass_exclusivity_check(body):
    assert 'answer_plan_exclusivity_unverified' in check(
        body, 'Answer Panel is included in the Summit plan.')


def test_an_exclusive_plan_set_cannot_be_narrowed():
    assert 'answer_plan_exclusivity_unverified' in check(
        'Only the Summit plan includes Answer Panel.',
        'Answer Panel is only available on the Summit and Launch plans.')


def test_paid_plan_family_is_not_dropped_from_an_exclusive_set():
    assert 'answer_plan_exclusivity_unverified' in check(
        'Only the Education plan includes Answer Panel.',
        'Answer Panel is only available on paid and Education plans.')
