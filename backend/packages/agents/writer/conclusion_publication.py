"""Freeze and authenticate one semantic publication after all coverage overrides.

Receipt JSON is data. Only rebuilding actual producer transports, selected
bindings and independent source reviews can issue an ephemeral authority.
RunJournal's storage revision is deliberately absent from the semantic hash.
"""

import json
from copy import deepcopy

from packages.agents.writer.structured_conclusions import (
    CONTRACT,
    checked_contract,
    digest,
)
from packages.agents.writer.task_answer_outcomes import TaskOutcomeAuthority
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.snapshot_models import canonical_json

_ISSUER = object()


class ConclusionAuthority(TaskOutcomeAuthority):
    def __init__(self, answer, context, bundle, token=None):
        if token is not _ISSUER:
            raise ValueError("A conclusion receipt cannot issue publication authority")
        super().__init__(answer, context)
        object.__setattr__(self, "_bundle_json", canonical_json(bundle))
        object.__setattr__(self, "revision_sha256", bundle["revision_sha256"])

    def matches(self, answer):
        bundle = json.loads(self._bundle_json)
        revision = bundle.pop("revision_sha256")
        return (
            revision == self.revision_sha256 == digest(bundle)
            and self.answer == answer
            and bundle["answers"].get(answer.question_id) == answer.model_dump(mode="json")
        )

    @property
    def has_typed_entry(self):
        return bool(self.question_projection()["entries"])

    def covers_core_gap(self, question):
        if not self.matches(self.answer) or not self.has_typed_entry:
            return False
        from packages.agents.writer.atomic_question_projection import generation_tasks

        tasks = generation_tasks(question, f"{self.context.competitor}/{self.context.dimension}")
        entries = self.question_projection()["entries"]
        return (
            any(e["relation"] == "quantity_upper_bound" for e in entries)
            or bool(tasks)
            and all(t["focus"] == "billing_inputs" for t in tasks)
        )

    def question_projection(self):
        bundle = json.loads(self._bundle_json)
        return dict(
            contract=CONTRACT,
            revision_sha256=self.revision_sha256,
            entries=[
                row for row in bundle["entries"] if row["question_id"] == self.answer.question_id
            ],
        )


def visible_observations(detail, audit):
    from packages.agents.writer.answer_presentation import audit_heading

    lines = detail.report_md.splitlines()
    starts = [
        i for i, line in enumerate(lines) if line == audit_heading(audit, detail.output_language)
    ]
    if len(starts) != 1:
        return None
    start = starts[0] + 1
    end = next(
        (
            i
            for i in range(start, len(lines))
            if lines[i].startswith("#### ") or lines[i].startswith("### ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def derived_observation_lines(audit, language, authorities):
    from packages.schema.decision_brief import safe_decision_brief_text as plain

    lines, seen = [], set()
    supported = {a.claim.id: a.claim for a in audit.claims if a.status == "supported"}
    for answer in audit.answer_coverage:
        authority = (authorities or {}).get(answer.question_id)
        if not isinstance(authority, ConclusionAuthority) or not authority.matches(answer):
            continue
        for entry in authority.question_projection()["entries"]:
            if entry["conclusion_id"] in seen or entry["claim_id"] not in supported:
                continue
            seen.add(entry["conclusion_id"])
            prefix = "条件推断：" if language.startswith("zh") else "Conditional inference: "
            sources = "".join(f"[source:{sid}]" for sid in supported[entry["claim_id"]].source_ids)
            lines.extend([f"- {prefix}{plain(entry['observation'])} {sources}", ""])
    return lines


def observations_match(detail, audit, authorities):
    from packages.agents.writer.answer_presentation import observation_lines

    lines = observation_lines(detail, audit, decision_reviews=authorities)
    return visible_observations(detail, audit) == "\n".join(lines).strip()


def final_coverage_overrides(detail, snapshot, questions, supported, view, compact, coverage):
    """The same final price/clarification merge is rerun by the cold producer."""
    from packages.agents.writer.answer_coverage import (
        is_qualified_partial_clarification,
        unverified_coverage,
    )
    from packages.agents.writer.price_answers import server_missing_price_answers
    from packages.agents.writer.request_clarification import (
        has_lifecycle_rule,
        server_clarification_answer,
    )

    published = [c.model_dump(mode="json") for c in supported]
    prices = server_missing_price_answers(
        detail,
        snapshot,
        questions,
        view.competitor,
        claims=supported,
        delivery_policy=compact.get("delivery_policy"),
        question_claim_whitelist={
            p["question_id"]: set(p["claim_ids"]) for p in compact.get("question_answer_plans", ())
        },
    )
    by_id = {
        a.question_id: a
        for a in unverified_coverage(questions, "No supported answer claims are available.")
    }
    by_id.update({a.question_id: a for a in coverage})
    by_id.update({qid: ReportAnswerCoverage(**row) for qid, row in prices.items()})
    candidates = {
        q["question_id"]: a
        for q in questions
        if q["question_id"] not in prices and (a := server_clarification_answer(q)) is not None
    }
    by_id.update(
        {
            q["question_id"]: candidates[q["question_id"]]
            for q in questions
            if q["question_id"] in candidates and not has_lifecycle_rule(q["question"], published)
        }
    )
    for qid, answer in candidates.items():
        current = by_id[qid]
        if current.status != "answered" and not is_qualified_partial_clarification(
            current,
            published,
            facts=view.facts,
            answer_review_contract=compact.get("answer_review_contract"),
        ):
            by_id[qid] = answer
    return tuple(by_id[q["question_id"]] for q in questions)


def _quantity_coverage_eligible(candidate, question, tasks):
    from packages.agents.writer.task_answer_outcomes import quantity_and_eligible

    if quantity_and_eligible(question, tasks):
        return True
    import re

    from packages.agents.writer.question_allocation import _request_units
    from packages.agents.writer.subquestion_premises import _counts
    from packages.research.evidence.source_exceptions import _missing_question_inputs

    # A typed local task needs no AND promotion. This does not add any natural
    # language task parsing; an untyped single question remains on its old path.
    rule = candidate["rule"]
    return (
        len(tasks) == 1
        and tasks[0]["task_id"] == candidate["task_id"]
        and tasks[0].get("request_property") in {"people_limit", "container_limit"}
        and tasks[0]["focus"] == "source_rule"
        and not tasks[0].get("resource")
        and len(_request_units(question)) == 1
        and not _missing_question_inputs(question)
        and _counts(question) == {rule["unit"]: [rule["required"]]}
        and not re.search(
            r"或|分别|逐项|各自|如果|若|除非|\b(?:or|either|separately|if|unless)\b", question, re.I
        )
    )


def _derived_answer(candidate, claim, current, question, tasks, snapshot_id):
    relation, rule = candidate["relation"], candidate["rule"]
    if relation == "quantity_upper_bound":
        if not _quantity_coverage_eligible(candidate, question["question"], tasks):
            return current, None
        observation = (
            f"在题设共享范围内，请求的 {rule['required']} {rule['unit']} "
            f"超过已核实上限 {rule['maximum']} {rule['unit']}，因此该需求无法满足。"
        )
        text = claim.text + " " + observation
        answer = ReportAnswerCoverage(
            question_id=current.question_id,
            question=current.question,
            status="answered",
            conclusion="no",
            resolution="direct",
            claim_ids=(claim.id,),
            answer=text,
            reason=(
                "Server same-unit upper-bound derivation from independently reviewed source fact."
            ),
            binding_version=3,
            basis_snapshot_id=snapshot_id,
            evidence_spans=[dict(claim_id=claim.id, quote=claim.text)],
            subquestion_bindings=[
                dict(
                    question_quote=question["question"],
                    claim_ids=[claim.id],
                    conclusion="no",
                    relation="upper_bound",
                    support_digest=digest(candidate),
                )
            ],
        )
        return answer, observation
    # The known relation is independent of whether this request fixes its cost.
    # Never enumerate runtime/rates or claim an amount/excess from positive pricing.
    missing = set(current.missing_fields)
    if rule["input_sufficient"]:
        missing.discard("cpu_usage")
        suffix = "当前请求已提供足以确定 CPU 费用项的输入；其他费用与完整账单仍需各自核实。"
    else:
        missing.add("cpu_usage")
        suffix = (
            "当前缺少足以确定该项费用的可计费 CPU 总量或可靠用量界限，"
            "不能仅凭动态请求数核实完整账单。"
        )
    text = claim.text + " " + suffix
    answer = ReportAnswerCoverage(
        question_id=current.question_id,
        question=current.question,
        status="partial",
        conclusion="unknown",
        resolution="insufficient",
        claim_ids=(claim.id,),
        answer=text,
        missing_fields=sorted(missing),
        basis_snapshot_id=snapshot_id,
        reason=(
            "Server billing-input derivation from independently reviewed selected CPU billing rule."
        ),
        binding_version=3,
        evidence_spans=[dict(claim_id=claim.id, quote=claim.text)],
    )
    return answer, suffix


def materialize(context, detail, snapshot, coverage):
    """Never deserialize authority; replay SELECT→GEN→source REVIEW before deriving."""
    if not checked_contract(context.compact):
        raise ValueError("Structured conclusion selector unavailable")
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.question_atomic_delivery import GENERATION_NAME
    from packages.agents.writer.selected_task_delivery import rebuild

    generated, owners, reviews = rebuild(context)
    audited = {a.claim.id: a for a in context.audited_claims if a.status == "supported"}
    by_id = {a.question_id: a for a in coverage}
    known = {q["question_id"]: q for q in context.questions}
    entries, producers = [], []
    for dispatch in context.compact["dispatches"]:
        expected = context.expected_inputs.get(dispatch["span_id"])
        if expected is None:
            raise ValueError("Conclusion producer input missing")
        producers.append(
            {
                k: deepcopy(dispatch[k])
                for k in (
                    "span_id",
                    "name",
                    "question_ids",
                    "claim_ids",
                    "fact_ids",
                    "full_input_sha256",
                    "full_output_sha256",
                    "native_transport",
                    "structured_response_failure",
                )
                if k in dispatch
            }
        )
        if dispatch["name"] != GENERATION_NAME:
            continue
        _, payload = expected
        if not payload.get("conclusion_candidates"):
            continue
        # rebuild authenticated this transport and compared its exact local
        # generation_outcome, including rejected/declined attempts, with IDs.
        # Do not parse a known failed proposal a second time during publication.
        if not dispatch["claim_ids"]:
            continue
        if len(dispatch["claim_ids"]) != 1:
            raise ValueError("Conclusion generation identity changed")
        cid = dispatch["claim_ids"][0]
        claim, reviewed = generated[cid], reviews.get(cid)
        if (
            cid not in audited
            or audited[cid].claim != claim
            or not reviewed
            or reviewed[0] != audited[cid].review
            or reviewed[0].verdict != "supported"
        ):
            continue
        candidates = [
            c
            for c in payload["conclusion_candidates"]
            if c["source_fact_text"] == claim.text and c["task_id"] == owners[cid]["task_id"]
        ]
        if len(candidates) != 1:
            raise ValueError("Authenticated conclusion candidate changed")
        candidate = candidates[0]
        task, qid = owners[cid], candidate["question_id"]
        if task["task_id"] != candidate["task_id"] or qid not in known:
            raise ValueError("Conclusion task scope changed")
        tasks = generation_tasks(known[qid], f"{context.competitor}/{context.dimension}")
        answer, observation = _derived_answer(
            candidate, claim, by_id[qid], known[qid], tasks, snapshot.id
        )
        if observation is None:
            continue
        by_id[qid] = answer
        entries.append(
            dict(
                conclusion_id="conclusion-" + digest([candidate, cid])[:24],
                question_id=qid,
                task_id=task["task_id"],
                claim_id=cid,
                relation=candidate["relation"],
                candidate=deepcopy(candidate),
                source_fact=claim.model_dump(mode="json"),
                source_review=reviewed[0].model_dump(mode="json"),
                source_review_span_id=reviewed[1]["span_id"],
                observation=observation,
                verification_status="verified",
                delivery_status="complete" if answer.status == "answered" else "limitation",
                publication_status="published",
                missing_inputs=list(answer.missing_fields),
            )
        )
    body = dict(
        contract=CONTRACT,
        scope=dict(
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
            run_id=detail.id,
            snapshot_id=snapshot.id,
            snapshot_version=snapshot.version,
            snapshot_content_hash=snapshot.content_hash,
            consumption_id=context.consumption_id,
            competitor=context.competitor,
            dimension=context.dimension,
        ),
        request_sha256=digest(
            dict(questions=context.questions, request_context=context.request_context)
        ),
        final_coverage_inputs_sha256=digest([a.model_dump(mode="json") for a in coverage]),
        producers=producers,
        entries=entries,
        answers={qid: by_id[qid].model_dump(mode="json") for qid in known},
    )
    bundle = dict(body, revision_sha256=digest(body))
    authorities = {
        qid: ConclusionAuthority(answer, context, bundle, _ISSUER) for qid, answer in by_id.items()
    }
    return tuple(by_id[qid] for qid in known), bundle, authorities


def freeze(service, record, view, use, compact, audited, coverage):
    from packages.agents.qa.question_context import _observations
    from packages.agents.writer.question_atomic_delivery import (
        atomic_decision_context,
        save_atomic_receipt,
    )

    service._validate_evidence_use(record, use)
    compact["_decision_audited"] = tuple(audited)
    live = service._evidence_live_record(record)
    snapshot = service._current_evidence_snapshot(live)
    context = atomic_decision_context(service, record, view, use, compact)
    coverage, bundle, authorities = materialize(context, live.detail, snapshot, coverage)
    compact["conclusion_set"] = bundle
    compact["_task_outcome_authorities"] = authorities
    packets = _observations(live.detail, "question_evidence_selection", use.id)["packets"]
    save_atomic_receipt(service, record, compact, view, use, packets)
    return coverage
