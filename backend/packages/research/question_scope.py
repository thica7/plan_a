"""Keep original explicit requests and the established per-product scope."""

import hashlib
import json
import re

REQUEST_CONTEXT_VERSION = 2


def _grouped_question_segments(text, products):
    segments = []
    for line in text.splitlines():
        pieces = re.split(r"(?<=[?？])\s*(?=\S)", line)
        if len(pieces) > 1 and not re.search(r"[?？]|是否|能否|如何|哪些|什么|怎样", pieces[-1]):
            pieces[-2:] = [pieces[-2] + pieces[-1]]
        segments.extend(pieces)
    grouped = []
    for segment in segments:
        tail = segment.strip()
        presentation = re.fullmatch(r"请将[^?？\n]*(?:分别|逐项)(?:说明|列出|展示)[。.!]?", tail)
        if (grouped and presentation
                and not any(name in tail and name not in grouped[-1] for name in products)):
            grouped[-1] += " " + tail
        else:
            grouped.append(segment)
    return grouped


def questions_match_scope(detail, product, dimension, questions):
    """A transported subset must retain exact, unique, ordered server questions."""
    if (not isinstance(questions, list) or not questions
            or any(not isinstance(q, dict) or not isinstance(q.get('question_id'), str)
                   for q in questions)):
        return False
    ids = {q['question_id'] for q in questions}
    return questions == [q for q in research_questions(detail, product, dimension)
                         if q['question_id'] in ids]


def question_request_context(detail, product, dimension, questions, *,
                             version=REQUEST_CONTEXT_VERSION):
    """Bind unchanged questions to a unique complete same-product source line.

    This is request-only context. Never infer a parent across lines or choose
    among different original requests containing the same question fragment.
    """
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Unknown request context version')
    canonical = {q['question_id']: q['question']
                 for q in research_questions(detail, product, dimension)}
    brief = detail.plan.decision_brief
    text = getattr(brief, 'decision_question', '') if brief else ''
    if not text and re.search(r'[?？]|是否|能否|如何|哪些|什么|怎样', detail.topic):
        text = detail.topic
    candidates, active = [], []
    if dimension == 'feature':
        for line in text.splitlines():
            parent = line.strip()
            mentioned = [name for name in detail.plan.competitors if re.search(
                r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])'
                if name.isascii() else re.escape(name), parent, re.I)]
            if mentioned:
                active = mentioned
            if active == [product] or not active and detail.plan.competitors == [product]:
                candidates.append(parent)
    grouped = {
        parent: {re.sub(r'^\s*(?:[-*]|\d+[.)、])\s*', '', segment).strip()
                 for segment in _grouped_question_segments(parent, detail.plan.competitors)}
        for parent in candidates
    } if version == 2 else {}
    parents, bindings, unbound = {}, [], []
    for question in questions:
        qid, quote = question['question_id'], question['question']
        matches = set(parent for parent in candidates
                      if quote and (quote in parent or quote in grouped.get(parent, ())))
        if canonical.get(qid) != quote or len(matches) != 1:
            unbound.append(qid)
            continue
        parent = matches.pop()
        identity = json.dumps([version, product, dimension, parent],
                              ensure_ascii=False)
        pid = 'request-parent-' + hashlib.sha256(identity.encode()).hexdigest()[:20]
        parents[pid] = dict(parent_id=pid, text=parent)
        bindings.append(dict(question_id=qid, parent_id=pid))
    return dict(version=version, purpose='request_only_not_evidence',
                parents=list(parents.values()), bindings=bindings, unbound_question_ids=unbound)


def request_context_questions(context, questions):
    """Expanded queries only; public question text, IDs and packets stay unchanged."""
    parents = {p['parent_id']: p['text'] for p in context['parents']}
    bindings = {b['question_id']: parents[b['parent_id']] for b in context['bindings']}
    return [dict(q, question=bindings.get(q['question_id'], q['question'])) for q in questions]


def narrow_request_context(context, question_ids):
    bindings = [b for b in context['bindings'] if b['question_id'] in question_ids]
    parent_ids = {b['parent_id'] for b in bindings}
    return dict(context, bindings=bindings,
                parents=[p for p in context['parents'] if p['parent_id'] in parent_ids],
                unbound_question_ids=[qid for qid in context['unbound_question_ids']
                                      if qid in question_ids])


def research_questions(detail, product, dimension):
    if dimension != "feature":
        return []
    brief = detail.plan.decision_brief
    text = getattr(brief, "decision_question", "") if brief else ""
    if not text and re.search(r"[?？]|是否|能否|如何|哪些|什么|怎样", detail.topic):
        text = detail.topic
    if not text:
        return []
    products = detail.plan.competitors
    grouped = _grouped_question_segments(text, products)
    result, seen, active_products = [], set(), []
    for line in grouped:
        question = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).strip()
        if not question or question in seen:
            continue
        mentioned = [
            name
            for name in products
            if re.search(
                r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
                if name.isascii()
                else re.escape(name),
                question,
                re.I,
            )
        ]
        if mentioned:
            active_products = mentioned
        if active_products and product not in active_products:
            continue
        seen.add(question)
        question_id = hashlib.sha256(
            json.dumps([product, dimension, question], ensure_ascii=False).encode()
        ).hexdigest()[:20]
        result.append({"question_id": f"question-{question_id}", "question": question})
    return result
