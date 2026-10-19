import pytest
from pydantic import HttpUrl, TypeAdapter
from test_stage_evidence_views import FixedTime, distributed_detail

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.schema.models import DecisionBrief
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_missing_quote_is_an_explicit_answer_without_a_fabricated_price_claim(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Notion']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(
        decision_question='Notion Enterprise 套餐在中国当前含税人民币月费准确是多少？')
    detail.topic = '产品调研'
    detail.execution_mode = 'real'
    detail.raw_sources = [s for s in detail.raw_sources if s.competitor == 'Notion']
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
        source.metadata['normalized_fields'] = []
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase='analysis', canonical_documents={})

    async def forbidden(*args, **kwargs):
        pytest.fail('A server-proven quote gap needs no model call or invented observation.')
    monkeypatch.setattr(service, '_trace_llm_text', forbidden)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    answer = audit.answer_coverage[0]
    assert answer.status == 'partial' and answer.resolution == 'insufficient'
    assert answer.claim_ids == answer.evidence_spans == ()
    assert not audit.claims
    assert answer.answer in detail.report_md
    assert '不足以核实' in detail.report_md
    snapshot = current_snapshot(detail)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)

    forged = answer.model_copy(update={'answer': '当前含税月费为 99 元。'})
    detail.report_dimension_audits[0] = audit.model_copy(update={'answer_coverage': (forged,)})
    detail.report_md = detail.report_md.replace(answer.answer, forged.answer)
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(i.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for i in issues)
