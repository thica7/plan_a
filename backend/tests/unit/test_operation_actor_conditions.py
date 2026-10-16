"""Source-local actor and required-condition regressions; no model calls."""
from types import SimpleNamespace

import pytest

from test_capability_alignment import fact
from test_qualified_operations import qualified_fixture
from packages.research.evidence.operations import operation_binding, operation_observations, structured_operations
from packages.research.evidence.report_claims import ReportClaim, audit_report_claims
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.extraction.semantic import semantic_extraction


@pytest.mark.parametrize('quote,expected_actor', [
    ("To grant edit access to users who aren't members of your team, consider public sharing with visitors.", None),
    ('You can grant edit access to non-team members.', 'You'),
    ('When inviting guests, you can only grant view or comment access.', 'you'),
])
def test_receivers_and_excluded_members_are_never_the_acting_role(quote, expected_actor):
    rows = structured_operations(quote, [quote], 'Nuclino')
    assert rows
    assert all(row['role'] == expected_actor for row in rows)


def test_explicit_inviter_and_receiver_have_separate_source_spans():
    quote = "Owners can grant edit access to users who aren't members of the team."
    row = next(row for row in structured_operations(quote, [quote], 'Nuclino')
               if row['operation'] == 'manage_access')
    assert row['role'] == 'Owners'
    assert row['recipient_quote'] == "users who aren't members of the team"
    assert row['excluded_roles'] == ['members']


def test_selecting_a_permission_level_is_not_the_actors_comment_or_edit_capability():
    quote = '- Next to Anyone with the link, select Can view, Can comment or Can edit.'
    rows = structured_operations(quote, [quote], 'Nuclino')
    assert rows and {row['operation'] for row in rows} == {'manage_access'}
    assert all(row['role'] is None for row in rows)


def test_unresolved_positive_actor_cannot_publish_as_a_verified_operation():
    quote = 'Editing boards is available.'
    original, claim = original_and_claim('Guests can edit boards shared with them.', quote=quote, condition='')
    assert audit(original, claim, with_checks=False).status == 'rejected'


@pytest.mark.parametrize('actor', ['People', 'Users', 'You'])
def test_generic_explicit_source_subject_is_preserved_without_inventing_membership(actor):
    quote = f'{actor} can comment on shared pages.'
    condition = 'Requires membership in the workspace.'
    original, claim = original_and_claim(quote + ' ' + condition, quote=quote, condition=condition,
                                         operation='comment')
    assert claim.operation_binding.role == actor
    assert audit(original, claim).status == 'supported'


VISITOR_PLAN = 'Editing and commenting are only available for Visitors on paid and Education plans.'
GUEST_ACCESS = 'Guests must sign in to access boards and can only access boards they are directly invited to.'


def extracted(quote, condition, role='Visitors', *, other_condition='Guests can edit boards only on Enterprise plans.'):
    title = 'Collaboration with ' + role
    body = '\n'.join([title, 'Invitation steps', condition, other_condition,
                      'Frequently asked questions', quote])
    brief, _, page = qualified_fixture(body, headings=[(1, title), (2, 'Invitation steps'),
                                                      (2, 'Frequently asked questions')])
    result = semantic_extraction(brief, page, {'facts': [{'quote': quote}]})
    return next(iter(result.fields.values()))


def test_faq_same_source_role_and_operation_inherit_required_plan():
    quote = 'Anyone with the board link can edit or comment on the board.'
    value = extracted(quote, VISITOR_PLAN)
    assert VISITOR_PLAN in value['conditions']
    rows = [r for r in value['operations'] if r['operation'] in {'edit', 'comment'}]
    assert rows
    assert all(any(p['quote'] == VISITOR_PLAN for p in row['prerequisites']) for row in rows)
    assert all(not any('Enterprise plans' in p['quote'] for p in row['prerequisites']) for row in rows)


def test_other_role_or_other_operation_does_not_become_an_faq_prerequisite():
    quote = 'Members can read pages in the workspace.'
    value = extracted(quote, VISITOR_PLAN, role='Members',
                      other_condition='Members can edit pages only on paid plans.')
    assert all(not row['prerequisites'] for row in value['operations'])


def test_actor_access_level_does_not_turn_an_app_login_rule_into_an_edit_prerequisite():
    quote = 'Visitors can edit boards shared with them.'
    apps = 'Visitors with edit access must sign in to use collaborative apps.'
    value = extracted(quote, apps, other_condition='Guests must sign in to access boards.')
    assert all(not row['prerequisites'] for row in value['operations'])


def test_alternative_branch_condition_is_not_imported_across_an_faq_section():
    quote = 'Visitors can edit boards shared with them.'
    options = ('Choose your access mode:\n'
               '- Public: Visitors can edit boards only on paid plans.\n'
               '- Invited: Visitors can edit boards on all plans.')
    value = extracted(quote, options, other_condition='Guests must sign in to access boards.')
    assert all(not row['prerequisites'] for row in value['operations'])


def test_sentence_narrowing_preserves_the_original_alternative_branch_boundary():
    quote = 'Visitors can edit boards shared with them.'
    choices = ('Choose your access mode:\n'
               '- Public: Visitors can edit boards only after signing in. Administrators configure the mode.\n'
               '- Invited: Visitors can edit boards without signing in.')
    row = next(row for row in structured_operations(quote, [quote, choices], 'Nuclino')
               if row['operation'] == 'edit')
    assert row['condition_groups']
    assert not row['prerequisites']


def test_login_and_direct_invitation_follow_the_guest_access_operation():
    quote = 'Guests can view boards shared with them.'
    value = extracted(quote, GUEST_ACCESS, role='Guests', other_condition='Visitors can edit boards only on paid plans.')
    read = next(row for row in value['operations'] if row['operation'] == 'read')
    assert any(p['quote'] == GUEST_ACCESS for p in read['prerequisites'])
    assert read['object_type'] == 'board'


def test_captured_required_sign_in_and_only_have_access_wording_forms_a_bound_read_rule():
    quote = '- Guests are required to sign in and they only have access to boards they’re directly invited to.'
    rows = structured_operations(quote, [quote], 'Nuclino')
    read = next(row for row in rows if row['operation'] == 'read')
    assert read['role'] == 'Guests' and read['object_type'] == 'board'
    assert read['prerequisites']
    assert all('directly invited' in p['quote'] and 'sign in' in p['quote'] for p in read['prerequisites'])


def test_guest_read_does_not_inherit_paid_tools_or_an_admins_edit_invitation_task():
    quote = 'Guests can view boards shared with them.'
    tools = 'Guests can enjoy access to features in your paid plan, including voting and timer.'
    admin = 'To enable the feature to invite guests with edit access to your Enterprise Plan, your Admin needs to contact the Account Manager.'
    row = next(row for row in structured_operations(quote, [quote, GUEST_ACCESS, tools, admin], 'Nuclino')
               if row['operation'] == 'read')
    assert any(p['quote'] == GUEST_ACCESS for p in row['prerequisites'])
    assert not any(p['quote'] in {tools, admin} for p in row['prerequisites'])


def test_only_the_access_sentence_is_bound_from_a_mixed_invitation_and_login_line():
    quote = 'Guests can view boards shared with them.'
    login = 'Guests must be signed into the product in order to access shared boards.'
    context = 'Guests can only be invited to particular boards - you cannot invite a guest from Team settings. ' + login
    row = next(row for row in structured_operations(quote, [quote, context], 'Nuclino')
               if row['operation'] == 'read')
    assert any(p['quote'] == login for p in row['prerequisites'])
    assert not any('Team settings' in p['quote'] for p in row['prerequisites'])


def original_and_claim(text, *, quote='Visitors can edit boards.', condition=VISITOR_PLAN, role='Visitors', operation='edit', competitor='Nuclino'):
    original = fact(competitor, quote, slot='conditions')
    terms = [quote, condition]
    original = original.model_copy(update={'value_json': canonical_json(terms), 'qualifiers_json':
        canonical_json({'operations': structured_operations(quote, terms, competitor)})})
    row = next(row for row in operation_observations(original) if row['operation'] == operation)
    claim = ReportClaim(id='condition', text=text, kind='fact', competitor=competitor, dimension='feature',
                        fact_ids=[original.id], source_ids=[original.source_id], operation_binding=operation_binding(row))
    return original, claim


def audit(original, claim, *, with_checks=True):
    from packages.research.evidence.report_claims import required_operation_checks
    review = {'claim_id': claim.id, 'verdict': 'supported', 'reason': 'Forced supported for offline guard regression.'}
    if with_checks:
        review['checks'] = [{'check_id': item['check_id'], 'verdict': 'supported', 'claim_span': claim.text}
                            for item in required_operation_checks(claim.operation_binding)]
    return audit_report_claims([claim], [review], SimpleNamespace(facts=[original]),
                              [SimpleNamespace(allowed_fact_ids=[original.id])])[0]


def test_required_conditions_cannot_publish_with_only_a_broad_supported_verdict():
    original, claim = original_and_claim('Visitors can edit boards only on paid and Education plans.')
    result = audit(original, claim, with_checks=False)
    assert result.status == 'rejected'
    assert 'operation_checks_incomplete' in result.rule_reasons


@pytest.mark.parametrize('text', [
    'Visitors can edit boards.',
    'Visitors can edit boards on all plans.',
    'Visitors can edit boards on paid plans.',
    'Guests can edit boards only on paid and Education plans.',
    'Visitors can edit documents only on paid and Education plans.',
    'Visitors cannot edit boards on paid and Education plans.',
])
def test_forced_checks_cannot_override_explicit_missing_or_changed_conditions(text):
    original, claim = original_and_claim(text)
    assert audit(original, claim).status == 'rejected'


@pytest.mark.parametrize('text', [
    'Visitors can edit boards only on paid and Education plans.',
    'Visitor 只有在付费或 Education 套餐下才能编辑看板。',
])
def test_complete_same_actor_action_and_plan_statement_passes(text):
    original, claim = original_and_claim(text)
    assert audit(original, claim).status == 'supported'


@pytest.mark.parametrize('text', [
    'Guests can view boards.',
    'Guests can view directly invited boards without signing in.',
    'Guests must sign in and can view every board in the team.',
])
def test_guest_login_and_direct_invitation_cannot_be_omitted_or_negated(text):
    original, claim = original_and_claim(text, quote='Guests can view boards.', condition=GUEST_ACCESS,
                                         role='Guests', operation='read')
    assert audit(original, claim).status == 'rejected'


@pytest.mark.parametrize('text', [
    'Guests must sign in and can only view boards they are directly invited to.',
    'Guest 需登录，且只能查看直接受邀的看板。',
])
def test_complete_guest_login_and_invitation_statement_passes(text):
    original, claim = original_and_claim(text, quote='Guests can view boards.', condition=GUEST_ACCESS,
                                         role='Guests', operation='read')
    assert audit(original, claim).status == 'supported'


def test_check_ids_and_spans_are_exact_and_bound_to_each_source_condition():
    from packages.research.evidence.report_claims import required_operation_checks
    original, claim = original_and_claim('Visitors can edit boards only on paid and Education plans.')
    checks = required_operation_checks(claim.operation_binding)
    assert {item['kind'] for item in checks} >= {'role', 'object', 'effect', 'prerequisite'}
    assert checks == required_operation_checks(claim.operation_binding)
    review = {'claim_id': claim.id, 'verdict': 'supported', 'reason': 'Offline guard regression.',
              'checks': [{'check_id': item['check_id'], 'verdict': 'supported', 'claim_span': 'invented span'}
                         for item in checks]}
    result = audit_report_claims([claim], [review], SimpleNamespace(facts=[original]),
                                [SimpleNamespace(allowed_fact_ids=[original.id])])[0]
    assert result.status == 'rejected' and 'operation_check_span_invalid' in result.rule_reasons


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'uncertain'])
def test_each_bound_check_is_required_once_and_must_itself_be_supported(change):
    from packages.research.evidence.report_claims import required_operation_checks
    original, claim = original_and_claim('Visitors can edit boards only on paid and Education plans.')
    checks = [{'check_id': item['check_id'], 'verdict': 'supported', 'claim_span': claim.text}
              for item in required_operation_checks(claim.operation_binding)]
    if change == 'missing':
        checks.pop()
    elif change == 'duplicate':
        checks.append(checks[0])
    elif change == 'unknown':
        checks[0] = {**checks[0], 'check_id': 'unbound-condition'}
    else:
        checks[0] = {**checks[0], 'verdict': 'uncertain'}
    result = audit_report_claims([claim], [{'claim_id': claim.id, 'verdict': 'supported',
        'reason': 'Offline guard regression.', 'checks': checks}], SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])[0]
    assert result.status == 'rejected'


def test_empty_review_checks_do_not_change_legacy_serialized_payloads():
    from packages.research.evidence.report_claims import ClaimReview
    review = ClaimReview(claim_id='legacy', verdict='supported', reason='No bound conditions.')
    assert 'checks' not in review.model_dump(mode='json')


def test_explicit_receiver_and_exclusion_are_reviewed_even_without_other_prerequisites():
    quote = "Owners can grant edit access to users who aren't members of the team."
    original, claim = original_and_claim(quote, quote=quote, condition='', operation='manage_access')
    assert audit(original, claim, with_checks=False).status == 'rejected'
    assert audit(original, claim).status == 'supported'


@pytest.mark.parametrize('separator', ['\n', ' '])
@pytest.mark.parametrize('guest', [
    'Guests must sign in before starting a session.',
    'Guests are required to sign in and they only have access to boards they’re directly invited to.',
])
def test_access_restriction_is_an_independent_source_fact_with_its_own_offsets(separator, guest):
    from packages.research.extraction.semantic import extract_operation_rules
    from packages.research.evidence.admission import admit_evidence_items
    owner = 'Owners can edit boards in the workspace.'
    body = owner + separator + guest
    brief, candidate, page = qualified_fixture(body)
    result = extract_operation_rules(brief, page)
    assert {owner, guest} <= {quote.text for quote in result.quotes}
    for quote in result.quotes:
        assert body[quote.start_offset:quote.end_offset] == quote.text
    guest_quote = next(quote for quote in result.quotes if quote.text == guest)
    guest_value = result.fields[guest_quote.field]
    assert all(row['role'] == 'Guests' for row in guest_value['operations'])
    owner_value = result.fields[next(quote.field for quote in result.quotes if quote.text == owner)]
    assert all(not any('Guests' in p['quote'] for p in row['prerequisites'])
               for row in owner_value['operations'])
    admitted = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert all(item.status == 'accepted' for item in admitted)


@pytest.mark.parametrize('requirement', [
    'Owners must grant access before guests can comment on pages.',
    'Owners must give guests access before they can comment on pages.',
])
def test_another_actor_must_grant_this_exact_guests_access_before_commenting(requirement):
    quote = 'Guests can comment on pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert row['role'] == 'Guests'
    assert any(p['quote'] == requirement for p in row['prerequisites'])


@pytest.mark.parametrize('requirement', [
    'Owners must grant access before members can comment on pages.',
    'Owners must give members access before they can comment on pages.',
    'Owners must grant access before guests can create pages.',
    'Owners must grant access before they can comment on pages.',
    'Owners must give non-guests access before they can comment on pages.',
])
def test_access_grants_for_another_role_action_or_unresolved_pronoun_do_not_qualify_guest_commenting(requirement):
    quote = 'Guests can comment on pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert not row['prerequisites']


@pytest.mark.parametrize('quote,requirement,operation', [
    ('You can create pages.', 'Only invited members can create pages.', 'create'),
    ('You can comment on pages.', 'Only signed-in members can comment on pages.', 'comment'),
])
def test_generic_source_you_retains_exclusive_same_action_eligibility_without_becoming_members(quote, requirement, operation):
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == operation)
    assert row['role'] == 'You'
    assert any(p['quote'] == requirement for p in row['prerequisites'])


def test_generic_you_retains_a_role_scoped_condition_as_unresolved_not_universal_membership():
    quote = 'You can create pages.'
    requirement = 'Members can create pages only if they are logged in.'
    original, claim = original_and_claim(quote, quote=quote, condition=requirement, operation='create')
    assert claim.operation_binding.role == 'You'
    assert {'kind': 'role_scoped', 'quote': requirement} in claim.operation_binding.prerequisites
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert 'operation_condition_scope_unresolved' in result.rule_reasons


@pytest.mark.parametrize('product,quote,text', [
    ('Acme Vault 7', 'Acme Vault 7 supports offline editing and synchronizes changes when connected.',
     'Acme Vault 7 supports offline editing and synchronizes changes when connected.'),
    ('Notion', 'Multiple people edit a page at the same time with live changes.',
     '多人可以同时编辑页面，修改实时可见。'),
])
def test_generic_product_capability_does_not_require_a_permission_role_or_object(product, quote, text):
    original, claim = original_and_claim(text, quote=quote, condition='', competitor=product)
    assert claim.operation_binding.role is None
    assert audit(original, claim).status == 'supported'
    assert 'role' in operation_observations(original)[0]['missing_fields']


def test_complete_create_translation_can_use_the_common_xinjian_synonym():
    quote = 'Only workspace members with full access can create items.'
    original, claim = original_and_claim('仅完整访问权限的工作区成员可新建条目。', quote=quote,
                                         condition='', operation='create')
    assert audit(original, claim).status == 'supported'


def test_an_admin_in_an_approval_condition_is_not_the_unknown_actor_of_editing():
    quote = 'Editing boards is available only after admin approval.'
    original, claim = original_and_claim('需要管理员批准后才可以编辑看板。', quote=quote, condition='')
    assert claim.operation_binding.role is None
    assert audit(original, claim).status == 'supported'


@pytest.mark.parametrize('requirement', [
    'Members need permission to comment on pages.',
    'Members require workspace access before commenting on pages.',
])
def test_need_and_require_keep_their_named_subject_and_do_not_become_guest_requirements(requirement):
    quote = 'Guests can comment on pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert not row['prerequisites']


@pytest.mark.parametrize('requirement', [
    'Guests need permission to comment on pages.',
    'Guests require workspace access before commenting on pages.',
])
def test_need_and_require_still_qualify_their_own_named_guests(requirement):
    quote = 'Guests can comment on pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert any(p['quote'] == requirement for p in row['prerequisites'])


@pytest.mark.parametrize('requirement', [
    'Owners must approve before guests can comment on pages.',
    'Owners need to approve before guests can comment on pages.',
])
def test_required_approval_before_this_named_guests_operation_is_a_bound_requirement(requirement):
    quote = 'Guests can comment on pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert any(p['quote'] == requirement for p in row['prerequisites'])


@pytest.mark.parametrize('requirement', [
    'Owners must approve before members can comment on pages.',
    'Owners must approve before guests can edit pages.',
    'Owners must approve before they can comment on pages.',
    'Owners must not approve before guests can comment on pages.',
    'Owners need not approve before guests can comment on pages.',
    'Owners must approve before guests cannot comment on pages.',
])
def test_other_targets_actions_unresolved_pronouns_and_negative_approval_do_not_bind_guest_commenting(requirement):
    quote = 'Guests can comment on pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert not row['prerequisites']


def test_a_denial_of_editing_does_not_erase_the_positive_commenting_target_of_approval():
    quote = 'Guests can comment on pages.'
    requirement = 'Owners must approve before guests can comment on pages, but guests cannot edit pages.'
    row = next(row for row in structured_operations(quote, [quote, requirement], 'Nuclino')
               if row['operation'] == 'comment')
    assert any(p['quote'] == requirement for p in row['prerequisites'])


PAST_SELECTOR = ('Please make sure that you chose Can edit, Can comment or Can view next to Anyone with the link '
                 'option and sent the board link copied from the board Share menu or from the browser address bar, '
                 'it should have the following format:')


@pytest.mark.parametrize('verb', ['choose', 'chose', 'selected', 'set'])
def test_public_permission_selector_word_forms_are_configuration_not_actual_edit_or_comment(verb):
    quote = PAST_SELECTOR.replace('chose', verb)
    value = extracted(quote, VISITOR_PLAN)
    assert VISITOR_PLAN in value['conditions']
    rows = value['operations']
    assert rows and {row['operation'] for row in rows} == {'manage_access'}
    assert rows[0]['role'] == 'you'
    assert any(p['kind'] == 'permission_option' and p['quote'] == VISITOR_PLAN
               and set(p['operations'].split(',')) == {'edit', 'comment'} for p in rows[0]['prerequisites'])
    assert not any('Enterprise plans' in p['quote'] for p in rows[0]['prerequisites'])


def selector_original_and_claim(text):
    value = extracted(PAST_SELECTOR, VISITOR_PLAN)
    original = fact('Nuclino', PAST_SELECTOR, slot='past-selector', qualifiers={'operations': value['operations']})
    original = original.model_copy(update={'value_json': canonical_json(value['evidence_terms'])})
    row = next(row for row in operation_observations(original) if row['operation'] == 'manage_access')
    claim = ReportClaim(id='selector', text=text, kind='fact', competitor='Nuclino', dimension='feature',
                        fact_ids=[original.id], source_ids=[original.source_id], operation_binding=operation_binding(row))
    return original, claim


@pytest.mark.parametrize('text', [
    'Choose Can edit or Can comment for Anyone with the link; Visitors can edit or comment on boards.',
    '在 Anyone with the link 旁选择 Can edit 或 Can comment，持有链接的 Visitor 可编辑或评论看板。',
])
def test_a_supported_selector_review_cannot_omit_the_receivers_edit_and_comment_plan_condition(text):
    original, claim = selector_original_and_claim(text)
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert 'operation_plan_condition_omitted_or_changed' in result.rule_reasons


@pytest.mark.parametrize('text', [
    'On paid and Education plans, choose Can edit or Can comment for Anyone with the link; Visitors can edit or comment on boards.',
    '付费或 Education 套餐下，在 Anyone with the link 旁选择 Can edit 或 Can comment，Visitor 可编辑或评论看板。',
])
def test_complete_selector_and_receiver_plan_condition_remains_publishable(text):
    original, claim = selector_original_and_claim(text)
    assert audit(original, claim).status == 'supported'


def test_view_only_selection_does_not_inherit_the_edit_and_comment_plan_restriction():
    original, claim = selector_original_and_claim('Choose Can view next to Anyone with the link for Visitors.')
    assert audit(original, claim).status == 'supported'


WARNING_SELECTOR = ('Sharing a public board with edit access for Visitors⚠️ If you allow Can edit this includes '
                    'all future users as well as users you’ve already added as viewers or commenters.')


@pytest.mark.parametrize('verb', ['allow', 'allowed', 'enable', 'grant'])
def test_captioned_permission_setting_warning_binds_the_receivers_plan_not_the_operators_role(verb):
    quote = WARNING_SELECTOR.replace('allow', verb)
    value = extracted(quote, VISITOR_PLAN)
    assert {row['operation'] for row in value['operations']} == {'manage_access'}
    row = value['operations'][0]
    assert row['role'] == 'you'
    assert row['recipient_quote'] == 'Visitors'
    assert any(p['kind'] == 'permission_option' and p['operations'] == 'edit'
               and p['quote'] == VISITOR_PLAN for p in row['prerequisites'])
    assert not any('Enterprise plans' in p['quote'] for p in row['prerequisites'])


def test_an_explicit_guest_receiver_in_the_caption_is_not_replaced_by_the_visitor_document_heading():
    quote = WARNING_SELECTOR.replace('Visitors', 'Guests')
    guest_plan = 'Editing is only available for Guests on Enterprise plans.'
    value = extracted(quote, VISITOR_PLAN, other_condition=guest_plan)
    row = next(row for row in value['operations'] if row['operation'] == 'manage_access')
    assert row['role'] == 'you'
    assert row['recipient_quote'] == 'Guests'
    assert any(p['kind'] == 'permission_option' and p['operations'] == 'edit'
               and p['quote'] == guest_plan for p in row['prerequisites'])
    assert not any(p['quote'] == VISITOR_PLAN for p in row['prerequisites'])


def test_a_later_unrelated_access_sentence_does_not_supply_the_permission_settings_receiver():
    from packages.research.evidence.operations import permission_selector_context
    quote = ('If you allow Can edit, this applies to future users. '
             'Owners require access for Guests on Enterprise plans.')
    selector = permission_selector_context(quote, 'Visitors')
    assert selector['recipient_role'] is None
    assert selector['recipient_quote'] is None


def warning_original_and_claim(text):
    value = extracted(WARNING_SELECTOR, VISITOR_PLAN)
    original = fact('Nuclino', WARNING_SELECTOR, slot='caption-warning', qualifiers={'operations': value['operations']})
    original = original.model_copy(update={'value_json': canonical_json(value['evidence_terms'])})
    row = next(row for row in operation_observations(original) if row['operation'] == 'manage_access')
    claim = ReportClaim(id='warning', text=text, kind='fact', competitor='Nuclino', dimension='feature',
                        fact_ids=[original.id], source_ids=[original.source_id], operation_binding=operation_binding(row))
    return original, claim


@pytest.mark.parametrize('text', [
    'You can allow Can edit for Visitors, including all future users and existing viewers or commenters.',
    '你可以允许 Visitor 使用可编辑权限，该设置作用于未来用户以及已有查看者或评论者。',
])
def test_warning_supported_review_cannot_omit_the_edit_availability_condition(text):
    original, claim = warning_original_and_claim(text)
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert 'operation_plan_condition_omitted_or_changed' in result.rule_reasons


@pytest.mark.parametrize('text', [
    'On paid and Education plans, you can allow Can edit for Visitors, including future users and existing viewers or commenters.',
    '在付费或 Education 套餐下，你可以允许 Visitor 使用可编辑权限，该设置作用于未来用户以及已有查看者或评论者。',
])
def test_warning_with_complete_receiver_plan_condition_remains_publishable(text):
    original, claim = warning_original_and_claim(text)
    assert audit(original, claim).status == 'supported'
