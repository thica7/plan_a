"""Versioned single-claim review inputs and exact selected-support witnesses."""

from __future__ import annotations

import hashlib
import json
import re

from packages.agents.writer.task_execution import ADVISORY_KEYS
from packages.research.evidence.snapshot_models import canonical_json

REVIEW_PROJECTION_VERSION = 2
REVIEW_SYSTEM_IDENTITY = "Selected support atomic review v2. "
SELECTED_SUPPORT_SYSTEM = (
    "For this v2 protocol, extend the review schema above with support_witnesses. "
    "Review only the ONE supplied claim against its complete selected support_quotes and "
    "operation conditions. Keep every required check, whole-assertion support and atomicity "
    "check. Questions and the complete parent request are hypothetical inputs, never product "
    "evidence. constraint_context only restricts the selected support. upstream_identity_refs "
    "identify server-verified dependencies; their product content was NOT supplied to you. "
    "A supported verdict additionally requires support_witnesses, a list of objects with "
    "exactly support_index (zero-based integer, never boolean) and quote (nonempty exact "
    "excerpt from claims[0].support_quotes at that index). Include a witness for EVERY selected "
    "support quote. Never cite another claim, request premise, restriction or upstream advice "
    "as selected support. Excerpts do not replace full semantic review of the original support "
    "and its conditions. Unsupported or uncertain reviews may omit witnesses. "
    "External restrictions contain identities and typed dates only, never additional support. "
    "requires_complete_support means a potentially applicable condition was not fully supplied "
    "within the selected support/operation conditions; do not return supported for that claim. "
    'Example extension: "support_witnesses":[{"support_index":0,"quote":"exact excerpt"}]. '
)


def checked_review_projection_version(value):
    if type(value) is not int or value not in {1, REVIEW_PROJECTION_VERSION}:
        raise ValueError("Atomic review projection version changed")
    return value


def review_identity_metadata(metadata):
    """Keep producer identities without sending their fallible product assertions."""
    fields = ("kind", "competitor", "dimension", "snapshot_id", "producer_hash")
    return {
        **{key: value for key, value in metadata.items() if key not in ADVISORY_KEYS},
        "review_projection_version": REVIEW_PROJECTION_VERSION,
        "upstream_identity_refs": {
            key: {field: metadata[key][field] for field in fields}
            for key in ADVISORY_KEYS
            if key in metadata
        },
    }


def atomic_review_payload(claims, view, questions, plans, metadata, *, review_projection_version=2):
    from packages.agents.writer.dimension_writer import review_payload

    version = checked_review_projection_version(review_projection_version)
    if version == 2:
        if len(claims) != 1:
            raise ValueError("Selected-support review requires one claim")
        ids = {claim.id for claim in claims}
        plans = [
            dict(plan, claim_ids=[cid for cid in plan["claim_ids"] if cid in ids]) for plan in plans
        ]
        metadata = review_identity_metadata(metadata)
    payload = dict(
        review_payload(claims, view, review_version=3, questions=questions, plans=plans),
        **metadata,
        question_answer_plans=plans,
    )
    if version == 2:
        payload["constraint_context"] = isolated_review_constraints(payload)
    return payload


def _restriction_unrelated(kind, row, claim_text):
    """Only reuse existing finite scope exclusions; unknown scope stays unresolved."""
    if kind == "creation_date":
        from packages.agents.writer.answer_action_scope import _ACTIONS
        from packages.research.evidence.operations import OPERATIONS
        from packages.research.evidence.temporal_conditions import (
            _SAME_RIGHTS,
            _predicate_keys,
            _unresolved_cross_language_roles,
        )

        source = _predicate_keys(row.get("quote", ""), row.get("actor"))
        claim = _predicate_keys(claim_text, row.get("actor"))
        patterns = {**_ACTIONS, **{key: value[1] for key, value in OPERATIONS.items()}}

        def action_families(keys):
            families = set()
            for key in keys:
                known = {
                    name
                    for name, pattern in patterns.items()
                    if re.match(pattern, key.replace(":", " "), re.I)
                }
                if not known:
                    return set()
                families.update(known)
            return families

        source_actions, claim_actions = action_families(source), action_families(claim)
        return bool(
            source_actions
            and claim_actions
            and not source_actions.intersection(claim_actions)
            and not _SAME_RIGHTS.search(row.get("quote", ""))
            and not _unresolved_cross_language_roles(source, claim)
        )
    if kind == "authentication_access":
        from packages.research.evidence.source_exceptions import _ACCESS

        return not _ACCESS.search(claim_text)
    if kind == "retained_copy":
        return not re.search(
            r"delet|remov|copy|sync|access|删除|移除|副本|同步|访问|看不到", claim_text, re.I
        )
    if kind == "exception_list":
        return not re.search(r"unshar|取消共享", claim_text, re.I)
    return False


def isolated_review_constraints(payload):
    """Never expose a parent permission through a restriction's original prose.

    Full canonical facts still undergo publication/replay guards. A condition
    outside the selected originals cannot become a second model support pool;
    unresolved applicable conditions instead block a positive local review.
    """
    claim = payload["claims"][0]
    selected = list(claim.get("support_quotes", ()))
    operation = claim.get("operation_binding", {})
    selected.extend(operation.get("condition_evidence", ()))
    selected.extend(row["quote"] for row in operation.get("prerequisites", ()))
    selected.extend(
        option for group in operation.get("condition_groups", ()) for option in group["options"]
    )

    def project(row, kind, *, force_unresolved=False):
        result = dict(
            kind=kind, restriction_sha256=hashlib.sha256(canonical_json(row).encode()).hexdigest()
        )
        if force_unresolved or not isinstance(row, dict):
            return dict(result, requires_complete_support=True)
        quote = row.get("quote")
        if isinstance(quote, str) and quote and any(quote in text for text in selected):
            result["quote"] = quote
        else:
            result["requires_complete_support"] = not _restriction_unrelated(
                kind, row, claim["text"]
            )
        if kind == "creation_date":
            result.update(
                {key: row[key] for key in ("date_subject", "cutoff", "relation", "actor")}
            )
        return result

    result = []
    for row in payload.get("constraint_context", ()):
        qualifiers = row.get("qualifiers", {})
        links = qualifiers.get("source_condition_links", [])
        projected_links = (
            [
                project(
                    link,
                    "plan_dependency"
                    if isinstance(link, dict) and link.get("kind") == "plan_dependency"
                    else "unrecognized",
                )
                for link in links
            ]
            if isinstance(links, list)
            else [project(links, "unrecognized", force_unresolved=True)]
        )
        result.append(
            dict(
                fact_id=row["fact_id"],
                qualifiers={"source_condition_links": projected_links} if projected_links else {},
                temporal_conditions=[
                    project(item, "creation_date") for item in row.get("temporal_conditions", ())
                ],
                source_exceptions=[
                    project(item, item["kind"]) for item in row.get("source_exceptions", ())
                ],
            )
        )
    return result


def incomplete_review_restrictions(payload):
    for row in payload.get("constraint_context", ()):
        restrictions = [
            *row.get("temporal_conditions", ()),
            *row.get("source_exceptions", ()),
            *row.get("qualifiers", {}).get("source_condition_links", ()),
        ]
        if any(item.get("requires_complete_support") is True for item in restrictions):
            return True
    return False


def validated_review_payload(raw, expected):
    """Bind the complete actual encoding, including every reference-table member."""
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.research.question_delivery import _expand_text_refs

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Atomic review duplicate JSON member")
            result[key] = value
        return result

    encoded = json.loads(raw, object_pairs_hook=unique_object)
    if canonical_json(encoded) != canonical_json(json.loads(compact_prompt_json(expected))):
        raise ValueError("Atomic review encoding closure changed")
    return _expand_text_refs(encoded)


def selected_support_witness_valid(witness, selected_quotes):
    """Validate provenance only; exact overlap does not establish entailment."""
    if not isinstance(witness, dict) or set(witness) != {"support_index", "quote"}:
        return False
    index, quote = witness["support_index"], witness["quote"]
    return (
        type(index) is int
        and isinstance(selected_quotes, list)
        and 0 <= index < len(selected_quotes)
        and isinstance(selected_quotes[index], str)
        and isinstance(quote, str)
        and bool(quote.strip())
        and quote in selected_quotes[index]
    )


def witnessed_review_row(row, selected_quotes):
    """Check the v2 extension before passing the original schema to its strict parser."""
    witnesses = row.get("support_witnesses", [])
    if not isinstance(witnesses, list) or any(
        not selected_support_witness_valid(item, selected_quotes) for item in witnesses
    ):
        return None
    if row.get("verdict") == "supported" and (
        not selected_quotes
        or {item["support_index"] for item in witnesses} != set(range(len(selected_quotes)))
    ):
        return None
    return {key: value for key, value in row.items() if key != "support_witnesses"}
