from types import SimpleNamespace

import pytest

from test_capability_alignment import fact


def test_permission_request_expands_operations_but_unrelated_products_do_not():
    from packages.research.evidence.operations import required_operations
    assert required_operations('比较权限边界', []) == ('read', 'comment', 'edit', 'create', 'share', 'manage_access')
    assert required_operations('比较评论操作', []) == ('comment',)
    assert required_operations('手机性能与相机', []) == ()


def test_actions_and_negations_are_separate_and_keep_source_conditions():
    from packages.research.evidence.operations import operation_observations
    original = fact('Notion', 'Can comment: People on all plans can comment on a page; they cannot edit or share content.', slot='x')
    rows = operation_observations(original, ['Notion'])
    assert {row['operation']: row['effect'] for row in rows} == {'comment': 'allowed', 'edit': 'denied', 'share': 'denied'}
    assert all(row['quote'] == original.quote and row['fact_id'] == original.id for row in rows)
    assert all(row['role'] == 'Can comment' and row['plan'] == 'all plans' and row['access_scope'] == 'document' for row in rows)


def test_create_rule_cannot_fill_edit_or_share_rows():
    from packages.research.evidence.operations import operation_alignment
    facts = [fact('Notion', 'Can edit: People can edit a page but cannot share it.', slot='x'),
             fact('Confluence', 'To create a page, you need the Add content permission in the space.', slot='y')]
    view = SimpleNamespace(facts=facts, source_ids=('source-Notion', 'source-Confluence'))
    rows = {row['operation']: row for row in operation_alignment(view, ['Notion', 'Confluence'], ('edit', 'create', 'share'))}
    assert rows['edit']['product_statuses']['Confluence'] == 'unknown'
    assert rows['create']['product_statuses']['Notion'] == 'unknown'
    assert rows['share']['observations_by_product']['Notion'][0]['effect'] == 'denied'
    assert all(row['comparison_status'] == 'insufficient_evidence' for row in rows.values())


@pytest.mark.parametrize('mutation', ['source', 'status', 'foreign'])
def test_invalid_or_other_product_observation_is_not_coverage(mutation):
    from packages.research.evidence.operations import operation_alignment
    original = fact('Notion', 'Can edit: People on all plans can edit pages.', slot='x')
    ids = ('source-Notion',)
    if mutation == 'source':
        ids = ()
    elif mutation == 'status':
        original = original.model_copy(update={'status': 'signal'})
    else:
        original = original.model_copy(update={'quote': 'AcmeDocs users can edit pages.'})
    rows = operation_alignment(SimpleNamespace(facts=[original], source_ids=ids), ['Notion', 'AcmeDocs'], ('edit',))
    assert rows[0]['product_statuses']['Notion'] == 'unknown'


def test_unspecified_plan_is_unknown_and_different_roles_need_review():
    from packages.research.evidence.operations import operation_alignment
    facts = [fact('Notion', 'Can edit: People can edit pages.', slot='x'),
             fact('Coda', 'Full access: People on Enterprise plans can edit documents.', slot='y')]
    row = operation_alignment(SimpleNamespace(facts=facts, source_ids=('source-Notion', 'source-Coda')), ['Notion', 'Coda'], ('edit',))[0]
    assert row['comparison_status'] == 'needs_condition_review'
    assert row['observations_by_product']['Notion'][0]['plan'] is None
    assert 'plan' in row['observations_by_product']['Notion'][0]['missing_fields']


@pytest.mark.asyncio
@pytest.mark.parametrize('repair_ok', [True, False])
@pytest.mark.parametrize('repair_path', ['sharing-and-permissions', 'new-access-guide'])
async def test_pipeline_repairs_semantic_operation_gap_with_remaining_budget(repair_ok, repair_path):
    from packages.research.models import ResearchBrief, SourceCandidate
    from packages.research.pipeline import run_research_pipeline
    from packages.research.extraction.semantic import semantic_extraction
    brief = ResearchBrief(run_id='operation-repair', topic='比较评论操作', competitor='Notion', dimension='feature',
        product_category='文档', research_depth='quick', target_source_count=1, max_fetches=2, max_search_queries=1, max_candidates=2,
        max_repair_rounds=1, include_homepage_candidates=False, include_trusted_sources=False)
    seed = SourceCandidate(title='Notion comments', url='https://www.notion.com/help/comments-mentions-and-reminders', origin='manual', competitor='Notion', dimension='feature')
    queries, fetched = [], []

    async def fetch(url):
        fetched.append(url)
        text = ('Can comment: People on all plans can comment on a page.' if repair_ok
                else 'Notion provides comments on pages for team discussions.') if url.endswith('/' + repair_path) else 'Notion provides comments on pages for team discussions.'
        return SimpleNamespace(url=url, title='Notion collaboration', text=text, markdown=text,
            content_hash=url, ok=True, status='ok', quality_score=.9, metadata={})

    async def search(query, limit):
        from packages.search import SearchResult
        queries.append(query)
        return [SearchResult(title='Notion comment permissions', url='https://www.notion.com/help/' + repair_path, snippet='Notion comment roles and plans')]

    async def semantic(brief, page):
        return semantic_extraction(brief, page, {'facts': [{'quote': page.text}]})

    extra = seed.model_copy(update={'id': 'unused-candidate', 'url': 'https://www.notion.com/help/unused', 'confidence': .1})
    result = await run_research_pipeline(brief, fetch=fetch, search=search, seed_candidates=[seed, extra], semantic_extract=semantic)
    assert len(fetched) == 2 and len(queries) == 1
    assert 'comment' in queries[0].lower() and 'role' in queries[0].lower()
    gaps = [gap for gap in result.gaps if gap.metadata.get('operation') == 'comment']
    assert bool(gaps) is not repair_ok
    assert result.metrics['operation_repair_round_count'] == 1
    assert len(result.captured_pages) == 2
    assert len(result.candidates) <= brief.max_candidates
    from packages.research.evidence.admission import raw_sources_from_research_result
    sources = raw_sources_from_research_result(brief, result, batch_sources=[], target_source_count=1,
        requires_accepted_evidence=True, source_exists=lambda url, sources: False,
        confidence_for_source=lambda *args: .9, fallback_snippet=lambda page: page.snippet)
    assert len(sources) == 2  # Captured repair evidence must survive source projection.


def test_operation_matrix_field_is_backwards_compatible():
    from packages.schema.models import ComparisonMatrix
    matrix = ComparisonMatrix(competitors=['A'], dimensions=['feature'])
    assert matrix.operation_alignment == []


def test_operation_table_only_uses_reviewed_same_operation_claims():
    from packages.research.evidence.operations import operation_binding, operation_observations
    from packages.agents.writer.dimension_writer import render_operation_comparison
    from packages.research.evidence.report_claims import ReportClaim, AuditedReportClaim, ReportDimensionAudit
    facts = [fact('Notion', 'Can edit: People can edit a page but cannot share it.', slot='x'),
             fact('Confluence', 'To create a page, you need the Add content permission in the space.', slot='y')]
    detail = SimpleNamespace(topic='比较权限', output_language='zh-CN', plan=SimpleNamespace(dimensions=['feature'], competitors=['Notion', 'Confluence'], target_product=None))
    claims = [ReportClaim(id='edit', text='编辑者可以编辑页面，但不能分享。', kind='fact', competitor='Notion', dimension='feature', fact_ids=[facts[0].id], source_ids=['source-Notion'], operation_binding=operation_binding(next(row for row in operation_observations(facts[0]) if row['operation'] == 'edit'))),
              ReportClaim(id='create', text='创建页面需要空间的 Add content 权限。', kind='fact', competitor='Confluence', dimension='feature', fact_ids=[facts[1].id], source_ids=['source-Confluence'])]
    audits = [ReportDimensionAudit(competitor=claim.competitor, dimension='feature', consumption_id='use', claims=[AuditedReportClaim(claim=claim, status='supported' if claim.id == 'edit' else 'rejected')]) for claim in claims]
    snapshot = SimpleNamespace(facts=facts, source_ids=['source-Notion', 'source-Confluence'])
    lines = render_operation_comparison(detail, audits, snapshot=snapshot)
    edit_line = next(line for line in lines if line.startswith('| 编辑 |'))
    assert '编辑者可以编辑页面' in edit_line
    assert 'Add content' not in edit_line and '未取得已审核观察' in edit_line
    assert '创建页面需要空间' not in '\n'.join(lines)
    assert '套餐未核实' in edit_line


def test_nuclino_uses_same_operation_projection_without_preset_answers():
    from packages.business_intel.entity_resolver import resolve_competitor_identity
    from packages.research.evidence.operations import operation_alignment
    assert resolve_competitor_identity('Nuclino').sources_by_dimension['feature']
    original = fact('Nuclino', 'Comment-only: Members on paid plans can comment on content, but cannot edit content.', slot='new-product')
    rows = operation_alignment(SimpleNamespace(facts=[original], source_ids=('source-Nuclino',)), ['Nuclino'], ('comment', 'edit', 'share'))
    assert rows[0]['observations_by_product']['Nuclino'][0]['effect'] == 'allowed'
    assert rows[1]['observations_by_product']['Nuclino'][0]['effect'] == 'denied'
    assert rows[2]['product_statuses']['Nuclino'] == 'unknown'


def test_discovered_operation_repair_document_requires_trusted_product_and_scope():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_page_allowed
    brief, _, page = fixture()
    page = page.model_copy(update={'final_url': 'https://www.notion.com/help/new-access-guide'})
    assert not semantic_page_allowed(brief, page)
    repair = brief.model_copy(update={'required_fields': ['operation.share']})
    assert semantic_page_allowed(repair, page)
    assert not semantic_page_allowed(repair, page.model_copy(update={'final_url': 'https://notion.com.evil.example/help/new-access-guide'}))
    assert not semantic_page_allowed(repair, page.model_copy(update={'final_url': 'https://www.notion.com/pricing'}))


def test_fixed_acceptance_case_can_select_depth_without_changing_run_budget():
    from scripts.eval_live_products import acceptance_request
    request = acceptance_request({'id': 'four', 'topic': '权限', 'competitors': ['Notion', 'Coda', 'Confluence', 'Nuclino'],
                                  'dimensions': ['feature'], 'research_depth': 'standard'})
    assert request.research_depth == 'standard' and len(request.competitors) == 4


def test_quick_operation_repair_is_enabled_only_for_requested_document_actions():
    from packages.research.evidence.operations import operation_repair_rounds
    assert operation_repair_rounds('权限比较', (), 'feature', enabled=True, depth_rounds=0) == 1
    assert operation_repair_rounds('相机性能', (), 'feature', enabled=True, depth_rounds=0) == 0
    assert operation_repair_rounds('权限比较', (), 'feature', enabled=False, depth_rounds=0) == 0


def test_negative_later_action_does_not_deny_earlier_positive_action():
    from packages.research.evidence.operations import operation_observations
    rows = operation_observations(fact('Notion', 'Members on all plans can comment on a page and cannot edit it.', slot='x'))
    assert {row['operation']: row['effect'] for row in rows} == {'comment': 'allowed', 'edit': 'denied'}


def test_conditions_do_not_cross_roles_or_close_wrong_gap():
    from packages.research.evidence.operations import operation_alignment
    facts = [fact('Notion', 'Editors on all plans can edit pages; guests can read pages.', slot='x'),
             fact('Coda', 'Editors on all plans can edit docs; workspace members can read docs.', slot='y')]
    rows = operation_alignment(SimpleNamespace(facts=facts, source_ids=('source-Notion', 'source-Coda')), ['Notion', 'Coda'], ('read',))
    assert rows[0]['comparison_status'] == 'needs_condition_review'
    assert rows[0]['observations_by_product']['Notion'][0]['role'].lower() == 'guests'
    assert rows[0]['observations_by_product']['Notion'][0]['plan'] is None


def test_new_official_repair_document_survives_server_admission_context():
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    brief, candidate, page = fixture('Members on paid plans can comment on a document in the workspace.')
    brief = brief.model_copy(update={'required_fields': ['operation.comment']})
    candidate = candidate.model_copy(update={'url': 'https://www.notion.com/help/new-access-guide'})
    page = page.model_copy(update={'requested_url': candidate.url, 'final_url': candidate.url})
    result = semantic_extraction(brief, page, {'facts': [{'quote': page.text}]})
    assert result.fields
    assert admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])[0].status == 'accepted'


@pytest.mark.parametrize('depth', ['quick', 'standard', 'deep'])
def test_operation_writer_is_available_for_single_dimension_at_every_depth(depth):
    from packages.agents.writer.dimension_writer import dimension_writing_enabled
    detail = SimpleNamespace(topic='权限比较', execution_mode='real', plan=SimpleNamespace(
        dimensions=['feature'], research_depth=depth, target_product=None))
    assert dimension_writing_enabled(detail)
    detail.execution_mode = 'demo'
    assert not dimension_writing_enabled(detail)


def test_inline_access_prerequisites_are_not_erased_from_comparison():
    from packages.research.evidence.operations import operation_alignment
    facts = [fact('Notion', 'Members on all plans can edit pages only after owner approval.', slot='x'),
             fact('Coda', 'Members on all plans can edit pages without owner approval.', slot='y')]
    row = operation_alignment(SimpleNamespace(facts=facts, source_ids=('source-Notion', 'source-Coda')), ['Notion', 'Coda'], ('edit',))[0]
    assert row['comparison_status'] == 'needs_condition_review'
    assert 'only after owner approval' in row['observations_by_product']['Notion'][0]['condition_evidence'][0]


def test_while_role_transition_is_not_a_shared_negative_clause():
    from packages.research.evidence.operations import operation_observations
    rows = operation_observations(fact('Notion', 'Members on all plans can comment on a page, while guests cannot edit it.', slot='x'))
    assert rows[0]['operation'] == 'comment' and rows[0]['effect'] == 'allowed'
    assert rows[1]['operation'] == 'edit' and rows[1]['effect'] == 'denied'
    assert rows[1]['role'].lower() == 'guests' and rows[1]['plan'] is None


def test_registered_official_document_does_not_require_brand_in_title():
    from packages.research.extraction.semantic import semantic_extraction, semantic_page_allowed
    from packages.research.models import ResearchBrief, CapturedPage
    brief = ResearchBrief(run_id='new-product-title', topic='评论操作', competitor='Nuclino', dimension='feature', product_category='文档')
    url = 'https://help.nuclino.com/a6f815d8-comment-on-content'
    page = CapturedPage(candidate_id='candidate', requested_url=url, final_url=url, title='Comment on content',
        text='Workspace members with full access or comment-only roles can comment on text, images, and embeds within an item.',
        content_hash='capture', status='ok', quality_score=.9)
    assert semantic_page_allowed(brief, page)
    assert semantic_extraction(brief, page, {'facts': [{'quote': page.text}]}).fields
    assert not semantic_page_allowed(brief, page.model_copy(update={'final_url': 'https://help.nuclino.com/unregistered-page'}))


@pytest.mark.asyncio
async def test_semantic_support_is_admitted_before_unnecessary_discovery():
    from packages.research.pipeline import run_research_pipeline
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.models import ResearchBrief, SourceCandidate
    brief = ResearchBrief(run_id='early-semantic', topic='比较评论操作', competitor='Notion', dimension='feature',
        product_category='文档', research_depth='quick', target_source_count=1, max_fetches=2, max_search_queries=1,
        max_repair_rounds=1, include_homepage_candidates=False, include_trusted_sources=False)
    url = 'https://www.notion.com/help/sharing-and-permissions'
    candidate = SourceCandidate(title='Notion comments', url=url, origin='manual', competitor='Notion', dimension='feature')
    queries = []
    async def fetch(url):
        return SimpleNamespace(url=url, title='Notion comments', text='Can comment: People on all plans can comment on a page.', ok=True, quality_score=.9)
    async def search(query, limit):
        queries.append(query)
        return []
    async def semantic(brief, page):
        return semantic_extraction(brief, page, {'facts': [{'quote': page.text}]})
    result = await run_research_pipeline(brief, fetch=fetch, search=search, seed_candidates=[candidate], semantic_extract=semantic)
    assert queries == [] and result.coverage.passed
    assert not [gap for gap in result.gaps if gap.metadata.get('source') == 'operation_comparison']


def test_compound_access_roles_and_item_target_are_preserved():
    from packages.research.evidence.operations import operation_observations
    original = fact('Nuclino', 'Workspace members with full access or comment-only roles can comment on an item.', slot='x')
    row = operation_observations(original)[0]
    assert 'full access or comment-only' in row['role'].lower()
    assert row['access_scope'] == 'item'


def test_role_location_is_not_the_action_access_scope():
    from packages.research.evidence.operations import operation_observations
    row = operation_observations(fact('Notion', 'Workspace members can comment on content.', slot='x'))[0]
    assert row['access_scope'] == 'content'


@pytest.mark.parametrize('quote', ['Comment-only members cannot edit content.', 'Can comment: People cannot edit or share content.'])
def test_role_name_is_not_an_assertion_that_commenting_is_denied(quote):
    from packages.research.evidence.operations import operation_observations
    rows = operation_observations(fact('Notion', quote, slot='x'))
    assert 'comment' not in {row['operation'] for row in rows}
    assert next(row for row in rows if row['operation'] == 'edit')['effect'] == 'denied'


def test_without_action_does_not_establish_positive_or_negative_support():
    from packages.research.evidence.operations import operation_alignment, operation_observations, operation_gaps
    from test_semantic_extraction import fixture
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.evidence.admission import admit_evidence_items
    original = fact('Notion', 'Members on all plans can edit pages without sharing them.', slot='x')
    assert {row['operation'] for row in operation_observations(original)} == {'edit'}
    row = operation_alignment(SimpleNamespace(facts=[original], source_ids=('source-Notion',)), ['Notion'], ('share',))[0]
    assert row['product_statuses']['Notion'] == 'unknown'
    brief, candidate, page = fixture(original.quote)
    brief = brief.model_copy(update={'topic': '比较分享操作'})
    result = semantic_extraction(brief, page, {'facts': [{'quote': page.text}]})
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items[0].status == 'accepted'
    assert operation_gaps(brief, items)[0].metadata['operation'] == 'share'


def test_reviewed_edit_without_sharing_cannot_fill_share_cell():
    from packages.agents.writer.dimension_writer import render_operation_comparison
    from packages.research.evidence.report_claims import ReportClaim, AuditedReportClaim, ReportDimensionAudit
    original = fact('Notion', 'Members on all plans can edit pages without sharing them.', slot='x')
    claim = ReportClaim(id='edit', text='Members can edit pages without sharing them.', kind='fact', competitor='Notion',
        dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])
    audit = ReportDimensionAudit(competitor='Notion', dimension='feature', consumption_id='use',
        claims=[AuditedReportClaim(claim=claim, status='supported')])
    detail = SimpleNamespace(topic='权限对照', output_language='zh-CN', plan=SimpleNamespace(dimensions=['feature'], competitors=['Notion'], target_product=None))
    lines = render_operation_comparison(detail, [audit], snapshot=SimpleNamespace(facts=[original], source_ids=[original.source_id]))
    assert 'without sharing' not in next(line for line in lines if line.startswith('| 分享 |'))


@pytest.mark.parametrize('quote', ['Members can edit a comment within an item.', 'Members can share a comment link from a document.'])
def test_comment_suboperations_are_not_document_edit_or_share(quote):
    from packages.research.evidence.operations import operation_observations
    rows = operation_observations(fact('Nuclino', quote, slot='x'))
    assert not {'edit', 'share'} & {row['operation'] for row in rows}


@pytest.mark.parametrize('quote,expected', [
    ('Members on all plans can edit pages and share comments.', 'edit'),
    ('Members on all plans can share pages and edit comments.', 'share'),
    ('Members on all plans can edit comments and edit pages.', 'edit'),
])
def test_comment_suboperation_filter_keeps_independent_document_actions(quote, expected):
    from packages.research.evidence.operations import operation_observations
    assert expected in {row['operation'] for row in operation_observations(fact('Nuclino', quote, slot='x'))}


def test_actual_comment_edit_instruction_does_not_establish_document_editing():
    from packages.research.evidence.operations import operation_observations
    quote = "- Open the item or collection which contains the comment you'd like to edit.\n- Click on the highlighted content.\n- Click on the comment and edit the text directly.\n- Click on SAVE or use the Ctrl/Cmd +Enter keyboard shortcut."
    assert 'edit' not in {row['operation'] for row in operation_observations(fact('Nuclino', quote, slot='instruction'))}


def test_claim_object_filter_uses_same_scope_as_source_projection():
    from packages.research.evidence.operations import operation_matches_text
    assert not operation_matches_text('edit', 'Nuclino 编辑评论的操作方式：打开包含该评论的条目，点击该评论并直接编辑文本。')
    assert operation_matches_text('edit', '成员可以编辑页面并分享评论。')
    assert operation_matches_text('share', '成员可以分享页面并编辑评论。')


def test_structured_heading_role_and_wrapped_availability_are_source_local():
    from packages.research.evidence.operations import structured_operations
    quote = 'They can edit pages, but cannot share them.'
    context = 'Can edit\n' + quote
    rows = structured_operations(quote, [context, 'Available on\nAll plans'], 'Notion')
    assert rows and all(row['role'] == 'Can edit' and row['plan'] == 'All plans' for row in rows)
    assert {row['operation']: row['effect'] for row in rows} == {'edit': 'allowed', 'share': 'denied'}


def test_access_prerequisite_does_not_create_a_second_operation():
    from packages.research.evidence.operations import operation_observations
    quote = 'Guests can edit documents only after admins create a page for them.'
    rows = operation_observations(fact('Notion', quote, slot='conditional-edit'))
    assert [row['operation'] for row in rows] == ['edit']
    assert rows[0]['role'] == 'Guests' and rows[0]['object_type'] == 'document'


@pytest.mark.parametrize('quote', [
    'You can manage general access to your page by selecting Share at the top of a page.',
    'You can assign specific permissions to people tagged in a database property.',
    'You can change a user’s access on the doc from the sharing dialog.',
    'You can set view and edit restrictions at the content level.',
    '你可以更改文档的访问权限。',
])
def test_access_management_keeps_document_or_database_object(quote):
    from packages.research.evidence.operations import operation_observations
    rows = operation_observations(fact('Notion', quote, slot='access-rule'))
    assert any(row['operation'] == 'manage_access' for row in rows)
    assert all(row['plan'] is None for row in rows)


def test_generic_admitted_feature_also_stores_structured_operations():
    from packages.research.models import EvidenceItem
    from packages.research.evidence.normalization import normalized_feature_fields_from_evidence_items
    quote = 'Guests can edit documents only after access to the parent page is granted.'
    item = EvidenceItem(id='generic-edit', competitor='Notion', dimension='feature', field='capability_1',
        value={'status': 'supported', 'evidence_terms': [quote]}, quote=quote, confidence=.8,
        captured_page_id='page', source_candidate_id='candidate', source_url='https://www.notion.com/help/sharing-and-permissions', status='accepted')
    row = normalized_feature_fields_from_evidence_items([item])[0]
    assert row.qualifiers['operations'][0]['object_type'] == 'document'
    assert row.qualifiers['operations'][0]['prerequisites'][0]['kind'] == 'parent_access'


def test_permission_ui_and_restrictions_are_not_document_actions():
    from packages.research.evidence.operations import operation_observations
    rows = operation_observations(fact('Notion', 'You can manage general access to your page by selecting Share at the top of a page.', slot='general-access'))
    assert {row['operation'] for row in rows} == {'manage_access'}
    rows = operation_observations(fact('Notion', 'You can set view and edit restrictions at the content level.', slot='content-rules'))
    assert {row['operation'] for row in rows} == {'manage_access'}


def test_table_row_comment_is_not_a_document_wide_rule():
    from packages.research.evidence.operations import structured_operations
    text = 'You can only leave comments on an entire row.'
    row = structured_operations(text, [text], 'Coda')[0]
    assert row['operation'] == 'comment' and row['object_type'] == 'table_row'
    assert row['object_quote'] == 'row'


def test_control_or_permission_edit_subaction_does_not_remove_independent_doc_action():
    from packages.research.evidence.operations import operation_matches_text
    assert operation_matches_text('share', 'Members can click the Share button and share pages with guests.')
    assert operation_matches_text('edit', 'Members can edit the access restrictions and edit pages.')
