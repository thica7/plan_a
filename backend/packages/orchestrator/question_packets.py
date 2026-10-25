"""Question selection identity and replay; facts remain in the stage's shared pool."""
from __future__ import annotations

import hashlib
import os
from copy import deepcopy

from packages.agents.writer.question_retrieval import _reconcile_question_originals, _round_robin
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.question_scope import research_questions


def selection_config():
    # Only local ranking configuration participates; never record credentials.
    keys = ['KB_LOCAL_MODEL_STRICT'] + [f'KB_{kind}_{key}'
        for kind in ('EMBEDDING', 'RERANKER')
        for key in ('PROVIDER', 'MODEL', 'REVISION', 'LOCAL_PATH', 'MODEL_VERSION', 'BATCH_SIZE', 'MAX_LENGTH')]
    return hashlib.sha256(canonical_json({key: os.getenv(key) for key in keys}).encode()).hexdigest()


def packet_id(packet):
    return 'question-packet-' + hashlib.sha256(canonical_json(
        {key: value for key, value in packet.items() if key != 'packet_id'}).encode()).hexdigest()[:24]


async def prepare_packets(detail, snapshot, competitor=None, dimension=None):
    from packages.agents.writer.question_retrieval import retrieve_question_facts
    config = selection_config()
    packets = []
    for product in ([competitor] if competitor else detail.plan.competitors):
        for dim in ([dimension] if dimension else detail.plan.dimensions):
            questions = research_questions(detail, product, dim)
            if not questions:
                continue
            selected, retrieval = await retrieve_question_facts(detail, snapshot, product, dim)
            packet = dict(version=2, run_id=detail.id, workspace_id=detail.workspace_id,
                project_id=detail.project_id, snapshot_id=snapshot.id,
                snapshot_content_hash=snapshot.content_hash, competitor=product, dimension=dim,
                questions=questions, retrieval=retrieval, selected_fact_ids=list(selected or ()),
                selection_config=config)
            packet['packet_id'] = packet_id(packet)
            packets.append(packet)
    if selection_config() != config:
        raise ValueError('question retrieval configuration changed')
    validate_packets(detail, snapshot, packets)
    return packets


def validate_packets(detail, snapshot, packets):
    for packet in packets:
        if (packet.get('packet_id') != packet_id(packet)
                or (packet['run_id'], packet['workspace_id'], packet['project_id'])
                != (detail.id, detail.workspace_id, detail.project_id)
                or (packet['snapshot_id'], packet['snapshot_content_hash']) != (snapshot.id, snapshot.content_hash)
                or packet['competitor'] not in detail.plan.competitors
                or packet['dimension'] not in detail.plan.dimensions
                or packet['questions'] != research_questions(detail, packet['competitor'], packet['dimension'])
                or packet['selection_config'] != selection_config()):
            raise ValueError('question packet scope, snapshot, query or configuration changed')
        if packet.get('version', 1) not in {1, 2}:
            raise ValueError('unsupported question packet version')
        if packet.get('version') == 2:
            _validate_pool(detail, snapshot, packet)


def _validate_pool(detail, snapshot, packet):
    from packages.agents.writer.question_retrieval import (
        _eligible_facts,
        _pool_original_identity,
        _validate_scope,
    )
    from packages.research.evidence.source_exceptions import question_exception_fact_ids
    from packages.research.question_scope import question_request_context, request_context_questions

    _validate_scope(detail, snapshot, packet['competitor'], packet['dimension'])
    pool = packet['retrieval'].get('evidence_pool', {})
    facts = _eligible_facts(snapshot, packet['competitor'], packet['dimension'])
    identities = {fact.id: _pool_original_identity(fact) for fact in facts}
    if (pool.get('version') != 1 or pool.get('fact_ids') != list(identities)
            or len(pool.get('questions', ())) != len(packet['questions'])):
        raise ValueError('question pool originals or version changed')
    queries = request_context_questions(question_request_context(
        detail, packet['competitor'], packet['dimension'], packet['questions']),
        packet['questions'])
    for question, query, row in zip(packet['questions'], queries, pool['questions'], strict=True):
        candidates = row.get('candidates', ())
        if (row.get('question_id') != question['question_id']
                or row.get('question') != query['question']
                or len(candidates) != len(identities)
                or {candidate.get('fact_id') for candidate in candidates} != set(identities)
                or not set(row.get('core_fact_ids', ())) <= identities.keys()
                or row.get('required_exception_fact_ids') != question_exception_fact_ids(
                    question['question'], facts)):
            raise ValueError('question pool scope, query or exception closure changed')
        for rank, candidate in enumerate(candidates, 1):
            identity = identities[candidate['fact_id']]
            if candidate.get('rank') != rank or any(
                candidate.get(key) != value for key, value in identity.items()
            ):
                raise ValueError('question pool original identity or rank changed')
    selection = packet.get('pool_selection')
    if selection is not None:
        rows = {row['question_id']: row for row in pool['questions']}
        if (selection.get('version') != 1 or not selection.get('question_ids')
                or not set(selection['question_ids']) <= rows.keys()
                or selection.get('evidence_pool_sha256') != _identity_hash(pool)
                or packet['selected_fact_ids'] != selection.get('requested_fact_ids')
                or len(packet['selected_fact_ids']) != len(set(packet['selected_fact_ids']))
                or not set(packet['selected_fact_ids']) <= identities.keys()
                or any(not set(rows[qid]['required_exception_fact_ids'])
                       <= set(packet['selected_fact_ids']) for qid in selection['question_ids'])):
            raise ValueError('question pool selection or exception closure changed')


def question_pool_facts(detail, snapshot, packet, question_id=None):
    """Return verified whole originals for local selection, never a citation grant.

    ``None`` covers every complete question in the packet. A view/use is still
    required before any original may support a generated claim.
    """
    validate_packets(detail, snapshot, [packet])
    if packet.get('version') != 2:
        raise ValueError('question pool requires a version 2 packet')
    rows = packet['retrieval']['evidence_pool']['questions']
    if question_id is not None:
        rows = [row for row in rows if row['question_id'] == question_id]
        if not rows:
            raise ValueError('question is outside the evidence pool scope')
    by_id = {fact.id: fact for fact in snapshot.facts}
    ids = _round_robin([_pool_question_order(row, by_id, packet['competitor']) for row in rows],
                       len(snapshot.facts))
    return tuple(by_id[key] for key in ids)


def _pool_question_order(row, by_id, product):
    """Reserve finite subquestion branches before another matching background.

    These routing hints affect ordering only; all admitted originals remain
    available and every eventual claim still needs independent support review.
    """
    from packages.agents.writer.question_allocation import question_atom_tasks, task_support_score
    from packages.research.evidence.operations import operation_observations, required_operations

    ranked = [candidate['fact_id'] for candidate in row['candidates']]
    operations = {key: {item['operation'] for item in operation_observations(by_id[key], [product])}
                  for key in ranked}
    priority = [*row['core_fact_ids'], *row['required_exception_fact_ids']]
    for operation in required_operations(row['question']):
        match = next((key for key in ranked if operation in operations[key]), None)
        if match is not None:
            priority.append(match)
    for task in question_atom_tasks([row], max_atoms=None):
        if ranked:
            scores = {key: task_support_score(task, by_id[key].quote, row['question'], product)
                      for key in ranked}
            best = max(ranked, key=lambda key: scores[key])
            if scores[best]:
                priority.append(best)
    return list(dict.fromkeys([*priority, *ranked]))


def select_question_pool_packet(detail, snapshot, packet, question_id=None, fact_ids=None):
    """Create a replayable pool selection without the default top-three/eight cap."""
    available = question_pool_facts(detail, snapshot, packet, question_id)
    ids = list(dict.fromkeys(fact_ids)) if fact_ids is not None else [fact.id for fact in available]
    if not set(ids) <= {fact.id for fact in available}:
        raise ValueError('selected original is outside the accepted question pool')
    rows = [row for row in packet['retrieval']['evidence_pool']['questions']
            if question_id is None or row['question_id'] == question_id]
    closure = _round_robin([row['required_exception_fact_ids'] for row in rows],
                           len(snapshot.facts))
    ids = list(dict.fromkeys([*closure, *ids]))
    selected = deepcopy(packet)
    selected['selected_fact_ids'] = ids
    selected['pool_selection'] = dict(version=1, question_ids=[row['question_id'] for row in rows],
        requested_fact_ids=ids,
        evidence_pool_sha256=_identity_hash(packet['retrieval']['evidence_pool']))
    selected['packet_id'] = packet_id(selected)
    validate_packets(detail, snapshot, [selected])
    return selected


def selected_packet_ids(packets):
    # Each scope's selection already reserves every question before backgrounds.
    return tuple(_round_robin([packet['selected_fact_ids'] for packet in packets],
                             sum(len(packet['selected_fact_ids']) for packet in packets)))


def _identity_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _pool_replay_identity(pool):
    # Display traces may redact query/source text. Their hash-only original
    # identities and fact IDs remain replayable without retaining that text.
    return dict(fact_ids=pool.get('fact_ids'), version=pool.get('version'), questions=[
        dict(question_id=row['question_id'], core_fact_ids=row['core_fact_ids'],
             required_exception_fact_ids=row['required_exception_fact_ids'], candidates=[
                 {key: value for key, value in candidate.items() if key != 'source_id'}
                 for candidate in row['candidates']]) for row in pool.get('questions', ())])


def validate_pool_trace_packets(packets, receipt):
    """Check redaction-safe pool identities against the credential's receipt."""
    if len(packets) != len(receipt['packets']):
        raise ValueError('question pool trace packets missing')
    for packet, identity in zip(packets, receipt['packets'], strict=True):
        pool = packet['retrieval'].get('evidence_pool', {})
        if (packet.get('packet_id') != identity['packet_id']
                or _identity_hash(_pool_replay_identity(pool))
                != identity.get('evidence_pool_replay_sha256')
                or packet.get('pool_selection') != identity.get('pool_selection')):
            raise ValueError('question pool trace identity changed')


def _scope_hash(detail, product, dimension):
    return _identity_hash([detail.id, detail.workspace_id, detail.project_id, product, dimension])


def selection_receipt(detail, packets, requested_fact_ids):
    """A bounded identity receipt; persisted display packets may be redacted."""
    version = 2 if any(packet.get('version') == 2 for packet in packets) else 1
    result = dict(version=version, requested_fact_ids=list(requested_fact_ids), packets=[
        dict(packet_id=packet['packet_id'],
            scope_sha256=_scope_hash(detail, packet['competitor'], packet['dimension']),
            questions_sha256=_identity_hash(packet['questions']),
            snapshot_id=packet['snapshot_id'], snapshot_content_hash=packet['snapshot_content_hash'],
            selection_config=packet['selection_config'], selected_fact_ids=packet['selected_fact_ids'],
            retrieval_identity_sha256=_identity_hash({key: packet['retrieval'].get(key) for key in
                ('mode', 'embedding_model_version', 'reranker_model_version')}))
        for packet in packets])
    if version == 2:
        for receipt, packet in zip(result['packets'], packets, strict=True):
            receipt.update(packet_version=packet.get('version', 1),
                evidence_pool_sha256=_identity_hash(packet['retrieval'].get('evidence_pool')),
                evidence_pool_replay_sha256=_identity_hash(
                    _pool_replay_identity(packet['retrieval'].get('evidence_pool', {}))),
                pool_selection=packet.get('pool_selection'))
    return result


def receipt_hash(receipt):
    return _identity_hash(receipt)


def validate_selection_receipt(detail, snapshot, receipt, use):
    if (not isinstance(receipt, dict) or receipt.get('version') not in {1, 2}
            or not isinstance(receipt.get('packets'), list) or not receipt['packets']
            or not use.id.endswith('-' + receipt_hash(receipt))):
        raise ValueError('question selection receipt missing or changed; rebuild evidence use')
    scopes = {_scope_hash(detail, product, dimension): (product, dimension)
              for product in detail.plan.competitors for dimension in detail.plan.dimensions}
    config = selection_config()
    for packet in receipt['packets']:
        scope = scopes.get(packet['scope_sha256'])
        if (scope is None
                or packet['questions_sha256'] != _identity_hash(research_questions(detail, *scope))
                or (packet['snapshot_id'], packet['snapshot_content_hash']) != (snapshot.id, snapshot.content_hash)
                or packet['selection_config'] != config):
            raise ValueError('question receipt scope, snapshot, query or configuration changed')
        if receipt['version'] == 2:
            if (packet.get('packet_version') not in {1, 2}
                    or not isinstance(packet.get('evidence_pool_sha256'), str)):
                raise ValueError('question pool receipt identity changed')
            selection = packet.get('pool_selection')
            if selection is not None and (
                selection.get('version') != 1
                or selection.get('evidence_pool_sha256') != packet['evidence_pool_sha256']
                or selection.get('requested_fact_ids') != packet['selected_fact_ids']
            ):
                raise ValueError('question pool receipt selection changed')
    selected = selected_packet_ids(receipt['packets'])
    if (tuple(receipt['requested_fact_ids']) != use.requested_fact_ids
            or selected != use.requested_fact_ids[:len(selected)]):
        raise ValueError('question packet selection changed')


def reconcile_packet_originals(packet, snapshot, facts):
    """Replay every real question, including retrieval's empty-candidate exit.

    Missing known originals are capacity omissions. An empty eligible/ranked
    selection is unverified evidence availability, never proof that the whole
    source collection lacks a rule and never automatically a capacity gap.
    """
    retrieval = packet['retrieval']
    diagnostics = {row['question_id']: row for row in retrieval['questions']}
    rows = []
    for question in packet['questions']:
        row = diagnostics.get(question['question_id'])
        if row is None:
            row = dict(question_id=question['question_id'], fact_ids=[], minimum_evidence_missing=True,
                       minimum_evidence_gap=('no_eligible_original' if not retrieval['eligible_count']
                                             else 'no_relevant_original'))
        if packet.get('pool_selection') is not None:
            pool_row = next(item for item in retrieval['evidence_pool']['questions']
                            if item['question_id'] == question['question_id'])
            row = dict(row, fact_ids=[candidate['fact_id'] for candidate in pool_row['candidates']])
        rows.append(row)
    def in_scope(fact):
        return all((fact.get(key) if isinstance(fact, dict) else getattr(fact, key, None)) == packet[key]
                   for key in ('competitor', 'dimension'))
    # Strict original equivalence is local to this product and dimension.
    # An identical rule from a different scope cannot close this obligation.
    originals = [fact for fact in snapshot.facts if in_scope(fact)]
    sent_facts = [fact for fact in facts if in_scope(fact)]
    replay = _reconcile_question_originals(dict(retrieval, questions=rows), originals, sent_facts)
    all_gaps = set()
    for diagnostic, actual in zip(rows, replay['questions'], strict=True):
        gaps = []
        if actual['missing_core_fact_ids']:
            gaps.append('question_core_context_budget_exceeded')
        if actual['missing_exception_fact_ids']:
            gaps.append('question_exception_context_budget_exceeded')
        if actual['minimum_evidence_missing']:
            if diagnostic.get('fact_ids'):
                gaps.append('question_core_context_budget_exceeded')
            else:
                gap = diagnostic.get('minimum_evidence_gap') or 'no_relevant_original'
                gaps.append('question_' + gap)
        actual['evidence_gaps'] = sorted(set(gaps))
        if not gaps:
            actual['evidence_gap'] = None
        elif any(gap.endswith('_context_budget_exceeded') for gap in gaps):
            actual['evidence_gap'] = 'context_budget_exceeded'
        else:
            actual['evidence_gap'] = diagnostic.get('minimum_evidence_gap') or 'no_relevant_original'
        all_gaps.update(gaps)
    replay['gaps'] = sorted(all_gaps)
    return replay


def prompt_packets(packets, snapshot, facts):
    result = []
    for packet in packets:
        reconciliation = reconcile_packet_originals(packet, snapshot, facts)
        sent = set(reconciliation['sent_fact_ids'])
        diagnostics = {row['question_id']: row for row in packet['retrieval']['questions']}
        actual = {row['question_id']: row for row in reconciliation['questions']}
        questions = []
        for question in packet['questions']:
            diagnostic = diagnostics.get(question['question_id'], {})
            replay = actual.get(question['question_id'], {})
            candidate_ids = diagnostic.get('fact_ids', ())
            pool_metadata = {}
            if packet.get('version') == 2:
                pool = packet['retrieval']['evidence_pool']
                pool_row = next(row for row in pool['questions']
                                if row['question_id'] == question['question_id'])
                candidate_ids = [candidate['fact_id'] for candidate in pool_row['candidates']]
                requested = set(candidate_ids) & set(packet['selected_fact_ids'])
                deferred = set(candidate_ids) - sent
                pool_metadata = dict(pool_available_fact_count=len(candidate_ids),
                    pool_deferred_fact_count=len(deferred),
                    pool_status=('no_eligible_original' if not candidate_ids else
                                 'deferred_context_budget' if requested - sent else
                                 'selection_required' if deferred else 'available_in_view'))
            questions.append(dict(question, fact_ids=[fid for fid in candidate_ids if fid in sent],
                missing_core_fact_ids=replay.get('missing_core_fact_ids', []),
                missing_exception_fact_ids=replay.get('missing_exception_fact_ids', []),
                minimum_evidence_missing=replay.get('minimum_evidence_missing', True),
                evidence_gap=replay['evidence_gap'], evidence_gaps=replay['evidence_gaps'],
                **pool_metadata))
        result.append(dict(packet_id=packet['packet_id'], snapshot_id=packet['snapshot_id'],
            competitor=packet['competitor'], dimension=packet['dimension'], questions=questions))
    return result
