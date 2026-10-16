"""Authenticated request display lines are not product price assertions."""

import pytest
from pydantic import HttpUrl, TypeAdapter
from test_stage_evidence_views import FixedTime, distributed_detail

from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.answer_context import audit_answer_boundaries
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.schema.models import DecisionBrief
from packages.skills.registry import SkillRegistry


async def generated_gap_report(monkeypatch, language='zh-CN'):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ['Example Suite']
    detail.plan.dimensions = ['feature']
    detail.output_language = language
    detail.plan.decision_brief = DecisionBrief(decision_question=(
        'Example Suite Enterprise 套餐在中国当前含税人民币月费准确是多少？'
        '我们每月预算为 CNY 100。'))
    detail.topic = '产品调研'
    detail.execution_mode = 'real'
    detail.raw_sources = detail.raw_sources[:1]
    source = detail.raw_sources[0]
    source.competitor = 'Example Suite'
    source.covered_competitors = ['Example Suite']
    source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    source.metadata['normalized_fields'] = []
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase='analysis', canonical_documents={})

    async def forbidden(*args, **kwargs):
        pytest.fail('An admitted price gap must not trigger a model call.')

    monkeypatch.setattr(service, '_trace_llm_text', forbidden)
    await service._real_writer_step(record)
    return service, record, current_snapshot(detail)


def boundary_issues(service, record, snapshot):
    # Exercise amount validation independently of the producer hash gate, so
    # body mutations below cannot pass merely because another gate rejects them.
    return audit_answer_boundaries(service, record, snapshot, producer_verified=True,
                                   aliases=service._source_alias_map(record.detail))


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['zh-CN', 'en-US'])
async def test_bound_budget_question_allows_a_real_server_gap_in_final_audit(monkeypatch, language):
    service, record, snapshot = await generated_gap_report(monkeypatch, language)
    answer = record.detail.report_dimension_audits[0].answer_coverage[0]
    assert answer.resolution == 'insufficient' and answer.answer in record.detail.report_md
    assert service._final_qa_producer_verified(record, snapshot)
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues


@pytest.mark.asyncio
async def test_actual_answer_amount_still_blocks_even_when_its_line_has_a_question_mark(monkeypatch):
    service, record, snapshot = await generated_gap_report(monkeypatch)
    answer = record.detail.report_dimension_audits[0].answer_coverage[0]
    record.detail.report_md = record.detail.report_md.replace(answer.answer, '当前报价为 CNY 999，是否接受？')
    assert not service._final_qa_producer_verified(record, snapshot)
    issues = boundary_issues(service, record, snapshot)
    assert [item.metadata.get('amount') for item in issues] == ['999']


@pytest.mark.asyncio
async def test_rewritten_question_amount_is_not_exempted_by_the_original_request(monkeypatch):
    service, record, snapshot = await generated_gap_report(monkeypatch)
    record.detail.report_md = record.detail.report_md.replace('CNY 100', 'CNY 101')
    assert not service._final_qa_producer_verified(record, snapshot)
    issues = boundary_issues(service, record, snapshot)
    assert [item.metadata.get('amount') for item in issues] == ['101']


@pytest.mark.asyncio
async def test_ordinary_body_amount_is_checked_even_with_a_question_mark(monkeypatch):
    service, record, snapshot = await generated_gap_report(monkeypatch)
    heading = '## 置信度说明'
    record.detail.report_md = record.detail.report_md.replace(heading,
        '普通正文：套餐当前报价为 CNY 777，是否准确？\n\n' + heading)
    issues = boundary_issues(service, record, snapshot)
    assert [item.metadata.get('amount') for item in issues] == ['777']


@pytest.mark.asyncio
async def test_question_display_without_a_bound_writer_audit_remains_checked(monkeypatch):
    service, record, snapshot = await generated_gap_report(monkeypatch)
    audit = record.detail.report_dimension_audits[0]
    record.detail.report_dimension_audits[0] = audit.model_copy(update={'consumption_id': 'unbound-use'})
    issues = boundary_issues(service, record, snapshot)
    assert [item.metadata.get('amount') for item in issues] == ['100']
