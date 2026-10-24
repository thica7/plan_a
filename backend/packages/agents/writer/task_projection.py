"""Publish reviewed local task deductions without granting whole-question coverage."""

from __future__ import annotations

import hashlib
import json

from packages.agents.writer.task_protocol import CONTRACT, FOCUSES, task_atom_reasons
from packages.research.question_scope import research_questions


def _review_matches(detail, audit, task, claim, *, handoff_version=None, dispatches=()):
    from packages.agents.writer.dimension_writer import parse_json
    from packages.research.evidence.report_claims import ClaimReview
    from packages.research.question_delivery import _expand_text_refs

    spans = [s for s in detail.trace_spans if s.id == task.get("review_span_id")]
    if len(spans) != 1:
        return False
    span = spans[0]
    if (
        (span.kind, span.agent, span.subagent, span.name, span.status)
        != ("llm", "qa", f"{audit.competitor}/{audit.dimension}", "dimension_task_review", "ok")
        or type(span.metadata.get("llm_transport_attempts")) is not int
        or span.metadata["llm_transport_attempts"] <= 0
        or hashlib.sha256(span.full_input.encode()).hexdigest() != task.get("review_input_sha256")
    ):
        return False
    payload = _expand_text_refs(parse_json(span.full_input.split("\nJSON:\n", 1)[1]))
    from packages.agents.writer.task_execution import (
        has_task_handoff_system,
        task_request_context_version,
    )
    if (has_task_handoff_system(span.full_input) or handoff_version is not None
            or 'task_handoff_version' in payload or 'request_context' in payload):
        from packages.agents.writer.task_execution import HANDOFF_VERSION
        from packages.research.question_scope import question_request_context, questions_match_scope
        if (type(handoff_version) is not int or handoff_version != HANDOFF_VERSION
                or payload.get('task_handoff_version') != HANDOFF_VERSION
                or not questions_match_scope(detail, audit.competitor, audit.dimension,
                                             payload.get('questions'))
                or task['question_id'] not in {q['question_id'] for q in payload['questions']}
                or payload.get('request_context') != question_request_context(
                    detail, audit.competitor, audit.dimension, payload['questions'],
                    version=task_request_context_version(span.full_input))):
            return False
    from packages.agents.writer.task_execution import (
        ADVISORY_KEYS,
        ADVISORY_REVIEW_SYSTEM_IDENTITY,
        HANDOFF_SYSTEM_IDENTITY,
        has_two_phase_generation_system,
    )
    advisory_review = span.full_input.startswith(
        HANDOFF_SYSTEM_IDENTITY + ADVISORY_REVIEW_SYSTEM_IDENTITY)
    generations, two_phase, parent_v2 = [], False, False
    for dispatch in dispatches:
        if task['task_id'] not in dispatch['task_ids']:
            continue
        for generation in detail.trace_spans:
            if (generation.id == dispatch['span_id']
                    and generation.kind == 'llm' and generation.agent == 'writer'
                    and generation.subagent == f'{audit.competitor}/{audit.dimension}'
                    and generation.name == 'dimension_task_generation'
                    and generation.status == 'ok'
                    and type(generation.metadata.get('llm_transport_attempts')) is int
                    and generation.metadata['llm_transport_attempts'] > 0
                    and hashlib.sha256(generation.full_input.encode()).hexdigest()
                    == dispatch['full_input_sha256']):
                two_phase |= has_two_phase_generation_system(generation.full_input)
                parent_v2 |= task_request_context_version(generation.full_input) == 2
                generations.append(_expand_text_refs(parse_json(
                    generation.full_input.split('\nJSON:\n', 1)[1])))
    if two_phase and not advisory_review:
        return False
    if parent_v2 and task_request_context_version(span.full_input) != 2:
        return False
    if advisory_review:
        # Final QA separately rebuilds both inputs against current producers.
        keys = (*ADVISORY_KEYS, 'upstream_projection_version', 'upstream_context_gaps')
        if (not generations or payload.get('upstream_projection_version') != 2
                or any({k: payload[k] for k in keys if k in payload}
                       != {k: row[k] for k in keys if k in row} for row in generations)):
            return False
    assignments = [a for a in payload["task_assignments"] if a["task_id"] == task["task_id"]]
    expected = {
        k: task[k]
        for k in ("task_id", "question_id", "question_quote", "focus", "claim_id", "claim_digest")
    }
    expected["consumption_id"] = audit.consumption_id
    if task.get("resource") is not None:
        expected["resource"] = task["resource"]
    if assignments != [expected]:
        return False
    claim_rows = [c for c in payload["claims"] if c["id"] == claim.id]
    raw = parse_json(span.full_output)
    decisions = [
        d for d in raw["decisions"] if isinstance(d, dict) and d.get("task_id") == task["task_id"]
    ]
    reviews = [r for r in raw["reviews"] if isinstance(r, dict) and r.get("claim_id") == claim.id]
    audited = next(a for a in audit.claims if a.claim.id == claim.id)
    return (
        len(claim_rows) == 1
        and claim_rows[0]["text"] == claim.text
        and decisions == [task["decision"]]
        and len(reviews) == 1
        and ClaimReview.model_validate(reviews[0]) == audited.review
    )


def reviewed_task_results(detail, audit):
    if audit.claim_review_version != 3:
        return ()
    scope = f"{audit.competitor}/{audit.dimension}"
    uses = [u for u in detail.evidence_consumptions if u.id == audit.consumption_id]
    if (
        len(uses) != 1
        or uses[0].status not in {"validated", "reused"}
        or uses[0].snapshot_id != detail.evidence_snapshot_id
        or uses[0].validated_snapshot_id != detail.evidence_snapshot_id
        or (uses[0].run_id, uses[0].workspace_id, uses[0].project_id)
        != (detail.id, detail.workspace_id, detail.project_id)
        or (uses[0].agent, uses[0].competitor, uses[0].dimension)
        != ("writer", audit.competitor, audit.dimension)
    ):
        return ()
    receipts = []
    for span in detail.trace_spans:
        if span.name != "question_task_delivery":
            continue
        try:
            row = json.loads(span.full_output)
        except (ValueError, TypeError):
            continue
        if isinstance(row, dict) and row.get("consumption_id") == audit.consumption_id:
            receipts.append((span, row))
    if len(receipts) != 1:
        return ()
    span, receipt = receipts[0]
    if (
        (span.kind, span.agent, span.subagent, span.status) != ("tool", "writer", scope, "ok")
        or receipt.get("contract") != CONTRACT
        or receipt.get("snapshot_id") != detail.evidence_snapshot_id
    ):
        return ()
    questions = {
        q["question_id"]: q["question"]
        for q in research_questions(detail, audit.competitor, audit.dimension)
    }
    supported = {a.claim.id: a.claim for a in audit.claims if a.status == "supported"}
    result, seen = [], set()
    for task in receipt.get("tasks", ()):
        try:
            identity = [
                CONTRACT,
                scope,
                task["question_id"],
                task["question_quote"],
                task["focus"],
                task.get("resource"),
            ]
            expected = (
                "task-"
                + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
            )
            claim = supported[task["claim_id"]]
            decision = task["decision"]
            if (
                task["task_id"] != expected
                or expected in seen
                or task["state"] != "supported"
                or task["focus"] not in FOCUSES
                or not task["question_quote"]
                or task["question_quote"] not in questions[task["question_id"]]
                or decision["task_id"] != expected
                or decision["claim_id"] != claim.id
                or decision["task_fulfilled"] is not True
                or decision.get("conclusion") not in {"yes", "no", "depends", "not_applicable"}
                or decision.get("relation")
                not in {
                    "direct",
                    "explicit_negative",
                    "upper_bound",
                    "resource_scope",
                    "permission_entailment",
                    "destructive_effect",
                }
                or task["claim_digest"]
                != hashlib.sha256(claim.model_dump_json().encode()).hexdigest()
                or not set(claim.fact_ids) <= set(uses[0].fact_ids)
                or not set(claim.source_ids) <= set(uses[0].source_ids)
                or task_atom_reasons(task, claim.text, kind=claim.kind)
                or not _review_matches(detail, audit, task, claim,
                    handoff_version=receipt.get('task_handoff_version'),
                    dispatches=receipt.get('dispatches', ()))
            ):
                continue
            seen.add(expected)
            result.append(dict(task, question=questions[task["question_id"]]))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            continue
    return tuple(result)


def projected_task_claim_ids(detail, audit):
    return {row["claim_id"] for row in reviewed_task_results(detail, audit)}
