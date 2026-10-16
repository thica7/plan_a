"""Offline regressions for the saved document and sparse hardware report failures."""
import json
from types import SimpleNamespace

import pytest
from claim_review_fixture import supported_review

from test_capability_alignment import fact
from test_operation_condition_scope import CHOICE, COMMENT, VIEW
from test_partial_report_gaps import fixture
from test_stage_evidence_views import distributed_detail, FixedTime

from packages.agents.writer import dimension_writer as writer
from packages.research.evidence.operations import operation_binding, operation_observations, structured_operations
from packages.research.evidence.report_claims import AuditedReportClaim, ReportClaim, ReportDimensionAudit
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.snapshot_models import canonical_json


def test_invalid_middle_operation_candidate_keeps_later_bound_observations():
    originals = [fact('Notion', 'Can create: People can create pages.', slot='create'),
                 fact('Notion', COMMENT, slot='comment'),
                 fact('Notion', 'You can edit the same page at the same time with an unlimited number of people.', slot='edit')]
    bindings = [operation_binding(operation_observations(f)[0]) for f in originals]
    rows = [dict(text=text, kind='fact', competitor='Notion', dimension='feature',
                 fact_ids=[f.id], source_ids=[f.source_id], observation_id=b['observation_id'])
            for f, b, text in zip(originals, bindings, ['可以创建页面。', 'Can comment 角色可以对页面发表评论。', '你可以与不限人数的人同时编辑同一页面。'])]
    rows.insert(1, {key: value for key, value in rows[0].items() if key != 'observation_id'})
    claims, gaps = writer.parse_claim_drafts(json.dumps({'claims': rows}),
        {b['observation_id']: b for b in bindings}, {f.id for f in originals}, 'saved-run')
    assert [c.operation_binding.operation for c in claims] == ['create', 'comment', 'edit']
    assert 'operation_binding_required' in gaps
    assert 'claim_generation_unavailable' not in gaps
    assert all(c.operation_binding.model_dump(mode='json') == bindings[i] for i, c in enumerate(claims))


@pytest.mark.parametrize('background', [
    'In Superhuman Docs (formerly, "Coda"), we only have three types of members within our workspaces:',
    'There are only three member types in a workspace: makers, editors, and admins.',
])
def test_member_classification_is_context_not_a_creation_prerequisite(background):
    quote = 'Doc Makers can also create and delete docs, manage doc settings, create pages, use Docs AI, and create and manage folders.'
    row = next(r for r in structured_operations(quote, [quote, background], 'Coda') if r['operation'] == 'create')
    assert row['role'] == 'Doc Makers'
    assert row['prerequisites'] == []


@pytest.mark.parametrize('background', [
    'Confluence admins can create custom roles for recurring access needs that the default roles don’t support.',
    'This page answers frequently asked questions for Confluence sites transitioning from individual space permissions to role-based access.',
    "Can't create a page or blog?",
])
def test_other_actor_capabilities_document_introductions_and_help_titles_are_not_requirements(background):
    quote = 'Viewers can read and comment on content items.'
    assert all(not row['prerequisites'] for row in structured_operations(quote, [quote, background], 'Confluence'))


@pytest.mark.parametrize(('quote', 'background', 'product'), [
    ('Members can manage access to pages.', "Even in a shared space, you may have content that you're not ready to share with everyone yet. Or perhaps you have some confidential content that's only meant for a few eyes. Whatever the reason, Confluence lets you set view and edit restrictions at the content level so you can keep your content as open or as closed as you need.", 'Confluence'),
    ('Members can manage access to pages.', 'Confluence’s core tenet is about getting the right knowledge to the right people in your organization. To support this, Confluence’s permissions are open by default, which means that the content wants to be available to everyone unless otherwise noted.', 'Confluence'),
    ('Members can comment on content.', 'On the workspace level, you can decide which members of your team are allowed to add or edit content and who will only need to view it or comment on it.', 'Nuclino'),
])
def test_descriptive_capability_context_is_not_a_necessary_operation_condition(quote, background, product):
    original = fact(product, quote, slot='description').model_copy(update={'value_json': canonical_json([quote, background])})
    rows = operation_observations(original)
    assert rows and all(not row['prerequisites'] for row in rows)
    assert all(background in row['condition_evidence'] for row in rows)
    assert background in original.value


@pytest.mark.parametrize('requirement', [
    'Only after the page has been shared.',
    'You must have access to the parent workspace.',
    'Only invited members can access pages.',
    'You cannot comment without the comment permission.',
    'Available on paid plans.',
])
def test_background_filter_keeps_real_eligibility_access_plan_and_sequence_requirements(requirement):
    quote = 'Members can comment on pages.'
    row = next(r for r in structured_operations(quote, [quote, requirement], 'Notion') if r['operation'] == 'comment')
    assert any(p['quote'] == requirement for p in row['prerequisites'])


@pytest.mark.parametrize(('quote', 'requirement', 'operation'), [
    ('You can create pages.', 'Only invited members can create pages.', 'create'),
    ('You can comment on pages.', 'Only signed-in members can comment on pages.', 'comment'),
    ('You can create pages.', 'Members can create pages only if they are logged in.', 'create'),
])
def test_unknown_main_actor_keeps_explicit_member_eligibility(quote, requirement, operation):
    original = fact('Notion', quote, slot='unknown-actor').model_copy(update={'value_json': canonical_json([quote, requirement])})
    row = next(r for r in operation_observations(original) if r['operation'] == operation)
    assert row['role'] == 'You'
    assert any(p['quote'] == requirement for p in row['prerequisites'])
    assert requirement in row['condition_evidence']


@pytest.mark.parametrize(('requirement', 'kind'), [
    ('This page explains that members must have access to the parent workspace before commenting.', 'parent_access'),
    ('This guide explains that only invited members can comment on pages.', 'shared_access'),
])
def test_intro_prefix_does_not_hide_explicit_access_eligibility(requirement, kind):
    quote = 'Members can comment on pages.'
    row = next(r for r in structured_operations(quote, [quote, requirement], 'Notion') if r['operation'] == 'comment')
    assert {'kind': kind, 'quote': requirement} in row['prerequisites']


@pytest.mark.parametrize(('quote', 'requirement'), [
    ('Members can comment on pages.', 'This guide explains that members can comment on pages only after signing in.'),
    ('Guests can comment on pages.', 'Owners must grant access before guests can comment on pages.'),
    ('Guests can comment on pages.', 'Owners must give guests access before they can comment on pages.'),
])
def test_scoped_login_sequence_and_other_actor_access_grant_remain_prerequisites(quote, requirement):
    original = fact('Notion', quote, slot='grant-sequence').model_copy(update={'value_json': canonical_json([quote, requirement])})
    row = next(r for r in operation_observations(original) if r['operation'] == 'comment')
    assert any(p['quote'] == requirement for p in row['prerequisites'])
    assert requirement in row['condition_evidence']


def test_compact_context_keeps_six_actions_and_exact_access_branches_within_budget():
    quotes = [VIEW, COMMENT, 'You can edit the same page at the same time with an unlimited number of people.',
              'Can create: People on Business plans can create pages.',
              'Full access: People can share pages.', 'Members can manage access to pages.']
    originals = [fact('Notion', q, slot=str(i)) for i, q in enumerate(quotes)]
    originals = [f.model_copy(update={'value_json': canonical_json([f.quote, CHOICE])}) for f in originals]
    requested = ('read', 'comment', 'edit', 'create', 'share', 'manage_access')
    payload, omitted = writer.compact_dimension_context({'segment_competitor': 'Notion', 'dimension': 'feature'},
        SimpleNamespace(facts=originals), {f.id for f in originals}, requested_operations=requested, max_bytes=14000)
    assert not payload['missing_operations']
    assert len(writer.compact_prompt_json(payload).encode()) <= 14000
    candidates = [o for f in payload['evidence_view']['facts'] for o in f['operation_observations']]
    assert set(requested) <= {b['operation'] for b in candidates}
    assert all(any(b == operation_binding(o) for f in originals for o in operation_observations(f)) for b in candidates)
    assert any(b.get('condition_groups') for b in candidates)


def test_writer_prefers_page_comment_permission_over_database_property_instruction():
    permission = fact('Notion', COMMENT, slot='permission').model_copy(update={'value_json': canonical_json([COMMENT, CHOICE])})
    property_comment = fact('Notion', 'You can leave comments directly on database properties.', slot='property')
    ordinary = fact('Notion', 'Members can edit and share pages.', slot='ordinary')
    payload, _ = writer.compact_dimension_context({'segment_competitor': 'Notion', 'dimension': 'feature'},
        SimpleNamespace(facts=[permission, property_comment, ordinary]), {permission.id, property_comment.id, ordinary.id}, requested_operations=('comment', 'edit', 'share'))
    observation = next(o for f in payload['evidence_view']['facts'] for o in f['operation_observations'] if o['operation'] == 'comment')
    assert observation['fact_id'] == permission.id
    assert observation['role'] == 'Can comment' and observation['object_type'] == 'page'


def test_advisory_analysis_cannot_evict_an_original_operation_that_fits_the_budget():
    original = fact('Notion', COMMENT, slot='permission').model_copy(update={'value_json': canonical_json([COMMENT, CHOICE])})
    selected = {'segment_competitor': 'Notion', 'dimension': 'feature'}
    base, _ = writer.compact_dimension_context(selected, SimpleNamespace(facts=[original]), {original.id}, requested_operations=('comment',))
    budget = len(writer.compact_prompt_json(base).encode()) + 300
    payload, _ = writer.compact_dimension_context(selected, SimpleNamespace(facts=[original]), {original.id}, requested_operations=('comment',),
        max_bytes=budget, upstream_context={'upstream_analysis': {'content': 'Advisory claim. ' * 500}, 'upstream_context_gaps': []})
    assert payload['missing_operations'] == []
    assert 'upstream_analysis' not in payload
    assert 'upstream_analysis_context_budget_exceeded' in payload['upstream_context_gaps']
    assert len(writer.compact_prompt_json(payload).encode()) <= budget


def test_writer_view_shares_repeated_full_conditions_before_budget_selection(monkeypatch):
    from packages.research.evidence.views import select_evidence_view
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Notion']
    detail.raw_sources = [s for s in detail.raw_sources if s.competitor == 'Notion']
    template = detail.raw_sources[0].metadata['normalized_fields'][0]
    detail.raw_sources[0].metadata['normalized_fields'] = [
        {**template, 'slot': str(i), 'evidence_quote': q, 'evidence_terms': [q, CHOICE],
         'qualifiers': {'operations': structured_operations(q, [q, CHOICE], 'Notion')}}
        for i, q in enumerate([VIEW, COMMENT, 'Members can manage access to pages.',
            'You can edit the same page at the same time with an unlimited number of people.'])]
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    view = select_evidence_view(snapshot, agent='writer', competitor='Notion', dimension='feature', max_bytes=18000)
    assert {f.quote for f in view.facts if f.field == 'evidence_terms'} == {row['evidence_quote'] for row in detail.raw_sources[0].metadata['normalized_fields']}
    assert len(view.to_prompt_json().encode()) <= 18000


def test_sparse_standard_report_keeps_verified_facts_and_one_gap_plan():
    service, detail = fixture()
    detail.plan.research_depth = 'standard'
    detail.plan.dimensions = ['feature', 'persona']
    detail.raw_sources[0].metadata['normalized_fields'][0].update(
        support_level='documented', evidence_terms=[detail.raw_sources[0].snippet], evidence_item_ids=['accepted-observation'])
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    assert not writer.dimension_writing_enabled(detail)  # Missing scope alone does not bypass phase QA.
    detail.collect_qa_findings = service._build_collect_qa_issues(detail)
    assert writer.dimension_writing_enabled(detail)
    original = next(f for f in snapshot.facts if f.field == 'evidence_terms')
    claim = ReportClaim(id='verified', text='多人可以同时编辑页面，修改实时可见。', kind='fact',
        competitor='Notion', dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])
    audits = [ReportDimensionAudit(competitor=p, dimension=d, consumption_id=f'{p}/{d}',
        claims=[AuditedReportClaim(claim=claim, status='supported')] if (p, d) == ('Notion', 'feature') else [],
        gaps=['no_reviewed_claims'] if (p, d) != ('Notion', 'feature') else [])
        for p in detail.plan.competitors for d in detail.plan.dimensions]
    report = writer.render_dimension_report(detail, audits, snapshot=snapshot)
    assert claim.text in report and '[source:verified]' in report
    assert '### Coda —' not in report and '### Notion — 目标用户' not in report
    assert report.count('## 证据缺口与补证清单') == 1
    assert '目标用户' in report and 'Coda' in report and len(report) < 1800
    assert '官方功能或规格说明' in report
    assert 'SWOT' not in report and '暂无通过主张审核' not in report
    from packages.agents.writer.quality_preflight import run_writer_quality_preflight
    assert run_writer_quality_preflight(detail, report).passed


def test_repeated_multi_operation_sentence_is_not_printed_in_two_cells_or_body_items():
    original = fact('Notion', 'Can comment: People cannot edit or share content.', slot='denied')
    text = 'Can comment 角色不能编辑或分享内容。'
    claims = [ReportClaim(id=str(i), text=text, kind='fact', competitor='Notion', dimension='feature',
        fact_ids=[original.id], source_ids=[original.source_id], operation_binding=operation_binding(row))
        for i, row in enumerate(operation_observations(original))]
    detail = SimpleNamespace(topic='比较权限', output_language='zh-CN', raw_sources=[],
        comparison_matrix=None, plan=SimpleNamespace(dimensions=['feature'], competitors=['Notion'], target_product=None))
    audit = ReportDimensionAudit(competitor='Notion', dimension='feature', consumption_id='use',
        claims=[AuditedReportClaim(claim=c, status='supported') for c in claims])
    report = writer.render_dimension_report(detail, [audit], snapshot=SimpleNamespace(facts=[original], source_ids=[original.source_id]))
    table = '\n'.join(line for line in report.splitlines() if line.startswith('|'))
    assert table.count(text) == 1
    assert report.count('- ' + text) <= 1


def test_hardware_observations_do_not_render_empty_document_collaboration_tables():
    original = fact('Steam Deck OLED', 'Steam Deck OLED has 30-50% more battery life.', slot='battery')
    detail = SimpleNamespace(topic='硬件续航比较', output_language='zh-CN', raw_sources=[],
        comparison_matrix=None, plan=SimpleNamespace(dimensions=['feature'], competitors=['Steam Deck OLED'], target_product=None))
    claim = ReportClaim(id='battery', text=original.quote, kind='fact', competitor='Steam Deck OLED', dimension='feature',
        fact_ids=[original.id], source_ids=[original.source_id])
    audit = ReportDimensionAudit(competitor='Steam Deck OLED', dimension='feature', consumption_id='use',
        claims=[AuditedReportClaim(claim=claim, status='supported')])
    report = writer.render_dimension_report(detail, [audit], snapshot=SimpleNamespace(facts=[original], source_ids=[original.source_id]))
    assert '共享编辑' not in report and '权限边界' not in report and original.quote in report


def test_old_stored_classification_prerequisite_is_rejected_until_original_is_reprojected():
    quote = 'Doc Makers can create docs.'
    background = 'In Superhuman Docs, we only have three types of members within our workspaces:'
    rows = structured_operations(quote, [quote, background], 'Coda')
    old = [{**row, 'prerequisites': [{'kind': 'other', 'quote': background}]} for row in rows]
    original = fact('Coda', quote, slot='saved-taxonomy', qualifiers={'operations': old}).model_copy(
        update={'value_json': canonical_json([quote, background])})
    assert operation_observations(original) == []
    reprojected = original.model_copy(update={'id': 'new-projection', 'qualifiers_json': canonical_json({'operations': rows})})
    assert operation_observations(reprojected)[0]['prerequisites'] == []
    assert operation_binding(operation_observations(reprojected)[0])['fact_id'] == 'new-projection'


@pytest.mark.asyncio
async def test_real_partial_writer_final_audit_and_release_structure_keep_collection_blockers(monkeypatch):
    from datetime import datetime
    from packages.business_intel.release_gate import _compact_report_contract, _report_structure_issues, _run_quality_issues
    from packages.enterprise.projection import build_enterprise_projection
    service, detail = fixture()
    detail.plan.research_depth = 'standard'
    detail.plan.dimensions = ['feature', 'persona']
    source = detail.raw_sources[0]
    source.metadata.update(last_verified_at=datetime.utcnow().isoformat(), source_material_level='full_source')
    source.metadata['normalized_fields'][0].update(support_level='documented',
        evidence_terms=[source.snippet], evidence_item_ids=['accepted-observation'])
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    detail.collect_qa_findings = service._build_collect_qa_issues(detail)
    detail.qa_findings = list(detail.collect_qa_findings)
    original_blockers = [i.id for i in detail.collect_qa_findings if i.severity == 'blocker']

    async def model(record, **kwargs):
        payload = json.loads(kwargs['user'].split('\nJSON:\n', 1)[1])
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(c,
                'Offline fixture: the complete original supports simultaneous page editing.') for c in payload['claims']]})
        original = payload['evidence_view']['facts'][0]
        return json.dumps({'claims': [dict(text='多人可以同时编辑页面，修改实时可见。', kind='fact',
            competitor='Notion', dimension='feature', fact_ids=[original['id']], source_ids=[original['source_id']],
            observation_id=original['operation_observations'][0]['observation_id'])]})
    monkeypatch.setattr(service, '_trace_llm_text', model)
    record = service._runs[detail.id]
    await service._real_writer_step(record)
    assert len(detail.report_md) < 1800 and '多人可以同时编辑页面' in detail.report_md
    _, issues, _ = await service._final_qa_evidence(record)
    assert not any(i.metadata.get('claim_audit_reason') for i in issues)
    assert original_blockers == [i.id for i in detail.collect_qa_findings if i.severity == 'blocker']
    version = build_enterprise_projection(detail).report_version
    version.quality_metadata.update(analysis_plan=detail.plan.model_dump(mode='json'), execution_mode='real')
    assert _compact_report_contract(version)
    assert not _report_structure_issues(version)
    assert any(i.severity == 'blocker' for i in _run_quality_issues(version))
    version.quality_metadata.pop('report_structure_profile', None)
    assert not _compact_report_contract(version)  # Old unaudited legacy drafts get no new exemption.
