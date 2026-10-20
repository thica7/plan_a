"""Finite v3 rejection gates; a forced verdict never proves general entailment."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from claim_review_fixture import supported_review
from test_bound_claim_support import bound_claim, prepared_detail
from test_literal_non_operation import draft, fact
from test_writer_question_delivery import service_for

from packages.agents.writer.dimension_writer import render_dimension_report, review_payload
from packages.research.evidence.report_claims import (
    AuditedReportClaim, ReportClaim, ReportDimensionAudit, audit_report_claims,
)
from packages.research.evidence.snapshot_models import EvidenceFact
from packages.research.evidence.source_spans import projected_source_facts, source_span_candidates


CAPTURED = Path(__file__).with_name('fixtures') / 'claim_semantics_v33.json'


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('network is forbidden in claim semantics tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)


def selected_claim(source, text, *, parent=None, kind='fact'):
    original = fact(quote=parent or source, value=[source])
    span = next(row for row in source_span_candidates(original) if row['quote'] == source)
    return original, ReportClaim(id='semantic-atom', **draft(original, text, kind=kind), source_span_bindings=[span])


def audit(original, claim, *, review=None, version=3, extra=()):
    view = SimpleNamespace(facts=[original, *extra], sources=[])
    review = review or supported_review(review_payload([claim], view, review_version=version)['claims'][0])
    return audit_report_claims([claim], [review], view,
        [SimpleNamespace(allowed_fact_ids=[original.id])], review_version=version)[0]


@pytest.mark.parametrize('row', json.loads(CAPTURED.read_text()), ids=lambda row: row['product'])
@pytest.mark.parametrize('forced', [False, True])
def test_actual_v33_claim_is_rejected_even_with_original_or_forced_supported_review(row, forced):
    saved = AuditedReportClaim.model_validate(row['audited_claim'])
    original = EvidenceFact.model_validate(row['fact'])
    assert saved.review.verdict == 'supported' and saved.status == 'supported'
    assert saved.claim.operation_binding is None
    projected, reasons = projected_source_facts(saved.claim, [original])
    assert not reasons and projected
    result = audit(original, saved.claim, review=None if forced else saved.review)
    assert result.status == 'rejected'
    assert any(reason.startswith('claim_semantics_') for reason in result.rule_reasons)


@pytest.mark.parametrize('row', json.loads(CAPTURED.read_text()), ids=lambda row: row['product'])
def test_final_qa_replays_original_v33_claim_guard(row):
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.research.evidence.answer_models import AnswerBoundary
    from packages.schema.models import DecisionBrief
    from test_question_retrieval import replace_snapshot
    saved = AuditedReportClaim.model_validate(row['audited_claim'])
    original = EvidenceFact.model_validate(row['fact'])
    detail, snapshot = prepared_detail(original.quote)
    detail.plan.competitors = [original.competitor]
    detail.plan.decision_brief = DecisionBrief(decision_question=f'{original.competitor}: can guests share a vault?')
    source = snapshot.sources[0].model_copy(update={'id': original.source_id, 'competitor': original.competitor})
    snapshot = replace_snapshot(detail, snapshot, facts=(original,), sources=(source,), competitors=(original.competitor,))
    service, record = service_for(detail)
    view, use = service._begin_evidence_use(record, agent='writer', competitor=original.competitor,
        dimension='feature', fact_ids=[original.id])
    segment = service._writer_segment_context(record, dict(segment_name=f'dimension:{original.competitor}:feature',
        segment_competitor=original.competitor, dimension='feature'), view, use)
    detail.report_answer_boundaries = [AnswerBoundary.model_validate(item) for item in segment['answer_boundaries']]
    envelope = ReportDimensionAudit(competitor=original.competitor, dimension='feature', consumption_id=use.id,
        claims=[saved], claim_review_version=3)
    detail.report_dimension_audits = [ReportDimensionAudit.model_validate_json(envelope.model_dump_json())]
    detail.report_md = render_dimension_report(detail, detail.report_dimension_audits, snapshot=snapshot)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(detail))
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'claim_review_replay_failed' for issue in issues)


@pytest.mark.parametrize('kind', ['fact', 'inference'])
@pytest.mark.parametrize('source,text,reason', [
    ('Workspaces offer both users core tools and secure data sharing in up to two collections.',
     '工作区用于与另外一名用户安全共享数据，并为两名用户提供核心工具及最多两个集合中的安全共享。',
     'claim_semantics_recipient_outside_support'),
    ('Workspaces offer both users core tools and secure data sharing in up to two collections.',
     'Workspaces share data with one other user and offer both users core tools.',
     'claim_semantics_recipient_outside_support'),
    ('Workspaces support secure data sharing.', '工作区支持安全共享数据，也可以管理访问权限。',
     'claim_semantics_action_outside_support'),
    ('You can promote a guest to member.', '必须将访客升级为成员。', 'claim_semantics_modal_strengthened'),
    ('You may upgrade a guest to member.', 'You must upgrade a guest to member.', 'claim_semantics_modal_strengthened'),
    ('You can promote a guest to member. Admins must sign in.', '需将访客升级为成员。',
     'claim_semantics_modal_strengthened'),
    ('Guests can share documents.', 'Guests must share documents.', 'claim_semantics_modal_strengthened'),
    ('Guests can share documents. Admins must share documents.', 'Guests must share documents.',
     'claim_semantics_modal_strengthened'),
    ('Members can edit documents only if they sign in.', 'If members sign in, they can edit documents.',
     'claim_semantics_condition_direction_changed'),
    ('If members sign in, they can edit documents.', 'Members can edit documents only if they sign in.',
     'claim_semantics_condition_direction_changed'),
])
def test_selected_support_rejects_recognizable_semantic_conflicts(source, text, reason, kind):
    original, claim = selected_claim(source, text, kind=kind)
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert reason in result.rule_reasons


def test_parent_sibling_other_claim_and_arbitrary_hints_cannot_authorize_required_upgrade():
    source = 'You can promote a guest to member.'
    original, claim = selected_claim(source, '必须将访客升级为成员。',
        parent=source + ' You must promote a guest to member.')
    unrelated = fact('other', quote='You must promote a guest to member.')
    result = audit(original, claim, extra=[unrelated])
    assert 'claim_semantics_modal_strengthened' in result.rule_reasons


@pytest.mark.parametrize('binding', ['source_span', 'operation'])
@pytest.mark.parametrize('kind', ['fact', 'inference'])
@pytest.mark.parametrize('text', [
    'Guests can share documents. Guests must manage access to documents.',
    '访客可以分享文档。访客必须管理文档的访问权限。',
    'Guests must edit documents.',
    '访客必须编辑文档。',
])
def test_necessary_known_action_outside_exact_support_is_rejected(binding, kind, text):
    original, claim = selected_claim('Guests can share documents.', text, kind=kind)
    if binding == 'operation':
        claim = bound_claim(original, text, 'share').model_copy(update={'kind': kind})
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert 'claim_semantics_action_outside_support' in result.rule_reasons


@pytest.mark.parametrize('source,text,operation', [
    ('Guests must share documents.', 'Guests must share documents.', 'share'),
    ('Guests must manage access to documents.', 'Guests must manage access to documents.', 'manage_access'),
    ('Guests must manage access to documents.', '访客必须管理文档的访问权限。', 'manage_access'),
    ('Only members with permission to manage access can edit documents.',
     '拥有管理访问权限的成员可以编辑文档。', 'edit'),
    ('You can choose Can edit, Can comment or Can view for Anyone with the link.',
     'You can choose Can edit, Can comment or Can view for Anyone with the link.', 'manage_access'),
    ('Guests can share documents.',
     'If admins must manage access, guests can share documents.', 'share'),
    ('Guests can share documents.',
     '如果管理员必须管理访问权限，访客可以分享文档。', 'share'),
    ('Guests can share documents.',
     'Guests can share documents provided that admins must manage access.', 'share'),
    ('Guests can share documents.',
     'Guests can share documents. Guests must transmogrify widgets.', 'share'),
])
def test_necessary_action_recognition_preserves_selected_support_conditions_and_unknowns(source, text, operation):
    original = fact(quote=source)
    result = audit(original, bound_claim(original, text, operation))
    assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('version', [None, 2])
def test_necessary_extra_action_gate_does_not_change_legacy_protocol(version):
    original = fact(quote='Guests can share documents.')
    claim = bound_claim(original, 'Guests can share documents. Guests must manage access to documents.', 'share')
    assert audit(original, claim, version=version).status == 'supported'


@pytest.mark.parametrize('binding', ['source_span', 'operation'])
@pytest.mark.parametrize('kind', ['fact', 'inference'])
@pytest.mark.parametrize('extra', [
    ' Guests must manage access to documents.',
    ' 访客必须管理文档的访问权限。',
])
def test_admin_prerequisite_cannot_authorize_an_independent_guest_action(binding, kind, extra):
    source = 'Guests can share documents only after admins manage access to the workspace.'
    original, claim = selected_claim(source, source + extra, kind=kind)
    if binding == 'operation':
        claim = bound_claim(original, claim.text, 'share').model_copy(update={'kind': kind})
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert 'claim_semantics_action_outside_support' in result.rule_reasons


@pytest.mark.parametrize('binding', ['source_span', 'operation'])
def test_complete_admin_prerequisite_stays_a_condition_of_the_main_action(binding):
    source = 'Guests can share documents only after admins manage access to the workspace.'
    original, claim = selected_claim(source, source)
    if binding == 'operation':
        claim = bound_claim(original, source, 'share')
    result = audit(original, claim)
    assert 'claim_semantics_action_outside_support' not in result.rule_reasons
    if binding == 'operation':
        assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('text', [
    'Only members who do not need to manage access can edit documents.',
    '只有不需要管理访问权限的成员才可以编辑文档。',
])
def test_negative_necessity_in_role_condition_is_not_an_independent_management_action(text):
    source = 'Only members who do not need to manage access can edit documents.'
    original = fact(quote=source)
    result = audit(original, bound_claim(original, text, 'edit'))
    assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('source', [
    'Only members who need to manage access can edit documents.',
    'Only members who are required to manage access can edit documents.',
])
def test_relative_role_necessity_is_preserved_before_the_main_permission(source):
    original = fact(quote=source)
    result = audit(original, bound_claim(original, source, 'edit'))
    assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('source,text', [
    ('Only members who need to manage access can edit documents.',
     '只有需要管理访问权限的成员才可以编辑文档。'),
    ('Only members who need to manage access can edit documents.',
     '需要管理访问权限的成员可以编辑文档。'),
    ('Only members who need to manage access can edit documents.',
     '只有必须管理访问权限的成员才可以编辑文档。'),
    ('Only guests who need to manage access can edit documents.',
     '只有需要管理访问权限的访客才可以编辑文档。'),
])
def test_complete_chinese_necessary_role_modifier_is_not_an_independent_action(source, text):
    original = fact(quote=source)
    result = audit(original, bound_claim(original, text, 'edit'))
    assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('binding', ['source_span', 'operation'])
@pytest.mark.parametrize('kind', ['fact', 'inference'])
@pytest.mark.parametrize('source,text', [
    ('Guests can manage access to documents.', 'Guests must manage access to documents.'),
    ('Guests can manage access to documents.', '访客必须管理文档的访问权限。'),
    ('访客可以管理文档的访问权限。', '访客必须管理文档的访问权限。'),
    ('Guests can manage permissions for documents.', 'Guests must manage permissions for documents.'),
])
def test_known_management_object_modal_strengthening_is_rejected(binding, kind, source, text):
    original, claim = selected_claim(source, text, kind=kind)
    if binding == 'operation':
        claim = bound_claim(original, text, 'manage_access').model_copy(update={'kind': kind})
    result = audit(original, claim)
    assert result.status == 'rejected'
    assert 'claim_semantics_modal_strengthened' in result.rule_reasons


@pytest.mark.parametrize('source,text', [
    ('Guests can manage access to documents.', 'Guests can manage access to documents.'),
    ('Guests can manage access to documents.', '访客可以管理文档的访问权限。'),
    ('Guests must manage access to documents.', '访客必须管理文档的访问权限。'),
    ('访客必须管理文档的访问权限。', '访客必须管理文档的访问权限。'),
    ('Guests can manage access to documents, and management of access to documents is required.',
     'Guests must manage access to documents.'),
    ('Guests can manage access to documents, and access to documents must be managed by guests.',
     'Guests must manage access to documents.'),
    ('Guests can manage access to flurbs.', 'Guests must manage access to flurbs.'),
])
def test_management_modals_preserve_legal_support_and_defer_unparsed_forms(source, text):
    original = fact(quote=source)
    claim = bound_claim(original, text, 'manage_access')
    if ', and' in source:
        assert claim.operation_binding.operation_quote == source.rstrip('.')
    result = audit(original, claim)
    assert not any(reason.startswith('claim_semantics_') for reason in result.rule_reasons)


@pytest.mark.parametrize('source,operation,expected', [
    ('Guests can share documents.', 'share', 'rejected'),
    ('Guests must not manage access to documents.', 'manage_access', 'supported'),
])
def test_independent_must_not_remains_a_source_bound_prohibition(source, operation, expected):
    original = fact(quote=source)
    result = audit(original, bound_claim(original, 'Guests must not manage access to documents.', operation))
    assert result.status == expected, result.rule_reasons
    if expected == 'rejected':
        assert 'claim_semantics_action_outside_support' in result.rule_reasons


@pytest.mark.parametrize('source,text', [
    ('Workspaces support secure data sharing.', '工作区支持安全共享数据。'),
    ('Workspaces share data with one other user.', '工作区用于与另外一名用户共享数据。'),
    ('Workspaces offer both users core tools and secure data sharing between them.',
     '工作区用于与另外一名用户共享数据。'),
    ('If files are encrypted, members can edit documents only after they sign in.',
     'If files are encrypted, members can edit documents only if they sign in.'),
    ('Workspaces offer both users core tools and secure data sharing in up to two collections.',
     '工作区支持在最多两个集合中安全共享数据。'),
    ('You can promote a guest to member.', '可以将访客升级为成员。'),
    ('You may upgrade a guest to member.', 'You may upgrade a guest to member.'),
    ('You must promote a guest to member.', '必须将访客升级为成员。'),
    ('You can promote a guest to member. Guests must be promoted to member.', '必须将访客升级为成员。'),
    ('You can promote a guest to member. Promotion from guest to member is required.', '必须将访客升级为成员。'),
    ('Members can edit documents. Editing documents is required.', 'Members must edit documents.'),
    ('You can promote a guest to member, but must upgrade admins to owners.', '必须将管理员升级为所有者。'),
    ('Members must not share data.', '成员不得共享数据。'),
    ('Members can edit documents only if they sign in.', 'Members can edit documents only if they sign in.'),
    ('Members can edit documents if they sign in.', 'If they sign in, members can edit documents.'),
    ('Members can transmogrify widgets.', 'Members must transmogrify widgets.'),
    ('Members can edit flurbs.', 'Members must edit flurbs.'),
])
def test_legal_or_unrecognized_forms_still_require_model_review(source, text):
    original, claim = selected_claim(source, text)
    result = audit(original, claim)
    assert not any(reason.startswith('claim_semantics_') for reason in result.rule_reasons)
    # These statements may need an operation binding under existing transport
    # rules; this guard must not introduce an additional semantic rejection.
    if not result.rule_reasons:
        assert result.status == 'supported'


@pytest.mark.parametrize('source', [
    'Workspaces provide secure data sharing between the two users. '
    'Workspaces offer both users core tools and secure data sharing.',
    'Workspaces provide secure data sharing between them. '
    'Workspaces offer both users core tools and secure data sharing.',
    'Workspaces provide secure data sharing between two users, '
    'and offer both users core tools and secure data sharing.',
])
def test_complete_selected_recipient_relationship_is_not_hidden_by_nominal_summary(source):
    from test_literal_non_operation import candidates
    original, claim = selected_claim(source, '工作区用于与另外一名用户安全共享数据。')
    assert not candidates(original)
    result = audit(original, claim)
    assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('source,text,operation', [
    ('Only members with permission to manage access can edit documents.', '拥有管理访问权限的成员可以编辑文档。', 'edit'),
    ('Members can edit documents after signing in and accepting the invitation.',
     'Members can edit documents after signing in and accepting the invitation.', 'edit'),
    ('Members can edit documents after signing in or accepting the invitation.',
     'Members can edit documents after signing in or accepting the invitation.', 'edit'),
    ('Members cannot share documents.', 'Members cannot share documents.', 'share'),
    ('Guests can share documents.', '访客可共享文档。', 'share'),
])
def test_complete_operation_conditions_and_negation_are_preserved(source, text, operation):
    original = fact(quote=source)
    result = audit(original, bound_claim(original, text, operation))
    assert result.status == 'supported', result.rule_reasons


@pytest.mark.parametrize('version', [None, 2])
def test_legacy_protocol_keeps_preexisting_semantic_behavior(version):
    original, claim = selected_claim('You can promote a guest to member.', '必须将访客升级为成员。')
    assert audit(original, claim, version=version).status == 'supported'


def test_semantics_does_not_use_a_forged_span_as_support():
    original, claim = selected_claim('You can promote a guest to member.', '必须将访客升级为成员。')
    forged = claim.source_span_bindings[0].model_copy(update={'quote': 'You must promote a guest to member.'})
    result = audit(original, claim.model_copy(update={'source_span_bindings': (forged,)}))
    assert result.status == 'rejected' and 'source_span_binding_mismatch' in result.rule_reasons
    assert not any(reason.startswith('claim_semantics_') for reason in result.rule_reasons)


@pytest.mark.asyncio
@pytest.mark.parametrize('row', json.loads(CAPTURED.read_text()), ids=lambda row: row['product'])
@pytest.mark.parametrize('valid', [False, True])
async def test_actual_writer_keeps_legal_atoms_and_rejects_original_false_supported_claim(monkeypatch, row, valid):
    from claim_review_fixture import expand_prompt_payload
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.schema.models import DecisionBrief
    from test_question_retrieval import replace_snapshot
    saved = AuditedReportClaim.model_validate(row['audited_claim'])
    original = EvidenceFact.model_validate(row['fact'])
    detail, snapshot = prepared_detail(original.quote)
    detail.plan.competitors = [original.competitor]
    is_cap = row['product'] == 'bitwarden'
    question = ('Bitwarden: 我们都在 2026 年新建了 Bitwarden 账户，并建立一个 Free organization，'
        '想让包括我在内的 3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？\n'
        'Bitwarden: 我们准备把离职同事“删掉”。他保存的密码之后还会留下吗？' if is_cap else
        '1Password: 可以把访客升级为家庭成员以提供自己的 Private vault 和多个共享保险库访问吗？')
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    detail.raw_sources[0].id = original.source_id
    detail.raw_sources[0].competitor = original.competitor
    detail.raw_sources[0].covered_competitors = [original.competitor]
    source = snapshot.sources[0].model_copy(update={'id': original.source_id, 'competitor': original.competitor,
        'payload_json': detail.raw_sources[0].model_dump_json()})
    replace_snapshot(detail, snapshot, facts=(original,), sources=(source,), competitors=(original.competitor,))
    service, record = service_for(detail)
    texts = ([
        'Free organization 为两名用户提供 Password Manager 的全部核心功能。',
        'Free organization 提供最多两个 collections 的安全数据共享。',
    ] if is_cap else [
        '若要让访客拥有自己的 Private vault 并访问多个共享保险库，可以将其从访客升级为家庭成员。',
    ]) if valid else [saved.claim.text]
    calls = []

    async def model(_record, **kwargs):
        calls.append(kwargs['name'])
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            span = saved.claim.source_span_bindings[0]
            sent = next(item for item in payload['evidence_view']['facts'] if item['id'] == original.id)
            assert span.span_id in {item['span_id'] for item in sent['source_span_candidates']}
            atoms = [dict(text=text, kind='fact', competitor=original.competitor, dimension='feature',
                fact_ids=[original.id], source_ids=[original.source_id], source_span_ids=[span.span_id]) for text in texts]
            return json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=atoms if index == 0 else [],
                missing_fields=[]) for index, q in enumerate(payload['questions'])]})
        if kwargs['name'] == 'dimension_claim_review':
            assert len(payload['claims']) == 1
            assert 'SAME governed predicate' in kwargs['system']
            assert payload['claims'][0]['support_quotes'] == [saved.claim.source_span_bindings[0].quote]
            return json.dumps({'reviews': [supported_review(payload['claims'][0])]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        selected = next((item for item in payload['claims'] if 'collections' in item['text']), payload['claims'][0])
        return json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'],
            status='answered' if is_cap else 'unverified', resolution='direct' if is_cap else 'unresolved',
            conclusion='no' if is_cap else 'unknown', claim_ids=[selected['id']] if is_cap else [],
            missing_fields=[], reason='The exact selected atom supports this answer.') for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    audited = [claim for envelope in detail.report_dimension_audits for claim in envelope.claims]
    assert [item.claim.text for item in audited if item.status == 'supported'] == (texts if valid else [])
    assert calls.count('dimension_claim_review') == len(texts)
    if valid:
        assert all(item.claim.operation_binding is None for item in audited)
        assert all(text in detail.report_md for text in texts)
        if is_cap:
            assert any(answer.status == 'answered' and answer.conclusion == 'no'
                       for envelope in detail.report_dimension_audits for answer in envelope.answer_coverage)
            assert calls.count('dimension_answer_review') == 1
        from packages.research.evidence.snapshot import current_snapshot
        assert not any(issue.metadata.get('claim_audit_reason') == 'claim_review_replay_failed'
                       for issue in audit_dimension_claims(service, record, current_snapshot(detail), producer_verified=True))
