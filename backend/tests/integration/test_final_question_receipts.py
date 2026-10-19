"""Persisted producer receipts must replay without consuming or rewriting them."""

import json
from datetime import UTC, datetime

import pytest
from claim_review_fixture import supported_review
from test_question_retrieval import research_case
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer.answer_coverage import parse_answer_coverage, research_questions
from packages.agents.writer.dimension_writer import compact_dimension_context, render_dimension_report, review_payload
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.research.evidence.answer_models import AnswerBoundary
from packages.research.evidence.report_claims import ReportClaim, ReportDimensionAudit, audit_report_claims
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.source_spans import source_span_candidates
from packages.schema.models import (
    ComparisonMatrix, CompetitorKnowledge, DecisionBrief, KnowledgeClaim, ReflectionRecord,
)


async def saved_report(monkeypatch, *, restore='json', legacy=False, upstream=False):
    from packages.agents.writer import question_retrieval

    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda kind: None)
    text = 'Organizations own collections.'
    question = 'Example Product: Who owns collections?'
    detail, _ = research_case([text], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    uses = {}
    if upstream:
        source_id = snapshot.sources[0].id
        detail.competitor_knowledge['Example Product'] = CompetitorKnowledge(competitor='Example Product')
        detail.competitor_knowledge['Example Product'].feature_tree.summary_claims = [
            KnowledgeClaim(claim=text, source_ids=[source_id], confidence=.9)]
        detail.comparison_matrix = ComparisonMatrix(competitors=['Example Product'], dimensions=['feature'])
        detail.reflections = [ReflectionRecord(iteration=1, writer_constraints=['Preserve ownership scope.'])]
        for agent in ('analyst', 'comparator', 'reflector'):
            scope = dict(competitor='Example Product', dimension='feature') if agent == 'analyst' else {}
            _, use, _ = await service._begin_question_evidence_use(record, agent=agent, **scope)
            service._validate_evidence_use(record, use)
            payload = (service._analyst_evidence_artifact_payload(detail, 'Example Product', 'feature')
                       if agent == 'analyst' else service._comparator_evidence_artifact_payload(detail)
                       if agent == 'comparator' else detail.reflections[-1].model_dump(mode='json'))
            service._record_evidence_artifact(record, kind=agent, uses=[use], payload=payload, **scope)
            uses[agent] = use.id
    if legacy:
        view, use = service._begin_evidence_use(record, agent='writer', competitor='Example Product', dimension='feature')
    else:
        view, use, _ = await service._begin_question_evidence_use(record, agent='writer', competitor='Example Product', dimension='feature')
    uses['writer'] = use.id
    fact = next(row for row in view.facts if row.field == 'evidence_terms' and row.quote == text)
    segment = service._writer_segment_context(record, dict(segment_name='dimension:Example Product:feature',
        segment_competitor='Example Product', dimension='feature'), view, use)
    boundaries = [AnswerBoundary.model_validate(row) for row in segment['answer_boundaries']]
    detail.report_answer_boundaries = boundaries
    # Bind only the actual compact advisory markers, using the same server
    # selection/validation as Writer. Model facts/reviews remain fixed fixtures.
    compact, _ = compact_dimension_context(segment, view,
        {fact_id for boundary in boundaries for fact_id in boundary.allowed_fact_ids},
        upstream_context=service._dimension_upstream_context(record, view) if upstream else {})
    selected_edges = service._validate_dimension_upstream(record, compact)
    if upstream:
        assert {edge.kind for edge in selected_edges} == {'analyst', 'comparator', 'reflector'}
    claim = ReportClaim(id='persisted-ownership', text=text, kind='fact', competitor=fact.competitor,
        dimension=fact.dimension, fact_ids=[fact.id], source_ids=[fact.source_id],
        source_span_bindings=[source_span_candidates(fact)[0]])
    version = 2 if legacy else 3
    review = supported_review(review_payload([claim], view, review_version=None if legacy else 3)['claims'][0])
    claims = audit_report_claims([claim], [review], view, boundaries, review_version=None if legacy else 3)
    assert claims[0].status == 'supported'
    questions = research_questions(detail, 'Example Product', 'feature')
    row = dict(question_id=questions[0]['question_id'], status='answered', claim_ids=[claim.id],
               resolution='direct', conclusion='yes', missing_fields=[], reason='Complete published ownership rule.')
    coverage = parse_answer_coverage(json.dumps(dict(version=version, answers=[row])), questions, {claim.id},
        claims=[claim.model_dump(mode='json')], required_binding_version=version, facts=view.facts)
    assert coverage[0].status == 'answered'
    detail.report_dimension_audits = [ReportDimensionAudit(competitor='Example Product', dimension='feature',
        consumption_id=use.id, claims=claims, answer_coverage=coverage,
        answer_binding_version=version, claim_review_version=None if legacy else 3,
        upstream_dependencies=None if legacy else selected_edges)]
    detail.report_md = render_dimension_report(detail, detail.report_dimension_audits, snapshot=snapshot)
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='writer', uses=[use], payload=service._writer_evidence_artifact_payload(detail))
    if restore == 'journal':
        service._journal.save_run(detail)
        record.detail = service._journal.load_run(detail.id)
    else:
        record.detail = type(detail).model_validate_json(detail.model_dump_json())
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    if legacy:
        assert 'upstream_dependencies' not in record.detail.report_dimension_audits[0].model_dump(mode='json')
    return service, record, snapshot, uses


def mutate_receipt(detail, use_id, change):
    span = next(span for span in detail.trace_spans if span.name == 'question_evidence_selection'
                and json.loads(span.full_output)['consumption_id'] == use_id)
    if change == 'missing':
        detail.trace_spans.remove(span)
    elif change == 'duplicate':
        detail.trace_spans.append(span.model_copy(deep=True))
    elif change == 'invalid_envelope':
        span.full_output = 'null'
    else:
        selection = json.loads(span.full_output)
        selection['receipt']['packets'][0][change] = 'changed'
        span.full_output = json.dumps(selection)


@pytest.mark.asyncio
@pytest.mark.parametrize('restore', ['json', 'journal'])
@pytest.mark.parametrize('agent,change', [
    ('writer', 'missing'), ('writer', 'duplicate'), ('writer', 'questions_sha256'),
    ('writer', 'scope_sha256'), ('writer', 'selection_config'), ('writer', 'selected_fact_ids'),
    ('writer', 'invalid_envelope'),
    ('analyst', 'missing'), ('comparator', 'missing'), ('reflector', 'missing'),
    ('analyst', 'duplicate'), ('comparator', 'scope_sha256'), ('reflector', 'selection_config'),
])
async def test_final_qa_replays_writer_and_current_upstream_receipts_without_side_effects(monkeypatch, restore, agent, change):
    service, record, snapshot, uses = await saved_report(monkeypatch, restore=restore, upstream=True)
    mutate_receipt(record.detail, uses[agent], change)
    before = record.detail.model_dump_json()
    # The final producer check is a read. It must not consume credentials, add
    # dispatch observations, persist, or reject credentials as a side effect.
    monkeypatch.setattr(service, '_persist_run', lambda *args: pytest.fail('final replay persisted'))
    verified = service._final_qa_producer_verified(record, snapshot)
    assert record.detail.model_dump_json() == before
    assert not verified, f'{agent} {change} receipt remained a verified producer'
    assert any(issue.metadata.get('claim_audit_reason') == 'claim_producer_unverified'
               for issue in audit_dimension_claims(service, record, snapshot, producer_verified=verified))


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['query', 'scope', 'config'])
async def test_final_qa_replays_receipt_against_current_identity(monkeypatch, change):
    service, record, snapshot, _ = await saved_report(monkeypatch)
    if change == 'query':
        record.detail.plan.decision_brief.decision_question = 'Example Product: Who owns shared collections?'
        # Even an attacker refreshing only the public upstream payload hash
        # cannot authorize a receipt for another question.
        dependency = record.detail.evidence_artifact_dependencies[-1]
        record.detail.evidence_artifact_dependencies[-1] = dependency.model_copy(update={
            'upstream_hash': service._artifact_upstream_hash(record.detail, 'writer')})
    elif change == 'scope':
        record.detail.plan.competitors = ['Other Suite']
    else:
        monkeypatch.setenv('KB_EMBEDDING_MODEL_VERSION', 'changed-after-save')
    before = record.detail.model_dump_json()
    assert not service._final_qa_producer_verified(record, snapshot)
    assert record.detail.model_dump_json() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('agent', ['writer', 'analyst'])
async def test_full_final_qa_rejects_lost_receipt_after_dto_restore(monkeypatch, agent):
    service, record, _, uses = await saved_report(monkeypatch, upstream=True)
    mutate_receipt(record.detail, uses[agent], 'missing')
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(issue.metadata.get('claim_audit_reason') == 'claim_producer_unverified' for issue in issues)


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', [False, True])
async def test_final_receipt_replay_preserves_legacy_and_ignores_unrelated_old_use(monkeypatch, legacy):
    service, record, snapshot, _ = await saved_report(monkeypatch, restore='journal', legacy=legacy)
    _, unused, _ = await service._begin_question_evidence_use(record, agent='analyst', competitor='Example Product', dimension='feature')
    mutate_receipt(record.detail, unused.id, 'missing')
    # Neither a missing receipt nor a rejected status on an unreferenced old
    # use may invalidate the actual report producer.
    record.detail.evidence_consumptions = [use.model_copy(update={'status': 'rejected'})
        if use.id == unused.id else use for use in record.detail.evidence_consumptions]
    before = record.detail.model_dump_json()
    assert service._final_qa_producer_verified(record, snapshot)
    assert record.detail.model_dump_json() == before
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)


@pytest.mark.asyncio
async def test_final_receipt_failure_agrees_with_normal_consumer(monkeypatch):
    service, record, snapshot, uses = await saved_report(monkeypatch)
    mutate_receipt(record.detail, uses['writer'], 'missing')
    assert not service._final_qa_producer_verified(record, snapshot)
    use = next(use for use in record.detail.evidence_consumptions if use.id == uses['writer'])
    with pytest.raises(EvidenceUseRejectedError, match='selection missing or ambiguous'):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_explicitly_omitted_upstream_does_not_become_a_dependency_from_matching_hash(monkeypatch):
    service, record, snapshot, uses = await saved_report(monkeypatch, upstream=True)
    audit = record.detail.report_dimension_audits[0]
    data = audit.model_dump(mode='json') | {'upstream_dependencies': []}
    record.detail.report_dimension_audits = [type(audit).model_validate(data)]
    # Same producer payload remains available, but this Writer explicitly used
    # no advisory markers. Its invalid receipt cannot retroactively add an edge.
    mutate_receipt(record.detail, uses['analyst'], 'missing')
    writer = next(use for use in record.detail.evidence_consumptions if use.id == uses['writer'])
    service._record_evidence_artifact(record, kind='writer', uses=[writer],
        payload=service._writer_evidence_artifact_payload(record.detail))
    saved = record.detail.report_dimension_audits[0].model_dump(mode='json')
    assert saved['upstream_dependencies'] == []
    assert service._final_qa_producer_verified(record, snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['kind', 'scope', 'producer_hash', 'consumptions', 'current_edge', 'missing_current'])
async def test_recorded_direct_upstream_edge_cannot_be_replaced(monkeypatch, change):
    service, record, snapshot, uses = await saved_report(monkeypatch, upstream=True)
    detail = record.detail
    audit = detail.report_dimension_audits[0]
    edge = next(item for item in audit.upstream_dependencies if item.kind == 'analyst')
    updates = {'kind': {'kind': 'writer'}, 'scope': {'competitor': 'Other Suite'},
               'producer_hash': {'payload_hash': 'changed'},
               'consumptions': {'consumption_ids': (uses['writer'],)}}
    if change == 'missing_current':
        detail.evidence_artifact_dependencies = [item for item in detail.evidence_artifact_dependencies if item != edge]
    elif change == 'current_edge':
        detail.evidence_artifact_dependencies = [item.model_copy(update={'consumption_ids': (uses['writer'],)})
            if item == edge else item for item in detail.evidence_artifact_dependencies]
    else:
        detail.report_dimension_audits = [audit.model_copy(update={'upstream_dependencies': tuple(
            item.model_copy(update=updates[change]) if item == edge else item for item in audit.upstream_dependencies)})]
    writer = next(use for use in detail.evidence_consumptions if use.id == uses['writer'])
    service._record_evidence_artifact(record, kind='writer', uses=[writer],
        payload=service._writer_evidence_artifact_payload(detail))
    record.detail = type(detail).model_validate_json(detail.model_dump_json())
    assert not service._final_qa_producer_verified(record, snapshot)
