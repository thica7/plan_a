"""Reviewed task deductions survive an incomplete original question."""

import hashlib
import json

import pytest
from test_answer_presentation import INFERENCE, prepared

from packages.agents.writer.answer_presentation import observation_claims
from packages.agents.writer.task_protocol import CONTRACT, parse_tasks
from packages.research.question_scope import research_questions
from packages.schema.models import TraceSpan


def projected_case():
    service, record, snapshot, audit = prepared(status="unverified")
    service._validate_evidence_use(record, record.detail.evidence_consumptions[0])
    q = research_questions(record.detail, audit.competitor, audit.dimension)[0]
    task = parse_tasks(
        json.dumps(
            dict(
                tasks=[
                    dict(
                        question_id=q["question_id"],
                        question_quote=q["question"],
                        focus="source_rule",
                    )
                ]
            )
        ),
        [q],
        f"{audit.competitor}/{audit.dimension}",
    )[0]
    claim = next(a.claim for a in audit.claims if a.claim.kind == "inference")
    decision = dict(
        task_id=task["task_id"],
        claim_id=claim.id,
        task_fulfilled=True,
        conclusion="yes",
        relation="direct",
    )
    digest = hashlib.sha256(claim.model_dump_json().encode()).hexdigest()
    assignment = {k: v for k, v in task.items() if k not in {"state", "reason"}}
    assignment.update(claim_id=claim.id, claim_digest=digest, consumption_id=audit.consumption_id)
    review_input = "SYSTEM\nJSON:\n" + json.dumps(
        dict(task_assignments=[assignment], claims=[dict(id=claim.id, text=claim.text)])
    )
    audited = next(a for a in audit.claims if a.claim.id == claim.id)
    review_span = TraceSpan(
        id="independent-task-review",
        kind="llm",
        agent="qa",
        subagent=f"{audit.competitor}/{audit.dimension}",
        name="dimension_task_review",
        status="ok",
        duration_ms=0,
        full_input=review_input,
        full_output=json.dumps(
            dict(reviews=[audited.review.model_dump(mode="json")], decisions=[decision])
        ),
        metadata={"llm_transport_attempts": 1},
    )
    record.detail.trace_spans.append(review_span)
    task.update(
        state="supported",
        claim_id=claim.id,
        decision=decision,
        claim_digest=digest,
        review_span_id=review_span.id,
        review_input_sha256=hashlib.sha256(review_input.encode()).hexdigest(),
    )
    receipt = dict(
        contract=CONTRACT,
        consumption_id=audit.consumption_id,
        snapshot_id=snapshot.id,
        tasks=[task],
    )
    span = TraceSpan(
        id="task-delivery",
        kind="tool",
        agent="writer",
        subagent=f"{audit.competitor}/{audit.dimension}",
        name="question_task_delivery",
        status="ok",
        duration_ms=0,
        full_output=json.dumps(receipt),
    )
    record.detail.trace_spans.append(span)
    return record, audit, span, receipt


def test_supported_task_inference_is_visible_without_promoting_the_whole_question():
    record, audit, _, _ = projected_case()
    assert INFERENCE in [item.claim.text for item in observation_claims(record.detail, audit)]
    assert audit.answer_coverage[0].status == "unverified"


@pytest.mark.parametrize(
    "change",
    [
        "consumer",
        "claim",
        "digest",
        "task",
        "question",
        "decision",
        "rejected",
        "producer",
        "duplicate",
        "focus",
        "run",
        "project",
        "validated_snapshot",
        "sources",
        "review",
    ],
)
def test_task_projection_rejects_changed_identity_and_review(change):
    record, audit, span, receipt = projected_case()
    task = receipt["tasks"][0]
    if change == "consumer":
        receipt["consumption_id"] = "old-use"
    elif change == "claim":
        task["claim_id"] = "other-claim"
    elif change == "digest":
        task["claim_digest"] = "0" * 64
    elif change == "task":
        task["task_id"] = "other-task"
    elif change == "question":
        task["question_quote"] = "invented request"
    elif change == "decision":
        task["decision"]["task_fulfilled"] = False
    elif change == "rejected":
        task["state"] = "rejected"
    elif change == "producer":
        span.agent = "collector"
    elif change == "duplicate":
        record.detail.trace_spans.append(span.model_copy(update={"id": "duplicate"}))
    elif change == "focus":
        task["focus"] = "download"
        task["task_id"] = (
            "task-"
            + hashlib.sha256(
                json.dumps(
                    [
                        CONTRACT,
                        f"{audit.competitor}/{audit.dimension}",
                        task["question_id"],
                        task["question_quote"],
                        task["focus"],
                        None,
                    ],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()[:20]
        )
        task["decision"]["task_id"] = task["task_id"]
    elif change == "review":
        task["review_span_id"] = "missing"
    else:
        use = record.detail.evidence_consumptions[0]
        fields = {
            "run": dict(run_id="other-run"),
            "project": dict(project_id="other-project"),
            "validated_snapshot": dict(validated_snapshot_id="old"),
            "sources": dict(source_ids=()),
        }
        record.detail.evidence_consumptions[0] = use.model_copy(update=fields[change])
    span.full_output = json.dumps(receipt)
    assert INFERENCE not in [item.claim.text for item in observation_claims(record.detail, audit)]


def test_task_decisions_keep_conclusion_and_relation_but_isolate_bad_rows():
    from packages.agents.writer import task_execution

    parse = getattr(task_execution, "parse_task_decisions", None)
    assert callable(parse), "Task conclusion parser is missing"
    assignments = [dict(task_id="t1", claim_id="c1"), dict(task_id="t2", claim_id="c2")]
    good = dict(
        task_id="t1", claim_id="c1", task_fulfilled=True, conclusion="no", relation="upper_bound"
    )
    bad = dict(
        task_id="t2", claim_id="c2", task_fulfilled=True, conclusion="no", relation="invented"
    )
    assert parse([good, bad], assignments) == {"c1": good}
    assert parse([good, dict(good, conclusion="invalid")], assignments) == {}


@pytest.mark.parametrize(
    "field,value", [("conclusion", []), ("conclusion", {}), ("relation", []), ("relation", {})]
)
def test_unhashable_task_decision_field_cannot_delete_a_valid_peer(field, value):
    from packages.agents.writer.task_execution import parse_task_decisions

    good = dict(
        task_id="t1", claim_id="c1", task_fulfilled=True, conclusion="no", relation="upper_bound"
    )
    bad = dict(good, task_id="t2", claim_id="c2", **{field: value})
    assert parse_task_decisions(
        [good, bad], [dict(task_id="t1", claim_id="c1"), dict(task_id="t2", claim_id="c2")]
    ) == {"c1": good}


@pytest.mark.parametrize("field", ["decisions", "reviews"])
def test_unrelated_malformed_review_row_does_not_hide_a_supported_task(field):
    record, audit, _, _ = projected_case()
    review = next(s for s in record.detail.trace_spans if s.name == "dimension_task_review")
    raw = json.loads(review.full_output)
    raw[field].append([])
    review.full_output = json.dumps(raw)
    assert INFERENCE in [a.claim.text for a in observation_claims(record.detail, audit)]


def test_task_review_from_another_consumption_cannot_authorize_projection():
    record, audit, span, receipt = projected_case()
    fresh = record.detail.evidence_consumptions[0].model_copy(update={"id": "fresh-use"})
    record.detail.evidence_consumptions.append(fresh)
    audit = audit.model_copy(update={"consumption_id": fresh.id})
    receipt["consumption_id"] = fresh.id
    span.full_output = json.dumps(receipt)
    assert INFERENCE not in [a.claim.text for a in observation_claims(record.detail, audit)]


@pytest.mark.asyncio
@pytest.mark.parametrize("task_count", [1, 3])
async def test_real_writer_draft_projects_reviewed_task_before_whole_question_review(
    monkeypatch, task_count
):
    import time
    from datetime import UTC, datetime

    from claim_review_fixture import expand_prompt_payload, supported_review
    from pydantic import HttpUrl, TypeAdapter
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for

    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    question = (
        "Example Product: Who owns archived collections, active collections and shared collections?"
        if task_count == 3
        else "Example Product: Who owns archived collections?"
    )
    parts = ["archived collections", "active collections", "shared collections"][:task_count]
    texts = {part: f"Organizations own {part}." for part in parts}
    detail, _ = research_case(["Organizations own all collections."], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        if name == "dimension_task_plan":
            result = dict(
                tasks=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        question_quote=part,
                        focus="source_rule",
                    )
                    for part in parts
                ]
            )
        elif name == "dimension_task_generation":
            row = payload["evidence_view"]["facts"][0]
            result = dict(
                results=[
                    dict(
                        task_id=task["task_id"],
                        status="generated",
                        atom=dict(
                            text=texts[task["question_quote"]],
                            kind="inference",
                            support_refs=[row["source_span_candidates"][0]["support_ref"]],
                        ),
                    )
                    for task in payload["tasks"]
                ]
            )
        elif name == "dimension_task_review":
            result = dict(
                reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[
                    dict(
                        task_id=a["task_id"],
                        claim_id=a["claim_id"],
                        task_fulfilled=True,
                        conclusion="yes",
                        relation="direct",
                    )
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            assert payload["reviewed_task_decisions"][0]["conclusion"] == "yes"
            return None
        response = json.dumps(result)
        service._append_trace_span(
            service._evidence_live_record(record),
            kind="llm",
            agent=kwargs["agent"],
            subagent=kwargs["subagent"],
            name=name,
            status="ok",
            started=time.perf_counter(),
            input_text=kwargs["system"] + kwargs["user"],
            output_text=response,
            metadata={"llm_transport_attempts": 1},
        )
        return response

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert INFERENCE in detail.report_md
    assert detail.report_dimension_audits[0].answer_coverage[0].status == "unverified"
    assert sum(s.name == "dimension_task_generation" for s in detail.trace_spans) == 1
    if task_count == 3:
        assert sum(s.name == "dimension_task_review" for s in detail.trace_spans) == 2
        assert all(text in detail.report_md for text in texts.values())
