"""Collector ledger + real snapshot enter the actual Writer without injected selectors."""

import json
from dataclasses import replace

import httpx
import pytest
from test_complete_task_evidence import ACCESS, PACKAGE
from test_final_question_reconciliation import reviewed
from test_independent_final_question_qa import receipt
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_clauses import clause_wire_response

from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.research.question_delivery import _expand_text_refs


@pytest.mark.asyncio
async def test_collector_checkpoint_real_writer_automatically_selects_package_and_repairs(
    monkeypatch,
):
    from test_execution_limits import _service

    from packages.agents.writer.dimension_writer import dimension_writing_enabled
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery
    from packages.research.evidence.views import select_evidence_view

    case = await atomic_case(
        [ACCESS], question='Example Product：Visitor 已接受邀请且已确认，'
        '能否同时访问 2 个 vaults？')
    service, record, snapshot = case[:3]
    provider, _ = await _service(llm_provider_name='deepseek')
    service._llm = provider._llm
    service._settings = replace(
        service._settings, demo_mode=False, writer_task_execution_enabled=True,
        writer_question_atomic_enabled=True, run_llm_max_calls=64, run_llm_max_tokens=240000,
        llm_max_output_tokens=1600,
    )
    record.detail.execution_mode = 'real'
    assert dimension_writing_enabled(record.detail)
    seen, review_count = [], []

    async def post(url, body, headers):
        system, user = [m['content'] for m in body['messages']]
        if system == 'Offline Collector ledger boundary.':
            data = 'Collector input is ready.'
        else:
            raw = user.split('\nJSON:\n', 1)[1]
            payload = _expand_text_refs(json.loads(raw))
            seen.append((system, payload))
            if 'selections' in system and payload.get('tasks') and 'task_attempt' in payload:
                target = payload['task_predicates'][0]
                data = dict(selections=[dict(task_id=payload['tasks'][0]['task_id'],
                    status='selected', binding_kind='span',
                    support_refs=target['required_relation_refs'][:1])])
            elif 'conclusion_candidates' in payload:
                data = dict(version=1, task_id=payload['generation_tasks'][0]['task_id'],
                            status='selected', candidate_ref=payload['conclusion_candidates'][0][
                                'candidate_ref'])
            elif payload.get('task_context'):
                data = clause_wire_response(payload, dict(
                    reviews=[supported_review(c) for c in payload['claims']],
                    atomicity=[dict(claim_id=c['id'], predicate_count=1, clauses=[])
                               for c in payload['claims']]))
                if not review_count:
                    data['atomicity'] = []
                review_count.append(True)
            elif payload.get('task_outcome_contract'):
                data = dict(version=1, task_reviews=[dict(
                    task_id=t['task_id'], outcome='unknown', support_refs=[], missing_fields=[],
                    reason='Source facts alone do not establish application outcomes.')
                    for t in payload['tasks']])
            elif 'basis_hash' in payload:
                data = json.loads(reviewed(payload))
            else:
                raise AssertionError((system[:80], list(payload)))
        text = data if isinstance(data, str) else json.dumps(data)
        return httpx.Response(200, json=dict(choices=[dict(message=dict(content=text))],
                              usage=dict(prompt_tokens=100, completion_tokens=30)))

    monkeypatch.setattr(service._llm, '_post_chat_completion', post)
    await service._trace_llm_text(record, agent='collector', subagent='Example Product/feature',
        name='collector_input_ready', system='Offline Collector ledger boundary.',
        user='A registered captured source and accepted analysis snapshot are present.',
        max_output_tokens=1600)
    assert record.detail.llm_budget_checkpoint['calls'] > 0
    budget = service._run_llm_budget(record)
    limits_before = (budget.max_calls, budget.max_tokens)
    collector_charge = budget.delivery_charged['collector:Example Product/feature']
    assert limits_before[0] <= 64 and limits_before[1] <= 240000
    assert not any(s.name == 'question_atomic_delivery' for s in record.detail.trace_spans)
    before_snapshots = {s.id: s.model_dump(mode='json') for s in record.detail.evidence_snapshots}
    before_latest = record.detail.evidence_snapshot_id
    assert before_latest == snapshot.id
    await service._real_writer_step(record)
    audit = record.detail.report_dimension_audits[0]
    assert audit.answer_coverage[0].conclusion == 'no', json.dumps(dict(
        gaps=audit.gaps, calls=[dict(name=s.name, status=s.status, output=s.full_output[:900])
        for s in record.detail.trace_spans if s.kind == 'llm' or 'repair_preflight' in s.name],
        claims=[dict(status=c.status, reasons=c.rule_reasons) for c in audit.claims],
    ), ensure_ascii=False)
    assert all(c.status == 'supported' for c in audit.claims if c.review)
    snapshots = {s.id: s for s in record.detail.evidence_snapshots}
    assert all(sid in snapshots and snapshots[sid].model_dump(mode='json') == value
               for sid, value in before_snapshots.items())
    latest = snapshot
    additions = sorted((s for sid, s in snapshots.items() if sid not in before_snapshots),
                       key=lambda s: s.version)
    for added in additions:
        assert added.parent_id == latest.id and added.version == latest.version + 1
        assert added.sources == latest.sources and added.facts == latest.facts
        assert added.conflicts == latest.conflicts and added.gaps == latest.gaps
        assert added.phase == latest.phase and added.content_hash == latest.content_hash
        latest = added
    assert record.detail.evidence_snapshot_id == latest.id
    task_payloads = [p for _, p in seen if p.get('task_execution_policy')]
    assert task_payloads and all(p['task_package_contract'] == PACKAGE for p in task_payloads)
    preflights = [json.loads(s.full_output) for s in record.detail.trace_spans
                  if s.name == 'question_task_repair_preflight']
    assert preflights and preflights[0]['admitted']
    assert preflights[0]['forecast_mode'] == 'canonical_remaining_positive_delta'
    use = next(u for u in record.detail.evidence_consumptions if u.id == audit.consumption_id)
    assert use.snapshot_id == use.validated_snapshot_id == latest.id
    view = select_evidence_view(latest, agent='writer', competitor=use.competitor,
        dimension=use.dimension, source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids, max_bytes=use.view_max_bytes or use.max_bytes)
    replay = replay_atomic_delivery(service, record.detail, latest, use, view, audit=audit)
    assert replay['decision_review'][audit.answer_coverage[0].question_id].matches(
        audit.answer_coverage[0])
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    assert (output['planned_issue_ids'] == output['sent_issue_ids']
            == output['valid_review_issue_ids'])
    assert output['unsent_issue_ids'] == []
    assert service._settings.run_llm_max_calls == 64
    budget = service._run_llm_budget(record)
    assert (budget.max_calls, budget.max_tokens) == limits_before
    assert budget.delivery_charged['collector:Example Product/feature'] == collector_charge
    await service.aclose()
    await provider.aclose()
