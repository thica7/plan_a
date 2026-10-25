"""Private source-bound Collector receipts and observations of actual downstream use.

Receipts never establish semantic completeness. Later observations are separate
trace events so an earlier Collector receipt cannot acquire future provenance.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from packages.research.evidence.admission import admit_evidence_items
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.extraction.semantic import SEMANTIC_EXTRACTOR_NAMES, semantic_extraction, semantic_focus_signature
from packages.research.models import CapturedPage, EvidenceItem, ResearchBrief, SourceCandidate

VERSION = 'question_delivery.v1'


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _scope(detail, competitor, dimension):
    return dict(run_id=detail.id, workspace_id=detail.workspace_id, project_id=detail.project_id,
                competitor=competitor, dimension=dimension)


def _canonical_ref(source):
    return dict(document_id=source.metadata.get('kb_document_id'),
                version=source.metadata.get('kb_document_version'),
                content_hash=source.metadata.get('kb_document_content_hash'))


def _build_question_delivery(detail, brief, result, sources, conversion_rejections):
    """Capture the actual post-persistence production state, without copying bodies."""
    captures, recipes = [], []
    for page in result.captured_pages:
        body = page.text or page.markdown or page.snippet
        captures.append(dict(page_id=page.id, candidate_id=page.candidate_id, url=page.final_url,
            requested_url=page.requested_url, title=page.title, content_hash=page.content_hash,
            body_sha256=_sha(body), captured_at=page.captured_at.isoformat(), status=page.status, status_code=page.status_code,
            quality_score=page.quality_score, failure_reason=page.failure_reason,
            fetch_method=page.fetch_method, source_material_level=page.source_material_level,
            capture_completeness={key: deepcopy(page.metadata[key]) for key in
                ('capture_structure_version', 'capture_incomplete', 'capture_gaps') if key in page.metadata},
            anchors=deepcopy(page.metadata.get('disclosures', []))))
    page_by_id = {page.id: page for page in result.captured_pages}
    for extraction in result.extractions:
        if extraction.extractor_name not in SEMANTIC_EXTRACTOR_NAMES:
            continue
        focus_brief = brief.model_copy(update={'metadata': {**brief.metadata,
            'active_question_ids': extraction.metadata.get('active_question_ids', [])}})
        page = page_by_id.get(extraction.captured_page_id)
        recipes.append(dict(id=extraction.id, extractor_name=extraction.extractor_name,
            extractor_version=extraction.extractor_version, page_id=extraction.captured_page_id,
            focus_signature=semantic_focus_signature(focus_brief, page) if page else None,
            confidence=extraction.confidence,
            brief={key: focus_brief.model_dump(mode='json')[key] for key in
                ('run_id', 'topic', 'competitor', 'dimension', 'product_name', 'product_category',
                 'product_use_cases', 'questions')} | {'metadata': {
                    'active_question_ids': extraction.metadata.get('active_question_ids', [])}},
            proposals=deepcopy(extraction.metadata.get('proposal_diagnostics', [])),
            quotes=[quote.model_dump(mode='json') for quote in extraction.quotes]))
    persistence_errors = {}
    for span in detail.trace_spans:
        if span.name == 'kb_ingest_captured_sources':
            try:
                for row in json.loads(span.full_output).get('results', []):
                    if row.get('error'):
                        persistence_errors[row.get('source_id')] = row['error']
            except (ValueError, TypeError, AttributeError):
                continue
    actual_sources = [dict(id=source.id, page_id=source.metadata.get('captured_page_id'),
        normalized_fields=deepcopy(source.metadata.get('normalized_fields', [])),
        canonical_ref=_canonical_ref(source),
        ingest_status=source.metadata.get('kb_full_source_ingest_status'),
        persistence_error=persistence_errors.get(source.id)) for source in sources]
    missing = []
    for item in result.evidence_items:
        if item.status != 'accepted':
            continue
        if not any(item.id in row.get('evidence_item_ids', []) for source in actual_sources
                   for row in source['normalized_fields']):
            rejection = next((row for row in conversion_rejections
                              if row.get('candidate_id') == item.source_candidate_id), {})
            missing.append(dict(item_id=item.id, page_id=item.captured_page_id,
                                reason=rejection.get('reason', 'conversion_missing')))
    questions = []
    for question in brief.questions:
        focused = [row for row in recipes if question.question_id in
                   row['brief']['metadata']['active_question_ids']]
        recipe_ids = {row['id'] for row in focused}
        item_ids = [item.id for item in result.evidence_items
                    if item.metadata.get('extraction_id') in recipe_ids]
        questions.append(dict(question_id=question.question_id, question=question.question,
            semantic_status='unverified', capture_ids=sorted({row['page_id'] for row in focused}),
            recipe_ids=sorted(recipe_ids), item_ids=item_ids,
            next_action='resolve_conversion_missing' if any(row['item_id'] in item_ids for row in missing)
                else 'retry_canonical_persistence' if any(source['ingest_status'] == 'failed' for source in actual_sources)
                else 'replay_canonical_and_review_question'))
    receipt = dict(version=VERSION, scope=_scope(detail, brief.competitor, brief.dimension),
        questions=questions, captures=captures, recipes=recipes,
        items=[item.model_dump(mode='json') for item in result.evidence_items],
        raw_sources=actual_sources, conversion_missing=missing,
        conversion_rejections=deepcopy(conversion_rejections))
    receipt['id'] = 'question-delivery-' + _sha(canonical_json(receipt))[:24]
    for source in sources:
        source.metadata['question_delivery_ref'] = receipt['id']
    return receipt


def _question_delivery_capsules(detail):
    for span in detail.trace_spans:
        if span.name != 'clean_research_pipeline' or not span.full_output:
            continue
        try:
            capsule = json.loads(span.full_output).get('question_delivery_v1')
        except (ValueError, AttributeError):
            continue
        if isinstance(capsule, dict) and capsule.get('version') == VERSION:
            yield capsule


def _replay_question_delivery(detail, capsule, documents, *, authorized_brief=None):
    """Re-run original validators against typed canonical records, never accepted flags."""
    scope = capsule.get('scope', {})
    scope_valid = (scope == _scope(detail, scope.get('competitor'), scope.get('dimension'))
                   and scope.get('competitor') in detail.plan.competitors
                   and scope.get('dimension') in detail.plan.dimensions)
    receipt_valid = capsule.get('id') == 'question-delivery-' + _sha(canonical_json(
        {key: value for key, value in capsule.items() if key != 'id'}))[:24]
    sources = {source.id: source for source in detail.raw_sources}
    captures = {row['page_id']: row for row in capsule.get('captures', [])}
    raw_by_page = {row['page_id']: row for row in capsule.get('raw_sources', [])}
    parsed, page_reasons, producers = {}, {}, {}
    for recipe in capsule.get('recipes', []):
        reasons = []
        capture, raw = captures.get(recipe['page_id']), raw_by_page.get(recipe['page_id'])
        source = sources.get(raw['id']) if raw else None
        document = documents.get(raw['canonical_ref']['document_id']) if raw else None
        if not scope_valid:
            reasons.append('scope_mismatch')
        if not receipt_valid:
            reasons.append('receipt_identity_mismatch')
        if authorized_brief is None:
            reasons.append('original_request_unverified')
        if not capture or not source or not document:
            reasons.append('canonical_document_missing' if source else 'conversion_missing')
        if capture and source and document:
            from packages.research.evidence.snapshot import _SIGNAL_MATERIAL_LEVELS, _SIGNAL_TYPES
            if (document.source_role != 'source' or document.source_type in _SIGNAL_TYPES
                    or source.source_type in _SIGNAL_TYPES
                    or document.metadata.get('source_material_level') in _SIGNAL_MATERIAL_LEVELS
                    or source.metadata.get('source_material_level') in _SIGNAL_MATERIAL_LEVELS):
                reasons.append('canonical_material_not_original')
            ref = raw['canonical_ref']
            if ((document.workspace_id, document.project_id, document.competitor, document.dimension)
                    != (scope.get('workspace_id'), scope.get('project_id'), scope.get('competitor'), scope.get('dimension'))):
                reasons.append('canonical_scope_mismatch')
            if (not document.is_active or document.status != 'active' or document.version != ref['version']
                    or document.content_hash != ref['content_hash'] or _canonical_ref(source) != ref
                    or _sha(document.text)[:16] != document.content_hash):
                reasons.append('canonical_reference_mismatch')
            if (_sha(document.text) != capture['body_sha256']
                    or capture['content_hash'] not in {_sha(document.text), _sha(document.text)[:16]}
                    or (document.url or '') != capture['url'] or str(source.url or '') != capture['url']
                    or source.metadata.get('captured_page_id') != capture['page_id']
                    or source.metadata.get('capture_content_hash') != capture['content_hash']):
                reasons.append('canonical_capture_mismatch')
        if not reasons:
            try:
                brief = ResearchBrief.model_validate(recipe['brief'])
                # Exact original questions and focus are a prerequisite, never evidence.
                expected_questions = [(q.question_id, q.question) for q in authorized_brief.questions]
                if ([(q['question_id'], q['question']) for q in capsule['questions']] != expected_questions
                        or any(getattr(brief, key) != getattr(authorized_brief, key) for key in
                               ('topic', 'competitor', 'dimension', 'product_name', 'product_category', 'product_use_cases'))):
                    raise ValueError('original_request_mismatch')
                if ([(q.question_id, q.question) for q in brief.questions] != expected_questions
                        or brief.run_id != detail.id or brief.competitor != scope['competitor']
                        or brief.dimension != scope['dimension'] or brief.topic != detail.topic):
                    raise ValueError('question_focus_mismatch')
                page = CapturedPage(candidate_id=capture['candidate_id'], requested_url=capture['requested_url'],
                    final_url=capture['url'], title=capture['title'], text=document.text,
                    content_hash=capture['content_hash'], status=capture['status'], status_code=capture['status_code'],
                    quality_score=capture['quality_score'], failure_reason=capture['failure_reason'],
                    captured_at=capture['captured_at'], source_material_level=capture['source_material_level'],
                    fetch_method=capture['fetch_method'], metadata=deepcopy(document.metadata))
                if page.id != capture['page_id'] or semantic_focus_signature(brief, page) != recipe['focus_signature']:
                    raise ValueError('page_or_focus_identity_mismatch')
                if recipe['extractor_name'] not in SEMANTIC_EXTRACTOR_NAMES:
                    raise ValueError('extractor_unverified')
                facts = [{'quote': row.get('original_quote', row['quote_anchor']['quote'])} for row in recipe['proposals']]
                extraction = semantic_extraction(
                    brief, page, {'facts': facts}, extractor_name=recipe['extractor_name'],
                    extractor_version=recipe['extractor_version'],
                )
                if extraction.id != recipe['id']:
                    raise ValueError('recipe_identity_mismatch')
                if (extraction.extractor_version != recipe['extractor_version']
                        or [quote.model_dump(mode='json') for quote in extraction.quotes] != recipe['quotes']
                        or extraction.confidence != recipe['confidence']
                        or extraction.metadata['proposal_diagnostics'] != recipe['proposals']):
                    raise ValueError('recipe_replay_mismatch')
                candidate = SourceCandidate(id=page.candidate_id, title=page.title, url=page.final_url, origin='manual')
                admitted = admit_evidence_items([extraction], brief=brief, captured_pages=[page], candidates=[candidate])
                parsed[extraction.id] = admitted
                producers[extraction.id] = {'active_question_ids': extraction.metadata['active_question_ids'],
                    'page_id': page.id, 'items': [item for item in admitted
                        if item.metadata.get('extraction_id') == extraction.id]}
            except (ValueError, KeyError, TypeError) as error:
                reasons.append(str(error)[:120])
        page_reasons[recipe['id']] = reasons
    results, verified = [], []
    all_replayed = {item.id: item for batch in parsed.values() for item in batch if item.status == 'accepted'}
    normalized = [row.model_dump(mode='json') for row in normalized_fields_from_evidence_items(all_replayed.values())]
    for original in capsule.get('items', []):
        producer_id = original.get('metadata', {}).get('extraction_id')
        reasons = list(page_reasons.get(producer_id, ['extractor_unverified']))
        replayed = next((item for item in parsed.get(producer_id, [])
                         if item.id == original['id'] and item.status == 'accepted'), None)
        if replayed is None or replayed.metadata.get('extraction_id') != producer_id:
            reasons.append('item_producer_mismatch')
        raw = raw_by_page.get(original['captured_page_id'])
        source = sources.get(raw['id']) if raw else None
        if not replayed or (replayed.field, replayed.value, replayed.quote, replayed.source_url,
                replayed.competitor, replayed.dimension) != (original['field'], original['value'], original['quote'],
                original['source_url'], original['competitor'], original['dimension']):
            reasons.append('item_replay_mismatch')
        try:
            rebuilt = EvidenceItem.model_validate({**original, 'id': ''})
            if rebuilt.id != original['id']:
                reasons.append('item_identity_mismatch')
        except ValueError:
            reasons.append('item_identity_invalid')
        expected = [row for row in normalized if original['id'] in row.get('evidence_item_ids', [])]
        annotation_status = 'not_available'
        if not expected or not raw or not source:
            reasons.append('conversion_missing')
        else:
            document = documents.get(raw['canonical_ref']['document_id'])
            for row in expected:
                if row not in raw['normalized_fields'] or row not in source.metadata.get('normalized_fields', []):
                    reasons.append('normalized_binding_mismatch')
            annotation_status = ('matching' if document and all(row in document.metadata.get('normalized_fields', [])
                                 for row in expected) else 'not_represented')
        status = 'partial' if reasons else 'ready'
        results.append(dict(item_id=original['id'], status=status, reasons=list(dict.fromkeys(reasons)), fact_ids=[],
                            canonical_annotation_status=annotation_status))
        if not reasons:
            verified.append(original['id'])
    questions = []
    authorized = ([question.model_dump(mode='json') for question in authorized_brief.questions]
                  if authorized_brief is not None else capsule.get('questions', []))
    for question in authorized:
        qid = question['question_id']
        focused = {key: producer for key, producer in producers.items()
                   if qid in producer['active_question_ids']}
        actual = dict(recipe_ids=sorted(focused),
            capture_ids=sorted({producer['page_id'] for producer in focused.values()}),
            item_ids=[item.id for producer in focused.values() for item in producer['items']])
        claimed = next((row for row in capsule.get('questions', []) if row['question_id'] == qid), {})
        # Receipt associations are claims to check; only replayed producers grant links.
        registered = {recipe['id'] for recipe in capsule.get('recipes', [])}
        unregistered = any(key not in registered for key in claimed.get('recipe_ids', []))
        unknown = any(key not in producers for key in claimed.get('recipe_ids', []))
        association = ('partial' if unregistered else 'unverified' if unknown or authorized_brief is None else 'verified'
                       if all(claimed.get(key) == value for key, value in actual.items()) else 'partial')
        questions.append(dict(question_id=qid, question=question['question'], **actual,
            association_status=association,
            reasons=[] if association == 'verified' else ['question_association_' + association]))
    return dict(version=VERSION, capsule_id=capsule.get('id'), scope=scope, questions=questions,
                canonical_documents=[dict(document_id=document.id, version=document.version,
                    content_hash=document.content_hash, source_run_id=document.metadata.get('run_id'),
                    source_raw_source_id=document.metadata.get('raw_source_id')) for document in documents.values()
                    if any(row['canonical_ref']['document_id'] == document.id for row in capsule.get('raw_sources', []))],
                canonical_annotations='not_authoritative', verified_item_ids=verified, item_results=results)


def _seal_question_delivery(detail, capsule, documents, snapshot, *, authorized_brief=None):
    replay = _replay_question_delivery(detail, capsule, documents, authorized_brief=authorized_brief)
    replay['snapshot_id'] = snapshot.id
    replay['snapshot_content_hash'] = snapshot.content_hash
    replay['phase'] = snapshot.phase
    originals = {item['id']: item for item in capsule['items']}
    sources = {source.id: source for source in snapshot.sources}
    for result in replay['item_results']:
        item = originals[result['item_id']]
        matches = [fact for fact in snapshot.facts if result['item_id'] in fact.evidence_item_ids
                   and fact.quote == item['quote'] and fact.competitor == item['competitor']
                   and fact.dimension == item['dimension']]
        content = [fact for fact in matches if fact.field == 'evidence_terms'
                   and isinstance(item['value'], dict) and fact.value == item['value'].get('evidence_terms')]
        if result['status'] == 'ready' and not content:
            result['reasons'].append('snapshot_content_missing')
        from packages.research.evidence.snapshot import _facts
        for fact in matches:
            if fact.status != 'supported':
                result['reasons'].append('snapshot_fact_not_supported')
            source = sources.get(fact.source_id)
            if not source or source.document_id not in documents:
                result['reasons'].append('snapshot_canonical_missing')
            else:
                document = documents[source.document_id]
                if (source.document_version != document.version or source.document_content_hash != document.content_hash
                        or (source.document_workspace_id, source.document_project_id) != (document.workspace_id, document.project_id)):
                    result['reasons'].append('snapshot_canonical_mismatch')
                raw = next((row for row in capsule['raw_sources'] if row['id'] == source.id), None)
                rows = [row for row in raw['normalized_fields'] if result['item_id'] in row.get('evidence_item_ids', [])] if raw else []
                try:
                    if fact not in _facts(source, rows):
                        result['reasons'].append('snapshot_fact_binding_mismatch')
                except (ValueError, KeyError, TypeError):
                    result['reasons'].append('snapshot_fact_binding_invalid')
        if result['reasons']:
            result['status'] = 'partial'
        result['fact_ids'] = [fact.id for fact in matches]
        result['content_fact_ids'] = [fact.id for fact in content]
    replay['verified_item_ids'] = [row['item_id'] for row in replay['item_results'] if row['status'] == 'ready']
    for question in replay['questions']:
        question['semantic_status'] = 'unverified'
        question['ready_item_ids'] = ([item for item in question['item_ids'] if item in replay['verified_item_ids']]
                                      if question['association_status'] == 'verified' else [])
        question['next_action'] = ('review_question_semantics' if question['ready_item_ids']
                                   else 'resolve_delivery_gaps')
    return replay


def _observe_question_view(view, use, replay):
    valid = (use.status in {'validated', 'reused'} and use.validated_snapshot_id == view.snapshot_id
             and use.snapshot_id == view.snapshot_id and use.dependency_hash == view.dependency_hash
             and replay.get('snapshot_id') == view.snapshot_id)
    content, controls = [], []
    verified = set(replay.get('verified_item_ids', []))
    for fact in view.facts:
        row = dict(fact_id=fact.id, evidence_item_ids=list(fact.evidence_item_ids),
                   content_sha256=_sha(canonical_json(dict(quote=fact.quote, value=fact.value, qualifiers=fact.qualifiers))))
        if fact.field == 'evidence_terms':
            bound = all(any(item['item_id'] == item_id and fact.id in item.get('content_fact_ids', [])
                            for item in replay.get('item_results', [])) for item_id in fact.evidence_item_ids)
            row['replay_status'] = 'ready' if valid and fact.evidence_item_ids and set(fact.evidence_item_ids) <= verified and bound else 'unverified'
            content.append(row)
        else:
            controls.append(row)
    return dict(version=VERSION, consumption_id=use.id, agent=use.agent,
        snapshot_id=view.snapshot_id, dependency_hash=view.dependency_hash,
        status='view_selected' if valid else 'unverified', dispatch_status='unverified',
        content_observed=content, control_selected=controls)


def _expand_text_refs(payload):
    refs = payload.get('text_sets', {})
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'text_ref'}:
                target = refs.get(value['text_ref'])
                if not isinstance(target, str):
                    raise ValueError('text_reference_unverified')
                return target
            return {key: expand(item) for key, item in value.items() if key != 'text_sets'}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value
    return expand(payload)


def _observe_writer_dispatch(detail, view, use, prompt, span_start):
    """Match one actual LLM span and inspect its full input and transport counter."""
    result = dict(version=VERSION, consumption_id=use.id, agent='writer', snapshot_id=use.snapshot_id,
        dependency_hash=use.dependency_hash, status='unverified', dispatch_attempted=False,
        content_dispatched=False,
        prompt_bytes=len(prompt.encode()), prompt_sha256=_sha(prompt), span_id=None,
        transport_attempts=None, content_observed=[], omitted_fact_ids=[], reasons=[])
    spans = [span for span in detail.trace_spans[span_start:]
             if span.kind == 'llm' and span.name == 'dimension_claim_writer' and span.agent == 'writer'
             and span.subagent == f'{use.competitor}/{use.dimension}'
             and span.full_input.endswith('\nJSON:\n' + prompt)]
    if len(spans) != 1:
        result['reasons'].append('writer_span_missing_or_ambiguous')
        return result
    span = spans[0]
    result['span_id'] = span.id
    result['full_input_sha256'] = _sha(span.full_input)
    attempts = span.metadata.get('llm_transport_attempts')
    if type(attempts) is not int or attempts < 0:
        result['reasons'].append('transport_attempts_unverified')
        return result
    result['transport_attempts'] = attempts
    result['dispatch_attempted'] = attempts > 0
    result['transport_status'] = ('prepared' if attempts == 0 else
                                  'dispatch_succeeded' if span.status == 'ok' else 'dispatch_failed')
    if (use.status not in {'validated', 'reused'} or use.validated_snapshot_id != use.snapshot_id
            or use.snapshot_id != view.snapshot_id or use.dependency_hash != view.dependency_hash):
        result['reasons'].append('writer_use_unverified')
        return result
    try:
        payload = _expand_text_refs(json.loads(span.full_input[-len(prompt):]))
        rows = payload['evidence_view']['facts']
        if not isinstance(rows, list):
            raise ValueError('writer_facts_invalid')
        sent = {row['id']: row for row in rows}
        if len(sent) != len(rows):
            raise ValueError('writer_fact_identity_ambiguous')
        known = {fact.id: fact for fact in view.facts}
        if not set(sent) <= set(known):
            raise ValueError('writer_fact_not_selected')
        result['omitted_fact_ids'] = [fact.id for fact in view.facts
                                      if fact.field == 'evidence_terms' and fact.id not in sent]
        from packages.research.evidence.operations import operation_binding, operation_observations
        for fid, row in sent.items():
            fact = known[fid]
            expected = dict(id=fact.id, source_id=fact.source_id, competitor=fact.competitor,
                dimension=fact.dimension, field=fact.field, quote=fact.quote, value=fact.value,
                qualifiers={key: value for key, value in fact.qualifiers.items() if key != 'operations'})
            reasons = []
            if any(row.get(key) != value for key, value in expected.items()):
                reasons.append('writer_content_or_conditions_mismatch')
            legal = [operation_binding(item) for item in operation_observations(fact)]
            observed = row.get('operation_observations', [])
            if (legal and not observed or any(item not in legal for item in observed)):
                reasons.append('writer_operation_conditions_mismatch')
            result['content_observed'].append(dict(fact_id=fid, evidence_item_ids=list(fact.evidence_item_ids),
                status='partial' if reasons else 'complete', reasons=reasons,
                content_sha256=_sha(canonical_json(row)), expected_content_sha256=_sha(canonical_json(expected))))
        if result['omitted_fact_ids'] or any(row['reasons'] for row in result['content_observed']):
            result['status'] = 'partial'
            result['reasons'].append('writer_content_omitted_or_changed')
        else:
            result['status'] = result['transport_status']
            result['content_dispatched'] = attempts > 0
    except (ValueError, KeyError, TypeError) as error:
        result['status'] = 'partial'
        result['reasons'].append(str(error)[:120])
    return result
