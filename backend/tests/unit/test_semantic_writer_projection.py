"""Semantic fact IDs survive the protected Writer's first draft projection."""

import json
from claim_review_fixture import answer_response
from datetime import UTC, datetime

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response, supported_review
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case

from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.schema.models import DecisionBrief
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_protected_writer_projects_new_semantic_source_and_replays_its_producer(monkeypatch):
    product = 'Example Product'
    question = 'Example Product: Must Guests sign in?'
    login = 'Guests must sign in before starting a session.'
    detail, _ = research_case(['Guests can read documents.', 'Editors can edit documents.', login],
                              question=question)
    detail.plan.competitors = [product]
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    detail.output_language = 'en-US'
    detail.created_at = datetime.now(UTC)
    detail.updated_at = detail.created_at
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    target = next(f for f in snapshot.facts if f.field == 'evidence_terms' and f.quote == login)
    old_ids = tuple(f.id for f in snapshot.facts if f.field == 'evidence_terms' and f.id != target.id)
    old_source_ids = {f.source_id for f in snapshot.facts if f.id in old_ids}
    assert target.source_id not in old_source_ids
    # This seam fixes the prior lexical result, independently of future token
    # dictionaries, so the test measures propagation rather than ranking quality.
    monkeypatch.setattr('packages.agents.writer.answer_coverage.question_fact_ids',
                        lambda *args, **kwargs: old_ids)
    retrieval_calls = []

    async def semantic_ids(live_detail, live_snapshot, competitor, dimension, **kwargs):
        assert live_detail is detail and live_snapshot.id == snapshot.id
        assert (competitor, dimension) == (product, 'feature')
        retrieval_calls.append((live_snapshot.id, target.id))
        from packages.agents.writer.question_retrieval import (
            _eligible_facts,
            _question_evidence_pool,
        )
        from packages.research.question_scope import (
            question_request_context,
            request_context_questions,
            research_questions,
        )
        questions = research_questions(live_detail, competitor, dimension)
        queries = request_context_questions(question_request_context(
            live_detail, competitor, dimension, questions), questions)
        facts = _eligible_facts(live_snapshot, competitor, dimension)
        ranked = [[target.id] for _ in questions]
        empty = [[] for _ in questions]
        pool = _question_evidence_pool(facts, questions, queries, ranked,
            [list(old_ids) for _ in questions], ranked, ranked, empty,
            (target.id,), {fact.id for fact in facts})
        return (target.id,), {'mode': 'hybrid', 'ranking_only': True,
            'eligible_count': len(facts), 'evidence_pool': pool,
            'selected_fact_ids': [target.id], 'snapshot_id': snapshot.id,
            'questions': [dict(question_id=q['question_id'], fact_ids=[target.id],
                core_fact_ids=[target.id], required_exception_fact_ids=[],
                missing_core_fact_ids=[], missing_exception_fact_ids=[], minimum_evidence_missing=False)
                for q in questions]}

    monkeypatch.setattr('packages.agents.writer.question_retrieval.retrieve_question_facts', semantic_ids)
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True, writer_task_execution_enabled=False),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    projections, writer_fact_ids = [], []
    original_write = service._write_report_draft

    async def capture_draft(draft):
        projections.append({source.id for source in draft.detail.raw_sources})
        return await original_write(draft)

    monkeypatch.setattr(service, '_write_report_draft', capture_draft)

    async def response(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            rows = payload['evidence_view']['facts']
            writer_fact_ids.extend(row['id'] for row in rows)
            row = next(row for row in rows if row['id'] == target.id)
            return question_plan_response(payload, [dict(text=login, kind='fact', competitor=product,
                dimension='feature', fact_ids=[row['id']], source_ids=[row['source_id']])])
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(c) for c in payload['claims']]})
        if kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}:
            return answer_response(payload, {'version': 3, 'answers': [dict(question_id=q['question_id'], status='answered',
                resolution='direct', conclusion='yes',
                claim_ids=[c['id'] for c in payload['claims']],
                missing_fields=[], reason='The published sign-in rule answers the question.')
                for q in payload['questions']]})
        raise AssertionError(kwargs['name'])

    monkeypatch.setattr(service, '_trace_llm_text', response)
    await service._real_writer_step(record)
    assert projections and target.source_id in projections[0], (
        'The initial protected projection discarded the newly selected semantic source.')
    assert projections[0].isdisjoint(old_source_ids)
    assert len(retrieval_calls) >= 2, 'Initial projection and inner Writer both need semantic selection.'
    assert target.id in writer_fact_ids and login in detail.report_md
    assert f'[source:{target.source_id}]' in detail.report_md
    audit = detail.report_dimension_audits[0]
    generation = next(use for use in detail.evidence_consumptions if use.id == audit.consumption_id)
    assert generation.status == 'validated'
    assert target.id in generation.fact_ids and target.source_id in generation.source_ids
    assert target.id in generation.requested_fact_ids
    snapshot = current_snapshot(detail)
    assert service._final_qa_producer_verified(record, snapshot)
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues, 'Final QA must replay the actual semantic source and Writer view.'
