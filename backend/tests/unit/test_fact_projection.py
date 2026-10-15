from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_stage_evidence_views import distributed_detail, FixedTime
from test_report_claim_audit import price_view
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.service import RunRecord, RunService
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.skills.registry import SkillRegistry
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view
from packages.schema.models import PricingModel, PricingTier


def service_for(detail):
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    return service, record


def docs_prices():
    source = price_view().sources[0].to_raw_source()
    source.competitor = 'Coda'
    source.covered_competitors = ['Coda']
    prototype = source.metadata['normalized_fields'][0]
    rows = []
    for plan, amount, interval in [('Free',0,'unknown'),('Pro',12,'annual'),('Pro',15,'monthly'),('Business',33,'annual'),('Business',40,'monthly')]:
        row = deepcopy(prototype)
        row.update(competitor='Coda', tier_name=plan, price=f'{amount} USD', billing_cycle=interval, source_quote=f'{plan} {amount} USD per Doc Maker / month, billed {interval}.', evidence_item_ids=[f'{plan}-{interval}'])
        row['qualifiers'].update(plan=plan, amount=amount, currency='USD', amount_basis='doc_maker', amount_period='monthly', billing_interval=interval, tax_scope='unknown')
        rows.append(row)
    source.metadata['normalized_fields'] = rows
    return source


def test_normalized_prices_replace_model_and_text_invented_tiers(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Coda']
    source = docs_prices()
    detail.raw_sources = [source]
    service, _ = service_for(detail)
    pricing = PricingModel(tiers=[PricingTier(name='Team',price='$12'),PricingTier(name='Pro ($12)',price='$12')])
    service._enrich_pricing_model_from_sources(detail,'Coda','pricing',pricing)
    assert [(t.name,t.price,t.billing_cycle) for t in pricing.tiers] == [(r['tier_name'],r['price'],r['billing_cycle']) for r in source.metadata['normalized_fields']]
    assert all(c.source_ids == [source.id] for t in pricing.tiers for c in t.claims)


def test_matrix_uses_original_observation_instead_of_model_number_restatement(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Confluence']
    detail.plan.dimensions = ['feature']
    source = next(s for s in detail.raw_sources if s.competitor == 'Confluence')
    quote = 'You and up to 29 teammates can edit the same page at the same time.'
    source.metadata['normalized_fields'][0].update(evidence_quote=quote,evidence_terms=[quote])
    detail.raw_sources = [source]
    service, _ = service_for(detail)
    snapshot = seal_snapshot(detail,phase='analysis',canonical_documents={})
    view = select_evidence_view(snapshot,agent='comparator',max_bytes=8192)
    matrix = service._build_comparison_matrix(detail, {'matrix_summary':['Confluence 最多29人同时编辑。']},evidence_view=view)
    assert quote in matrix.cells[0].value
    assert not any('最多29人' in row for row in matrix.summary)


def test_pricing_branch_and_writer_keep_all_five_plan_interval_observations(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Coda']
    detail.plan.dimensions = ['feature','pricing']
    source = docs_prices()
    # Real pages repeat enough quote/context that a single quick 8KiB loses rows.
    for row in source.metadata['normalized_fields']:
        row['source_quote'] += ' Original billing conditions retained from the official pricing card.' * 6
    detail.raw_sources = [source]
    service, record = service_for(detail)
    seal_snapshot(detail,phase='analysis',canonical_documents={})
    view, _ = service._begin_evidence_use(record,agent='analyst',competitor='Coda',dimension='pricing')
    assert {f.qualifiers['amount'] for f in view.facts if f.field=='price'} == {0,12,15,33,40}
    selected, use = service._writer_segment_evidence(record,dict(segment_name='price',segment_competitor='Coda',dimension='pricing',answer_intent='recorded_price',allowed_source_ids=[source.id]))
    assert {f['value'] for f in selected['evidence_view']['facts'] if f['field']=='price'} == {'0 USD','12 USD','15 USD','33 USD','40 USD'}
    assert len(service._writer_evidence_context_json(selected).encode()) <= use.max_bytes <= 16384
    service._merge_structured_knowledge_payload(detail,'Coda','pricing',{'pricing_model': {'tiers': [{'name': 'Team', 'price': '$12'}]}})
    assert {(tier.name,tier.price,tier.billing_cycle) for tier in detail.competitor_knowledge['Coda'].pricing_model.tiers} == {
        (row['tier_name'],row['price'],row['billing_cycle']) for row in source.metadata['normalized_fields']}


def test_report_common_axes_use_only_audited_bound_claims(monkeypatch):
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import AuditedReportClaim, ReportClaim, ReportDimensionAudit
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.dimensions = ['feature','pricing']
    detail.plan.competitors = ['Notion', 'Confluence', 'Coda']
    snapshot = seal_snapshot(detail,phase='analysis',canonical_documents={})
    audits=[]
    for product in detail.plan.competitors:
        f = next(f for f in snapshot.facts if f.competitor==product and f.field=='evidence_terms')
        c = ReportClaim(id='claim-'+product,text='支持评论，需工作区成员访问权限。',kind='fact',competitor=product,dimension='feature',fact_ids=[f.id],source_ids=[f.source_id])
        audits.append(ReportDimensionAudit(competitor=product,dimension='feature',consumption_id='use-'+product,claims=[AuditedReportClaim(claim=c,status='supported')]))
    report = render_dimension_report(detail,audits)
    assert '| 能力 | Notion | Confluence | Coda |' in report
    assert '| 评论 |' in report
    assert '| 共享编辑 |' in report and '未取得已审核观察' in report
    rejected=audits[0].model_copy(update={'claims':tuple(a.model_copy(update={'status':'rejected'}) for a in audits[0].claims)})
    changed=render_dimension_report(detail,[rejected,*audits[1:]])
    comment_row=next(line for line in changed.splitlines() if line.startswith('| 评论 |'))
    assert audits[0].claims[0].claim.source_ids[0] not in comment_row


def test_explicit_feature_depth_has_three_source_and_two_public_browser_budget():
    from packages.research.budget import research_depth_budget
    budget=research_depth_budget('quick', dimension='feature')
    assert (budget.target_sources,budget.max_fetches,budget.max_advanced_fetches)==(3,4,2)
    assert research_depth_budget('quick').max_advanced_fetches==1


def test_semantic_complete_sentence_keeps_restriction_from_whole_paragraph():
    from packages.research.extraction.semantic import _local_context
    paragraph='Docs supports real-time co-editing and threaded comments. Only invited editors may change the content.'
    quote='Docs supports real-time co-editing and threaded comments.'
    assert _local_context(paragraph,0,len(quote))==paragraph
    assert _local_context(paragraph,0,len('Docs supports real-time co-editing')) is None


def test_feature_runtime_brief_uses_dimension_budget():
    detail=distributed_detail(observations=1)
    service,_=service_for(detail)
    brief=service._research_brief(detail,'Coda','feature')
    assert (brief.target_source_count,brief.max_fetches,brief.max_advanced_fetches)==(3,4,2)


def test_unreviewed_comparison_prose_cannot_restate_people_or_plans(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail=distributed_detail(observations=1)
    detail.plan.competitors=['Confluence']
    detail.plan.dimensions=['feature']
    detail.raw_sources=[s for s in detail.raw_sources if s.competitor=='Confluence']
    service,_=service_for(detail)
    view=select_evidence_view(seal_snapshot(detail,phase='analysis',canonical_documents={}),agent='comparator',max_bytes=8192)
    payload={'assessments':{'feature':{'status':'insufficient_evidence','rationale':'Confluence最多29人编辑。','tradeoffs':['Team套餐更便宜。'],'gaps':['29人上限是否够用？'],'source_ids':[detail.raw_sources[0].id]}}}
    matrix=service._build_comparison_matrix(detail,payload,evidence_view=view)
    published=matrix.model_dump_json()
    assert '最多29人' not in published and 'Team套餐' not in published and '29人上限' not in published


def test_common_table_rejects_cross_product_claim_even_if_audit_says_supported(monkeypatch):
    from packages.agents.writer.dimension_writer import render_common_capabilities
    from packages.research.evidence.report_claims import AuditedReportClaim,ReportClaim,ReportDimensionAudit
    monkeypatch.setattr('packages.research.evidence.views.datetime',FixedTime)
    detail=distributed_detail(observations=1)
    detail.plan.dimensions=['feature']
    snapshot=seal_snapshot(detail,phase='analysis',canonical_documents={})
    other=next(f for f in snapshot.facts if f.competitor=='Confluence' and f.field=='evidence_terms')
    claim=ReportClaim(id='cross-product',text='串产品的评论观察。',kind='fact',competitor='Notion',dimension='feature',fact_ids=[other.id],source_ids=[other.source_id])
    audit=ReportDimensionAudit(competitor='Notion',dimension='feature',consumption_id='use',claims=[AuditedReportClaim(claim=claim,status='supported')])
    assert '串产品的评论观察' not in '\n'.join(render_common_capabilities(detail,[audit]))


def test_reflection_uses_current_original_fact_refs_not_repeated_matrix_prose(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime',FixedTime)
    detail=distributed_detail(observations=1)
    service,_=service_for(detail)
    view=select_evidence_view(seal_snapshot(detail,phase='analysis',canonical_documents={}),agent='reflector',max_bytes=24576)
    detail.comparison_matrix=service._build_comparison_matrix(detail,{},evidence_view=view)
    digest=service._reflector_matrix_digest(detail,evidence_view=view)
    assert all('value' not in cell and cell['evidence_fact_refs'] for cell in digest['cells'])
    assert {fid for cell in digest['cells'] for fid in cell['evidence_fact_refs']}<=set(view.fact_ids)


def test_common_table_can_render_from_guarded_draft_and_explicit_live_snapshot(monkeypatch):
    from packages.agents.writer.dimension_writer import render_dimension_report
    monkeypatch.setattr('packages.research.evidence.views.datetime',FixedTime)
    detail=distributed_detail(observations=1)
    detail.plan.dimensions=['feature','pricing']
    snapshot=seal_snapshot(detail,phase='analysis',canonical_documents={})
    draft=detail.model_copy(deep=True)
    draft.evidence_snapshots=[]
    draft.evidence_snapshot_id=None
    assert '| 能力 |' in render_dimension_report(draft,[],snapshot=snapshot)


def test_common_table_does_not_repeat_comment_claim_on_editing_axis(monkeypatch):
    from packages.agents.writer.dimension_writer import render_common_capabilities
    from packages.research.evidence.report_claims import AuditedReportClaim, ReportClaim, ReportDimensionAudit
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Coda']
    source = detail.raw_sources[0]
    source.metadata['normalized_fields'][0].update(
        evidence_quote='Docs supports real-time co-editing and threaded comments.',
        evidence_terms=['Docs supports real-time co-editing and threaded comments.'])
    detail.raw_sources = [source]
    snapshot = seal_snapshot(detail,phase='analysis',canonical_documents={})
    fact = next(f for f in snapshot.facts if f.field == 'evidence_terms')
    claim = ReportClaim(id='comment-only',text='支持线程评论。',kind='fact',competitor='Coda',dimension='feature',fact_ids=[fact.id],source_ids=[fact.source_id])
    audit = ReportDimensionAudit(competitor='Coda',dimension='feature',consumption_id='use',claims=[AuditedReportClaim(claim=claim,status='supported')])
    rows = render_common_capabilities(detail,[audit])
    assert '支持线程评论' in next(row for row in rows if row.startswith('| 评论 |'))
    assert '支持线程评论' not in next(row for row in rows if row.startswith('| 共享编辑 |'))
