"""Canonical readable JSON for current question QA; legacy v5 codec stays separate."""

from __future__ import annotations

import json

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


def final_review_batches(candidates, basis_hash, *, max_bytes, max_batches,
                         protocol="independent_questions_v7"):
    """Admit complete same-question items using the actual readable wire bytes."""
    from packages.agents.qa.question_reconciliation import MAX_FINDINGS

    if protocol not in {"independent_questions_v6", "independent_questions_v7",
                        "independent_questions_v8", "independent_questions_v9"}:
        raise ValueError("Unsupported final QA wire protocol")
    if protocol in {"independent_questions_v8", "independent_questions_v9"} and any(
        row.get("verification_target") not in {
            "complete_finding_resolution", "canonical_clarification_delivery"}
        for row in candidates
    ):
        raise ValueError("Final QA verification target missing or invalid")
    if protocol == "independent_questions_v9" and any(
        row.get("review_scope") != {"kind": (
            "current_question" if row.get("independent_question_check") is True
            else "historical_finding")}
        for row in candidates
    ):
        raise ValueError("Final QA review scope missing or invalid")

    def payload(rows):
        result = dict(version=1, basis_hash=basis_hash, findings=rows)
        if len(rows) < 2 or any("context_id" in row for row in rows):
            return result
        contexts = [
            {key: value for key, value in row.items() if key in QUESTION_CONTEXT_FIELDS}
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
                    if key not in QUESTION_CONTEXT_FIELDS or key == "question_id"
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
                    and (protocol not in {"independent_questions_v8", "independent_questions_v9"}
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
