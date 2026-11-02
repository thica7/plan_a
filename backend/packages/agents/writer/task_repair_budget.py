"""Finite optional-repair forecasts over the same complete ANSWER packet table.

Preview claims remain unreviewed proposals and are used only for budget bounds.
They are never inserted into publication, reviews or decision authority.
"""

from copy import deepcopy
from dataclasses import dataclass

from packages.agents.writer.structured_conclusions import digest
from packages.agents.writer.task_evidence_package import (
    answer_packet,
    answer_windows,
    checked_contract,
)


@dataclass(frozen=True)
class RemainingAnswerPlan:
    owner: tuple
    revision: str
    payloads: tuple
    windows: tuple
    required_tokens: int
    window_count: int
    max_bytes: int


def make_plan(service, owner, native_revision, payloads, max_bytes):
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.task_answer_outcomes import answer_system

    complete = deepcopy(tuple(payloads))
    windows = []
    for payload in complete:
        if (not checked_contract(payload)
                or (payload['consumption_id'], payload['snapshot_id']) != owner[1:]):
            raise ValueError('Repair plan owner changed')
        packed, omitted = answer_windows(payload, max_bytes)
        if omitted:
            raise ValueError('Repair plan complete task exceeds context bound')
        windows.extend(packed)
    required = sum(sum(service._llm_request_envelope(
        system=answer_system(p), user='\nJSON:\n' + compact_prompt_json(p),
        max_output_tokens=1600)[1:]) for p in windows)
    return RemainingAnswerPlan(
        owner, digest(dict(owner=owner, native_revision=native_revision, payloads=complete)),
        complete, tuple(windows), required, len(windows), max_bytes,
    )


def repair_delta(service, budget, phase, plan, variants):
    if (not getattr(budget, '_fresh_selected_task_budget', False)
            or getattr(budget, '_complete_task_plan_owners', {}).get(phase) != plan.owner
            or getattr(budget, '_complete_task_plan_revisions', {}).get(phase) != plan.revision):
        raise ValueError('Repair plan owner or revision changed or restored')
    affected, rebuilt, token_delta, call_delta = set(), [], 0, 0
    for variant in variants:
        owner, choice = variant['task'], variant['choice']
        payloads, found = deepcopy(plan.payloads), False
        for payload in payloads:
            for task in payload['tasks']:
                if task['question_id'] != owner['question_id']:
                    continue
                primary = task['task_id'] == owner['task_id']
                dependency = owner['task_id'] in task.get('dependency_task_ids', ())
                if (not primary and 'dependency_task_ids' not in task
                        and owner['focus'].startswith('rule_')):
                    raise ValueError('Repair dependency scope has no finite bound')
                if not primary and not dependency:
                    continue
                found |= primary
                affected.add(task['task_id'])
                if choice is None:
                    continue
                projected = deepcopy(choice)
                projected['primary'] = primary
                projected['ref'] = 'reviewed-claim-' + digest(
                    [task['task_id'], projected['claim']])[:24]
                task['support_choices'].append(projected)
                if primary and owner.get('semantic_target'):
                    task['semantic_target'] = deepcopy(owner['semantic_target'])
        if not found:
            raise ValueError('Repair task is absent from remaining packet plan')
        payloads = [answer_packet(p) for p in payloads]
        future = make_plan(service, plan.owner, plan.revision, payloads, plan.max_bytes)
        rebuilt.append(future.windows)
        token_delta = max(token_delta, future.required_tokens - plan.required_tokens)
        call_delta = max(call_delta, future.window_count - plan.window_count)
    if not variants:
        raise ValueError('Repair has no complete finite variants')
    return dict(additional_answer_tokens=max(0, token_delta),
                additional_answer_windows=max(0, call_delta),
                affected_task_ids=sorted(affected), variants=rebuilt,
                before_remaining_tokens=plan.required_tokens,
                after_remaining_upper_tokens=plan.required_tokens + max(0, token_delta),
                plan_revision=plan.revision)


def finite_variants(service, record, view, use, packets, candidate, choices, reused=None):
    """Enumerate all legal finite selections without creating reviewed facts."""
    import json

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.permission_relations import source_application_allowed
    from packages.agents.writer.question_atomic_delivery import (
        GENERATION_NAME,
        REVIEW_NAME,
        handoff_context,
    )
    from packages.agents.writer.selected_task_delivery import (
        generation_context,
        parse_generation,
        review_context,
        task_system,
    )
    from packages.agents.writer.task_answer_outcomes import support_choice

    task = candidate['generation_tasks'][0]
    if reused is not None:
        generations = [reused]
    else:
        target = candidate['task_predicates'][0]
        refs = target.get('required_relation_refs', target.get('required_support_refs'))
        if not refs:
            return None
        generations = []
        for ref in refs:
            generations.append(generation_context(candidate, {task['task_id']: dict(
                state='selected', binding_kind='span', support_refs=[ref])},
                choices, service, record, packets))
    result = []
    for generated in generations:
        if not generated.get('conclusion_candidates'):
            return None
        for conclusion in generated['conclusion_candidates']:
            response = json.dumps(dict(version=1, task_id=task['task_id'], status='selected',
                                       candidate_ref=conclusion['candidate_ref']))
            claims, _, plans = parse_generation(response, generated, view, use)
            if len(claims) != 1 or claims[0].kind != 'fact':
                return None
            owner = generated['generation_tasks'][0]
            review = review_context(
                claims, view, generated['questions'][0], plans[0],
                dict(handoff_context(service, record, view, generated['questions'], use),
                     delivery_policy='complete-predicates-v1'), owner,
                execution_policy=generated['task_execution_policy'],
                task_clause_contract=generated['task_clause_contract'],
                support_refs=conclusion['support_refs'],
                structured_conclusions_contract=generated['structured_conclusions_contract'],
                conclusion_candidate=conclusion,
            )
            review['task_package_contract'] = generated['task_package_contract']
            choice = support_choice(owner, claims[0], owner, {f.id: f for f in view.facts})
            choice.pop('quote_refs', None)
            choice['source_scopes'] = {
                sid: scope for sid, scope in generated['source_scopes'].items()
                if sid in claims[0].source_ids}
            if not source_application_allowed(conclusion, owner):
                choice = None
            requests = []
            for name, agent, payload in ((GENERATION_NAME, 'writer', generated),
                                          (REVIEW_NAME, 'qa', review)):
                system = task_system(
                    name, record.detail.output_language, generated['task_execution_policy'],
                    generated['task_clause_contract'], generated['structured_conclusions_contract'],
                    conclusion_candidates=bool(payload.get('conclusion_candidates')),
                    task_package_contract=generated['task_package_contract'],
                )
                requests.append((name, agent, system,
                                 '\nJSON:\n' + compact_prompt_json(payload), 1600))
            result.append(dict(task=owner, choice=choice, requests=requests))
    return result or None
