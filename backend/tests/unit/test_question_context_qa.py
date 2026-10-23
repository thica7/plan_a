"""Question-owned context omissions never relax factual or publication guards."""

import hashlib
import json
from datetime import UTC, datetime

import pytest
from claim_review_fixture import supported_review
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_source_span_binding import parse_bound
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer.answer_coverage import parse_answer_coverage, research_questions
from packages.agents.writer.dimension_writer import render_dimension_report, review_payload
from packages.agents.writer.request_clarification import server_clarification_answer
from packages.orchestrator.question_packets import (
    packet_id,
    prompt_packets,
    receipt_hash,
    selection_config,
    selection_receipt,
)
from packages.research.evidence.answer_models import AnswerBoundary
from packages.research.evidence.operations import operation_binding, operation_observations
from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.source_spans import source_span_candidates
from packages.schema.models import DecisionBrief, TraceSpan

CORE = "question_core_context_budget_exceeded"
EXCEPTION = "question_exception_context_budget_exceeded"
CAP = "Basic includes up to 2 users."
CLARIFY = "Example Product: 我们准备把离职同事“删掉”，他保存的那些密码之后还会留下吗？"


def case(
    *,
    factual=False,
    missing_for="clarification",
    gap=CORE,
    unknown_original=False,
    include_operation=False,
):
    question = ("Example Product: Can Basic support 3 users?\n" if factual else "") + CLARIFY
    quotes = [CAP, "Deleting an account permanently deletes all vault data."]
    if include_operation:
        quotes.append(
            "Members can edit documents only after signing in. "
            "Members can comment on documents only after signing in."
        )
    detail, _ = research_case(quotes, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)
    questions = research_questions(detail, "Example Product", "feature")
    cap = next(f for f in snapshot.facts if f.field == "evidence_terms" and f.quote == CAP)
    missing = next(f for f in snapshot.facts if f.field == "evidence_terms" and f.quote != CAP)
    selected_ids = [cap.id]
    if include_operation:
        selected_ids.append(
            next(
                f.id
                for f in snapshot.facts
                if f.quote == quotes[-1] and f.field == "evidence_terms"
            )
        )
    rows = []
    for q in questions:
        owns_gap = missing_for is not None and (q["question"] == CLARIFY) == (
            missing_for == "clarification"
        )
        rows.append(
            dict(
                question_id=q["question_id"],
                fact_ids=[cap.id],
                core_fact_ids=["unknown" if unknown_original else missing.id]
                if owns_gap and gap == CORE
                else [],
                missing_core_fact_ids=[],
                missing_exception_fact_ids=[],
                required_exception_fact_ids=[missing.id] if owns_gap and gap == EXCEPTION else [],
                minimum_evidence_missing=False,
            )
        )
    packet = dict(
        run_id=detail.id,
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        snapshot_id=snapshot.id,
        snapshot_content_hash=snapshot.content_hash,
        competitor="Example Product",
        dimension="feature",
        questions=questions,
        retrieval=dict(mode="lexical", eligible_count=len(quotes), questions=rows),
        selected_fact_ids=selected_ids,
        selection_config=selection_config(),
    )
    packet["packet_id"] = packet_id(packet)
    view, use = service._begin_evidence_use(
        record,
        agent="writer",
        competitor="Example Product",
        dimension="feature",
        fact_ids=selected_ids,
    )
    receipt = selection_receipt(detail, [packet], use.requested_fact_ids)
    use = use.model_copy(
        update={
            "id": "question-" + use.id + "-" + receipt_hash(receipt),
            "status": "validated",
            "validated_snapshot_id": snapshot.id,
        }
    )
    detail.evidence_consumptions = [use]
    selection = dict(consumption_id=use.id, packets=[packet], receipt=receipt)
    detail.trace_spans.append(
        TraceSpan(
            id="selection",
            kind="tool",
            agent="writer",
            name="question_evidence_selection",
            status="ok",
            duration_ms=0,
            full_output=canonical_json(selection),
        )
    )
    sent = [
        dict(
            id=f.id,
            source_id=f.source_id,
            competitor=f.competitor,
            dimension=f.dimension,
            field=f.field,
            quote=f.quote,
            value=f.value,
            qualifiers={k: v for k, v in f.qualifiers.items() if k != "operations"},
        )
        for f in view.facts
    ]
    operation_ref, span_ref = 0, 0
    for row, original in zip(sent, view.facts, strict=True):
        operations = [operation_binding(op) for op in operation_observations(original)]
        if operations:
            row.update(
                operation_observations=operations,
                operation_targets=sorted({op["operation"] for op in operations}),
                operation_support_refs=[
                    f"o{i}" for i in range(operation_ref + 1, operation_ref + 1 + len(operations))
                ],
            )
            operation_ref += len(operations)
        spans = source_span_candidates(original)
        if spans:
            span_ref += 1
            row["source_span_candidates"] = [
                dict(support_ref=f"s{span_ref}", quote=spans[0]["quote"])
            ]
    payload = dict(
        segment_competitor=use.competitor,
        dimension=use.dimension,
        questions=questions,
        evidence_view=dict(facts=sent),
        question_evidence_packets=prompt_packets([packet], snapshot, sent),
    )
    full_input = "SYSTEM\n\n\nJSON:\n" + canonical_json(payload)
    detail.trace_spans.append(
        TraceSpan(
            id="writer",
            kind="llm",
            agent="writer",
            subagent="Example Product/feature",
            name="dimension_claim_writer",
            status="ok",
            duration_ms=0,
            full_input=full_input,
            metadata={"llm_transport_attempts": 1},
        )
    )
    dispatch = dict(
        consumption_id=use.id,
        packet_ids=[packet["packet_id"]],
        snapshot_id=snapshot.id,
        span_id="writer",
        full_input_sha256=hashlib.sha256(full_input.encode()).hexdigest(),
        status="unverified",
        dispatch_cause="dispatch_unverified",
    )
    detail.trace_spans.append(
        TraceSpan(
            id="dispatch",
            kind="tool",
            agent="writer",
            name="question_evidence_dispatch",
            status="ok",
            duration_ms=0,
            full_output=canonical_json(dispatch),
        )
    )
    claims, answers = [], []
    if factual:
        selected = service._writer_segment_context(
            record,
            dict(
                segment_name="dimension:Example Product:feature",
                segment_competitor="Example Product",
                dimension="feature",
                answer_intent="facts",
            ),
            view,
            use,
        )
        detail.report_answer_boundaries = [
            AnswerBoundary.model_validate(b) for b in selected["answer_boundaries"]
        ]
        drafts, gaps = parse_bound(cap, CAP)
        assert drafts and not gaps
        reviews = [
            supported_review(row)
            for row in review_payload(drafts, view, review_version=3)["claims"]
        ]
        claims = audit_report_claims(
            drafts, reviews, view, detail.report_answer_boundaries, review_version=3
        )
        assert all(c.status == "supported" for c in claims), claims
        answers = list(
            parse_answer_coverage(
                json.dumps(
                    dict(
                        version=3,
                        answers=[
                            dict(
                                question_id=questions[0]["question_id"],
                                status="answered",
                                resolution="direct",
                                conclusion="no",
                                claim_ids=[drafts[0].id],
                                missing_fields=[],
                                reason="The source records a lower cap.",
                            )
                        ],
                    )
                ),
                questions[:1],
                {drafts[0].id},
                claims=[drafts[0].model_dump(mode="json")],
                required_binding_version=3,
                facts=view.facts,
            )
        )
        assert answers[0].status == "answered", answers
    answers.append(server_clarification_answer(questions[-1]))
    audit = ReportDimensionAudit(
        competitor="Example Product",
        dimension="feature",
        consumption_id=use.id,
        claims=claims,
        answer_coverage=answers,
        answer_binding_version=3,
        claim_review_version=3,
        gaps=[gap],
    )
    detail.report_dimension_audits = [audit]
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    service._record_evidence_artifact(
        record, kind="writer", uses=[use], payload=service._writer_evidence_artifact_payload(detail)
    )
    return service, record, snapshot


def findings(service, record, snapshot):
    return audit_dimension_claims(service, record, snapshot, producer_verified=True)


@pytest.mark.parametrize("factual", [False, True])
def test_verified_request_only_omission_does_not_block_other_complete_answers(factual):
    service, record, snapshot = case(factual=factual)
    before = record.detail.model_dump_json()
    assert not findings(service, record, snapshot)
    assert record.detail.model_dump_json() == before
    assert CORE in record.detail.report_dimension_audits[0].gaps


@pytest.mark.parametrize(
    "mode", ["factual", "exception", "unattributed", "legacy", "unknown_original"]
)
def test_factual_exception_unknown_and_legacy_omissions_remain_blocking(mode):
    service, record, snapshot = case(
        factual=True,
        missing_for=None
        if mode == "unattributed"
        else "factual"
        if mode == "factual"
        else "clarification",
        gap=EXCEPTION if mode == "exception" else CORE,
        unknown_original=mode == "unknown_original",
    )
    if mode == "legacy":
        record.detail.trace_spans = []
        use = record.detail.evidence_consumptions[0].model_copy(
            update={"id": "evidence-use-legacy"}
        )
        record.detail.evidence_consumptions = [use]
        audit = record.detail.report_dimension_audits[0]
        record.detail.report_dimension_audits = [
            audit.model_copy(update={"consumption_id": use.id})
        ]
        service._record_evidence_artifact(
            record,
            kind="writer",
            uses=[use],
            payload=service._writer_evidence_artifact_payload(record.detail),
        )
    assert any(
        i.metadata["claim_audit_reason"] == "answer_coverage_incomplete"
        for i in findings(service, record, snapshot)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "packet",
        "rehashed_packet",
        "receipt",
        "selection_duplicate",
        "dispatch_duplicate",
        "span_hash",
        "span_scope",
        "span_missing",
        "transport",
        "failed",
        "fact_content",
        "fact_foreign",
        "question_text",
        "answer",
        "body",
        "claim",
        "dispatch_packet",
    ],
)
def test_changed_identity_dispatch_or_publication_never_authorizes_gap_waiver(mutation):
    service, record, snapshot = case(factual=True)
    detail = record.detail
    selection, writer, dispatch = detail.trace_spans[:3]
    if mutation in {"packet", "rehashed_packet", "receipt"}:
        data = json.loads(selection.full_output)
        if mutation in {"packet", "rehashed_packet"}:
            data["packets"][0]["retrieval"]["questions"][0]["core_fact_ids"] = ["forged"]
            if mutation == "rehashed_packet":
                data["packets"][0]["packet_id"] = packet_id(data["packets"][0])
        else:
            data["receipt"]["packets"][0]["questions_sha256"] = "forged"
        selection.full_output = canonical_json(data)
    elif mutation == "selection_duplicate":
        detail.trace_spans.append(selection.model_copy(update={"id": "selection-copy"}))
    elif mutation == "dispatch_duplicate":
        detail.trace_spans.append(dispatch.model_copy(update={"id": "dispatch-copy"}))
    elif mutation == "dispatch_packet":
        data = json.loads(dispatch.full_output)
        data["packet_ids"] = ["another-packet"]
        dispatch.full_output = canonical_json(data)
    elif mutation == "span_hash":
        writer.full_input += " changed"
    elif mutation == "span_scope":
        writer.subagent = "Other Product/feature"
    elif mutation == "span_missing":
        detail.trace_spans.remove(writer)
    elif mutation == "transport":
        writer.metadata["llm_transport_attempts"] = 0
    elif mutation == "failed":
        writer.status = "error"
    elif mutation in {"fact_content", "fact_foreign"}:
        payload = json.loads(writer.full_input.split("\nJSON:\n", 1)[1])
        payload["evidence_view"]["facts"][0]["quote" if mutation == "fact_content" else "id"] = (
            "forged"
        )
        writer.full_input = "SYSTEM\n\n\nJSON:\n" + canonical_json(payload)
        data = json.loads(dispatch.full_output)
        data["full_input_sha256"] = hashlib.sha256(writer.full_input.encode()).hexdigest()
        dispatch.full_output = canonical_json(data)
    elif mutation == "question_text":
        detail.plan.decision_brief.decision_question += " Changed question?"
    else:
        audit = detail.report_dimension_audits[0]
        if mutation == "answer":
            answer = audit.answer_coverage[-1].model_copy(update={"reason": "Changed."})
            detail.report_dimension_audits = [
                audit.model_copy(update={"answer_coverage": (*audit.answer_coverage[:-1], answer)})
            ]
        elif mutation == "body":
            detail.report_md = detail.report_md.replace(
                audit.answer_coverage[-1].answer, "Changed."
            )
        elif mutation == "claim":
            detail.report_md = detail.report_md.replace(CAP, "Changed.")
    assert findings(service, record, snapshot)


def test_display_question_ids_cannot_reassign_a_factual_gap_to_request_only_answer():
    service, record, snapshot = case(factual=True, missing_for="factual")
    dispatch = record.detail.trace_spans[2]
    data = json.loads(dispatch.full_output)
    data["actual"] = [
        dict(
            questions=[
                dict(
                    question_id=record.detail.report_dimension_audits[0]
                    .answer_coverage[-1]
                    .question_id,
                    evidence_gaps=[CORE],
                )
            ]
        )
    ]
    dispatch.full_output = canonical_json(data)
    assert any(
        i.metadata["claim_audit_reason"] == "answer_coverage_incomplete"
        for i in findings(service, record, snapshot)
    )


@pytest.mark.parametrize(
    "gap",
    [
        "question_dispatch_unverified",
        "question_context_budget_exceeded",
        "question_no_relevant_original",
    ],
)
def test_an_unknown_question_gap_is_not_hidden_by_an_attributable_core_omission(gap):
    service, record, snapshot = case(factual=True)
    audit = record.detail.report_dimension_audits[0]
    record.detail.report_dimension_audits = [audit.model_copy(update={"gaps": (*audit.gaps, gap)})]
    assert any(
        i.metadata["claim_audit_reason"] == "answer_coverage_incomplete"
        for i in findings(service, record, snapshot)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "effect",
        "prerequisites",
        "removed_operations",
        "operation_ref",
        "removed_operation_refs",
        "operation_targets",
        "forged_span",
        "unknown_span",
        "removed_spans",
        "removed_span_ref",
    ],
)
def test_dispatched_operations_and_support_catalogs_are_canonical_even_after_rehash(mutation):
    service, record, snapshot = case(factual=True, include_operation=True)
    assert not findings(service, record, snapshot)
    writer, dispatch = record.detail.trace_spans[1:3]
    payload = json.loads(writer.full_input.split("\nJSON:\n", 1)[1])
    row = next(
        row for row in payload["evidence_view"]["facts"] if row.get("operation_observations")
    )
    if mutation == "effect":
        row["operation_observations"][0]["effect"] = "denied"
    elif mutation == "prerequisites":
        assert row["operation_observations"][0]["prerequisites"]
        row["operation_observations"][0]["prerequisites"] = []
    elif mutation == "removed_operations":
        row["operation_observations"] = []
    elif mutation == "operation_ref":
        row["operation_support_refs"][0] = "s1"
    elif mutation == "removed_operation_refs":
        row["operation_support_refs"] = []
    elif mutation == "operation_targets":
        row["operation_targets"] = ["delete"]
    elif mutation == "forged_span":
        row["source_span_candidates"][0]["quote"] = "Forged unlimited sharing rule."
    elif mutation == "unknown_span":
        row["source_span_candidates"].append(dict(support_ref="s999", quote="Unknown source rule."))
    elif mutation == "removed_spans":
        row["source_span_candidates"] = []
    elif mutation == "removed_span_ref":
        row["source_span_candidates"][0].pop("support_ref")
    writer.full_input = "SYSTEM\n\n\nJSON:\n" + canonical_json(payload)
    observation = json.loads(dispatch.full_output)
    observation["full_input_sha256"] = hashlib.sha256(writer.full_input.encode()).hexdigest()
    dispatch.full_output = canonical_json(observation)
    assert service._final_qa_producer_verified(record, snapshot)
    assert any(
        i.metadata["claim_audit_reason"] == "answer_coverage_incomplete"
        for i in findings(service, record, snapshot)
    )


def test_a_complete_canonical_operation_subset_keeps_request_only_waiver():
    service, record, snapshot = case(factual=True, include_operation=True)
    writer, dispatch = record.detail.trace_spans[1:3]
    payload = json.loads(writer.full_input.split("\nJSON:\n", 1)[1])
    row = next(
        row for row in payload["evidence_view"]["facts"] if row.get("operation_observations")
    )
    assert len(row["operation_observations"]) >= 2
    row["operation_observations"] = row["operation_observations"][:1]
    row["operation_support_refs"] = row["operation_support_refs"][:1]
    row["operation_targets"] = [row["operation_observations"][0]["operation"]]
    writer.full_input = "SYSTEM\n\n\nJSON:\n" + canonical_json(payload)
    observation = json.loads(dispatch.full_output)
    observation["full_input_sha256"] = hashlib.sha256(writer.full_input.encode()).hexdigest()
    dispatch.full_output = canonical_json(observation)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not findings(service, record, snapshot)
