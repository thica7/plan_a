"""One canonical task packet feeds sizing, delivery and authenticated replay."""

from copy import deepcopy

import pytest

from packages.agents.writer.task_evidence_package import CONTRACT, SELECTOR


def package_payload():
    quote = "Role R may export object A only after approval; time and plan exceptions apply. " * 28
    parent = "Actor Lin has role R on A; actor Bo is unknown. " * 10
    contexts = {"f": dict(source_id="s", quote=quote, value=[quote],
                          qualifiers=dict(condition_evidence=[dict(quote="Full exception.")]))}
    return dict(
        task_package_contract=CONTRACT, task_execution_policy="selected-task-atoms-v3",
        structured_conclusions_contract="structured-conclusions-v2",
        task_clause_contract="semantic-target-clauses-v2",
        questions=[dict(question_id="q", question=parent)],
        request_context=dict(parents=[dict(parent_id="p", text=parent)]),
        upstream_analysis=dict(kind="analyst", producer_hash="hash", prose="Advice " * 1000),
        tasks=[dict(task_id=f"t{i}", support_choices=[dict(
            ref=f"c{i}", claim_id=f"c{i}", primary=True,
            claim=dict(id=f"c{i}", text=f"Source relation {i}",
                       source_span_bindings=[dict(quote=quote)]),
            quotes=[dict(quote=quote)], parent_context=deepcopy(contexts),
            source_scopes={"s": dict(source_id="s", scope="Full role and plan.")},
        )]) for i in range(3)], decision_candidates=[],
    )


def test_answer_packet_keeps_complete_source_and_parent_once_and_prunes_only_unused_context():
    from packages.agents.writer.task_evidence_package import answer_packet

    payload = package_payload()
    original = deepcopy(payload)
    packet = answer_packet(payload)
    assert payload == original
    assert packet["request_context"] == payload["request_context"]
    assert packet["source_contexts"]["f"] == (
        payload["tasks"][0]["support_choices"][0]["parent_context"]["f"])
    assert len(packet["source_contexts"]) == 1
    assert packet["upstream_identity_refs"]["upstream_analysis"]["producer_hash"] == "hash"
    assert "upstream_analysis" not in packet
    for task, before in zip(packet["tasks"], payload["tasks"], strict=True):
        choice = task["support_choices"][0]
        assert choice["claim"] == before["support_choices"][0]["claim"]
        assert choice["parent_context_refs"] == ["f"]
        assert "quotes" not in choice
    assert answer_packet(packet) == packet
    packet["tasks"] = []
    assert answer_packet(packet)["source_contexts"] == {}


def test_conflicting_parent_contexts_fail_closed_and_old_packet_is_unchanged():
    from packages.agents.writer.task_evidence_package import answer_packet

    payload = package_payload()
    payload["tasks"][1]["support_choices"][0]["parent_context"]["f"]["quote"] = "Foreign source"
    with pytest.raises(ValueError, match="context changed"):
        answer_packet(payload)
    payload.pop(SELECTOR)
    assert answer_packet(payload) == payload


def test_whole_task_packing_uses_the_same_packet_for_sizing_and_delivery():
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.task_evidence_package import answer_packet, answer_windows

    full = answer_packet(package_payload())
    single = answer_packet(dict(full, tasks=full['tasks'][:1]))
    cap = len(('\nJSON:\n' + compact_prompt_json(single)).encode()) + 100
    windows, omitted = answer_windows(full, cap)
    assert not omitted and len(windows) >= 2
    assert [t['task_id'] for p in windows for t in p['tasks']] == ['t0', 't1', 't2']
    assert all(len(('\nJSON:\n' + compact_prompt_json(p)).encode()) <= cap for p in windows)
    assert all(answer_packet(p) == p for p in windows)


def test_fresh_owned_answer_plan_releases_peak_without_changing_charges_or_other_floors():
    from packages.agents.writer.selected_task_delivery import reserve_answer_tail
    from packages.llm.execution_budget import RunLLMBudget

    budget = RunLLMBudget(max_calls=64, max_repairs=2, max_tokens=240000, calls=36,
                          tokens_used=120308)
    phase = 'answer:Example Suite/feature'
    budget.delivery_reserves = {phase: 87427, 'final_qa:run': 19702, 'writer:other': 123}
    budget.delivery_charged = {phase: 22934}
    budget.delivery_calls = {phase: 6}
    budget.delivery_call_reserves = {phase: 10, 'final_qa:run': 2}
    before = deepcopy(budget.delivery_charged)
    blocked = deepcopy(budget)
    blocked.delivery_charged[phase] = 0
    assert blocked.admission_error(is_repair=False, input_tokens=17100,
                                   max_output_tokens=600, phase='writer:Example Suite/feature')
    reserve_answer_tail(budget, phase, 16000, fresh=True,
                        package_owner=(CONTRACT, 'use', 'snapshot'), window_count=2)
    assert budget.delivery_reserves[phase] == 22934 + 16000
    assert budget.delivery_charged == before
    assert budget.delivery_reserves['final_qa:run'] == 19702
    assert budget.delivery_reserves['writer:other'] == 123
    assert budget.delivery_call_reserves[phase] == 8
    assert budget.admission_error(
        is_repair=False, input_tokens=17100,
        max_output_tokens=600, phase='writer:Example Suite/feature',
    ) is None
    with pytest.raises(ValueError, match='owner changed'):
        reserve_answer_tail(budget, phase, 0, fresh=True,
                            package_owner=(CONTRACT, 'foreign-use', 'snapshot'), window_count=0)
    assert budget.delivery_reserves[phase] == 38934


@pytest.mark.parametrize('fresh,owner', [(False, (CONTRACT, 'use', 'snapshot')), (True, None)])
def test_restored_or_old_contract_answer_floor_never_shrinks(fresh, owner):
    from packages.agents.writer.selected_task_delivery import reserve_answer_tail
    from packages.llm.execution_budget import RunLLMBudget

    budget = RunLLMBudget(max_calls=64, max_repairs=2)
    budget.delivery_reserves = {'answer:p': 87427}
    reserve_answer_tail(budget, 'answer:p', 100, fresh=fresh,
                        package_owner=owner, window_count=1)
    assert budget.delivery_reserves['answer:p'] == 87427


def test_new_package_qa_wire_keeps_selected_source_conditions_and_removes_only_duplicates():
    from packages.agents.qa.question_review_transport import _v11_publication_row

    binding = dict(span_id='span', fact_id='f', source_id='s', fact_hash='hash',
                   source_path='value/1', start=0, end=10, quote='Full source and exception.')
    row = dict(task_package_contract=CONTRACT,
               claims=[dict(id='c', text='One source relation.', fact_ids=['f'], source_ids=['s'],
                            source_span_bindings=[binding])],
               selected_source_context=[dict(fact_id='f', source_id='s', quote=binding['quote'],
                    value=[binding['quote']], reviewed_constraints=[dict(
                        source_exceptions=[dict(quote='Complete negative dependency.')])])])
    actual = _v11_publication_row(row)
    assert actual['claims'][0]['source_span_bindings'] == [dict(
        fact_id='f', source_id='s', quote=binding['quote'])]
    assert 'fact_ids' not in actual['claims'][0] and 'source_ids' not in actual['claims'][0]
    assert 'value' not in actual['selected_source_context'][0]
    assert actual['selected_source_context'][0]['reviewed_constraints'] == (
        row['selected_source_context'][0]['reviewed_constraints'])
    old = deepcopy(row)
    old.pop(SELECTOR)
    assert _v11_publication_row(old)['claims'] == old['claims']
    assert _v11_publication_row(old)['selected_source_context'] == old['selected_source_context']
    reordered = deepcopy(row)
    reordered['claims'][0]['fact_ids'] = ['extra', 'f']
    assert _v11_publication_row(reordered)['claims'][0]['fact_ids'] == ['extra', 'f']
    different = deepcopy(row)
    different['selected_source_context'][0]['value'] = ['Another complete value']
    assert _v11_publication_row(different)['selected_source_context'][0]['value'] == (
        ['Another complete value'])
