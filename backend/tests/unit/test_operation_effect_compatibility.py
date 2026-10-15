"""A source-bound operation must agree with the reported assertion direction."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_capability_alignment import fact

from packages.research.evidence.operations import operation_binding, operation_observations
from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
from packages.research.evidence.snapshot_models import EvidenceFact


def reasons(original, text, operation, *, row_filter=lambda row: True):
    observation = next(row for row in operation_observations(original)
        if row['operation'] == operation and row_filter(row))
    claim = ReportClaim(id='direction', text=text, kind='fact', competitor=original.competitor,
        dimension='feature', fact_ids=[original.id], source_ids=[original.source_id],
        operation_binding=operation_binding(observation))
    return claim_rule_reasons(claim, SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])


def saved_coda():
    saved = json.loads((Path(__file__).parents[1] / 'fixtures/coda_manage_access_denial.json').read_text())
    return EvidenceFact.model_validate(saved['fact']), ReportClaim.model_validate(saved['audited_claim']['claim'])


def test_saved_coda_wrong_allowed_binding_is_rejected_and_fresh_denied_passes():
    original, claim = saved_coda()
    view = SimpleNamespace(facts=[original]); boundaries = [SimpleNamespace(allowed_fact_ids=[original.id])]
    assert 'operation_binding_mismatch' in claim_rule_reasons(claim, view, boundaries)
    # Old stored metadata cannot authorize a matching but wrong affirmative
    # rewrite, even if the model would mark it supported.
    affirmative = claim.model_copy(update={'text': claim.text.replace('不能被授予管理访问权限', '可以被授予管理访问权限')})
    assert 'operation_binding_mismatch' in claim_rule_reasons(affirmative, view, boundaries)
    fresh = original.model_copy(update={'qualifiers_json': json.dumps({key:value for key,value in original.qualifiers.items() if key!='operations'})})
    row = next(row for row in operation_observations(fresh) if row['operation_quote']=='not manage access')
    assert row['effect'] == 'denied'
    assert row['role'] is row['plan'] is row['access_scope'] is None
    correct = claim.model_copy(update={'operation_binding': type(claim.operation_binding).model_validate(operation_binding(row))})
    assert not claim_rule_reasons(correct, SimpleNamespace(facts=[fresh]), boundaries)
    contradicted = correct.model_copy(update={'text': affirmative.text})
    assert 'operation_effect_mismatch' in claim_rule_reasons(contradicted, SimpleNamespace(facts=[fresh]), boundaries)


@pytest.mark.parametrize('quote,effect', [
    ('You can grant external users edit, comment, or view access, but not manage access.', 'denied'),
    ('Members can not only manage access but also edit pages.', 'allowed'),
    ('Members can manage access.', 'allowed'),
    ('Members cannot manage access.', 'denied'),
    ('Members may manage access only after approval.', 'allowed'),
])
def test_access_control_source_fragments_preserve_local_negation(quote, effect):
    rows = operation_observations(fact('Coda', quote, slot='fragment'))
    assert next(row for row in rows if row['operation']=='manage_access')['effect'] == effect


@pytest.mark.parametrize('quote,text,operation,expected', [
    ('Members can manage access.', '成员不能管理访问权限。', 'manage_access', 'operation_effect_mismatch'),
    ('Members cannot manage access.', '成员可以管理访问权限。', 'manage_access', 'operation_effect_mismatch'),
    ('Members can manage access.', '成员可以管理访问权限。', 'manage_access', None),
    ('Members cannot manage access.', '成员不能管理访问权限。', 'manage_access', None),
    ('Members can comment on pages but cannot edit pages.', '成员可以评论页面，但不能编辑页面。', 'comment', None),
    ('Members can comment on pages but cannot edit pages.', '成员可以评论页面，但不能编辑页面。', 'edit', None),
    ('Members can edit documents.', '成员可以编辑页面，但不能编辑评论。', 'edit', None),
    ('Members cannot create items.', '成员可以创建页面。', 'create', None),
    ('Guests can edit documents only after invitation.', 'Guests can edit documents only after invitation.', 'edit', None),
    ('Members can manage access.', 'Members manage access.', 'manage_access', None),
    ('Members can manage access.', 'Members can not only manage access but also edit pages.', 'manage_access', None),
    ('Members can comment on pages.', '成员可以评论页面；前提是邀请者拥有 Can manage access 权限。', 'comment', None),
    ('Members can manage access.', '前提是邀请者拥有 Can manage access 权限。', 'manage_access', None),
])
def test_claim_effect_compatibility_is_operation_and_object_local(quote,text,operation,expected):
    original = fact('Coda', quote, slot='claim-direction')
    actual = reasons(original,text,operation)
    if expected: assert expected in actual
    else: assert not actual


def test_another_actor_affirmation_does_not_override_bound_denial():
    original=fact('Coda','Guests cannot edit pages; admins can edit pages.',slot='actors')
    assert not reasons(original,'Guests cannot edit pages; admins can edit pages.','edit',
        row_filter=lambda row: row['role'].casefold()=='guests')


@pytest.mark.parametrize('quote,text', [
    ('Members can edit pages.', '成员不能评论页面，可以编辑页面。'),
    ('Guests can edit pages.', 'Admins cannot comment on pages while guests can edit pages.'),
])
def test_mixed_action_or_actor_denial_is_left_to_original_semantic_review(quote, text):
    original = fact('Coda', quote, slot='mixed-polarity')
    assert not reasons(original, text, 'edit')
