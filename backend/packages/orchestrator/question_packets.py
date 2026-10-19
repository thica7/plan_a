"""Question selection identity and replay; facts remain in the stage's shared pool."""
from __future__ import annotations

import hashlib
import os

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
            packet = dict(run_id=detail.id, workspace_id=detail.workspace_id,
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


def selected_packet_ids(packets):
    # Each scope's selection already reserves every question before backgrounds.
    return tuple(_round_robin([packet['selected_fact_ids'] for packet in packets],
                             sum(len(packet['selected_fact_ids']) for packet in packets)))


def _identity_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _scope_hash(detail, product, dimension):
    return _identity_hash([detail.id, detail.workspace_id, detail.project_id, product, dimension])


def selection_receipt(detail, packets, requested_fact_ids):
    """A bounded identity receipt; persisted display packets may be redacted."""
    return dict(version=1, requested_fact_ids=list(requested_fact_ids), packets=[
        dict(packet_id=packet['packet_id'],
            scope_sha256=_scope_hash(detail, packet['competitor'], packet['dimension']),
            questions_sha256=_identity_hash(packet['questions']),
            snapshot_id=packet['snapshot_id'], snapshot_content_hash=packet['snapshot_content_hash'],
            selection_config=packet['selection_config'], selected_fact_ids=packet['selected_fact_ids'],
            retrieval_identity_sha256=_identity_hash({key: packet['retrieval'].get(key) for key in
                ('mode', 'embedding_model_version', 'reranker_model_version')}))
        for packet in packets])


def receipt_hash(receipt):
    return _identity_hash(receipt)


def validate_selection_receipt(detail, snapshot, receipt, use):
    if (not isinstance(receipt, dict) or receipt.get('version') != 1
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
            questions.append(dict(question, fact_ids=[fid for fid in diagnostic.get('fact_ids', ()) if fid in sent],
                missing_core_fact_ids=replay.get('missing_core_fact_ids', []),
                missing_exception_fact_ids=replay.get('missing_exception_fact_ids', []),
                minimum_evidence_missing=replay.get('minimum_evidence_missing', True),
                evidence_gap=replay['evidence_gap'], evidence_gaps=replay['evidence_gaps']))
        result.append(dict(packet_id=packet['packet_id'], snapshot_id=packet['snapshot_id'],
            competitor=packet['competitor'], dimension=packet['dimension'], questions=questions))
    return result
