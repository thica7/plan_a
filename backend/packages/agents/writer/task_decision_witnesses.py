"""Rebuild two finite task decisions from current producers and real transports.

TaskDecisionContext is ephemeral server input, not a deserializable credential.
Its expected_inputs MUST come from the current production payload builders (or
the already validated replay loop), never from copying a stored span. Callers
must authenticate the current consumption/snapshot before constructing it.
Neither a supported claim review nor any digest proves target fulfillment: only
the separate v6 ANSWER transport may issue a decision credential. Source and
request prose remain data throughout.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from packages.agents.writer.atomic_claim_review import validated_review_payload
from packages.research.evidence.answer_coverage_models import DecisionCredential
from packages.research.evidence.report_claims import AuditedReportClaim, claim_review_reasons
from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json
from packages.research.evidence.source_spans import projected_source_facts
from packages.research.question_scope import narrow_request_context

WitnessKind = Literal["quantity_excess", "resource_non_entailment"]
APPROVED_QUANTITY_CORE_POLICY = 'approved_quantity_core-v1'


@dataclass(frozen=True)
class TaskDecisionContext:
    consumption_id: str
    snapshot_id: str
    competitor: str
    dimension: str
    questions: tuple[dict, ...]
    request_context: dict
    facts: tuple[EvidenceFact, ...]
    audited_claims: tuple[AuditedReportClaim, ...]
    compact: dict
    trace_spans: tuple[Any, ...]
    expected_inputs: Mapping[str, tuple[str, dict]]


class DecisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_ref: str
    question_id: str
    task_id: str
    claim_id: str
    witness_kind: WitnessKind
    witness: dict
    evidence_refs: tuple[str, ...]
    scenario_refs: tuple[str, ...]
    binding_sha256: str
    task: dict
    claim: dict
    sources: tuple[dict, ...]

    def review_payload(self, *, projection_version=1):
        """Keep full server bindings; v2 reuses the published claim's semantics."""
        if type(projection_version) is not int or projection_version not in {1, 2}:
            raise ValueError("Decision candidate projection unknown")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if projection_version == 2:
            payload.pop("claim")
            payload["sources"] = [
                {key: value for key, value in source.items()
                 if key in {"source_ref", "fact_id", "source_id", "quote"}}
                for source in payload["sources"]
            ]
        return payload


def candidate_projection_version(payload):
    """An absent selector is the original v6 wire; only explicit integer 2 is new."""
    if "decision_candidate_projection_version" not in payload:
        return 1
    version = payload["decision_candidate_projection_version"]
    if type(version) is not int or version != 2:
        raise ValueError("Decision candidate projection unknown")
    return version


def decision_selection_policy(payload):
    """Missing is legacy; only an explicit known policy selects new delivery."""
    if 'decision_selection_policy' not in payload:
        return None
    policy = payload['decision_selection_policy']
    if type(policy) is not str or policy != APPROVED_QUANTITY_CORE_POLICY:
        raise ValueError('Decision selection policy unknown')
    return policy


def _digest(value):
    text = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(text.encode()).hexdigest()


def _unique_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Decision duplicate JSON member")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique)


def _transport(context, dispatch):
    from packages.agents.writer.question_atomic_delivery import GENERATION_NAME
    from packages.research.question_delivery import _expand_text_refs

    spans = [span for span in context.trace_spans if span.id == dispatch["span_id"]]
    if len(spans) != 1 or dispatch["span_id"] not in context.expected_inputs:
        raise ValueError("Decision transport or current producer missing")
    span = spans[0]
    system, expected = context.expected_inputs[span.id]
    prefix, separator, raw = span.full_input.partition("\nJSON:\n")
    if (
        not system
        or not separator
        or prefix.rstrip("\n") != system
        or (span.kind, span.status, span.name, span.agent, span.subagent)
        != (
            "llm",
            "ok",
            dispatch["name"],
            "writer" if span.name == GENERATION_NAME else "qa",
            f"{context.competitor}/{context.dimension}",
        )
        or type(span.metadata.get("llm_transport_attempts")) is not int
        or span.metadata["llm_transport_attempts"] <= 0
        or _digest(span.full_input) != dispatch["full_input_sha256"]
        or _digest(span.full_output) != dispatch["full_output_sha256"]
    ):
        raise ValueError("Decision transport changed")
    validated_review_payload(raw, expected)
    payload = _expand_text_refs(_unique_json(raw))
    known = {q["question_id"]: q for q in context.questions}
    ids = dispatch["question_ids"]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or not set(ids) <= known.keys()
        or payload.get("questions") != [known[qid] for qid in ids]
        or payload.get("consumption_id") != context.consumption_id
        or payload.get("snapshot_id") != context.snapshot_id
        or payload.get("segment_competitor") != context.competitor
        or payload.get("dimension") != context.dimension
        or payload.get("request_context") != narrow_request_context(context.request_context, ids)
    ):
        raise ValueError("Decision question, scope or parent changed")
    return span, payload


def _task_identity(task):
    # Capacity and advisory ranks legitimately change on the single repair.
    return {
        key: value
        for key, value in task.items()
        if key not in {"max_claims", "advisory_support_refs", "support_refs"}
    }


def _rebuild(context):
    from packages.agents.writer.question_atomic_delivery import (
        GENERATION_NAME,
        REVIEW_NAME,
        merge_generation_plan,
        missing_task_results,
        parse_atomic_generation,
        parse_atomic_reviews,
    )

    compact = context.compact
    if (
        compact.get("generation_projection_version") != 5
        or compact.get("review_projection_version") != 3
        or compact.get("consumption_id") != context.consumption_id
        or compact.get("snapshot_id") != context.snapshot_id
    ):
        raise ValueError("Decision requires authenticated GEN5 and REVIEW3")
    if (
        len({q["question_id"] for q in context.questions}) != len(context.questions)
        or context.request_context.get("version") != 2
        or context.request_context.get("purpose") != "request_only_not_evidence"
    ):
        raise ValueError("Decision canonical request missing")
    parents = {row["parent_id"]: row["text"] for row in context.request_context["parents"]}
    bindings = context.request_context["bindings"]
    if len(parents) != len(context.request_context["parents"]) or any(
        len(
            [
                b
                for b in bindings
                if b["question_id"] == q["question_id"]
                and b["parent_id"] in parents
                and parents[b["parent_id"]]
            ]
        )
        != 1
        for q in context.questions
    ):
        raise ValueError("Decision parent binding missing or ambiguous")
    tasks, generated, plans, reviewed, dispatch_ids = {}, {}, {}, {}, set()
    initial_questions, repaired_questions = set(), set()
    for dispatch in compact["dispatches"]:
        if dispatch["name"] not in {GENERATION_NAME, REVIEW_NAME}:
            continue
        if dispatch["span_id"] in dispatch_ids:
            raise ValueError("Decision dispatch repeated")
        dispatch_ids.add(dispatch["span_id"])
        span, payload = _transport(context, dispatch)
        if dispatch["name"] == GENERATION_NAME:
            attempt = dispatch.get("attempt")
            ids = dispatch["question_ids"]
            if (
                type(attempt) is not int
                or attempt not in {0, 1}
                or len(ids) != 1
                or not attempt
                and ids[0] in initial_questions
                or attempt
                and (ids[0] not in initial_questions or ids[0] in repaired_questions)
                or payload.get("generation_projection_version") != 5
            ):
                raise ValueError("Decision generation attempt changed")
            (repaired_questions if attempt else initial_questions).add(ids[0])
            for task in payload["generation_tasks"]:
                tid = task["task_id"]
                if task["question_id"] != ids[0]:
                    raise ValueError("Decision task question changed")
                if attempt:
                    if tid not in tasks or _task_identity(tasks[tid]) != _task_identity(task):
                        raise ValueError("Decision repair task identity changed")
                elif tid in tasks:
                    raise ValueError("Decision initial task repeated")
                else:
                    tasks[tid] = task
            try:
                claims, _, parsed = parse_atomic_generation(
                    span.full_output,
                    payload,
                    SimpleNamespace(facts=context.facts),
                    SimpleNamespace(id=context.consumption_id),
                )
            except (ValueError, TypeError, AttributeError):
                from packages.research.evidence.source_exceptions import _missing_question_inputs

                # Match the production GEN5 replay's missing-task outcome.
                # Transport and task identity checks above remain outside this
                # parser-only recovery, as do the receipt comparisons below.
                claims = []
                parsed = [dict(
                    question_id=ids[0], claim_ids=[],
                    missing_fields=list(_missing_question_inputs(payload['questions'][0]['question'])),
                    task_results=missing_task_results(payload),
                )]
            if dispatch["claim_ids"] != [c.id for c in claims]:
                raise ValueError("Decision generation claim identity changed")
            if dispatch["fact_ids"] != sorted(
                row["id"] for row in payload["evidence_view"]["facts"]
            ):
                raise ValueError("Decision dispatched originals changed")
            merge_generation_plan(plans.setdefault(ids[0], {}), parsed[0], attempt=attempt)
            for claim in claims:
                if claim.id in generated:
                    raise ValueError("Decision generated claim repeated")
                generated[claim.id] = claim
        else:
            claim_ids = dispatch["claim_ids"]
            if len(claim_ids) != 1 or claim_ids[0] not in generated:
                raise ValueError("Decision independent review has no generated claim")
            cid = claim_ids[0]
            if cid in reviewed or payload.get("review_projection_version") != 3:
                raise ValueError("Decision review identity changed")
            claim = generated[cid]
            (row,) = payload["claims"]
            # Existing review projection may narrow operation condition_evidence;
            # its complete current payload is already validated above. These two
            # decision types additionally require literal source-span bindings.
            if any(
                row.get(key) != value
                for key, value in claim.model_dump(mode="json").items()
                if key != "operation_binding"
            ):
                raise ValueError("Decision reviewed claim changed")
            try:
                reviews = parse_atomic_reviews(
                    span.full_output, [claim], payload=payload, review_projection_version=3
                )
            except (ValueError, TypeError, AttributeError):
                # An authenticated malformed model response reviews nothing;
                # a supposedly supported audit still fails the equality below.
                reviews = []
            reviewed[cid] = (reviews[0] if len(reviews) == 1 else None, dispatch)
    expected_plans = {
        row["question_id"]: row
        for row in compact["question_answer_plans"]
        if row["question_id"] in initial_questions
    }
    if len(expected_plans) != len(plans) or any(
        any(expected_plans[qid].get(key) != value for key, value in plan.items())
        for qid, plan in plans.items()
    ):
        raise ValueError("Decision merged task plan changed")
    by_claim = {}
    for qid, plan in plans.items():
        for result in plan.get("task_results", ()):
            tid = result["task_id"]
            if tid not in tasks or tasks[tid]["question_id"] != qid:
                raise ValueError("Decision merged task identity changed")
            for cid in result.get("claim_ids", ()):
                if cid in by_claim or cid not in plan["claim_ids"] or cid not in generated:
                    raise ValueError("Decision task claim mapping changed")
                by_claim[cid] = tasks[tid]
    for audited in context.audited_claims:
        if audited.status == "supported" and (
            audited.review is None
            or audited.claim.id not in reviewed
            or reviewed[audited.claim.id][0] != audited.review
        ):
            raise ValueError("Decision supported review missing or changed")
    return generated, by_claim, reviewed


def _quantity_witness(task, source, question, competitor, claim_text):
    from packages.agents.writer.subquestion_premises import (
        _COUNT,
        _RESTATEMENT_SCOPE,
        _count_actions,
        _count_clause,
        _count_occurrences,
        _counts,
        _finite_scope_matches,
    )

    prop = task.get("request_property")
    if prop not in {"people_limit", "container_limit"}:
        return None
    identity = _RESTATEMENT_SCOPE.match(source)
    if not identity or (
        identity["product"] and identity["product"].strip().casefold() != competitor.casefold()
    ):
        return None
    # This is a finite grammar for an unconditional literal maximum, not a
    # classifier of the inference's wording. Unknown tails/conditions stay out.
    predicate = source[identity.end() :]
    if not re.fullmatch(
        r"\s+(?:offer both users all the core features of Password Manager "
        r"and secure data sharing in"
        r"|support (?:secure )?data sharing in|allow (?:secure )?data sharing (?:for|in))\s+"
        rf"(?:up to|at most|a maximum of)\s+{_COUNT}\s+"
        r"(?:users?|people|collections?|containers?|vaults?)\.?",
        predicate,
        re.I,
    ):
        return None
    source_counts = _counts(source, upper=True)
    required = _counts(task["question_quote"])
    if len(source_counts) != 1 or len(required) != 1:
        return None
    unit, maxima = next(iter(source_counts.items()))
    numbers = required.get(unit, ())
    actions = [
        _count_actions(_count_clause(question, match))
        for key, number, match in _count_occurrences(question)
        if key == unit and number in numbers
    ]
    if (
        len(maxima) != 1
        or len(numbers) != 1
        or numbers[0] <= maxima[0]
        or (prop == "people_limit") != (unit == "people")
        or _count_actions(source) != {"share"}
        or not actions
        or any(action != {"share"} for action in actions)
        or not _finite_scope_matches(question, source)
        or re.search(r"\b(?:or|either)\b|或", question, re.I)
    ):
        return None
    plan = identity["plan"]
    if not re.search(rf"(?<![A-Za-z]){re.escape(plan)}\s*(?:organizations?|组织)", question, re.I):
        return None
    # A claim review cannot reconcile explicit incompatible numbers or units.
    # Missing/implied applications still belong to independent target review.
    if any(
        key != unit or value not in {maxima[0], numbers[0]}
        for key, value, _ in _count_occurrences(claim_text)
    ):
        return None
    if any(
        key != unit or any(value != maxima[0] for value in values)
        for key, values in _counts(claim_text, upper=True).items()
    ):
        return None
    return dict(unit=unit, maximum=maxima[0], required=numbers[0], operation="share")


def _resource_witness(task, source, claim, question):
    from packages.agents.writer.subquestion_premises import _NEGATIVE, _scope_objects
    from packages.research.evidence.source_exceptions import _ACCESS

    # The branch itself must name two resources. Parent context can resolve the
    # scenario but cannot convert a billing branch into a permission question.
    def names(text):
        return tuple(
            dict.fromkeys(
                re.findall(r"(?<![A-Za-z0-9_])([A-Z](?:[0-9]{1,3})?)(?![A-Za-z0-9_])", text)
            )
        )

    resources = names(task["question_quote"])
    claim_resources = names(claim.text)
    if len(resources) != 2 or set(claim_resources) != set(resources) or _ACCESS.search(claim.text):
        return None
    # A positive distributive rule is required; absence of a connection proves
    # nothing. The independent ANSWER still checks the exact target predicate.
    rule = re.fullmatch(
        r"(?:Because an (?P<prefix_role>[a-z]+) is a (?P<prefix_scope>board|resource|project) "
        r"member permission it isn't currently possible to set a user as an (?P=prefix_role) "
        r"at the\s+Workspace\s+level, and )?each (?P<role>[a-z]+) "
        r"is set individually per member per "
        r"(?P<scope>board|resource|project)\s*\.?",
        source,
        re.I,
    )
    if (
        not rule
        or rule["scope"].casefold() not in _scope_objects(question)
        or rule["prefix_role"]
        and (
            rule["prefix_role"].casefold() != rule["role"].casefold()
            or rule["prefix_scope"].casefold() != rule["scope"].casefold()
        )
    ):
        return None
    if re.search(
        rf"(?:{_NEGATIVE.pattern})\s*(?:{re.escape(rule['role'])}\b|permissions?\b|权限)",
        claim.text,
        re.I,
    ):
        return None
    return dict(resources=list(resources), scope=rule["scope"].casefold())


def _resource_parent_member_safe(text, source):
    """Consume the closed source envelope; arbitrary extra prose stays unknown.

    These source formats describe a title, unrelated negative operations and a
    single-resource member selector. None asserts a relationship between two
    resources. Full matches keep extra rules out, irrespective of their wording.
    """
    if not isinstance(text, str):
        return False
    if text == source:
        return True
    identity = re.search(
        r"\beach (?P<role>[a-z]+) is set individually per member per (?P<scope>[a-z]+)",
        source,
        re.I,
    )
    if identity is None:
        return False
    role, scope = map(re.escape, identity.group("role", "scope"))
    formats = (
        r"(?:Inviting|Adding) (?:people|users|members) by using a shareable link\s*\n\.\n"
        + re.escape(source),
        rf"{role}s? are not able to move or edit cards, upload card attachments, "
        rf"tick the box on a checklist item, and {role}s? can't change {scope} settings\.",
        rf"from the top of the {scope}\. Enter the member's username or email address\. "
        r"When you choose the person to add, the default choice is to add them as regular "
        rf"{scope} members, but you can click on the dropdown\s+to change that to '{role}'\.",
    )
    return any(re.fullmatch(pattern, text, re.I) is not None for pattern in formats)


def _parent_context_safe(fact, source, *, quantity):
    from packages.agents.writer.subquestion_premises import _source_context_v5

    # Reuse the closed v5 parent envelope for its finite sharing-cap rule. It
    # checks whole members and all normalized conditions without publishing a
    # second cap fact. Other literal caps need no extra parent premises.
    if quantity and _source_context_v5(fact):
        return True
    qualifiers = fact.qualifiers
    if set(qualifiers) - {"slot", "source_scope", "operations"}:
        return False
    scope = qualifiers.get("source_scope", {})
    if (
        not isinstance(scope, dict)
        or set(scope) - {"captured_page_id", "context", "operations", "raw_source_id", "source_url"}
        or qualifiers.get("operations")
        or scope.get("operations")
    ):
        return False
    context = scope.get("context", {})
    if (
        not isinstance(context, dict)
        or set(context) - {"document_section", "plan", "role", "section_path"}
        or any(context.get(key) is not None for key in ("plan", "role", "section_path"))
    ):
        return False
    members = [fact.quote, *(fact.value if isinstance(fact.value, list) else [fact.value])]
    if quantity:
        return all(text == source for text in members)
    # Every extra member needs a closed interpretation. Absence of familiar
    # condition words cannot certify arbitrary prose as irrelevant to scope.
    return fact.quote == source and all(
        _resource_parent_member_safe(text, source) for text in members
    )


def build_decision_candidates(context: TaskDecisionContext):
    """Recover task→claim mappings; supported is eligibility, not fulfillment."""
    if not context.facts:
        return ()
    generated, tasks, reviews = _rebuild(context)
    known_questions = {q["question_id"]: q for q in context.questions}
    result = []
    for audited in context.audited_claims:
        claim = audited.claim
        if (
            audited.status != "supported"
            or claim.kind != "inference"
            or audited.review is None
            or audited.review.verdict != "supported"
            or claim_review_reasons(claim, audited.review)
            or claim.id not in tasks
            or generated.get(claim.id) != claim
            or audited.rule_reasons
            or (claim.competitor, claim.dimension) != (context.competitor, context.dimension)
        ):
            continue
        task = tasks[claim.id]
        projected, reasons = projected_source_facts(claim, context.facts)
        if (
            reasons
            or not claim.source_span_bindings
            or len(projected) != 1
            or set(claim.source_ids) != {b.source_id for b in claim.source_span_bindings}
            or any(
                (f.competitor, f.dimension) != (context.competitor, context.dimension)
                for f in projected
            )
        ):
            continue
        question = known_questions[task["question_id"]]
        source = projected[0].quote
        quantity = _quantity_witness(
            task, source, question["question"], context.competitor, claim.text
        )
        resource = (
            _resource_witness(task, source, claim, question["question"])
            if not task.get("request_property")
            else None
        )
        witness = quantity or resource
        original = next(fact for fact in context.facts if fact.id == projected[0].id)
        if witness is None or not _parent_context_safe(original, source, quantity=bool(quantity)):
            continue
        sources = tuple(
            dict(
                source_ref="decision-source-" + _digest(b.model_dump(mode="json"))[:24],
                **b.model_dump(mode="json"),
            )
            for b in claim.source_span_bindings
        )
        request = narrow_request_context(context.request_context, [question["question_id"]])
        scenario = ("decision-scenario-" + _digest([question, request])[:24],)
        binding = dict(
            consumption_id=context.consumption_id,
            snapshot_id=context.snapshot_id,
            question=question,
            request_context=request,
            task=_task_identity(task),
            claim=claim.model_dump(mode="json"),
            sources=sources,
            claim_review=audited.review.model_dump(mode="json"),
            review_dispatch=reviews[claim.id][1],
        )
        digest = _digest(binding)
        result.append(
            DecisionCandidate(
                candidate_ref="decision-candidate-" + digest[:24],
                question_id=question["question_id"],
                task_id=task["task_id"],
                claim_id=claim.id,
                witness_kind="quantity_excess" if quantity else "resource_non_entailment",
                witness=witness,
                evidence_refs=tuple(s["source_ref"] for s in sources),
                scenario_refs=scenario,
                binding_sha256=digest,
                task=_task_identity(task),
                claim=claim.model_dump(mode="json"),
                sources=sources,
            )
        )
    return tuple(result)


def issue_decision_credentials(context: TaskDecisionContext, answer_dispatch):
    """The same factory serves live/replay; no v6 transport means no upgrade."""
    from packages.agents.writer.question_atomic_delivery import ANSWER_NAME

    if answer_dispatch is None:
        return ()
    try:
        candidates = tuple(c for c in build_decision_candidates(context)
                           if c.question_id in answer_dispatch['question_ids'])
        span, payload = _transport(context, answer_dispatch)
        sent = payload.get("decision_candidates")
        projection_version = candidate_projection_version(payload)
        decision_selection_policy(payload)
        if (
            answer_dispatch["name"] != ANSWER_NAME
            or payload.get("answer_review_contract") != "subquestion-premises-v6"
            or sent != [candidate.review_payload(projection_version=projection_version)
                        for candidate in candidates]
            or not {candidate.question_id for candidate in candidates}
            <= set(answer_dispatch["question_ids"])
            or not {candidate.claim_id for candidate in candidates}
            <= set(answer_dispatch["claim_ids"])
            or not {source["fact_id"] for candidate in candidates for source in candidate.sources}
            <= set(answer_dispatch["fact_ids"])
        ):
            return ()
        raw = _unique_json(span.full_output)
        if raw.get("version") != 3 or not isinstance(raw.get("task_decisions"), list):
            return ()
        rows = raw["task_decisions"]
        if any(not isinstance(row, dict) for row in rows):
            return ()
        refs = Counter(row.get("candidate_ref") for row in rows if isinstance(row, dict))
        if set(refs) - {candidate.candidate_ref for candidate in candidates}:
            return ()
        result = []
        for candidate in candidates:
            if refs[candidate.candidate_ref] != 1:
                continue
            row = next(row for row in rows if row.get("candidate_ref") == candidate.candidate_ref)
            if (
                set(row)
                != {
                    "candidate_ref",
                    "task_fulfilled",
                    "target_grounding",
                    "conclusion",
                    "evidence_refs",
                    "scenario_refs",
                }
                or row["task_fulfilled"] is not True
                or row["target_grounding"] != "supported"
                or row["conclusion"] != "no"
                or row["evidence_refs"] != list(candidate.evidence_refs)
                or row["scenario_refs"] != list(candidate.scenario_refs)
            ):
                continue
            result.append(
                DecisionCredential(
                    **candidate.model_dump(
                        include={
                            "candidate_ref",
                            "question_id",
                            "task_id",
                            "claim_id",
                            "witness_kind",
                            "evidence_refs",
                            "scenario_refs",
                            "binding_sha256",
                        }
                    ),
                    conclusion="no",
                    answer_span_id=span.id,
                    answer_input_sha256=_digest(span.full_input),
                    answer_output_sha256=_digest(span.full_output),
                )
            )
        return tuple(result)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return ()


def verify_decision_credential(credential, context: TaskDecisionContext, answer_dispatch):
    """Reconstruct with current sources, tasks, parents and both actual reviews."""
    return credential in issue_decision_credentials(context, answer_dispatch)


@dataclass(frozen=True)
class DecisionReview:
    """Ephemeral validated producer context; never deserialize this from a report."""

    context: TaskDecisionContext
    answer_dispatch: dict

    def credentials(self):
        return issue_decision_credentials(self.context, self.answer_dispatch)

    def approved_quantity_core(self, question_id, binding, parent_claim_ids):
        """Project one original approved core only for a complete joint quantity no."""
        from packages.agents.writer.question_allocation import _request_units
        from packages.agents.writer.question_atomic_delivery import GENERATION_NAME
        from packages.agents.writer.subquestion_premises import _COUNT, _UNITS, _counts

        try:
            span, payload = _transport(self.context, self.answer_dispatch)
            if decision_selection_policy(payload) != APPROVED_QUANTITY_CORE_POLICY:
                return ()
            question, = [q['question'] for q in self.context.questions
                         if q['question_id'] == question_id]
            raw = _unique_json(span.full_output)
            parent, = [row for row in raw['answers'] if row['question_id'] == question_id]
            original, = parent['subquestions']
            ids = binding.claim_ids
            if (
                (parent['status'], parent['resolution'], parent['conclusion'])
                != ('answered', 'direct', 'no')
                or parent['missing_fields'] != []
                or parent['claim_ids'] != list(parent_claim_ids)
                or len(parent_claim_ids) != len(set(parent_claim_ids))
                or set(parent_claim_ids) != set(ids)
                or len(ids) != len(set(ids))
                or original != binding.model_dump(mode='json', exclude={'support_digest'})
                or binding.question_quote != question
                or binding.conclusion != 'no'
                or binding.relation == 'unresolved'
                or len(_request_units(question)) != 1
                or re.search(r'分别|逐项|各自|\b(?:each|separately|independently|respectively)\b',
                             question, re.I)
            ):
                return ()
            _, by_claim, _ = _rebuild(self.context)
            if any(cid not in by_claim or by_claim[cid]['question_id'] != question_id
                   or by_claim[cid]['question_quote'] not in question for cid in ids):
                return ()
            tasks = {}
            for dispatch in self.context.compact['dispatches']:
                if dispatch['name'] != GENERATION_NAME:
                    continue
                _, generated = _transport(self.context, dispatch)
                for task in generated['generation_tasks']:
                    if task['question_id'] == question_id:
                        tasks.setdefault(task['task_id'], _task_identity(task))
            if not tasks:
                return ()
            for task in tasks.values():
                counts = _counts(task['question_quote'])
                if (task.get('focus') != 'source_rule' or task.get('state') != 'planned'
                        or task.get('resource') is not None
                        or task.get('request_property') not in {'people_limit', 'container_limit'}
                        or task['question_quote'] not in question or len(counts) != 1):
                    return ()
                unit, numbers = next(iter(counts.items()))
                if (len(numbers) != 1 or numbers[0] < 1
                        or (task['request_property'] == 'people_limit') != (unit == 'people')
                        or re.fullmatch(rf'\s*{_COUNT}\s*{_UNITS[unit]}\s*',
                                        task['question_quote'], re.I) is None):
                    return ()
            credentials = {c.claim_id: c for c in self.credentials()
                           if c.question_id == question_id and c.witness_kind == 'quantity_excess'
                           and c.conclusion == 'no'}
            return next(((credentials[cid],) for cid in ids if cid in credentials), ())
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            return ()

    def branch(self, question_id, binding):
        """Check every v6 claim's task ownership before any conclusion shortcut."""
        try:
            _, tasks, _ = _rebuild(self.context)
            selected = [tasks[cid] for cid in binding.claim_ids]
            if any(task['question_id'] != question_id
                   or task['question_quote'] not in binding.question_quote for task in selected):
                return False, False, ()
            target = any(task.get('request_property') in {'people_limit', 'container_limit'}
                         or re.search(r'自动|确定|决定|\b(?:automatically|determine|entail)\b',
                                      task['question_quote'], re.I)
                         and len(set(re.findall(
                             r'(?<![A-Za-z0-9_])[A-Z](?:[0-9]{1,3})?(?![A-Za-z0-9_])',
                                                task['question_quote']))) == 2
                         for task in selected)
            credentials = tuple(c for c in self.credentials()
                                if c.question_id == question_id and c.claim_id in binding.claim_ids)
            # Only the independently reviewed exact inference receives the new
            # negative eligibility; another same-task deduction cannot ride along.
            inferences = {a.claim.id for a in self.context.audited_claims
                          if a.claim.kind == 'inference' and a.claim.id in binding.claim_ids}
            target = (target or bool(credentials)) and bool(inferences)
            qualified = bool(credentials) and inferences == {c.claim_id for c in credentials}
            if any(c.witness_kind == 'resource_non_entailment' for c in credentials):
                # This credential answers one requested entailment predicate.
                # A second requested task (such as billing) cannot disappear
                # inside a larger branch just because the first task says no.
                branch_tasks = {
                    task['task_id']
                    for _, payload in self.context.expected_inputs.values()
                    if payload.get('generation_projection_version') == 5
                    for task in payload['generation_tasks']
                    if task['question_id'] == question_id
                    and task['question_quote'] in binding.question_quote
                }
                qualified &= branch_tasks <= {task['task_id'] for task in selected}
            return True, target, credentials if qualified else ()
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            return False, False, ()
