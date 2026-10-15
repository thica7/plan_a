"""Original operation assertions through reviewed prose and matrix projection."""
from types import SimpleNamespace

import pytest

from test_capability_alignment import fact
from packages.research.evidence.operations import operation_matches_text, operation_observations, operation_binding


@pytest.mark.parametrize('text', [
    '成员可以创建和编辑数据库内的页面。',
    '成员可以创建和编辑数据库内的文档。',
    '成员可以创建工作区内的页面。',
])
def test_create_preserves_original_object_qualifiers(text):
    assert operation_matches_text('create', text)


@pytest.mark.parametrize('text', [
    'You can change a user’s access on the doc by modifying their access directly from the sharing dialog',
    'Members can change permissions using the sharing settings.',
    'Members can open the Share dialog.',
])
def test_sharing_ui_name_does_not_assert_document_sharing(text):
    rows = operation_observations(fact('Coda', text, slot='ui'))
    assert not any(row['operation'] == 'share' for row in rows)


def test_share_action_survives_a_sharing_ui_reference():
    assert operation_matches_text('share', 'Editors can share the doc through the sharing dialog.')


@pytest.mark.parametrize('text', ['成员可以创建权限。', '成员可以创建数据库内的评论。', '成员可以创建页面模板。'])
def test_create_does_not_widen_other_operation_objects(text):
    assert not operation_matches_text('create', text)


def test_reviewed_notion_create_reaches_its_matrix_cell():
    from packages.agents.writer.dimension_writer import render_operation_comparison
    from packages.research.evidence.report_claims import ReportClaim, ReportDimensionAudit, AuditedReportClaim
    original = fact('Notion', '- Can edit content: People with this level of access can create and edit pages within the database.', slot='create')
    claim = ReportClaim(id='create', text='成员可以创建和编辑数据库内的页面。', kind='fact', competitor='Notion', dimension='feature', fact_ids=[original.id], source_ids=[original.source_id], operation_binding=operation_binding(next(row for row in operation_observations(original) if row['operation'] == 'create')))
    audit = ReportDimensionAudit(competitor='Notion', dimension='feature', consumption_id='use', claims=[AuditedReportClaim(claim=claim, status='supported')])
    detail = SimpleNamespace(topic='创建页面', output_language='zh-CN', plan=SimpleNamespace(competitors=['Notion'],dimensions=['feature'],target_product=None))
    table = '\n'.join(render_operation_comparison(detail, [audit], snapshot=SimpleNamespace(facts=[original],source_ids=[original.source_id], operation_binding=operation_binding(next(row for row in operation_observations(original) if row['operation'] == 'create')))))
    assert '| 创建 | 成员可以创建和编辑数据库内的页面。' in table
    assert '未取得已审核观察' not in table


@pytest.mark.parametrize(('role', 'description', 'expected'), [
    ('Viewer', 'Views and comments on content', {'read', 'comment'}),
    ('Collaborator', 'Creates and edits content', {'create', 'edit'}),
])
def test_vertical_role_definition_table_preserves_actor_and_actions(role, description, expected):
    original = fact('Confluence', f'| {role} | {description} |', slot='role')
    rows = operation_observations(original)
    assert {row['operation'] for row in rows} == expected
    assert all(row['role'] == role and row['quote'] == original.quote for row in rows)
    assert all(row['object_type'] == 'content' and 'plan' in row['missing_fields'] for row in rows)


def test_known_role_table_and_permission_action_are_selected_without_model():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import extract_operation_rules
    role_quote = '| Viewer | Views and comments on content |'
    body = 'Permissions\n| Role | What the role allows |\n|---|---|\n' + role_quote + '\n'
    brief, _, page = qualified_fixture(body, product='Confluence', url='https://support.atlassian.com/confluence-cloud/docs/faq-role-based-access-in-confluence/', headings=[(1, 'Permissions')])
    brief = brief.model_copy(update={'required_fields':['operation.read','operation.comment']})
    fields = extract_operation_rules(brief, page).fields
    assert {row['operation'] for f in fields.values() for row in f['operations']} == {'read', 'comment'}


def test_explicit_assignment_rule_is_selected_without_ui_steps():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import extract_operation_rules
    quote = 'For every person, group, or teamspace you share a page with, you can assign a different permission level.'
    brief, _, page = qualified_fixture('Access levels\n'+quote, product='Notion', url='https://www.notion.com/help/sharing-and-permissions', headings=[(1, 'Access levels')])
    result = extract_operation_rules(brief,page)
    assert any(row['operation']=='manage_access' for f in result.fields.values() for row in f['operations'])


def test_repair_capture_prioritizes_missing_operation_before_more_role_pages():
    from packages.research.models import ResearchBrief,SourceCandidate
    from packages.research.capture.selection import select_capture_candidates
    brief = ResearchBrief(run_id='target',topic='文档权限',competitor='Nuclino',dimension='feature',product_category='文档',target_source_count=1,max_fetches=1,metadata={'operation_repair_targets':['create']})
    candidates=[SourceCandidate(origin='manual',url='https://help.nuclino.com/roles',title='Roles and permissions',competitor='Nuclino',dimension='feature'),SourceCandidate(origin='manual',url='https://help.nuclino.com/create-an-item',title='Create an item',competitor='Nuclino',dimension='feature')]
    assert select_capture_candidates(brief,candidates).selected[0].title=='Create an item'


def test_verified_missing_operation_pages_are_registered():
    from packages.business_intel.entity_resolver import resolve_competitor_identity
    expected={'Nuclino':'https://help.nuclino.com/01dd45c4-create-an-item','Confluence':'https://support.atlassian.com/confluence-cloud/docs/faq-role-based-access-in-confluence/','Coda':'https://help.superhuman.com/hc/en-us/articles/46210170717965-Control-sharing-of-docs-and-Packs'}
    for product,url in expected.items():
        assert url in {s.url for s in resolve_competitor_identity(product).sources_by_dimension['feature']}


def test_repair_orders_absent_action_before_incomplete_plan():
    from packages.research.models import QualityGap,ResearchBrief
    from packages.research.repair.planner import repair_tasks_from_gaps
    from packages.research.pipeline import _same_branch_repairs,_repair_brief
    tasks=repair_tasks_from_gaps([QualityGap(severity='warn',acceptance_rule='Bind operation and conditions to official evidence',dimension='feature',competitor='Nuclino',field='operation.comment',reason='plan unknown',suggested_action='targeted_discovery',metadata={'source':'operation_comparison','operation':'comment','missing_fields':['plan']}),QualityGap(severity='warn',acceptance_rule='Bind operation and conditions to official evidence',dimension='feature',competitor='Nuclino',field='operation.create',reason='missing operation',suggested_action='targeted_discovery',metadata={'source':'operation_comparison','operation':'create','missing_fields':['operation_evidence']})])
    brief=ResearchBrief(run_id='repair',topic='文档权限',competitor='Nuclino',dimension='feature',product_category='文档')
    selected=_same_branch_repairs(brief,tasks)
    assert selected[0].metadata['operation']=='create'
    assert _repair_brief(brief,selected,round_index=1).metadata['operation_repair_targets']==['create']


def test_same_operation_plan_branches_preserve_capacity_limits():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import semantic_extraction
    quote='Only workspace members with full access can create items.'
    limits='On the Free plan, you can create up to 50 items. On the paid plans, you can create an unlimited number of items.'
    brief,_,page=qualified_fixture('Create an item\n'+quote+'\n'+limits, url='https://help.nuclino.com/01dd45c4-create-an-item',headings=[(1,'Create an item')])
    rows=next(iter(semantic_extraction(brief,page,{'facts':[{'quote':quote}]}).fields.values()))['operations']
    assert rows[0]['plan']=='Free plan / paid plans'
    assert any(limits in p['quote'] for p in rows[0]['prerequisites'])


def test_other_operation_or_role_plan_branch_is_not_borrowed():
    from packages.research.evidence.operations import structured_operations
    quote='Full access: Members can create items.'
    for condition in ['On the Free plan, you can edit items.', 'On the Free plan, guests can create items.']:
        assert structured_operations(quote,[quote,condition],'Nuclino')[0]['plan'] is None


def test_rule_selection_keeps_complete_creation_before_incomplete_multi_action():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import extract_operation_rules
    lines=['Members can create and edit pages in this workspace.', 'Members can read pages in this workspace.', 'Members can comment on pages in this workspace.', 'Members can share pages in this workspace.', 'Members can change permissions on pages in this workspace.', 'Members can view pages shared with other members.', 'Can create: Members on Business and Enterprise plans can create new pages within the database.']
    brief,_,page=qualified_fixture('Access levels\n'+'\n'.join(lines),product='Notion',url='https://www.notion.com/help/sharing-and-permissions',headings=[(1,'Access levels')])
    result=extract_operation_rules(brief,page)
    assert any(row['operation']=='create' and not row['missing_fields'] for f in result.fields.values() for row in f['operations'])


def test_page_creation_plan_does_not_bind_document_creation():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote='Doc Makers can create new docs in the workspace.'
    condition='On the Free plan, you can create pages within an existing doc.'
    brief,candidate,page=qualified_fixture('Creating docs\n'+quote+'\n'+condition,product='Coda',url='https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors',headings=[(1,'Creating docs')])
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    row=next(iter(result.fields.values()))['operations'][0]
    assert row['object_type']=='document' and row['plan'] is None
    assert 'plan' in row['missing_fields']
    items=admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])
    assert items[0].status=='accepted'


def test_item_creation_translation_reaches_reviewed_matrix():
    from packages.agents.writer.dimension_writer import render_operation_comparison
    from packages.research.evidence.report_claims import ReportClaim,ReportDimensionAudit,AuditedReportClaim
    original=fact('Nuclino','Only workspace members with full access can create items.',slot='item')
    claim=ReportClaim(id='item',text='只有拥有完整访问权限的工作区成员可以创建条目。',kind='fact',competitor='Nuclino',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id], operation_binding=operation_binding(next(row for row in operation_observations(original) if row['operation'] == 'create')))
    audit=ReportDimensionAudit(competitor='Nuclino',dimension='feature',consumption_id='use',claims=[AuditedReportClaim(claim=claim,status='supported')])
    detail=SimpleNamespace(topic='创建页面',output_language='zh-CN',plan=SimpleNamespace(competitors=['Nuclino'],dimensions=['feature'],target_product=None))
    table='\n'.join(render_operation_comparison(detail,[audit],snapshot=SimpleNamespace(facts=[original],source_ids=[original.source_id], operation_binding=operation_binding(next(row for row in operation_observations(original) if row['operation'] == 'create')))))
    assert '| 创建 | 只有拥有完整访问权限的工作区成员可以创建条目。' in table


@pytest.mark.asyncio
async def test_late_repair_keeps_gap_targets_in_final_fetch_selection(monkeypatch):
    from packages.research.models import ResearchBrief,SourceCandidate
    from packages.research.pipeline import run_research_pipeline
    from packages.research.extraction.semantic import semantic_extraction
    from packages.search import SearchResult
    # Limit each pass to one query so the second repair uses the late branch.
    from packages.research import pipeline
    from packages.research.discovery.planner import build_search_queries
    monkeypatch.setattr(pipeline,'build_search_queries',lambda active,**kwargs:build_search_queries(active,**kwargs)[:1])
    seed=SourceCandidate(origin='manual',url='https://www.notion.com/help/sharing-and-permissions',title='Notion editing',competitor='Notion',dimension='feature')
    brief=ResearchBrief(run_id='late',topic='比较创建页面',competitor='Notion',dimension='feature',product_category='文档',research_depth='standard',max_repair_rounds=2,target_source_count=1,max_fetches=2,max_search_queries=2,max_candidates=3,include_homepage_candidates=False,include_trusted_sources=False)
    searches=[];fetched=[]
    async def search(query,limit):
        searches.append(query)
        if len(searches)==1:return []
        return [SearchResult(title='Notion roles and permissions',url='https://www.notion.com/help/new-roles',snippet='roles'),SearchResult(title='Notion create pages',url='https://www.notion.com/help/create-pages',snippet='creation')]
    async def fetch(url):
        fetched.append(url)
        text='Members on all plans can create pages in the workspace.' if url.endswith('/create-pages') else 'Members on all plans can edit documents in the workspace.'
        return SimpleNamespace(url=url,title='Notion permissions',text=text,ok=True,status='ok',quality_score=.9,content_hash=url,metadata={})
    async def semantic(active,page):return semantic_extraction(active,page,{'facts':[{'quote':page.text}]})
    result=await run_research_pipeline(brief,fetch=fetch,search=search,seed_candidates=[seed],semantic_extract=semantic)
    assert len(searches)==2 and len(fetched)==2
    assert result.metrics['repair_round_count']==2
    assert fetched[-1].endswith('/create-pages')
    assert not any(g.metadata.get('operation')=='create' for g in result.gaps)


def test_permission_assignment_does_not_assert_recipient_sharing_action():
    quote='For every person, group, or teamspace you share a page with, you can assign a different permission level.'
    rows=operation_observations(fact('Notion',quote,slot='assign'))
    assert {r['operation'] for r in rows}=={'manage_access'}


def test_generic_access_rule_does_not_inherit_adjacent_role_restrictions():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote='For every person, group, or teamspace you share a page with, you can assign a different permission level.'
    restriction='Can create: Members on Business and Enterprise plans can create pages but cannot edit pages.'
    body='Access levels\n'+quote+'\nHere are the available permission levels:\n'+restriction
    brief,candidate,page=qualified_fixture(body,product='Notion',url='https://www.notion.com/help/sharing-and-permissions',headings=[(1,'Access levels')])
    e=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    value=next(iter(e.fields.values()))
    assert all(restriction not in term for term in value['evidence_terms'])
    assert all(r['plan'] is None and not r['prerequisites'] for r in value['operations'])
    assert admit_evidence_items([e],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


@pytest.mark.parametrize('quote', [
    'Team owners and admins can disable public item sharing using advanced security controls.',
    'Workspace admins can manage sharing settings for docs.',
])
def test_control_over_sharing_is_not_permission_to_share(quote):
    assert not any(r['operation']=='share' for r in operation_observations(fact('Nuclino',quote,slot='control')))


def test_start_sharing_documents_is_still_a_source_bound_action():
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote='Members on all plans can start sharing documents with invited editors.'
    brief,candidate,page=qualified_fixture(quote,product='Notion',url='https://www.notion.com/help/sharing-and-permissions')
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    rows=next(iter(result.fields.values()))['operations']
    assert any(r['operation']=='share' and r['object_type']=='document' for r in rows)
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


@pytest.mark.parametrize('negative',['must not be sharing','will not be sharing','must not start sharing'])
def test_negative_sharing_form_is_never_an_allowed_permission(negative):
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote=f'Members on all plans {negative} documents with invited editors.'
    brief,candidate,page=qualified_fixture(quote,product='Notion',url='https://www.notion.com/help/sharing-and-permissions')
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    rows=next(iter(result.fields.values()))['operations']
    assert all(r['effect']=='denied' for r in rows if r['operation']=='share')
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


@pytest.mark.parametrize('negative',['must not be sharing','will not be sharing','must not start sharing'])
def test_negative_sharing_does_not_deny_previous_comment_action(negative):
    from test_qualified_operations import qualified_fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote=f'Members on all plans can comment on pages and {negative} documents.'
    brief,candidate,page=qualified_fixture(quote,product='Notion',url='https://www.notion.com/help/sharing-and-permissions')
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    rows=next(iter(result.fields.values()))['operations']
    assert {r['operation']:r['effect'] for r in rows}=={'comment':'allowed','share':'denied'}
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'
