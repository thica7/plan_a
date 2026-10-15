"""Verified original structure through capture, admission and report projection."""
from types import SimpleNamespace
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'third_party/webfetch_v2'))


def test_capture_restores_headings_at_unique_original_section_anchors():
    from packages.tools.fetch_page import _html_to_text
    html=('<article><h1>Roles and permissions</h1><p>Who can use this feature?</p>'
          '<p>Available on paid plans.</p><h1>Team roles</h1>'
          '<p>On the team level, owners can manage members and billing settings.</p>'
          '<h1>Workspace roles</h1><p>On the workspace level, members can comment on content.</p></article>')
    body=_html_to_text(html)
    assert body.index('Roles and permissions') < body.index('Who can use this feature?')
    assert body.index('Team roles') < body.index('On the team level')
    assert body.index('Workspace roles') < body.index('On the workspace level')


def test_restored_heading_never_guesses_between_repeated_body_anchors():
    from packages.tools.fetch_page import _restore_headings
    from lxml.html import document_fromstring
    sentence='Members can edit documents shared by other members.'
    tree=document_fromstring('<article><h2>Paid roles</h2><p>'+sentence+'</p><h2>Free roles</h2><p>'+sentence+'</p></article>')
    body=sentence+'\n'+sentence
    assert _restore_headings(tree,body)==body


@pytest.mark.parametrize('capture', ['basic', 'advanced'])
def test_restored_headings_do_not_assign_prior_content_to_later_section(capture):
    from packages.research.extraction.semantic import document_condition_context
    first = 'Members can read pages on all plans.'
    second = 'Members can edit documents only on paid plans.'
    html = f'<article><h2>Free roles</h2><p>{first}</p><h2>Paid roles</h2><p>{second}</p></article>'
    if capture == 'basic':
        from packages.tools.fetch_page import _restore_headings
        from lxml.html import document_fromstring
        text = _restore_headings(document_fromstring(html), first + ' ' + second)
    else:
        from webfetch_v2.extract import _restore_headings
        text = _restore_headings(html, first + ' ' + second)
    assert text.index(first) < text.index('Paid roles') < text.index(second)
    _, _, page = qualified_fixture(text, headings=[(2, 'Free roles'), (2, 'Paid roles')])
    begin = text.index(first)
    read_scope = document_condition_context(text, page, begin, begin + len(first))
    assert read_scope is not None
    assert not any('paid plans' in line for line in read_scope[1])
    begin = text.index(second)
    edit_scope = document_condition_context(text, page, begin, begin + len(second))
    assert edit_scope is not None and second in edit_scope[1]


@pytest.mark.parametrize('capture', ['basic', 'advanced'])
def test_original_duplicate_blocks_cannot_locate_a_deduplicated_capture(capture):
    sentence = 'People with this level of access can read pages.'
    html = f'<article><h2>Guests</h2><p>{sentence}</p><h2>Members</h2><p>{sentence}</p></article>'
    if capture == 'basic':
        from packages.tools.fetch_page import _restore_headings
        from lxml.html import document_fromstring
        text = _restore_headings(document_fromstring(html), sentence)
    else:
        from webfetch_v2.extract import _restore_headings
        text = _restore_headings(html, sentence)
    assert text == sentence


@pytest.mark.parametrize('capture', ['basic', 'advanced'])
@pytest.mark.parametrize('attribute', ['hidden', 'aria-hidden="true"', 'style="display:none"', 'style="visibility: hidden"'])
def test_hidden_heading_cannot_be_restored_over_visible_content(capture, attribute):
    sentence = 'Members can read documents with workspace access.'
    html = f'<article><h2 {attribute}>Paid roles</h2><p>{sentence}</p></article>'
    if capture == 'basic':
        from packages.tools.fetch_page import _restore_headings, _document_headings
        from lxml.html import document_fromstring
        text = _restore_headings(document_fromstring(html), sentence)
        headings = _document_headings(html)
    else:
        from webfetch_v2.extract import _restore_headings, extract_headings
        text = _restore_headings(html, sentence)
        headings = extract_headings(html)
    assert text == sentence
    assert not any(heading == 'Paid roles' for _, heading in headings)


@pytest.mark.parametrize('capture', ['basic', 'advanced'])
def test_heading_in_an_inline_hidden_ancestor_cannot_supply_scope(capture):
    sentence = 'Members can read documents with workspace access.'
    html = f'<article><div style="display: none"><h2>Paid roles</h2></div><p>{sentence}</p></article>'
    if capture == 'basic':
        from packages.tools.fetch_page import _restore_headings, _document_headings
        from lxml.html import document_fromstring
        text = _restore_headings(document_fromstring(html), sentence)
        headings = _document_headings(html)
    else:
        from webfetch_v2.extract import _restore_headings, extract_headings
        text = _restore_headings(html, sentence)
        headings = extract_headings(html)
    assert text == sentence
    assert not any(heading == 'Paid roles' for _, heading in headings)


def qualified_fixture(body, *, product='Nuclino', url=None, headings=()):
    from packages.research.models import CapturedPage,ResearchBrief,SourceCandidate
    url=url or 'https://help.nuclino.com/0f8a5a5b-share-an-item'
    brief=ResearchBrief(run_id='qualified',topic='文档权限与六项操作',competitor=product,dimension='feature',product_category='文档')
    candidate=SourceCandidate(origin='manual',url=url,title=product+' permissions',competitor=product,dimension='feature')
    page=CapturedPage(candidate_id=candidate.id,requested_url=url,final_url=url,title=candidate.title,text=body,content_hash='body',status='ok',quality_score=.9,metadata={'document_headings':list(headings)})
    return brief,candidate,page


def test_icon_availability_binds_plan_to_the_same_operation():
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote='Only workspace members with full access can share items.'
    body='Share an item\nWho can use this feature?\n'+quote+'\n⭐️ Available on all plans.\n'
    brief,candidate,page=qualified_fixture(body,headings=[(1,'Share an item')])
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    row=next(iter(result.fields.values()))['operations'][0]
    assert row['plan']=='all plans' and row['access_scope']=='item'
    assert not row['missing_fields']
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


def test_folder_role_plan_enumeration_preserves_all_allowed_tiers():
    from packages.research.extraction.semantic import semantic_extraction
    quote='- Can view: View all docs in the folder. Team/Business and Enterprise only.'
    body='Folder permission levels\nThere are four access levels for folders:\n'+quote+'\n- Can edit: Edit all docs in the folder. Team/Business and Enterprise only.'
    brief,_,page=qualified_fixture(body,product='Coda',url='https://help.superhuman.com/hc/en-us/articles/47804378033677-Share-folders-and-the-docs-within',headings=[(2,'Folder permission levels')])
    row=next(iter(semantic_extraction(brief,page,{'facts':[{'quote':quote}]}).fields.values()))['operations'][0]
    assert row['role']=='Can view'
    assert row['plan']=='Team/Business and Enterprise'
    assert row['object_type']=='document' and 'plan' not in row['missing_fields']


def test_document_maker_is_acting_role_and_compound_creation_is_not_lost():
    from packages.research.evidence.operations import structured_operations
    quote='Doc Makers can create and delete docs, manage doc settings, and create pages.'
    rows=structured_operations(quote,[quote],'Coda')
    assert any(row['operation']=='create' and row['role']=='Doc Makers' and row['object_type']=='document' for row in rows)


def test_role_table_rows_bind_original_columns_and_cell_restrictions():
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    header='|  | Full access | Comment-only | Read-only |'
    quote='| View content | ✅ | ✅ | ✅ |'
    edit='| Edit content | ✅ (except guests) | ✖️ | ✖️ |'
    body='Permissions\n⭐️ Available on all plans.\n'+header+'\n'+quote+'\n'+edit+'\n'
    brief,candidate,page=qualified_fixture(body,url='https://help.nuclino.com/fed9f070-roles-and-permissions',headings=[(1,'Permissions')])
    result=semantic_extraction(brief,page,{'facts':[{'quote':header+'\n'+quote},{'quote':edit}]})
    rows=[r for value in result.fields.values() for r in value['operations']]
    assert {r['role'] for r in rows if r['operation']=='read'}=={'Full access','Comment-only','Read-only'}
    assert {r['role']:r['effect'] for r in rows if r['operation']=='edit'}=={'Full access':'allowed','Comment-only':'denied','Read-only':'denied'}
    assert all(r['plan']=='all plans' for r in rows)
    assert any('except guests' in p['quote'] for r in rows for p in r['prerequisites'])
    assert all(i.status=='accepted' for i in admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate]))


def test_deterministic_rules_use_registered_page_and_same_admission():
    from packages.research.extraction.semantic import extract_operation_rules
    from packages.research.evidence.admission import admit_evidence_items
    quote='Only workspace members with full access can share items.'
    body='Share an item\n'+quote+'\n⭐️ Available on all plans.\n'
    brief,candidate,page=qualified_fixture(body,headings=[(1,'Share an item')])
    result=extract_operation_rules(brief,page)
    assert result.fields
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'
    assert not extract_operation_rules(brief,page.model_copy(update={'final_url':'https://evil.example/help/sharing'})).fields


@pytest.mark.asyncio
async def test_pipeline_admits_explicit_official_rules_without_semantic_model():
    from packages.research.pipeline import run_research_pipeline
    quote='Only workspace members with full access can share items.'
    body='Share an item\n'+quote+'\n⭐️ Available on all plans.\n'
    brief,candidate,_=qualified_fixture(body)
    brief=brief.model_copy(update={'include_trusted_sources':False,'include_homepage_candidates':False,'target_source_count':1,'max_fetches':1,'max_search_queries':0,'max_repair_rounds':0})
    async def fetch(url):return SimpleNamespace(url=url,title='Share an item',text=body,ok=True,status='ok',quality_score=.9,content_hash='original',document_headings=((1,'Share an item'),))
    result=await run_research_pipeline(brief,fetch=fetch,seed_candidates=[candidate])
    rules=[i for i in result.evidence_items if i.status=='accepted' and isinstance(i.value,dict) and i.value.get('operations')]
    assert rules and any(r['operation']=='share' and not r['missing_fields'] for i in rules for r in i.value['operations'])
    assert not any(g.metadata.get('operation')=='share' for g in result.gaps)


def test_writer_fits_original_conditions_by_lossless_text_references():
    import json
    from packages.agents.writer.dimension_writer import compact_dimension_context,compact_prompt_json,encoded
    from packages.research.evidence.operations import operation_binding,operation_observations
    from test_capability_alignment import fact
    conditions='Only invited members can edit the shared document. '+('Parent access must remain valid. '*30)
    first=fact('Notion','Members on all plans can edit documents.',slot='edit')
    second=fact('Notion','Members on all plans can share documents.',slot='share')
    facts=[f.model_copy(update={'value_json':json.dumps([f.quote,conditions]),'qualifiers_json':json.dumps({'context':[conditions]*4})})for f in (first,second)]
    # Quick evidence views allow 8192 bytes; full source-local Task3 bindings are
    # part of the prompt and must fit without dropping or truncating conditions.
    max_bytes=8192
    payload,omitted=compact_dimension_context({'segment_competitor':'Notion','dimension':'feature'},SimpleNamespace(facts=facts),{f.id for f in facts},max_bytes=max_bytes,requested_operations=('edit','share'))
    prompt=json.loads(compact_prompt_json(payload))
    def restore(value):
        if isinstance(value,dict):
            if set(value)=={'text_ref'}:return prompt['text_sets'][value['text_ref']]
            return {k:restore(v)for k,v in value.items()}
        if isinstance(value,list):return [restore(v)for v in value]
        return value
    assert not omitted and len(compact_prompt_json(payload).encode())<=max_bytes
    assert len(encoded(payload).encode())>max_bytes
    assert len(prompt['evidence_view']['facts'])==2
    for rendered,original in zip(prompt['evidence_view']['facts'],facts):
        assert restore(rendered['value'])==original.value
        assert restore(rendered['qualifiers'])==original.qualifiers
        assert rendered['quote']==original.quote
        assert restore(rendered['operation_observations'])==[operation_binding(row)for row in operation_observations(original)]


def test_multiple_role_plan_branches_never_borrow_first_plan():
    from packages.research.extraction.semantic import semantic_extraction
    quote='Guests can edit documents shared with their workspace.'
    body='Permissions\nAvailable to workspace owners on paid plans and guests on all plans.\n'+quote
    brief,_,page=qualified_fixture(body,headings=[(1,'Permissions')])
    row=next(iter(semantic_extraction(brief,page,{'facts':[{'quote':quote}]}).fields.values()))['operations'][0]
    assert row['plan'] in (None,'all plans')


def test_starred_cell_cannot_borrow_footnote_from_another_table():
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    header='|  | Full access | Comment-only | Read-only |'
    read='| View content | ✅ * | ✅ | ✅ |'
    body='Permissions\nAvailable on all plans.\n'+header+'\n'+read+'\n\nEditing settings\n'+header+'\n| Edit content | ✅ * | ❌ | ❌ |\n* Editing requires Enterprise plans.'
    brief,candidate,page=qualified_fixture(body,url='https://help.nuclino.com/fed9f070-roles-and-permissions',headings=[(1,'Permissions')])
    result=semantic_extraction(brief,page,{'facts':[{'quote':header+'\n'+read}]})
    rows=next(iter(result.fields.values()))['operations']
    assert not any(r['role']=='Full access' for r in rows)
    assert all(not r['prerequisites'] for r in rows)
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


def test_complete_creation_rule_precedes_incomplete_multi_operation_paragraph():
    from packages.agents.writer.dimension_writer import compact_dimension_context
    from test_capability_alignment import fact
    incomplete=fact('Notion','Can edit content: People can create and edit pages within a database.',slot='incomplete')
    complete=fact('Notion','Can create: People on Business and Enterprise plans can create pages.',slot='complete')
    payload,_=compact_dimension_context({'segment_competitor':'Notion','dimension':'feature'},SimpleNamespace(facts=[incomplete,complete]),{incomplete.id,complete.id},requested_operations=('create','edit'))
    assert payload['evidence_view']['facts'][0]['id']==complete.id
    assert 'create' in payload['evidence_view']['facts'][0]['operation_targets']


def test_coordinated_chinese_creation_is_still_the_original_action():
    from packages.research.evidence.operations import operation_matches_text
    assert operation_matches_text('create','用户可以在数据库内创建和编辑页面。')
    assert not operation_matches_text('create','用户可以创建文件夹或修改评论。')


def test_deterministic_actor_and_creation_prerequisite_paragraphs_survive():
    from packages.research.extraction.semantic import extract_operation_rules
    doc='Doc Makers can create and delete docs, manage doc settings, and create pages.'
    brief,_,page=qualified_fixture('What Doc Makers can do\n'+doc,product='Coda',url='https://help.superhuman.com/hc/en-us/articles/46210078082701-Roles-in-Superhuman-Docs-Doc-Makers-Admins-and-Editors',headings=[(1,'What Doc Makers can do')])
    result=extract_operation_rules(brief,page)
    assert any(r['operation']=='create' and r['role']=='Doc Makers' for v in result.fields.values() for r in v['operations'])
    prerequisite='To create a page or blog post, you need the Add content permission in the space.'
    brief,_,page=qualified_fixture('Creating pages\n'+prerequisite,product='Confluence',url='https://support.atlassian.com/confluence-cloud/docs/create-edit-and-publish-a-page/',headings=[(1,'Creating pages')])
    result=extract_operation_rules(brief,page)
    assert any(r['operation']=='create' for v in result.fields.values() for r in v['operations'])


def test_role_header_cannot_take_later_guests_plan():
    from packages.research.evidence.operations import structured_operations
    quote='Can comment: People can comment on documents. Guests can edit pages on paid plans.'
    rows=structured_operations(quote,[quote],'Notion')
    assert next(r for r in rows if r['operation']=='comment')['plan'] is None


def test_workspace_access_table_row_survives_quality_and_admission():
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    header='|  | Full access | Comment-only | Read-only |'
    quote='| Change workspace default access | ✅ (except guests) | ✖️ | ✖️ |'
    body='Permissions\nAvailable on all plans.\n'+header+'\n'+quote
    brief,candidate,page=qualified_fixture(body,url='https://help.nuclino.com/fed9f070-roles-and-permissions',headings=[(1,'Permissions')])
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    assert result.fields and any(r['operation']=='manage_access' for v in result.fields.values()for r in v['operations'])
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


def test_remote_requirements_need_permission_is_bound_and_replayed():
    from packages.research.extraction.semantic import extract_operation_rules
    from packages.research.evidence.admission import admit_evidence_items
    quote='Members can create pages within the workspace.'
    requirement='You need the Add content permission in the parent space.'
    body='Creating pages\nAvailable on all plans.\n'+quote+'\nOpen the page menu.\nChoose a new page.\nReview the page title.\nRequirements\n'+requirement
    brief,candidate,page=qualified_fixture(body,product='Confluence',url='https://support.atlassian.com/confluence-cloud/docs/create-edit-and-publish-a-page/',headings=[(1,'Creating pages'),(2,'Requirements')])
    result=extract_operation_rules(brief,page)
    value=next(value for value in result.fields.values() if quote in value['evidence_terms'][0])
    assert requirement in value['conditions']
    assert any(p['kind']=='parent_access' and p['quote']==requirement for r in value['operations'] for p in r['prerequisites'])
    assert all(i.status=='accepted' for i in admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate]))


def test_named_access_role_remains_bound_across_definition_sentences():
    from packages.research.evidence.operations import structured_operations
    quote='- Can create: This permission level is only found on database pages and is available on Business and Enterprise plans. People with this level of access can create new pages within the database.'
    rows=structured_operations(quote,[quote],'Notion')
    create=next(r for r in rows if r['operation']=='create')
    assert create['role']=='Can create' and create['plan']=='Business and Enterprise'


def test_chinese_default_access_level_matches_the_same_management_operation():
    from packages.research.evidence.operations import operation_matches_text
    assert operation_matches_text('manage_access','只有拥有完全访问权限的工作区成员可以更改工作区默认访问级别。')
