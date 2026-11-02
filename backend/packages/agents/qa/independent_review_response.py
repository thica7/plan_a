"""Strict v7 envelope and isolated, unrepaired final-QA decision rows."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.agents.qa.question_reconciliation import MAX_FINDINGS, _Decision


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    basis_hash: str
    reviews: list[object] = Field(max_length=MAX_FINDINGS)


class _DeliveryGap(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal[
        "unanswered_branch", "unsupported_rule", "wrong_source", "condition_omitted",
        "clarification_omitted", "input_already_given", "publication_changed",
        "unsupported_premise",
    ]
    obligation_ref: str = Field(min_length=1, max_length=180)


class _DeliveryDecision(_Decision):
    delivery_gaps: list[_DeliveryGap] = Field(max_length=8)


@dataclass
class ReviewRows:
    reviews: dict[str, _Decision]
    invalid_issue_ids: list[str]
    missing_issue_ids: list[str]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate final QA JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite final QA JSON number")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        return _nonfinite(value)
    return parsed


def parse_response(response, basis_hash, candidates, *, delivery_contract=False):
    """Keep valid peers; ambiguous envelopes or batch identities reject globally."""
    value = json.loads(
        response, object_pairs_hook=_unique_object, parse_constant=_nonfinite,
        parse_float=_finite_float)
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        raise ValueError("Final QA envelope version must be an integer")
    parsed = _Envelope.model_validate(value)
    if parsed.basis_hash != basis_hash:
        raise ValueError("Final QA envelope identity mismatch")
    returned = set()
    for row in parsed.reviews:
        issue_id = row.get("issue_id") if isinstance(row, dict) else None
        if isinstance(issue_id, str):
            if issue_id in returned or issue_id not in candidates:
                raise ValueError("Duplicate or foreign final QA finding")
            returned.add(issue_id)
    reviews = {}
    for row in parsed.reviews:
        candidate = candidates.get(row.get("issue_id"), {}) if isinstance(row, dict) else {}
        delivery = delivery_contract and "delivery_obligations" in candidate
        try:
            review = (_DeliveryDecision if delivery else _Decision).model_validate(row)
        except ValidationError:
            continue
        candidate = candidates[review.issue_id]
        if delivery:
            obligations = {o["ref"]: o["gap_kinds"] for o in candidate["delivery_obligations"]}
            gaps = review.delivery_gaps
            if (any(g.obligation_ref not in obligations
                    or g.kind not in obligations[g.obligation_ref] for g in gaps)
                    or len({(g.kind, g.obligation_ref) for g in gaps}) != len(gaps)
                    or (review.disposition == "keep" or not review.finding_fully_addressed
                        or bool(review.remaining_gaps)) != bool(gaps)):
                continue
        if (review.question_id == candidate["question_id"]
                and review.support_digest == candidate["support_digest"]
                and len(review.claim_ids) == len(set(review.claim_ids))
                and set(review.claim_ids) == set(candidate["answer"]["claim_ids"])):
            reviews[review.issue_id] = review
    return ReviewRows(
        reviews=reviews,
        invalid_issue_ids=[key for key in candidates if key in returned and key not in reviews],
        missing_issue_ids=[key for key in candidates if key not in returned],
    )
