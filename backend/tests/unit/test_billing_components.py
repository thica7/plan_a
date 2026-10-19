"""Anonymous source components; supported transport labels are not semantic proof."""

import hashlib
from types import SimpleNamespace

import pytest
from test_credit_allowance_boundaries import allowance_case

from packages.orchestrator.answer_context import audit_answer_boundaries
from packages.research.evidence.report_claims import (
    AuditedReportClaim, ReportClaim, ReportDimensionAudit,
)
from packages.research.evidence.snapshot_models import (
    EvidenceArtifactDependency, EvidenceConsumption,
)
from packages.research.evidence.source_spans import ReportSourceSpanBinding, source_span_candidates

RATE = 'Plus plan requests cost $0.47 per million requests per month.'
CPU = 'Plus plan CPU time costs $0.06 per million CPU milliseconds per month.'
MINIMUM = 'Compute Paid plan has a minimum charge of $17 USD per month for an account.'
SERVICE = SimpleNamespace(_evidence_artifact_hash=lambda value: hashlib.sha256(repr(value).encode()).hexdigest())


def component_case(monkeypatch, text=RATE, *, support=RATE, source=None, bound=True):
    detail, snapshot, view, boundary = allowance_case(monkeypatch, source or support)
    use = EvidenceConsumption(id='billing-writer-use', agent='writer', snapshot_id=snapshot.id,
        snapshot_version=snapshot.version, dependency_hash=view.dependency_hash,
        competitor=view.competitor, dimension=view.dimension,
        source_ids=view.source_ids, fact_ids=view.fact_ids, max_bytes=16384,
        status='validated', created_at=detail.created_at)
    detail.evidence_consumptions = [use]
    detail.evidence_artifact_dependencies = [EvidenceArtifactDependency(
        kind='writer', consumption_ids=(use.id,), payload_hash='fixture-verified-by-caller')]
    detail.report_answer_boundaries = [boundary]
    fact = next(f for f in view.facts if f.field == 'evidence_terms')
    span = next(s for s in source_span_candidates(fact) if s['quote'] == support)
    claim = ReportClaim(id='component-claim', text=text, kind='fact', competitor=view.competitor,
        dimension=view.dimension, fact_ids=(fact.id,), source_ids=(fact.source_id,),
        source_span_bindings=(ReportSourceSpanBinding(**span),) if bound else ())
    detail.report_dimension_audits = [ReportDimensionAudit(competitor=view.competitor,
        dimension=view.dimension, consumption_id=use.id,
        claims=(AuditedReportClaim(claim=claim, status='supported'),))]
    detail.report_md = text + ' [source:' + fact.source_id + ']'
    aliases = {sid: sid for sid in view.source_ids}
    return detail, snapshot, aliases


def audit(case):
    detail, snapshot, aliases = case
    return audit_answer_boundaries(SERVICE, SimpleNamespace(detail=detail), snapshot,
                                   producer_verified=True, aliases=aliases)


@pytest.mark.parametrize(('support', 'text'), [
    (RATE, RATE), (CPU, CPU), (MINIMUM, MINIMUM),
    (RATE, 'Plus 套餐每月请求超额费率为每 100 万次请求 $0.47。'),
    (CPU, 'Plus 套餐每月 CPU 超额费率为每 100 万 CPU 毫秒 $0.06。'),
    (MINIMUM, 'Compute Paid 套餐账户每月最低费用为 $17 USD。'),
])
def test_exact_published_component_keeps_its_meaning(monkeypatch, support, text):
    assert not audit(component_case(monkeypatch, text, support=support))


@pytest.mark.parametrize('text', [
    RATE.replace('million requests', 'request'),
    RATE.replace('requests cost', 'CPU time costs').replace('million requests', 'million CPU milliseconds'),
    RATE.replace('Plus', 'Ultra'), RATE.replace('month', 'year'),
    RATE.replace('$0.47', '€0.47'),
    'Plus plan actual complete monthly bill is $0.47.',
    'Plus plan requests cost $0.47 per million requests per month including tax.',
    'Plus plan requests cost $0.47 per million requests per month in China.',
    'Plus plan CPU time costs $0.47 per million requests per month.',
    'Plus plan includes $0.47 of credits per million requests per month.',
    'Plus plan requests cost $0.47 EUR per million requests per month.',
    'Plus plan requests cost $0.47 per million requests per month, which is our final monthly bill.',
    'Plus plan requests cost $0.47 per million requests per month, which is our exact monthly total.',
])
def test_same_number_does_not_authorize_changed_rate_scope(monkeypatch, text):
    assert audit(component_case(monkeypatch, text))


@pytest.mark.parametrize('text', [
    MINIMUM.replace('month', 'year'), MINIMUM.replace('account', 'project'),
    MINIMUM.replace('Compute Paid', 'Compute Free'), MINIMUM.replace('$17 USD', 'EUR 17'),
    'Compute Paid plan actual complete monthly bill for an account is $17 USD.',
    'Compute Paid 套餐账户每月实际完整账单准确为 $17 USD。',
])
def test_minimum_never_authorizes_an_actual_total_or_another_scope(monkeypatch, text):
    assert audit(component_case(monkeypatch, text, support=MINIMUM))


@pytest.mark.parametrize(('text', 'blocked'), [
    (MINIMUM, False),
    (MINIMUM.replace('for an account', 'for each project in an account'), True),
    (MINIMUM.replace('has a minimum', 'for each allocation has a minimum'), True),
    (MINIMUM.replace('for an account', 'for an account for each allocation'), True),
    ('Compute Paid 套餐每个项目在账户中每月最低费用为 $17 USD。', True),
])
def test_minimum_account_scope_requires_the_complete_local_clause(monkeypatch, text, blocked):
    assert bool(audit(component_case(monkeypatch, text, support=MINIMUM))) == blocked


def test_an_unknown_source_resource_scope_cannot_authorize_an_account_minimum(monkeypatch):
    source = MINIMUM.replace('for an account', 'for each project in an account')
    assert audit(component_case(monkeypatch, MINIMUM, support=source))


@pytest.mark.parametrize('mutation', ['other_span', 'unpublished', 'unseen', 'source', 'tamper', 'no_binding'])
def test_components_need_exact_published_allowed_source_span(monkeypatch, mutation):
    source = RATE + '\n\n' + CPU
    case = component_case(monkeypatch, CPU, support=RATE if mutation == 'other_span' else CPU,
                          source=source, bound=mutation != 'no_binding')
    detail, _, _ = case
    if mutation == 'unpublished':
        row = detail.report_dimension_audits[0]
        detail.report_dimension_audits = [row.model_copy(update={'claims': ()})]
    elif mutation == 'unseen':
        detail.report_answer_boundaries = [detail.report_answer_boundaries[0].model_copy(
            update={'allowed_fact_ids': ()})]
    elif mutation == 'source':
        detail.report_md = CPU + ' [source:unrelated-source]'
    elif mutation == 'tamper':
        row = detail.report_dimension_audits[0]
        item = row.claims[0]
        changed = item.claim.source_span_bindings[0].model_copy(update={'quote': CPU.replace('0.06', '0.09')})
        claim = item.claim.model_copy(update={'source_span_bindings': (changed,)})
        detail.report_dimension_audits = [row.model_copy(update={'claims': (item.model_copy(update={'claim': claim}),)})]
    assert audit(case)


@pytest.mark.parametrize('text', [
    'Plus plan monthly requests overage component is $1.88, based on 15 million minus 11 million requests.',
    'Plus plan monthly requests overage component is $1.89.',
    'Plus plan monthly CPU overage component is $1.88.',
])
def test_unproven_derivation_remains_blocked(monkeypatch, text):
    assert audit(component_case(monkeypatch, text))


def test_each_bad_mention_survives_deduplication_and_one_good_amount_does_not_mask_another(monkeypatch):
    case = component_case(monkeypatch, RATE + ' Actual bill is $99 and tax is $3.')
    issues = audit(case)
    assert [i.metadata['amount'] for i in issues] == ['99', '3']
    assert len({i.id for i in issues}) == 2
    assert len({i.metadata['mention_start'] for i in issues}) == 2


def test_another_published_claim_cannot_supply_a_components_source_span(monkeypatch):
    case = component_case(monkeypatch, RATE, source=RATE + '\n\n' + CPU)
    detail, _, _ = case
    detail.report_md += ' ' + CPU
    assert [i.metadata['amount'] for i in audit(case)] == ['0.06']
