"""Canonical readable JSON for current question QA; legacy v5 codec stays separate."""

from __future__ import annotations

import json
from copy import deepcopy

from packages.research.evidence.snapshot_models import canonical_json

QUESTION_CONTEXT_FIELDS = frozenset(
    {
        "question_id",
        "question",
        "request_context",
        "answer",
        "visible_answer",
        "claims",
        "task_answers",
        "task_support_claim_ids",
        "publication_matches",
        "support_verified",
        "server_delivery_type",
        "task_semantic_contract",
        "coverage_contract",
        "source_scopes",
    }
)


def _json_value(value):
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("Review object keys must be strings")
        for child in value.values():
            _json_value(child)
    elif isinstance(value, list):
        for child in value:
            _json_value(child)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ValueError("Review context must be JSON")


def dumps(value):
    """Serialize the complete context without a model-side decoding protocol."""
    _json_value(value)
    return canonical_json(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate review JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite review JSON number: " + value)


def loads(raw, *, expected=None):
    """Reject ambiguous wire or any difference from the full server reconstruction."""
    value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    if raw != dumps(value):
        raise ValueError("Noncanonical review JSON")
    if expected is not None and raw != dumps(expected):
        raise ValueError("Review payload differs from server reconstruction")
    return value


def _v11_publication_row(row):
    """Remove repeated prose/witnesses, retaining complete source and task semantics."""
    row = deepcopy(row)
    from packages.agents.writer.task_evidence_package import CONTRACT, SELECTOR

    package = row.get(SELECTOR)
    if package is not None and package != CONTRACT:
        raise ValueError('Unknown final QA task package contract')
    if package:
        for claim in row.get('claims', ()):
            bindings = claim.get('source_span_bindings', ())
            if bindings:
                for key, binding_key in (('fact_ids', 'fact_id'), ('source_ids', 'source_id')):
                    if claim.get(key) == list(dict.fromkeys(b[binding_key] for b in bindings)):
                        claim.pop(key, None)
                for binding in bindings:
                    for key in ('span_id', 'fact_hash', 'source_path', 'start', 'end'):
                        binding.pop(key, None)
        for source in row.get('selected_source_context', ()):
            if source.get('value') == [source.get('quote')]:
                source.pop('value')
    answer = row.get('answer', {})
    visible = ' '.join(row.get('visible_answer', '').split())
    if answer.get('answer') and ' '.join(answer['answer'].split()) in visible:
        answer.pop('answer')
    for key in ('question', 'question_id'):
        if answer.get(key) == row.get(key):
            answer.pop(key, None)
    by_claim = {claim['id']: claim for claim in row.get('claims', ())}
    evidence = answer.get('evidence_spans')
    if evidence is not None and all(
        span.get('quote') == by_claim.get(span.get('claim_id'), {}).get('text')
        for span in evidence
    ):
        answer.pop('evidence_spans')
    for key in ('reason', 'basis_snapshot_id'):
        answer.pop(key, None)
    for binding in answer.get('subquestion_bindings', ()):
        binding.pop('support_digest', None)
    projection = row.get('structured_conclusions', {})
    entries = projection.get('entries', ())
    for key in ('verification_status', 'publication_status'):
        values = {entry.get(key) for entry in entries}
        if entries and len(values) == 1 and None not in values:
            projection[key] = values.pop()
            for entry in entries:
                entry.pop(key)
    for entry in entries:
        entry.pop('conclusion_id', None)
        if entry.get('question_id') == row.get('question_id'):
            entry.pop('question_id')
        relation = entry.get('source_relation', {})
        for key in ('candidate_ref', 'source_binding_sha256'):
            relation.pop(key, None)
        if relation.get('relation') == entry.get('relation'):
            relation.pop('relation', None)
        if relation.get('source_fact_text') == by_claim.get(entry.get('claim_id'), {}).get('text'):
            relation.pop('source_fact_text', None)
        cell = entry.get('task_cell', {})
        cell.pop('task_sha256', None)
        repeated = dict(task_id=entry.get('task_id'), observation=entry.get('observation'),
                        missing_fields=entry.get('missing_inputs'),
                        support_refs=relation.get('support_refs'))
        for key, value in repeated.items():
            if key in cell and cell[key] == value:
                cell.pop(key)
    return row


def final_review_batches(candidates, basis_hash, *, max_bytes, max_batches,
                         protocol="independent_questions_v7"):
    """Admit complete same-question items using the actual readable wire bytes."""
    from packages.agents.qa.question_reconciliation import MAX_FINDINGS

    if protocol not in {"independent_questions_v6", "independent_questions_v7",
                        "independent_questions_v8", "independent_questions_v9",
                        "independent_questions_v10", "independent_questions_v11"}:
        raise ValueError("Unsupported final QA wire protocol")
    targets = {"complete_finding_resolution", "canonical_clarification_delivery"}
    if protocol in {"independent_questions_v10", "independent_questions_v11"}:
        targets.add("supported_billing_limitation_delivery")
        targets.add('supported_sourced_limitation_delivery')
    if protocol in {"independent_questions_v8", "independent_questions_v9",
                    "independent_questions_v10", "independent_questions_v11"} and any(
        row.get("verification_target") not in targets
        for row in candidates
    ):
        raise ValueError("Final QA verification target missing or invalid")
    if protocol in {"independent_questions_v9", "independent_questions_v10",
                    "independent_questions_v11"} and any(
        row.get("review_scope") != {"kind": (
            "current_question" if row.get("independent_question_check") is True
            else "historical_finding")}
        for row in candidates
    ):
        raise ValueError("Final QA review scope missing or invalid")

    def payload(rows):
        if protocol == 'independent_questions_v11':
            rows = [_v11_publication_row(row) for row in rows]
        result = dict(version=1, basis_hash=basis_hash, findings=rows)
        if len(rows) < 2 or any("context_id" in row for row in rows):
            return result
        context_fields = QUESTION_CONTEXT_FIELDS
        if protocol == 'independent_questions_v11':
            context_fields = context_fields | {
                'visible_observations', 'selected_source_context', 'structured_conclusions',
                'structured_conclusions_contract', 'conclusion_revision_sha256',
            }
        contexts = [
            {key: value for key, value in row.items() if key in context_fields}
            for row in rows
        ]
        if any(dumps(context) != dumps(contexts[0]) for context in contexts[1:]):
            return result
        # A single named complete question context is directly readable. No
        # recursive references, string table or cross-question sharing exists.
        result["question_contexts"] = {"current": contexts[0]}
        result["findings"] = [
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key not in context_fields or key == "question_id"
                },
                "context_id": "current",
            }
            for row in rows
        ]
        return result

    def fits(rows):
        return (
            len(rows) <= MAX_FINDINGS
            and len(("\nJSON:\n" + dumps(payload(rows))).encode()) <= max_bytes
        )

    groups, omitted = [], []
    for row in candidates:
        for group in groups:
            if (group[0]["question_id"] == row["question_id"]
                    and (protocol not in {"independent_questions_v8", "independent_questions_v9",
                                          "independent_questions_v10", "independent_questions_v11"}
                         or group[0]["verification_target"] == row["verification_target"])
                    and fits([*group, row])):
                group.append(row)
                break
        else:
            if len(groups) < max_batches and fits([row]):
                groups.append([row])
            else:
                omitted.append(row["issue_id"])
    return [payload(group) for group in groups], omitted
