"""Source-backed operation coverage, capacity and producer integrity regressions."""
from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import seal_snapshot
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource
from packages.skills.registry import SkillRegistry


def four_branch_service():
    now = datetime.now(UTC)
    detail = RunDetail(id='operation-coverage', topic='Document permissions', execution_mode='real',
        status='running', created_at=now, updated_at=now,
        plan=AnalysisPlan(topic='Document permissions', competitors=['A', 'B', 'C', 'D'],
                          dimensions=['feature'], research_depth='standard'))
    for product in detail.plan.competitors:
        detail.raw_sources.append(RawSource(id='source-'+product, competitor=product,
            dimension='feature', source_type='official_docs', title=product+' permissions',
            url=f'https://{product.lower()}.example/docs', snippet='Members can edit documents.',
            content_hash='body-'+product, extracted_at=now, confidence=.9,
            metadata={'last_verified_at':now.isoformat(), 'normalized_fields':[
                dict(kind='feature', dimension='feature', competitor=product, slot=f'op-{i}',
                     support_level='documented', evidence_quote=f'Members can edit documents under source rule {i}. '+ 'Captured original condition. '*18,
                     evidence_terms=['Only invited members may edit the shared document. ' * 14],
                     qualifiers={'complete_condition':f'Original rule {i}. '+'Parent access must be granted. '*38}, confidence=.9)
                for i in range(5)]}))
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), trace_store=TraceStore.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail);service._runs[detail.id] = record
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    for product in detail.plan.competitors:
        view, use = service._begin_evidence_use(record, agent='analyst', competitor=product, dimension='feature')
        service._validate_evidence_use(record, use)
        service._merge_structured_knowledge_payload(detail,product,'feature',
            service._deterministic_structured_knowledge_payload(competitor=product,dimension='feature',
                dimension_sources=[s.to_raw_source().model_dump(mode='json') for s in view.sources]),
            evidence_source_ids=set(view.source_ids))
        service._record_evidence_artifact(record, kind='analyst', competitor=product, dimension='feature',
            uses=[use],payload=service._analyst_evidence_artifact_payload(detail,product,'feature'))
    return service, record


@pytest.mark.parametrize('agent',['comparator','reflector'])
def test_four_valid_producers_fit_comparison_without_losing_conditions(agent):
    service, record = four_branch_service()
    view, use = service._begin_evidence_use(record,agent=agent)
    producer_facts={f for c in record.detail.evidence_consumptions if c.agent=='analyst' for f in c.fact_ids}
    assert set(view.fact_ids) == producer_facts
    projected, gaps = service._project_evidence_detail(record,[view])
    assert not any('Analysis dependency unavailable' in gap for gap in gaps)
    assert all(projected.competitor_kbs[p].slices['feature'] for p in projected.plan.competitors)
    payload=json.loads(view.to_prompt_json())
    for rendered, fact in zip(payload['facts'],view.facts):
        qualifiers=payload['qualifier_sets'][rendered['qualifiers_ref']] if 'qualifiers_ref' in rendered else rendered['qualifiers']
        assert qualifiers == fact.qualifiers
    assert len(view.to_prompt_json().encode()) <= use.view_max_bytes
    record.detail.competitor_kbs['A'].slices['feature'].append('Injected finding')
    projected, gaps = service._project_evidence_detail(record,[view])
    assert any('Analysis dependency unavailable: A' in gap for gap in gaps)
    assert 'feature' not in projected.competitor_kbs['A'].slices


def test_writer_does_not_fill_missing_operations_with_comment_ui_steps():
    from test_capability_alignment import fact
    from packages.agents.writer.dimension_writer import compact_dimension_context
    facts = [fact('Notion',f'Click on comment number {i} to open its menu.',slot=f'ui-{i}') for i in range(8)]
    facts += [fact('Notion','Can comment: Members on all plans can comment on documents.',slot='comment-rule'),
              fact('Notion','Guests on paid plans can edit documents only after access is granted.',slot='edit-rule'),
              fact('Notion','Full access: Members on all plans can share documents.',slot='share-rule')]
    payload, omitted = compact_dimension_context({'segment_competitor':'Notion','dimension':'feature'},
        SimpleNamespace(facts=facts),{f.id for f in facts},
        requested_operations=('read','comment','edit','create','share','manage_access'))
    selected=payload['evidence_view']['facts']
    assert len(selected)==3 and not any('comment number' in f['quote'] for f in selected)
    assert payload['missing_operations']==['read','create','manage_access']
    assert len([f for f in selected if 'comment' in f['operation_targets']])==1


@pytest.mark.asyncio
async def test_registered_docs_are_read_before_operation_gap_search():
    from packages.research.pipeline import run_research_pipeline
    from packages.research.models import ResearchBrief, SourceCandidate
    from packages.research.extraction.semantic import semantic_extraction
    from packages.search import SearchResult
    quote='Can comment: Members on all plans can comment on documents.'
    brief=ResearchBrief(run_id='target-repair',topic='permissions',competitor='Notion',dimension='feature',
        product_category='文档',research_depth='standard',target_source_count=1,max_fetches=2,max_search_queries=2,
        max_candidates=3,max_repair_rounds=1,include_homepage_candidates=False,include_trusted_sources=False)
    seed=SourceCandidate(title='Notion comments',url='https://www.notion.com/help/comments-mentions-and-reminders',
        origin='manual',competitor='Notion',dimension='feature')
    events=[]
    async def fetch(url):
        events.append(('fetch',url))
        return SimpleNamespace(url=url,title='Notion collaboration',text=quote,markdown=quote,
            content_hash=url,ok=True,status='ok',quality_score=.9,metadata={})
    async def search(query,limit):
        events.append(('search',query))
        return [SearchResult(title='Notion permission rules',url='https://www.notion.com/help/sharing-and-permissions',snippet='Notion roles')]
    async def semantic(active,page):return semantic_extraction(active,page,{'facts':[{'quote':quote}]})
    result=await run_research_pipeline(brief,fetch=fetch,search=search,seed_candidates=[seed],semantic_extract=semantic)
    assert events[0][0]=='fetch'
    queries=[value for kind,value in events if kind=='search']
    assert queries and all('role' in q and 'comment role' not in q for q in queries)
    assert len(queries)<=2 and len([e for e in events if e[0]=='fetch'])<=2
    assert any(g.metadata.get('operation')=='read' for g in result.gaps)


def test_long_document_model_window_and_admission_bind_late_role_rules():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction, semantic_body_window
    from packages.research.evidence.admission import admit_evidence_items
    quote='Can view: Members on all plans can view pages, but cannot edit content.'
    text=('Click on a comment to open its menu.\n'*500)+'\nRoles and permissions\n'+quote+'\n'
    brief,candidate,page=fixture(text);brief.topic='permissions'
    body=semantic_body_window(brief,page)
    assert len(body)<=12000 and quote in body
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    assert result.quotes[0].start_offset==text.index(quote)>12000
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


def test_capture_prefers_role_and_sharing_rules_before_comment_menus():
    from packages.research.capture.selection import select_capture_candidates
    from packages.research.models import ResearchBrief, SourceCandidate
    brief=ResearchBrief(run_id='capture-order',topic='permissions',competitor='Notion',dimension='feature',
        product_category='文档',target_source_count=2,max_fetches=3)
    candidates=[SourceCandidate(origin='manual',title='Notion comments',url='https://www.notion.com/help/comments-mentions-and-reminders',competitor='Notion',dimension='feature'),
        SourceCandidate(origin='manual',title='Notion roles and permissions',url='https://www.notion.com/help/sharing-and-permissions',competitor='Notion',dimension='feature'),
        SourceCandidate(origin='manual',title='Notion sharing',url='https://www.notion.com/help/share-doc',competitor='Notion',dimension='feature')]
    chosen=select_capture_candidates(brief,candidates)
    assert [c.title for c in chosen.selected]==['Notion roles and permissions','Notion sharing']


@pytest.mark.asyncio
async def test_semantic_budget_for_other_products_survives_first_collector():
    from test_execution_limits import _service
    from packages.llm.execution_budget import LLMCallExecution
    from packages.llm.errors import LLMExecutionLimitError
    service,record=await _service(run_llm_max_tokens=200000)
    record.detail.topic='权限与文档协作'
    record.detail.plan.competitors=['A','B','C','D'];record.detail.plan.dimensions=['feature']
    budget=service._run_llm_budget(record)
    phases={f'{agent}:{product}/feature' for product in record.detail.plan.competitors
            for agent in ('collector','analyst','writer','qa')} | {'comparator:run','reflector:run'}
    assert set(budget.delivery_reserves)==phases
    assert all(budget.delivery_reserves[phase]>0 for phase in phases)
    assert budget.max_tokens==200000 and budget.stage_headroom>0
    protected_before=dict(budget.delivery_reserves)
    first=LLMCallExecution(budget,False,phase='collector:A/feature',input_tokens=18000)
    first.reserve();first.settle()
    # The first collector can borrow free capacity while every other core stage
    # retains its actual Task2 floor; do not pin obsolete allocation constants.
    assert all(budget.delivery_reserves[phase]==amount for phase,amount in protected_before.items())
    assert all(budget.delivery_charged.get(phase,0)==0 for phase in phases if phase!='collector:A/feature')
    with pytest.raises(LLMExecutionLimitError):
        budget.reserve(is_repair=False,input_tokens=60000)
    other=LLMCallExecution(budget,False,phase='collector:B/feature',input_tokens=12000)
    other.reserve()
    service._finish_delivery_phase(record,'collector','A/feature')
    assert 'collector:A/feature' in budget.delivery_finished


def test_capacity_omission_does_not_label_valid_analysis_as_broken_dependency():
    from packages.research.evidence.views import select_evidence_view
    service, record = four_branch_service()
    view=select_evidence_view(service._current_evidence_snapshot(record),agent='comparator',max_bytes=8192)
    projected,gaps=service._project_evidence_detail(record,[view])
    assert gaps and all(g.startswith('Analysis context omitted:') for g in gaps)
    assert not any(kb.slices.get('feature') for kb in projected.competitor_kbs.values())


def test_writer_review_selection_keeps_different_operations_and_drops_duplicate_comments():
    from packages.agents.writer.dimension_writer import operation_claim_selection
    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.evidence.operations import operation_binding, operation_observations
    from test_capability_alignment import fact
    comment=fact('Notion','Can comment: Members can comment on documents.',slot='comment')
    edit=fact('Notion','Members can edit documents.',slot='edit')
    comment_binding=operation_binding(next(row for row in operation_observations(comment) if row['operation']=='comment'))
    edit_binding=operation_binding(next(row for row in operation_observations(edit) if row['operation']=='edit'))
    claims=[ReportClaim(id=f'comment-{i}',text='成员可以对文档发表评论。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[comment.id],source_ids=[comment.source_id],operation_binding=comment_binding) for i in range(3)]
    claims.append(ReportClaim(id='edit',text='成员可以编辑文档。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[edit.id],source_ids=[edit.source_id],operation_binding=edit_binding))
    chosen=operation_claim_selection(claims,SimpleNamespace(facts=[comment,edit]),('comment','edit'),{comment.id,edit.id})
    assert [c.id for c in chosen]==['comment-0','edit']
    assert operation_claim_selection(claims,SimpleNamespace(facts=[comment,edit]),('comment','edit'),{edit.id})==[claims[-1]]


def test_late_window_quote_does_not_bind_to_earlier_broader_permission():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_body_window, semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote='They can read documents and view pages shared by other members.'
    text='Guide\nPreview\nCan view\n'+quote+'\nAvailable on all plans.\n\n'+('Click on a comment to open its menu.\n'*500)+'\nRoles and permissions\nFull access\n'+quote+'\nAvailable on paid plans.\n'
    brief,candidate,page=fixture(text);brief.topic='permissions'
    page.metadata['document_headings']=[(1,'Guide'),(2,'Preview'),(2,'Roles and permissions')]
    assert semantic_body_window(brief,page).count(quote)==1
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    assert result.quotes[0].start_offset==text.rindex(quote)
    values=next(iter(result.fields.values()))
    assert 'Available on paid plans.' in values['evidence_terms']
    assert all(row['plan']=='paid plans' for row in values['operations'])
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


def test_ambiguous_quote_in_same_window_requires_complete_role_context():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction
    quote='They can edit documents shared by other members.'
    text='Can edit\n'+quote+'\nAvailable on all plans.\n\nFull access\n'+quote+'\nAvailable on paid plans.'
    brief,_,page=fixture(text);brief.topic='permissions'
    assert not semantic_extraction(brief,page,{'facts':[{'quote':quote}]}).fields


def test_source_negation_keeps_curly_apostrophes_and_role_labels_out_of_actions():
    from test_capability_alignment import fact
    from packages.research.evidence.operations import operation_observations, operation_matches_text
    quote='- Can comment : Select this level of access for people who should only have the ability to comment on a page. They won’t be able to edit or share the content.'
    rows=operation_observations(fact('Notion',quote,slot='actual-denial'))
    assert {r['operation']:r['effect'] for r in rows}=={'comment':'allowed','edit':'denied','share':'denied'}
    assert not operation_matches_text('comment','选择“Can comment”访问级别的人不能编辑或分享内容。')
    assert operation_matches_text('read','文件夹权限允许查看该文件夹内的所有文档。')


def test_writer_assigns_positive_actions_before_comment_role_denials():
    from test_capability_alignment import fact
    from packages.agents.writer.dimension_writer import compact_dimension_context
    comments=fact('Notion','Can comment: People can comment on a page; they cannot edit or share content.',slot='denials')
    full=fact('Notion','Full access: Members can edit documents and share documents.',slot='positive')
    payload,_=compact_dimension_context({'segment_competitor':'Notion','dimension':'feature'},
        SimpleNamespace(facts=[comments,full]),{comments.id,full.id},requested_operations=('comment','edit','share'))
    selected={r['id']:r['operation_targets'] for r in payload['evidence_view']['facts']}
    assert selected=={full.id:['edit','share'],comments.id:['comment']}


def test_writer_review_respects_server_assigned_operation_targets():
    from test_capability_alignment import fact
    from packages.agents.writer.dimension_writer import operation_claim_selection
    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.evidence.operations import operation_binding, operation_observations
    original=fact('Notion','Can comment: People can comment on a page; they cannot edit or share content.',slot='limits')
    texts=['成员可以对页面发表评论，但不能编辑或分享内容。','成员不能编辑或分享内容。']
    bindings=[operation_binding(next(row for row in operation_observations(original) if row['operation']==op)) for op in ('comment','edit')]
    claims=[ReportClaim(id=f'c-{i}',text=text,kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id],operation_binding=bindings[i]) for i,text in enumerate(texts)]
    chosen=operation_claim_selection(claims,SimpleNamespace(facts=[original]),('comment','edit','share'),
        {original.id},fact_targets={original.id:['comment']})
    assert chosen==[claims[0]]


def test_operation_cell_chooses_one_reviewed_positive_observation():
    from test_capability_alignment import fact
    from packages.agents.writer.dimension_writer import render_operation_comparison
    from packages.research.evidence.report_claims import ReportClaim, AuditedReportClaim, ReportDimensionAudit
    from packages.research.evidence.operations import operation_binding, operation_observations
    limit=fact('Notion','Can comment: People can comment on a page; they cannot edit or share content.',slot='limit')
    full=fact('Notion','Full access: Members on all plans can edit documents.',slot='full')
    denied_edit=operation_binding(next(row for row in operation_observations(limit) if row['operation']=='edit'))
    allowed_edit=operation_binding(next(row for row in operation_observations(full) if row['operation']=='edit'))
    claims=[ReportClaim(id='limit',text='成员可以对页面发表评论，但不能编辑或分享内容。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[limit.id],source_ids=[limit.source_id],operation_binding=denied_edit),
        ReportClaim(id='full',text='Full access 成员在所有套餐上可以编辑文档。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[full.id],source_ids=[full.source_id],operation_binding=allowed_edit)]
    audit=ReportDimensionAudit(competitor='Notion',dimension='feature',consumption_id='use',claims=[AuditedReportClaim(claim=c,status='supported') for c in claims])
    detail=SimpleNamespace(topic='权限',output_language='zh-CN',plan=SimpleNamespace(dimensions=['feature'],competitors=['Notion'],target_product=None))
    lines=render_operation_comparison(detail,[audit],snapshot=SimpleNamespace(facts=[limit,full],source_ids=[limit.source_id,full.source_id]))
    edit=next(line for line in lines if line.startswith('| 编辑 |'))
    assert 'Full access' in edit and '不能编辑' not in edit


@pytest.mark.parametrize('modal',['won’t be able to','will not be able to'])
def test_new_denial_modal_does_not_change_earlier_affirmative_action(modal):
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    quote=f'Members on all plans can comment on documents and {modal} edit pages.'
    brief,candidate,page=fixture(quote);brief.topic='permissions'
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    rows=next(iter(result.fields.values()))['operations']
    assert {r['operation']:r['effect'] for r in rows}=={'comment':'allowed','edit':'denied'}
    assert admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])[0].status=='accepted'


def test_single_quoted_comment_role_cannot_claim_comment_target():
    from test_capability_alignment import fact
    from packages.agents.writer.dimension_writer import operation_claim_selection
    from packages.research.evidence.report_claims import ReportClaim
    original=fact('Notion','Can comment: People can comment on pages but cannot edit content.',slot='label')
    claim=ReportClaim(id='label',text="选择 'Can comment' 访问级别的人不能编辑内容。",kind='fact',competitor='Notion',dimension='feature',fact_ids=[original.id],source_ids=[original.source_id])
    assert operation_claim_selection([claim],SimpleNamespace(facts=[original]),('comment',),{original.id})==[]


def test_comment_menu_mutations_do_not_fill_document_operation_targets():
    from test_capability_alignment import fact
    from packages.research.evidence.operations import operation_observations
    quote='To edit or delete a comment, hover over it and select ••• → Edit comment or Delete comment.'
    original=fact('Notion',quote,slot='actual-menu')
    assert not operation_observations(original)


def test_reading_comment_context_is_not_document_read_or_posting_comment():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    from packages.research.evidence.operations import operation_gaps
    quote='管理员在所有套餐中可以在活动侧边栏中查看该评论的内容，了解该评论的上下文。'
    brief,candidate,page=fixture(quote);brief.topic='permissions'
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    assert not next(iter(result.fields.values()))['operations']
    items=admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])
    assert items[0].status=='accepted'
    assert {'read','comment'} <= {gap.metadata['operation'] for gap in operation_gaps(brief,items)}


def test_share_intent_or_recipient_does_not_establish_recipient_permission():
    from test_capability_alignment import fact
    from packages.research.evidence.operations import operation_observations
    intent="The email domain of the guest you’re trying to share the page with is not an allowed email domain for your workspace."
    assert not operation_observations(fact('Notion',intent,slot='share-failure'))
    rows=operation_observations(fact('Notion','You can share a page with guests.',slot='share-recipient'))
    assert rows[0]['role'] is None


def test_short_comment_reading_phrase_cannot_close_posting_gap():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    from packages.research.evidence.operations import operation_gaps,operation_matches_text
    quote='管理员在所有套餐中可以查看该评论的内容和作者名称，从而了解讨论记录。'
    brief,candidate,page=fixture(quote);brief.topic='permissions'
    result=semantic_extraction(brief,page,{'facts':[{'quote':quote}]})
    assert not next(iter(result.fields.values()))['operations']
    items=admit_evidence_items([result],brief=brief,captured_pages=[page],candidates=[candidate])
    assert any(g.metadata['operation']=='comment' for g in operation_gaps(brief,items))
    assert operation_matches_text('comment','成员可以对页面发表评论。')
    assert operation_matches_text('comment','该角色可以查看并评论该文件夹中的所有文档。')
