"""Offline regressions from captured permission guides; no provider calls."""
from types import SimpleNamespace

import pytest

from test_capability_alignment import fact
from test_qualified_operations import qualified_fixture
from packages.research.evidence.operations import operation_binding, operation_observations, structured_operations
from packages.research.evidence.report_claims import ReportClaim, ReportOperationBinding, claim_rule_reasons
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.extraction.semantic import semantic_extraction


INVITED = '- Only people invited : This means only you and people you invite can access your page.'
WEB = '- Anyone on the web with link : This means that anyone who has the link to your page can access it, even if they aren’t part of your workspace or aren’t a Notion user. Note that page visitors will need to be logged into Notion if they want to comment on or edit your page.'
CHOICE = 'Here, you can choose to share your page with:\n' + INVITED + '\n' + WEB
COMMENT = '- Can comment : Select this level of access for people who should only have the ability to comment on a page. They won’t be able to edit or share the content.'
VIEW = '- Can view : People with this level of access can read the content on the page, but they won’t be able to comment, edit, or share.'
CONFIGURE = 'For example, in an “Open” state, you can change the permission for anyone in the space from “Can edit” to “Can view”. This will restrict who can edit the content item. In this state, you can then use the search bar to add people or groups to Specific access with “Can edit” permission.'
RESTRICTION = 'To list a person or group with specific access, you’ll need to add a restriction to the general access of the content item, then add individuals or groups. (Teams are not supported in the unified sharing experience yet.)'
FREE = 'You can’t restrict access to content on the free plan.'


def extracted_role(quote):
    body = 'Sharing & permissions settings\nGeneral access\n' + CHOICE + '\nAccess levels\n' + COMMENT + '\n' + VIEW
    brief, _, page = qualified_fixture(body, product='Notion', url='https://www.notion.com/help/sharing-and-permissions', headings=[(1,'Sharing & permissions settings'),(2,'General access'),(2,'Access levels')])
    result = semantic_extraction(brief, page, {'facts':[{'quote':quote}]})
    value = next(iter(result.fields.values()))
    original = fact('Notion', quote, slot='access-mode', qualifiers={'operations':value['operations']})
    original = original.model_copy(update={'value_json':canonical_json(value['evidence_terms'])})
    return value, original


@pytest.mark.parametrize(('quote','operation','effect'), [(COMMENT,'comment','allowed'),(COMMENT,'edit','denied'),(COMMENT,'share','denied'),(VIEW,'read','allowed')])
def test_alternative_general_access_modes_are_not_universal_prerequisites(quote, operation, effect):
    value, original = extracted_role(quote)
    rows = operation_observations(original)
    row = next(row for row in rows if row['operation']==operation)
    assert row['effect']==effect
    assert row.get('condition_groups') == [{'operator':'any_of','options':[INVITED,WEB]}]
    assert all(INVITED not in p['quote'] and WEB not in p['quote'] for p in row['prerequisites'])
    assert INVITED in str(value['evidence_terms']) and WEB in str(value['evidence_terms'])
    binding = operation_binding(row)
    assert ReportOperationBinding(**binding).model_dump(mode='json') == binding
    assert binding['condition_groups'][0]['options'][1] == WEB  # Login stays in its web branch.


def test_permission_configuration_is_not_actual_document_editing():
    rows = structured_operations(CONFIGURE, [CONFIGURE,RESTRICTION,FREE], 'Confluence')
    assert rows and {row['operation'] for row in rows} == {'manage_access'}
    assert any(FREE in p['quote'] for row in rows for p in row['prerequisites'])
    assert any(RESTRICTION in p['quote'] for row in rows for p in row['prerequisites'])


@pytest.mark.parametrize(('quote','effect'), [('Editors can edit content items.','allowed'),('Viewers cannot edit content items.','denied')])
def test_document_actions_do_not_inherit_permission_configuration_limits(quote, effect):
    row = next(row for row in structured_operations(quote, [quote,RESTRICTION,FREE], 'Confluence') if row['operation']=='edit')
    assert row['effect']==effect and row['object_type']=='item'
    assert not row['prerequisites']


def test_actual_only_and_parent_access_remain_mandatory():
    quote = 'Only invited members with full access can edit documents.'
    parent = 'You must have access to the parent workspace.'
    row = structured_operations(quote, [quote,parent], 'Notion')[0]
    assert row['operation']=='edit' and row['effect']=='allowed'
    assert {'kind':'shared_access','quote':quote.rstrip('.')} in row['prerequisites']
    assert {'kind':'parent_access','quote':parent} in row['prerequisites']
    assert not row.get('condition_groups')


@pytest.mark.parametrize('text', [
    '在 Notion 中，“Can view”角色可阅读页面内容，前提是访问范围设置为仅受邀者（Only people invited）。',
    'Can view can read the page only with Only people invited general access.',
])
def test_supported_review_cannot_promote_one_access_mode_to_a_universal_requirement(text):
    _, original = extracted_role(VIEW)
    row = next(row for row in operation_observations(original) if row['operation']=='read')
    claim = ReportClaim(id='scope',text=text,kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=operation_binding(row))
    reasons = claim_rule_reasons(claim, SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert 'operation_alternative_condition_promoted' in reasons


@pytest.mark.parametrize('text', [
    'Can view 角色可阅读页面内容；一般访问可选择 Only people invited 或 Anyone on the web with link。',
    '当一般访问选择 Only people invited 模式时，仅受邀者可访问；Can view 可阅读页面内容。',
    'Can view 角色可阅读页面内容。',
])
def test_branch_local_or_independent_capability_claims_remain_publishable(text):
    _, original = extracted_role(VIEW)
    row = next(row for row in operation_observations(original) if row['operation']=='read')
    claim = ReportClaim(id='scope',text=text,kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=operation_binding(row))
    reasons = claim_rule_reasons(claim, SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert not reasons


def test_legacy_binding_serialization_and_identity_omit_absent_scope_metadata():
    row = operation_observations(fact('Notion','Members can edit documents.',slot='legacy'))[0]
    binding = operation_binding(row)
    assert 'condition_groups' not in binding
    assert ReportOperationBinding(**binding).model_dump(mode='json') == binding
    assert binding['observation_id'] == 'operation-a04afcb45dc40433dbfeea90'


def test_nested_help_steps_do_not_end_the_access_mode_list_before_public_access():
    workspace = '- Everyone at {your workspace} : This means other workspace members can access your page using search or using the link.\n  - Open the dropdown next to Everyone at {your workspace} and toggle onHide in search to hide this page from search results for any users who haven’t visited the page before or don’t already have the link to the page.'
    public = WEB + '\n  - If you want access to this link to expire, open the dropdown next to Anyone on the web with link . Open the dropdown next toLink expires and select a time or date.\n  - Enterprise workspace owners can disable these public sharing links by going to Settings →Security and toggling onDisable publishing sites, forms and public links .'
    choice = 'You can manage general access to your page by selecting Share at the top of a page and configuring General access. Here, you can choose to share your page with:\n'+INVITED+'\n'+workspace+'\n'+public
    body = 'Sharing & permissions settings\nGeneral access\n'+choice+'\nAccess levels\n'+COMMENT+'\n'+VIEW
    brief, candidate, page = qualified_fixture(body, product='Notion', url='https://www.notion.com/help/sharing-and-permissions', headings=[(1,'Sharing & permissions settings'),(2,'General access'),(2,'Access levels')])
    result = semantic_extraction(brief,page,{'facts':[{'quote':COMMENT},{'quote':VIEW}]})
    assert len(result.fields)==2
    for value in result.fields.values():
        for row in value['operations']:
            assert row['condition_groups']==[{'operator':'any_of','options':[INVITED,workspace,public]}]
            assert not any('Only people invited' in p['quote'] or 'logged into' in p['quote'] or 'Enterprise workspace owners' in p['quote'] for p in row['prerequisites'])
    from packages.research.evidence.admission import admit_evidence_items
    assert all(item.status=='accepted' for item in admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate]))


def test_access_control_and_actual_edit_actions_keep_their_own_effects_and_objects():
    quote = 'Editors on the Free plan can edit content items, but administrators cannot restrict access to content on the Free plan.'
    rows = structured_operations(quote,[quote],'Confluence')
    assert {row['operation']:row['effect'] for row in rows}=={'edit':'allowed','manage_access':'denied'}
    edit, manage = rows
    assert edit['object_type']=='item' and manage['object_type']=='access_control'
    assert not edit['prerequisites']


def test_legacy_isolated_mode_definitions_do_not_establish_universal_prerequisites():
    rows = structured_operations(VIEW,[VIEW,INVITED,WEB],'Notion')
    assert rows and rows[0]['operation']=='read'
    assert not rows[0].get('condition_groups')  # Original selector was not captured.
    assert not any(INVITED in p['quote'] or WEB in p['quote'] for row in rows for p in row['prerequisites'])


def test_server_binding_and_review_payload_preserve_exact_alternative_scopes():
    from packages.agents.writer.dimension_writer import compact_dimension_context,review_payload
    from packages.research.evidence.operations import bound_operation_observation
    _, original = extracted_role(VIEW)
    view = SimpleNamespace(facts=[original],sources=[])
    row = next(row for row in operation_observations(original) if row['operation']=='read')
    binding = operation_binding(row)
    claim = ReportClaim(id='scope',text='Can view 角色可阅读页面。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=binding)
    assert bound_operation_observation(claim,{original.id:original}) == row
    context, omitted = compact_dimension_context({'segment_competitor':'Notion','dimension':'feature'},view,{original.id},requested_operations=('read',))
    assert not omitted
    assert context['evidence_view']['facts'][0]['operation_observations'][0]['condition_groups']==binding['condition_groups']
    payload = review_payload([claim],view)
    assert payload['claims'][0]['operation_binding']['condition_groups']==binding['condition_groups']
    assert payload['facts'][0]['qualifiers']['operations'][0]['condition_groups']==binding['condition_groups']
    altered = {**binding,'condition_groups':[{'operator':'any_of','options':[WEB,INVITED]}]}
    forged = claim.model_copy(update={'operation_binding':ReportOperationBinding(**altered)})
    assert bound_operation_observation(forged,{original.id:original}) is None


@pytest.mark.parametrize('requirement', [
    'Only invited people can access pages.',
    'You must view the page of the parent space before creating content.',
])
def test_real_access_and_parent_requirements_are_not_lost_as_other_read_actions(requirement):
    quote='Members can comment on pages.'
    rows=structured_operations(quote,[quote,requirement],'Notion')
    assert any(p['quote']==requirement for row in rows for p in row['prerequisites'])


@pytest.mark.parametrize('text', [
    'Can view 角色阅读页面的前提是 Only people invited 或 Anyone on the web with link，Everyone at {your workspace} 模式不允许阅读。',
    'Can view 角色可阅读页面，前提是必须先开启 Only people invited 或 Anyone on the web with link，并且所有访问者都需要登录 Notion。',
    '如果内容敏感则谨慎分享；Can view 角色阅读页面的前提是 Only people invited。',
    '当一般访问选择 Only people invited 模式时，仅受邀者可访问；所有访问者都必须登录。',
    'When Only people invited is selected, invited people can access the page, but Anyone on the web with link cannot read the page.',
    '当一般访问选择 Only people invited 模式时，仅受邀者可访问，所有访问者都必须登录。',
    '当一般访问选择 Only people invited 模式时，仅受邀者可访问，阅读页面的前提是 Only people invited。',
])
def test_independent_spec_rejects_global_promotions_despite_other_modes_or_conditions(text):
    from packages.research.evidence.report_claims import audit_report_claims
    workspace='- Everyone at {your workspace} : This means other workspace members can access your page using search or using the link.'
    choice='Here, you can choose to share your page with:\n'+INVITED+'\n'+workspace+'\n'+WEB
    original=fact('Notion',VIEW,slot='spec-three-mode')
    original=original.model_copy(update={'value_json':canonical_json([VIEW,choice]),'qualifiers_json':canonical_json({'operations':structured_operations(VIEW,[VIEW,choice],'Notion')})})
    row=next(row for row in operation_observations(original) if row['operation']=='read')
    claim=ReportClaim(id='spec',text=text,kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=operation_binding(row))
    result=audit_report_claims([claim],[{'claim_id':'spec','verdict':'supported','reason':'Forced-supported test, not an actual semantic judgment.'}],SimpleNamespace(facts=[original]),[SimpleNamespace(allowed_fact_ids=[original.id])])[0]
    assert result.status=='rejected'
    assert 'operation_alternative_condition_promoted' in result.rule_reasons


@pytest.mark.parametrize(('quote','condition','kind'), [
    ('Members can edit documents.','- Eligibility: This means only invited members can access your documents.','shared_access'),
    ('Only members with permission to manage access can edit documents.',None,'permission'),
    ('Members can edit documents.','You must manage access to the parent workspace before editing documents.','parent_access'),
])
def test_independent_spec_retains_eligibility_and_bound_management_prerequisites(quote,condition,kind):
    terms=[quote,*([condition] if condition else [])]
    row=next(row for row in structured_operations(quote,terms,'Notion') if row['operation']=='edit')
    expected=condition or quote.rstrip('.')
    assert {'kind':kind,'quote':expected} in row['prerequisites']


@pytest.mark.parametrize('text', [
    '当一般访问选择 Only people invited 模式时，仅受邀者可访问；Can view 可阅读页面内容。',
    'When Only people invited is selected, only invited people can access the page; Can view can read the page.',
    '在 Anyone on the web with link 模式下，访客评论需要登录；Can view 可阅读页面。',
    'Can view 角色可阅读页面；一般访问可选择 Only people invited 或 Anyone on the web with link。',
])
def test_explicit_mode_local_branches_remain_valid_after_scope_guard_tightening(text):
    _,original=extracted_role(VIEW)
    row=next(row for row in operation_observations(original) if row['operation']=='read')
    claim=ReportClaim(id='spec',text=text,kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=operation_binding(row))
    assert not claim_rule_reasons(claim,SimpleNamespace(facts=[original]),[SimpleNamespace(allowed_fact_ids=[original.id])])


@pytest.mark.parametrize(('choice','options'), [
    (CHOICE.replace(':\n-', ':\n\n-'), [INVITED,WEB]),
    (CHOICE.replace('\n- Anyone', '\n\n- Anyone'), [INVITED,WEB]),
    (CHOICE.replace('This means only', 'This means\n  only'), [INVITED.replace('This means only', 'This means\n  only'),WEB]),
    (CHOICE.replace('This means only', 'This means\n\n  only'), [INVITED.replace('This means only', 'This means\n\n  only'),WEB]),
    (CHOICE.replace(' Note that', '\n\n  Note that'), [INVITED,WEB.replace(' Note that', '\n\n  Note that')]),
    (CHOICE + '\n\n  - Visitors need to log in before commenting.\n\n    Only signed-in visitors can edit your page.',
     [INVITED,WEB + '\n\n  - Visitors need to log in before commenting.\n\n    Only signed-in visitors can edit your page.']),
])
@pytest.mark.parametrize(('quote','operation','role'), [(VIEW,'read','Can view'),(COMMENT,'comment','Can comment')])
def test_formatted_access_modes_survive_extraction_admission_binding_and_audit(choice, options, quote, operation, role):
    from packages.research.evidence.admission import admit_evidence_items
    from packages.research.evidence.operations import bound_operation_observation
    from packages.research.evidence.report_claims import audit_report_claims
    body = 'Sharing & permissions settings\nGeneral access\n' + choice + '\nAccess levels\n' + COMMENT + '\n' + VIEW
    brief, candidate, page = qualified_fixture(body, product='Notion', url='https://www.notion.com/help/sharing-and-permissions', headings=[(1,'Sharing & permissions settings'),(2,'General access'),(2,'Access levels')])
    result = semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    admitted = admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])
    assert len(admitted)==1 and admitted[0].status=='accepted'
    value = admitted[0].value
    original = fact('Notion',quote,slot='formatted-modes',qualifiers={'operations':value['operations']}).model_copy(update={'value_json':canonical_json(value['evidence_terms'])})
    row = next(row for row in operation_observations(original) if row['operation']==operation)
    binding = operation_binding(row)
    claim = ReportClaim(id='formatted',text=f'{role} 角色{operation}页面的前提是 Only people invited。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=binding)
    assert bound_operation_observation(claim,{original.id:original})==row
    assert ReportOperationBinding(**binding).model_dump(mode='json')==binding
    review = [{'claim_id':claim.id,'verdict':'supported','reason':'Forced-supported offline formatting regression.'}]
    view, boundaries = SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])]
    audit = audit_report_claims([claim],review,view,boundaries)[0]
    assert audit.status=='rejected'
    assert 'operation_alternative_condition_promoted' in audit.rule_reasons
    assert row['condition_groups']==[{'operator':'any_of','options':options}]
    branch_lines = {line.strip() for option in options for line in option.splitlines()}
    assert not any(p['quote'] in branch_lines for p in row['prerequisites'])
    independent = claim.model_copy(update={'text':f'{role} 角色可{operation}页面内容。'})
    assert audit_report_claims([independent],review,view,boundaries)[0].status=='supported'


@pytest.mark.parametrize('ending', ['Access levels','## Access levels','  ## Access levels','These rules apply to all pages.',VIEW])
def test_formatted_mode_list_stops_before_outer_text_and_keeps_real_requirements(ending):
    from packages.research.evidence.operations import alternative_condition_blocks
    quote = 'Members can edit documents.'
    parent = 'You must have access to the parent workspace.'
    only = 'Only invited members can access pages.'
    choice = CHOICE.replace('\n- Anyone', '\n\n- Anyone')
    terms = [quote,choice+'\n\n'+ending+'\n'+parent+'\n'+only]
    row = next(row for row in structured_operations(quote,terms,'Notion') if row['operation']=='edit')
    assert row['condition_groups']==[{'operator':'any_of','options':[INVITED,WEB]}]
    assert {'kind':'parent_access','quote':parent} in row['prerequisites']
    assert {'kind':'shared_access','quote':only} in row['prerequisites']
    assert alternative_condition_blocks(terms[1])==[CHOICE]
