"""Optional repairs reserve the positive difference of complete remaining packets."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_complete_task_package import package_payload

from packages.agents.writer.selected_task_delivery import repair_admitted, reserve_answer_tail
from packages.agents.writer.task_evidence_package import CONTRACT, answer_packet
from packages.llm.execution_budget import RunLLMBudget
from packages.orchestrator.llm_execution import LLMExecutionMixin


def preflight_case():
    from packages.agents.writer.task_repair_budget import make_plan

    payload = package_payload()
    payload['consumption_id'], payload['snapshot_id'] = 'use', 'snapshot'
    payload['segment_competitor'], payload['dimension'] = 'Example Suite', 'feature'
    for index, task in enumerate(payload['tasks']):
        task.update(question_id='q', focus='source_rule', dependency_task_ids=[])
        if index == 1:
            task['support_choices'] = []
    payload = answer_packet(payload)
    budget = RunLLMBudget(max_calls=64, max_repairs=2, max_tokens=240000)
    budget._fresh_selected_task_budget = True
    budget.delivery_reserves = {'answer:Example Suite/feature': 0, 'final_qa:run': 19702}
    budget.delivery_call_reserves = {'answer:Example Suite/feature': 1, 'final_qa:run': 2}
    logs = []
    service = SimpleNamespace(
        _settings=SimpleNamespace(llm_max_output_tokens=1600),
        _run_llm_budget=lambda record: budget,
        _llm_phase=lambda agent, scope, **kwargs: f'{agent}:{scope}',
        _trace_local_tool=lambda record, **kwargs: logs.append(json.loads(kwargs['output_text'])),
    )
    service._llm_request_envelope = LLMExecutionMixin._llm_request_envelope.__get__(service)
    record = SimpleNamespace(detail=SimpleNamespace(output_language='zh-CN'))
    owner = (CONTRACT, 'use', 'snapshot')
    plan = make_plan(service, owner, 'native-revision', [payload], 14000)
    reserve_answer_tail(budget, 'answer:Example Suite/feature', plan.required_tokens, fresh=True,
                        package_owner=owner, window_count=plan.window_count)
    budget._complete_task_plan_revisions = {'answer:Example Suite/feature': plan.revision}
    current = deepcopy(payload['tasks'][0]['support_choices'][0])
    current.update(ref='replacement', claim_id='replacement', primary=True)
    current['claim']['id'] = 'replacement'
    preview = dict(task=dict(task_id='t1', question_id='q', focus='source_rule'), choice=current)
    repair_payload = dict(payload, tasks=[payload['tasks'][1]], task_attempt=1)
    # Exact finite future GEN/REVIEW packet upper bounds, not responses or source approval.
    requests = [('dimension_question_atomic_generation', 'writer', 'g' * 400, 1600),
                ('dimension_question_atomic_review', 'qa', 'r' * 400, 1600)]
    return service, record, budget, plan, repair_payload, preview, requests, logs


def admit(case, **overrides):
    service, record, _, plan, payload, preview, requests, _ = case
    return repair_admitted(
        service, record, 'Example Suite/feature', payload,
        SimpleNamespace(max_bytes=plan.max_bytes),
        2, 'task-outcomes-v1', remaining_plan=overrides.get('plan', plan),
        finite_repairs=overrides.get('variants', [dict(preview, requests=requests)]),
    )


def test_actual_preflight_does_not_repeat_two_full_windows_for_one_known_repair():
    case = preflight_case()
    _, _, budget, plan, _, _, _, logs = case
    budget.tokens_used = 240000 - plan.required_tokens - 19702 - 25000
    before = deepcopy(budget.delivery_charged)
    assert admit(case)
    assert logs[-1]['forecast_mode'] == 'canonical_remaining_positive_delta'
    assert logs[-1]['additional_answer_tokens'] < 14000
    assert logs[-1]['affected_task_ids'] == ['t1']
    assert budget.delivery_charged == before
    assert budget.delivery_reserves['final_qa:run'] == 19702


def test_real_extra_requirement_is_still_rejected_without_changing_budget():
    case = preflight_case()
    _, _, budget, plan, _, _, _, logs = case
    budget.tokens_used = 240000 - plan.required_tokens - 19702 - 2000
    before = deepcopy(budget.delivery_reserves)
    assert not admit(case)
    assert logs[-1]['additional_answer_tokens'] > 0
    assert budget.delivery_reserves == before


def test_explicit_dependency_and_untouched_peers_remain_in_the_same_canonical_plan():
    from packages.agents.writer.task_repair_budget import repair_delta

    case = preflight_case()
    service, _, budget, plan, _, preview, _, _ = case
    payload = deepcopy(plan.payloads[0])
    payload['tasks'][2]['dependency_task_ids'] = ['t1']
    from packages.agents.writer.task_repair_budget import make_plan
    plan = make_plan(service, plan.owner, 'dependencies', [payload], 14000)
    budget._complete_task_plan_revisions['answer:Example Suite/feature'] = plan.revision
    result = repair_delta(service, budget, 'answer:Example Suite/feature', plan, [preview])
    assert result['affected_task_ids'] == ['t1', 't2']
    rebuilt = result['variants'][0]
    assert {t['task_id'] for p in rebuilt for t in p['tasks']} == {'t0', 't1', 't2'}
    peer = next(t for p in rebuilt for t in p['tasks'] if t['task_id'] == 't0')
    assert peer == payload['tasks'][0]
    dependency = next(t for p in rebuilt for t in p['tasks'] if t['task_id'] == 't2')
    assert any(c['claim_id'] == 'replacement' and not c['primary']
               for c in dependency['support_choices'])
    assert all(p['request_context'] == payload['request_context'] for p in rebuilt)


@pytest.mark.parametrize('fault', ['owner', 'revision', 'restored'])
def test_wrong_owner_revision_or_restored_floor_cannot_be_released(fault):
    case = preflight_case()
    _, _, budget, plan, _, _, _, _ = case
    if fault == 'owner':
        plan = replace(plan, owner=(CONTRACT, 'foreign', 'snapshot'))
    elif fault == 'revision':
        plan = replace(plan, revision='foreign')
    else:
        budget._fresh_selected_task_budget = False
    budget.tokens_used = 240000 - plan.required_tokens - 19702 - 25000
    before = deepcopy(budget.delivery_reserves)
    assert not admit(case, plan=plan)
    assert budget.delivery_reserves == before


def test_unbounded_generation_retains_explicit_conservative_fallback():
    case = preflight_case()
    _, _, budget, plan, _, _, _, logs = case
    budget.tokens_used = 240000 - plan.required_tokens - 19702 - 25000
    assert not admit(case, variants=None)
    assert logs[-1]['forecast_mode'] == 'conservative_unbounded_repair'
    assert logs[-1]['additional_answer_windows'] == 2


def test_admitted_replacement_keeps_extra_calls_and_tokens_protected_until_attempt_finishes():
    from packages.agents.writer.task_repair_budget import make_plan

    case = preflight_case()
    service, _, budget, plan, _, preview, requests, logs = case
    plan = make_plan(service, plan.owner, 'bounded-context', plan.payloads, 11000)
    budget._complete_task_plan_revisions['answer:Example Suite/feature'] = plan.revision
    case = (*case[:3], plan, *case[4:])
    choice = deepcopy(preview['choice'])
    quote = 'Complete selected source including all conditions. ' * 160
    choice['parent_context_refs'] = ['new-fact']
    choice['parent_context'] = {'new-fact': dict(source_id='new-source', quote=quote,
                                               value=[quote], qualifiers={})}
    choice['claim']['source_span_bindings'] = [dict(fact_id='new-fact', source_id='new-source',
                                                   quote=quote)]
    variant = dict(preview, choice=choice, requests=requests)
    assert admit(case, variants=[variant])
    assert logs[-1]['additional_answer_windows'] > 0
    phase = 'answer:Example Suite/feature'
    committed = (budget.delivery_reserves[phase], budget.delivery_call_reserves[phase])
    reserve_answer_tail(budget, phase, plan.required_tokens, fresh=True,
                        package_owner=plan.owner, window_count=plan.window_count)
    assert (budget.delivery_reserves[phase], budget.delivery_call_reserves[phase]) == committed
    assert budget.delivery_charged == {}
