"""Transport-shape fixtures, never semantic accuracy or real model evidence."""


def supported_review(claim, reason="The supplied statement and conditions are supported."):
    return {
        "claim_id": claim["id"],
        "verdict": "supported",
        "reason": reason,
        "checks": [
            {"check_id": item["check_id"], "verdict": "supported", "claim_span": claim["text"]}
            for item in claim.get("required_checks", [])
        ],
    }


def sent_source_span_id(row, text=None):
    """Choose only IDs actually present in a Writer transport fixture."""
    choices = row.get('source_span_candidates', [])
    for candidate in choices:
        path = candidate['source_path'].split('/')
        member = row['quote'] if path[0] == 'quote' else row['value']
        if len(path) == 2:
            member = member[int(path[1])]
        if isinstance(member, str):
            support = member[candidate['start']:candidate['end']]
            if text is None or text == support or text in support:
                return candidate['span_id']
    raise AssertionError('No sent complete source span supports the fixture text')


def sent_source_atom(rows, text, *, support_text=None):
    """Use complete sent short quotes, preserving legacy no-question fixtures."""
    if isinstance(rows, dict):
        rows = [rows]
    refs = []
    for row in rows:
        choices = row.get('source_span_candidates', [])
        candidate = next((span for span in choices if 'support_ref' in span
            and support_text is not None and span.get('quote') == support_text), None)
        if candidate is None:
            candidate = next((span for span in choices if 'support_ref' in span and 'quote' in span
                and (support_text is None or support_text in span['quote'])), None)
        if candidate is None:
            return dict(text=text, kind='fact', competitor=rows[0]['competitor'],
                dimension=rows[0]['dimension'], fact_ids=[row['id'] for row in rows],
                source_ids=list(dict.fromkeys(row['source_id'] for row in rows)),
                source_span_ids=[sent_source_span_id(row, support_text) for row in rows])
        refs.append(candidate['support_ref'])
    return dict(text=text, kind='fact', support_refs=refs)


def question_plan_response(payload, atoms):
    """Explicit current transport fixture; legacy no-question drafts keep their shape."""
    import json

    from packages.research.evidence.source_exceptions import required_question_clarifications
    required = {row['question_id']: row['missing_fields']
                for row in required_question_clarifications(payload.get('questions', []))}
    if not payload.get('questions'):
        return json.dumps({'claims': atoms})
    if payload.get('generation_projection_version') == 2:
        from packages.agents.writer.atomic_question_projection import generation_task_atom_reasons
        from packages.agents.writer.question_allocation import task_support_score
        atoms = [dict(atom, task_id=next((task['task_id']
            for task in sorted(payload['generation_tasks'], key=lambda t: -task_support_score(
                t, atom.get('text', ''), payload['questions'][0]['question'],
                payload['segment_competitor']))
            if task['state'] == 'planned' and not generation_task_atom_reasons(
                task, atom.get('text', ''), kind=atom.get('kind'))), 'unknown-task'))
            for atom in atoms]
    return json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=atoms,
        missing_fields=required.get(q['question_id'], [])) for q in payload['questions']]})


def expand_prompt_payload(payload):
    from packages.research.question_delivery import _expand_text_refs
    return _expand_text_refs(payload)


def answer_response(payload, response, *, relation='direct'):
    """Opted-in single-branch transport fixture, not a semantic reviewer.

    Each caller supplies its expected relation explicitly for negative cases.
    Historical/proposal responses and clarification/unknown rows stay untouched.
    Multi-predicate fixtures must supply explicit subquestions themselves.
    """
    import json
    from copy import deepcopy
    response = deepcopy(response)
    if payload.get('answer_review_contract') == 'subquestion-premises-v1':
        questions = {q['question_id']: q['question'] for q in payload['questions']}
        for row in response.get('answers', []):
            if (row['status'] in {'answered', 'partial'}
                    and row['resolution'] in {'direct', 'conditional'}
                    and 'subquestions' not in row):
                row['subquestions'] = [dict(question_quote=questions[row['question_id']],
                    claim_ids=row['claim_ids'], conclusion=row['conclusion'], relation=relation)]
    return json.dumps(response)
