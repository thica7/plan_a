"""Explicit fresh task packages; proposals restrict SELECT, never grant authority."""

import json
from copy import deepcopy

CONTRACT = "complete-task-evidence-v1"
SELECTOR = "task_package_contract"


def checked_contract(payload):
    value = payload.get(SELECTOR)
    if value is not None and (
        type(value) is not str or value != CONTRACT
        or payload.get("task_execution_policy") != "selected-task-atoms-v3"
        or payload.get("task_clause_contract") != "semantic-target-clauses-v2"
        or payload.get("structured_conclusions_contract") != "structured-conclusions-v2"
    ):
        raise ValueError("Unknown or mixed complete task package contract")
    return value


def fresh_contract(detail, scope):
    values = []
    for span in detail.trace_spans:
        if span.subagent != scope:
            continue
        if span.name == "question_atomic_delivery":
            values.append(checked_contract(json.loads(span.full_output)))
        elif span.name in {
            "dimension_question_task_support_selection",
            "dimension_question_atomic_generation",
            "dimension_question_atomic_review",
        }:
            values.append(checked_contract(json.loads(span.full_input.split("\nJSON:\n", 1)[1])))
    if values and any(value != values[0] for value in values):
        raise ValueError("Mixed saved complete task package contracts")
    return values[0] if values else CONTRACT


def system(base, contract):
    if contract is None:
        return base
    if contract != CONTRACT:
        raise ValueError("Unknown complete task package SYSTEM")
    return base + (
        " Complete task evidence v1. required_relation_refs, when present, requires one "
        "of those complete references in this task's actual selection; an empty list means "
        "insufficient evidence. Candidate eligibility is not source verification. Never "
        "borrow unselected or sibling-task evidence. An upgrade option or invitation limit "
        "does not establish a current access maximum or mandatory upgrade."
    )


def selection_requirements(payload):
    """Reuse the finite source parser independently of any selected/reviewed fact."""
    if not checked_contract(payload):
        return
    from packages.agents.writer.permission_relations import _parent, _source_relation

    for task, predicate in zip(
        payload["generation_tasks"], payload["task_predicates"], strict=True,
    ):
        parent = _parent(payload, task)
        target = predicate.get("semantic_target", {}).get("relation")
        refs = []
        for row in payload["evidence_view"]["facts"]:
            for span in row.get("source_span_candidates", ()):
                if parent and _source_relation(
                    dict(task, semantic_target=predicate.get("semantic_target", {})),
                    span["quote"], parent["text"],
                ) is not None:
                    refs.append(span["support_ref"])
        if refs or target == "current_access" or task["focus"] == "purge_cache":
            predicate["required_relation_refs"] = refs


def complete_selection(payload, selections):
    if not checked_contract(payload):
        return True
    return all(
        "required_relation_refs" not in target or (
            bool(selections.get(target["task_id"], {}).get("support_refs"))
            and set(selections[target["task_id"]]['support_refs'])
            <= set(target['required_relation_refs'])
        )
        for target in payload["task_predicates"]
    )


def selection_packet(context):
    """Show only complete eligible relations; hidden proposals still face server checks."""
    if not checked_contract(context):
        return context
    targets = context['task_predicates']
    if any('required_relation_refs' not in target for target in targets):
        return context
    allowed = {ref for target in targets for ref in target['required_relation_refs']}
    result = deepcopy(context)
    rows = []
    pairs = {fid for pair in context.get('source_exception_bindings', ())
             for fid in pair['fact_ids']}
    for row in result['evidence_view']['facts']:
        row['source_span_candidates'] = [s for s in row.get('source_span_candidates', ())
                                         if s['support_ref'] in allowed]
        operations = [(ref, op) for ref, op in zip(row.get('operation_support_refs', ()),
                      row.get('operation_observations', ()), strict=True) if ref in allowed]
        if 'operation_support_refs' in row:
            row['operation_support_refs'] = [ref for ref, _ in operations]
            row['operation_observations'] = [op for _, op in operations]
        if row['source_span_candidates'] or operations or row.get('id') in pairs:
            rows.append(row)
    result['evidence_view']['facts'] = rows
    for target in result.get('support_applicability', ()):
        target['candidates'] = [r for r in target['candidates'] if r['support_ref'] in allowed]
    return result


def source_review_state(response, claims, payload):
    """Authenticate source checks separately; this never authorizes publication."""
    from packages.agents.writer.permission_relations import source_review_matches
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews
    from packages.llm.json_extract import strict_json_object

    try:
        checked_contract(payload)
        raw = strict_json_object(response)
        if set(raw) != {"reviews", "atomicity"}:
            return "invalid"
        if payload.get("typed_source_relation") is not None and not source_review_matches(
            payload, claims
        ):
            return "invalid"
        rows = parse_atomic_reviews(
            json.dumps(dict(reviews=raw["reviews"]), ensure_ascii=False), claims,
            payload=payload, review_projection_version=3,
        )
        if len(rows) != 1 or len(claims) != 1 or rows[0].claim_id != claims[0].id:
            return "invalid"
        return rows[0].verdict
    except (ValueError, TypeError, AttributeError, KeyError):
        return "invalid"


def answer_packet(payload):
    """Lossless task-local consumer projection; the full producer receipt is retained."""
    if not checked_contract(payload):
        return payload
    from packages.agents.writer.task_execution import ADVISORY_KEYS

    result = deepcopy(payload)
    identities = result.setdefault('upstream_identity_refs', {})
    for key in ADVISORY_KEYS:
        if key in result:
            advisory = result.pop(key)
            identities[key] = {field: advisory[field] for field in (
                'kind', 'competitor', 'dimension', 'snapshot_id', 'producer_hash')
                if field in advisory}
    contexts = result.pop('source_contexts', {})
    scopes = result.pop('source_scopes', {})
    active_facts, active_sources = set(), set()
    for task in result['tasks']:
        for choice in task['support_choices']:
            parents = choice.pop('parent_context', {})
            for fid, parent in parents.items():
                if fid in contexts and contexts[fid] != parent:
                    raise ValueError('Complete task source context changed')
                contexts[fid] = parent
            refs = choice.setdefault('parent_context_refs', list(parents))
            if any(fid not in contexts for fid in refs):
                raise ValueError('Complete task source context changed')
            active_facts.update(refs)
            for sid, scope in choice.pop('source_scopes', {}).items():
                if sid in scopes and scopes[sid] != scope:
                    raise ValueError('Complete task source scope changed')
                scopes[sid] = scope
            claim = choice['claim']
            active_sources.update(claim.get('source_ids', ()))
            active_sources.update(contexts[fid]['source_id'] for fid in refs)
            quotes = choice.get('quotes')
            original_quotes = ([claim['operation_binding']] if claim.get('operation_binding')
                               else claim.get('source_span_bindings'))
            if quotes is not None and quotes == original_quotes:
                choice.pop('quotes')
    result['source_contexts'] = {fid: row for fid, row in contexts.items() if fid in active_facts}
    result['source_scopes'] = {sid: row for sid, row in scopes.items() if sid in active_sources}
    return result


def answer_windows(complete, max_bytes):
    """Pack canonical complete tasks, preserving every omitted task explicitly."""
    from packages.agents.writer.dimension_writer import compact_prompt_json

    checked_contract(complete)

    def build(ids):
        return answer_packet(dict(
            complete, tasks=[t for t in complete['tasks'] if t['task_id'] in ids],
            decision_candidates=[c for c in complete['decision_candidates'] if c['task_id'] in ids],
        ))

    def fits(packet):
        return len(('\nJSON:\n' + compact_prompt_json(packet)).encode()) <= max_bytes

    windows, current, omitted = [], [], []
    for task in complete['tasks']:
        tid = task['task_id']
        if fits(build([*current, tid])):
            current.append(tid)
            continue
        if current:
            windows.append(build(current))
        current = []
        if fits(build([tid])):
            current = [tid]
        else:
            omitted.append(tid)
    if current:
        windows.append(build(current))
    return windows, omitted


def reviewed_source_context(authority, claims):
    """QA sees the exact full source REVIEW inputs, not unselected parent values.

    The caller has authenticated the ephemeral authority and global publication.
    Original facts, hashes and values remain in its immutable context/receipt.
    """
    from packages.agents.writer.selected_task_delivery import verified_transport

    context = authority.context
    if not checked_contract(context.compact):
        raise ValueError('Reviewed source projection requires a complete task package')
    rows = {}
    for claim in claims:
        dispatches = [d for d in context.compact['dispatches']
                      if d['name'] == 'dimension_question_atomic_review'
                      and d['claim_ids'] == [claim['id']]]
        if len(dispatches) != 1:
            raise ValueError('Reviewed source projection has no unique source review')
        _, payload = verified_transport(context, dispatches[0])
        (reviewed,) = payload['claims']
        if reviewed['id'] != claim['id']:
            raise ValueError('Reviewed source claim changed')
        bindings = claim.get('source_span_bindings') or [claim.get('operation_binding')]
        if any(not isinstance(binding, dict) for binding in bindings):
            raise ValueError('Reviewed source projection requires selected bindings')
        quotes = [b.get('quote', b.get('operation_quote')) for b in bindings]
        if quotes != reviewed['support_quotes']:
            raise ValueError('Reviewed source quotes changed')
        constraints = deepcopy(payload.get('constraint_context', []))
        for binding, quote in zip(bindings, quotes, strict=True):
            row = dict(fact_id=binding['fact_id'], source_id=binding['source_id'],
                       quote=quote, value=[quote], reviewed_constraints=constraints)
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            result = rows.setdefault(key, dict(row, claim_ids=[]))
            result['claim_ids'].append(claim['id'])
    return list(rows.values())
