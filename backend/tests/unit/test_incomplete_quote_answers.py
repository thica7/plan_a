"""Recognize exact quote intent before asking for missing scope or usage inputs."""

from datetime import timedelta

import pytest
from test_missing_price_answers import AS_OF, answer, price_case
from test_question_retrieval import replace_snapshot

from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json


def test_currency_is_not_assumed_to_establish_the_quote_market():
    detail, snapshot, _ = price_case(money=False)
    row = answer(detail, snapshot,
                 'Example Product Pro 套餐含税人民币月费准确是多少？')['q-price']
    assert row['resolution'] == 'insufficient' and row['conclusion'] == 'unknown'
    assert 'market' in row['missing_fields']
    assert 'currency' not in row['missing_fields']
    assert '确认' in row['answer'] and '市场' in row['answer']
    assert row['basis_snapshot_id'] == snapshot.id
    assert row['claim_ids'] == row['evidence_spans'] == ()


def test_unknown_total_quote_scope_still_receives_concrete_clarification():
    detail, snapshot, _ = price_case(money=False)
    question = ('Example Product：我们有 240 名员工，准备购买整个安全平台一年。'
                '请仅凭公开定价页给出精确的人民币含税总价。')
    row = answer(detail, snapshot, question)['q-price']
    assert row['status'] == 'partial' and row['resolution'] == 'insufficient'
    assert {'market', 'plan', 'billing_interval'} <= set(row['missing_fields'])
    assert '240' not in row['answer']  # A requirement never becomes an observed price input.
    assert '12个月' in row['answer']
    assert '确认' in row['answer'] and '当前报价' in row['answer']
    assert row['basis_snapshot_id'] == snapshot.id


def usage_case():
    detail, snapshot, _ = price_case(money=False)
    quote = ('The Usage plan has a minimum charge of $13 USD per account per month. '
             'Your bill also depends on request count and CPU time.')
    fact = EvidenceFact(
        id='original-billing-rule', semantic_id='original-billing-rule',
        source_id=snapshot.sources[0].id, competitor='Example Product', dimension='pricing',
        field='evidence_terms', value_json=canonical_json([quote]), quote=quote,
        status='supported', confidence=.9,
    )
    return detail, replace_snapshot(detail, snapshot, facts=(fact,))


def rule_case(quote):
    detail, snapshot = usage_case()
    fact = snapshot.facts[0].model_copy(update={
        'quote': quote, 'value_json': canonical_json([quote]),
    })
    return detail, replace_snapshot(detail, snapshot, facts=(fact,))


@pytest.mark.parametrize('quote', [
    'CPU time is not billed and never affects your bill.',
    'CPU time is free and not part of billing.',
    'The Enterprise plan bill depends on CPU time. The Free plan has no CPU fees.',
])
def test_cpu_input_requires_an_applicable_affirmative_billing_dependency(quote):
    detail, snapshot = rule_case(quote)
    row = answer(detail, snapshot,
                 'Example Product Free plan 本月有2300万次请求，账单准确是多少美元？')['q-price']
    assert 'cpu_usage' not in row['missing_fields'] and 'CPU' not in row['answer']
    assert 'usage_inputs' in row['missing_fields']


@pytest.mark.parametrize('cpu', [
    'CPU 每次执行限制为50毫秒',
    'CPU 尚不知道总用量，单次测试约7毫秒',
    'CPU total limit is 50 milliseconds per execution',
])
def test_per_execution_cpu_or_a_limit_does_not_supply_total_cpu_usage(cpu):
    detail, snapshot = usage_case()
    row = answer(detail, snapshot,
                 f'Example Product Usage plan 本月有2300万次请求，{cpu}。账单准确是多少美元？')['q-price']
    assert 'cpu_usage' in row['missing_fields'] and 'CPU' in row['answer']


def test_request_count_does_not_determine_the_complete_bill():
    detail, snapshot = usage_case()
    row = answer(detail, snapshot,
                 'Example Product：Usage plan 本月有 2300 万次动态请求。账单准确是多少美元？')['q-price']
    assert row['resolution'] == 'insufficient' and row['conclusion'] == 'unknown'
    assert 'CPU' in row['answer'] and 'cpu_usage' in row['missing_fields']
    assert '2300' not in row['answer'] and '$13' not in row['answer']
    assert row['basis_snapshot_id'] == snapshot.id
    assert row['claim_ids'] == row['evidence_spans'] == ()


def test_cpu_requirement_is_not_invented_when_the_admitted_sources_have_no_cpu_rule():
    detail, snapshot, _ = price_case(money=False)
    row = answer(detail, snapshot,
                 'Example Product：本月有 2300 万次请求。账单准确是多少美元？')['q-price']
    assert row['resolution'] == 'insufficient'
    assert 'CPU' not in row['answer'] and 'cpu_usage' not in row['missing_fields']
    assert 'usage_inputs' in row['missing_fields']


@pytest.mark.parametrize('change', [
    {'role': 'historical_report'},
    {'status': 'inactive'},
    {'last_verified_at': AS_OF - timedelta(days=40)},
    {'last_verified_at': AS_OF + timedelta(days=1)},
])
def test_unqualified_source_cannot_supply_an_extra_cpu_requirement(change):
    detail, snapshot = usage_case()
    snapshot = replace_snapshot(detail, snapshot, sources=(snapshot.sources[0].model_copy(update=change),))
    row = answer(detail, snapshot,
                 'Example Product：本月有 2300 万次请求。账单准确是多少美元？')['q-price']
    assert 'CPU' not in row['answer'] and 'cpu_usage' not in row['missing_fields']


def test_explicit_cpu_total_is_not_reported_as_an_absent_request_input():
    detail, snapshot = usage_case()
    row = answer(detail, snapshot,
                 'Example Product：Usage plan 本月有 2300 万次请求，'
                 'CPU 总用量为 900000 毫秒。账单准确是多少美元？')['q-price']
    assert row['resolution'] == 'insufficient' and 'cpu_usage' not in row['missing_fields']
    assert '900000' not in row['answer'] and '2300' not in row['answer']


@pytest.mark.parametrize('question', [
    'Example Product 当前价格是多少？', 'Example Product 当前价格准确是多少？',
])
def test_incomplete_request_does_not_borrow_market_currency_or_plan_from_a_price(question):
    detail, snapshot, _ = price_case()
    row = answer(detail, snapshot, question)['q-price']
    assert {'market', 'currency', 'plan', 'billing_interval'} <= set(row['missing_fields'])
    assert '99' not in row['answer'] and 'CN、Pro' not in row['answer']


@pytest.mark.parametrize('question', [
    'Example Product 的套餐如何计费？',
    'Example Product 按月和按年计费有什么区别？',
    'Example Product: How does billing work?',
    'Example Product 能否准确显示账单？',
    'Example Product 支持多少种账单导出格式？',
    'Example Product 多少角色可以查看账单？',
    'Example Product 的账单最多可保留多少天？',
    'Example Product: How much storage is needed to export a bill?',
    'Example Product: What is the bill retention period?',
    'Example Product: What is the invoice export permission?',
    'Example Product: How much is the storage limit for bill exports?',
    'Example Product: What is the permission to view the pricing page?',
    'Example Product: What exact permissions are needed to view pricing pages?',
    'Example Product：截至2026-02-30，价格准确是多少？',
    'Example Product：截至2026-01-01及截至2026-01-02，价格准确是多少？',
])
def test_mechanism_and_invalid_or_conflicting_dates_do_not_generate_an_automatic_quote(question):
    detail, snapshot, _ = price_case(money=False)
    assert answer(detail, snapshot, question) == {}
