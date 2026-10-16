"""Source-local creation-date exceptions apply outside the operation taxonomy."""

from types import SimpleNamespace

import pytest

from test_capability_alignment import fact
from packages.research.evidence.report_claims import ReportClaim, audit_report_claims, claim_rule_reasons
from packages.research.evidence.snapshot_models import canonical_json


GENERAL = 'Guest Reviewers cannot be Auditors.'
EXCEPTION = ('In accounts created before March 8, 2024, Guest Reviewers have the same permissions '
             'as employees. They can also be Auditors or Custodians.')


def observation(general=GENERAL, exception=EXCEPTION, *, field='value', status='supported'):
    original = fact('Anonymous Suite', general, slot='creation-exception', status=status)
    full = 'Guest Reviewers\n' + general + '\nNOTE: ' + exception
    if field == 'quote':
        return original.model_copy(update={'quote': full, 'value_json': canonical_json([full])})
    if field == 'qualifiers':
        return original.model_copy(update={'qualifiers_json': canonical_json({'source_context_quote': full})})
    return original.model_copy(update={'value_json': canonical_json([full])})


def claim_for(original, text):
    return ReportClaim(id='creation-claim', text=text, kind='fact', competitor=original.competitor,
                       dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])


def reasons(original, text):
    return claim_rule_reasons(claim_for(original, text), SimpleNamespace(facts=[original]),
                              [SimpleNamespace(allowed_fact_ids=[original.id])])


@pytest.mark.parametrize('field', ['quote', 'value', 'qualifiers'])
def test_admin_like_eligibility_denial_requires_its_own_creation_date_exception(field):
    original = observation(field=field)
    assert 'source_temporal_condition_omitted_or_changed' in reasons(original, GENERAL)


@pytest.mark.parametrize('text', [
    'Guest Reviewers 不能担任 Auditor。',
    'Guest Reviewers can collaborate, but cannot be Auditors.',
    'Guest Reviewers 一律不能担任 Auditor，资料于 2026 年 10 月核验。',
])
def test_translated_or_mixed_claim_cannot_drop_exception(text):
    assert 'source_temporal_condition_omitted_or_changed' in reasons(observation(), text)


@pytest.mark.parametrize('text', [
    'Guest Reviewers 通常不能担任 Auditor，但有账号创建日期例外。',
    'Guest Reviewers 是否能担任 Auditor 取决于账号创建日期，需要先澄清。',
    'Guest Reviewers are not always barred from being Auditors; account creation date must be clarified.',
    'For accounts created on or after March 8, 2024, Guest Reviewers cannot be Auditors.',
    '在 2024 年 3 月 8 日之后创建的账号中，Guest Reviewers 不能担任 Auditor。',
    'In accounts created before March 8, 2024, Guest Reviewers can also be Auditors.',
])
def test_explicit_exception_or_correct_creation_date_scope_is_allowed(text):
    assert not reasons(observation(), text)


@pytest.mark.parametrize('text', [
    'In accounts created before March 8, 2024, Guest Reviewers cannot be Auditors.',
    'In accounts created before March 9, 2024, Guest Reviewers can be Auditors.',
    'As of March 8, 2024, Guest Reviewers cannot be Auditors.',
    'Guest Reviewers cannot be Auditors; dashboards created before March 8, 2024 have an exception.',
])
def test_cutoff_relation_and_date_subject_cannot_be_changed(text):
    assert 'source_temporal_condition_omitted_or_changed' in reasons(observation(), text)


def test_other_claim_and_review_reason_cannot_supply_missing_condition():
    original = observation()
    claims = [claim_for(original, GENERAL), claim_for(original, EXCEPTION).model_copy(update={'id': 'exception'})]
    reviews = [{'claim_id': c.id, 'verdict': 'supported', 'reason': 'The date exception is clarified by another claim.'}
               for c in claims]
    audited = audit_report_claims(claims, reviews, SimpleNamespace(facts=[original]),
                                 [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert audited[0].status == 'rejected'
    assert audited[1].status == 'supported'


@pytest.mark.parametrize(('general', 'exception', 'text'), [
    ('Guest Reviewers cannot be Auditors.', 'In accounts created before June 12, 2023, Staff can be Auditors.', GENERAL),
    ('Guest Reviewers cannot export files.', 'In accounts created before June 12, 2023, Guest Reviewers can publish dashboards.', 'Guest Reviewers cannot export files.'),
    ('Guest Reviewers cannot edit documents.', 'In workspaces created before June 12, 2023, Guest Reviewers can edit boards.', 'Guest Reviewers cannot edit documents.'),
    ('Guest Reviewers cannot be Auditors.', 'The documentation was updated on March 8, 2024.', GENERAL),
    ('Guest Reviewers cannot be Auditors.', 'Verification completed on March 8, 2024.', GENERAL),
    ('Guest Reviewers cannot be Auditors.', 'A conference for Guest Reviewers will be held before March 8, 2028.', GENERAL),
])
def test_other_actor_action_object_or_incidental_date_does_not_attach(general, exception, text):
    assert not reasons(observation(general, exception), text)


def test_helper_returns_replayable_source_and_creation_subject_without_product_dates():
    from packages.research.evidence.temporal_conditions import temporal_constraints

    original = observation('Partner Curators cannot be Custodians.',
        'For workspaces created after 2031-11-06, Partner Curators can be Custodians.')
    rows = temporal_constraints(original)
    assert len(rows) == 1
    assert rows[0]['date_subject'] == 'workspace'
    assert rows[0]['cutoff'] == '2031-11-06'
    assert rows[0]['relation'] == 'after'
    assert rows[0]['actor'] == 'Partner Curators'
    assert rows[0]['quote'] in original.value[0]
    assert rows[0]['source_path'] == 'value.0'


def test_unknown_fact_keeps_unknown_status_after_constraint_inspection():
    from packages.research.evidence.temporal_conditions import temporal_constraints

    original = observation(status='unknown')
    assert temporal_constraints(original)
    assert original.status == 'unknown'


@pytest.mark.parametrize('text', [
    'Guest Reviewers cannot export files.',
    'Guest Reviewers 不能导出文件。',
])
def test_same_permissions_exception_also_protects_other_explicit_general_denials(text):
    original = observation('Guest Reviewers cannot export files.', EXCEPTION)
    assert 'source_temporal_condition_omitted_or_changed' in reasons(original, text)


def test_unknown_actor_is_retained_and_does_not_become_an_unconditional_permission():
    original = observation('Guest Reviewers cannot be Auditors.',
                           'In accounts created before March 8, 2024, they can be Auditors.')
    from packages.research.evidence.temporal_conditions import temporal_constraints
    assert temporal_constraints(original)[0]['actor'] is None
    assert 'source_temporal_condition_scope_unresolved' in reasons(original, GENERAL)


@pytest.mark.parametrize('text', [
    'Guest Reviewers cannot be Auditors. Staff have an account creation date exception.',
    'Guest Reviewers cannot be Auditors, but Staff can be Auditors in accounts created before March 8, 2024.',
])
def test_a_different_actor_in_same_claim_cannot_supply_the_exception(text):
    assert 'source_temporal_condition_omitted_or_changed' in reasons(observation(), text)


def test_a_date_belonging_to_an_unrelated_sentence_is_not_attached():
    original = observation(GENERAL,
                           'Auditor training in accounts created before March 8, 2024 is online. '
                           'Guest Reviewers cannot be Custodians.')
    assert not reasons(original, GENERAL)


@pytest.mark.parametrize('text', [
    'Guest Reviewer 不能担任 Auditor，有账号创建日期例外。',
    'For accounts created on or after March 8, 2024, Guest Reviewer cannot be an Auditor.',
])
def test_singular_claim_role_and_unrelated_source_morphology_are_preserved(text):
    assert not reasons(observation(), text)


def test_actor_substring_cannot_attach_to_a_different_role():
    original = observation('Staff cannot be Auditors.',
                           'For accounts created before March 8, 2024, Staff can be Auditors.')
    assert not reasons(original, 'Staffing Coordinators cannot be Auditors.')


def test_source_creation_condition_after_permission_is_still_retained():
    original = observation(GENERAL,
        'Guest Reviewers can be Auditors in accounts created before March 8, 2024.')
    assert 'source_temporal_condition_omitted_or_changed' in reasons(original, GENERAL)


def test_chinese_source_role_and_creation_condition_remain_source_local():
    original = observation('特邀策展人不能担任审校员。',
                           '在2033年7月19日之前创建的工作区中，特邀策展人可以担任审校员。')
    assert 'source_temporal_condition_omitted_or_changed' in reasons(original, '特邀策展人不能担任审校员。')
    assert not reasons(original, '特邀策展人担任审校员存在工作区创建日期例外。')


def test_non_permission_creation_date_is_not_a_permission_constraint():
    from packages.research.evidence.temporal_conditions import temporal_constraints

    original = observation(GENERAL, 'In accounts created before March 8, 2024, the training is online.')
    assert not temporal_constraints(original)


def test_unnamed_permission_object_is_not_filled_from_the_claim():
    original = observation('Guest Reviewers cannot export files.',
        'In accounts created before March 8, 2024, Guest Reviewers can export.')
    assert 'source_temporal_condition_scope_unresolved' in reasons(original, 'Guest Reviewers cannot export files.')
    assert not reasons(original, GENERAL)


def test_same_date_elsewhere_in_claim_does_not_scope_an_unconditional_assertion():
    text = ('Guest Reviewers cannot be Auditors; '
            'accounts created before March 8, 2024 have smaller storage limits.')
    assert 'source_temporal_condition_omitted_or_changed' in reasons(observation(), text)


def test_a_matching_complement_date_in_another_assertion_cannot_scope_the_denial():
    text = ('Guest Reviewers cannot be Auditors; '
            'accounts created on or after March 8, 2024 have smaller storage limits.')
    assert 'source_temporal_condition_omitted_or_changed' in reasons(observation(), text)


def test_broad_rights_exception_does_not_absorb_a_different_source_actor_rule():
    original = observation('Staff cannot export files.', EXCEPTION)
    assert not reasons(original, 'Guest Reviewers cannot export files.')


def test_same_actor_date_on_another_action_cannot_scope_an_unconditional_denial():
    text = ('Guest Reviewers cannot be Auditors. '
            'For accounts created on or after March 8, 2024, Guest Reviewers can export files.')
    assert 'source_temporal_condition_omitted_or_changed' in reasons(observation(), text)


def test_another_action_negation_cannot_change_the_date_scoped_permission_polarity():
    original = observation(GENERAL,
        'In accounts created before March 8, 2024, Guest Reviewers can be Auditors.')
    text = ('In accounts created before March 8, 2024, Guest Reviewers can be Auditors, '
            'but cannot export files.')
    assert not reasons(original, text)


@pytest.mark.parametrize(('source_role', 'claim_role'), [
    ('Admins', '管理员'),
    ('Administrators', '管理员'),
    ('Administrators', 'Admins'),
    ('Owners', '所有者'),
])
def test_finite_role_aliases_cannot_hide_creation_date_exceptions(source_role, claim_role):
    original = observation(f'Guest Reviewers cannot be {source_role}.',
        f'In accounts created before June 17, 2032, Guest Reviewers can be {source_role}.')
    text = f'Guest Reviewers 不能成为 {claim_role}。'
    assert 'source_temporal_condition_omitted_or_changed' in reasons(original, text)


@pytest.mark.parametrize('text', [
    '在2032年6月17日之前创建的账号中，Guest Reviewers 可以成为管理员。',
    '在2032年6月17日之后创建的账号中，Guest Reviewers 不能成为管理员。',
    '在2032年6月17日之前创建的账号中，Guest Reviewers 可以成为管理员或所有者。',
])
def test_chinese_roles_with_complete_creation_scope_preserve_the_original_exception(text):
    from packages.research.evidence.temporal_conditions import _predicate_keys

    original = observation('Guest Reviewers cannot be Admins.',
        'In accounts created before June 17, 2032, Guest Reviewers can be Admins or Owners.')
    assert 'role:admin' in _predicate_keys(text, 'Guest Reviewers')
    assert not reasons(original, text)


def test_normalized_role_still_requires_the_original_date_subject_and_cutoff():
    original = observation('Guest Reviewers cannot be Administrators.',
        'In accounts created before June 17, 2032, Guest Reviewers can be Admins.')
    text = '在2032年6月17日之前创建的工作区中，Guest Reviewers 可以成为管理员。'
    assert 'source_temporal_condition_omitted_or_changed' in reasons(original, text)


def test_unmapped_cross_language_role_is_unresolved_instead_of_proven_unrelated():
    original = observation('Guest Reviewers cannot be Auditors.',
        'In accounts created before June 17, 2032, Guest Reviewers can be Auditors.')
    assert 'source_temporal_condition_scope_unresolved' in reasons(
        original, 'Guest Reviewers 不能成为审校员。')


@pytest.mark.parametrize('text', [
    'Staff 不能成为管理员。',
    'Guest Reviewers cannot export files.',
    'Guest Reviewers cannot be Custodians.',
])
def test_role_aliases_do_not_attach_other_actors_actions_or_explicit_roles(text):
    original = observation('Guest Reviewers cannot be Admins.',
        'In accounts created before June 17, 2032, Guest Reviewers can be Admins.')
    assert not reasons(original, text)
