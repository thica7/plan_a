"""Final answer records are the single source for report decisions and QA labels."""

import json
from datetime import UTC, datetime

import pytest
from claim_review_fixture import supported_review
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer.answer_coverage import parse_answer_coverage, research_questions
from packages.agents.writer.dimension_writer import (
    parse_claim_drafts,
    render_dimension_report,
    review_payload,
)
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.answer_models import AnswerBoundary
from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.source_spans import source_span_candidates
from packages.schema.decision_brief import safe_decision_brief_text

FACT = "Organizations own all collections."
INFERENCE = "Organizations own archived collections."
QUESTION = "Example Product: Who owns all collections?"


def prepared(*, selected_inference=False, status="answered", questions=True, language="zh-CN"):
    detail, _ = research_case(
        [FACT, INFERENCE], question=QUESTION if questions else "Evidence overview"
    )
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = None
    detail.output_language = language
    detail.created_at = detail.updated_at = datetime.now(UTC)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)
    originals = [fact for fact in snapshot.facts if fact.field == "evidence_terms"]
    view, use = service._begin_evidence_use(
        record,
        agent="writer",
        competitor="Example Product",
        dimension="feature",
        fact_ids=[fact.id for fact in originals],
    )
    segment = service._writer_segment_context(
        record,
        dict(
            segment_name="dimension:Example Product:feature",
            segment_competitor="Example Product",
            dimension="feature",
        ),
        view,
        use,
    )
    boundaries = [AnswerBoundary.model_validate(row) for row in segment["answer_boundaries"]]
    detail.report_answer_boundaries = boundaries
    spans = {span["span_id"]: span for fact in originals for span in source_span_candidates(fact)}
    claims, gaps = parse_claim_drafts(
        json.dumps(
            {
                "claims": [
                    dict(
                        text=fact.quote,
                        kind="inference" if fact.quote == INFERENCE else "fact",
                        competitor=fact.competitor,
                        dimension=fact.dimension,
                        fact_ids=[fact.id],
                        source_ids=[fact.source_id],
                        source_span_ids=[source_span_candidates(fact)[0]["span_id"]],
                    )
                    for fact in originals
                ]
            }
        ),
        {},
        {fact.id for fact in originals},
        use.id,
        source_facts=originals,
        span_candidates=spans,
    )
    assert not gaps and len(claims) == 2
    reviews = [
        supported_review(row) for row in review_payload(claims, view, review_version=3)["claims"]
    ]
    audited = audit_report_claims(claims, reviews, view, boundaries, review_version=3)
    assert all(item.status == "supported" for item in audited), [
        (item.status, item.rule_reasons) for item in audited
    ]
    coverage = ()
    if questions:
        question = research_questions(detail, "Example Product", "feature")[0]
        selected = [claim.id for claim in claims if selected_inference or claim.kind == "fact"]
        if status == "answered":
            coverage = parse_answer_coverage(
                json.dumps(
                    {
                        "version": 3,
                        "answers": [
                            dict(
                                question_id=question["question_id"],
                                status="answered",
                                claim_ids=selected,
                                resolution="direct",
                                conclusion="yes",
                                missing_fields=[],
                                reason="Complete support.",
                            )
                        ],
                    }
                ),
                [question],
                set(selected),
                claims=[claim.model_dump(mode="json") for claim in claims],
                required_binding_version=3,
                facts=originals,
            )
            assert coverage[0].status == "answered", coverage[0].reason
        else:
            coverage = (ReportAnswerCoverage(**question, status=status, reason="Awaiting review."),)
    audit = ReportDimensionAudit(
        competitor="Example Product",
        dimension="feature",
        consumption_id=use.id,
        claims=audited,
        answer_coverage=coverage,
        claim_review_version=3,
        answer_binding_version=3 if questions else None,
    )
    detail.report_dimension_audits = [audit]
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    service._record_evidence_artifact(
        record, kind="writer", uses=[use], payload=service._writer_evidence_artifact_payload(detail)
    )
    return service, record, snapshot, audit


@pytest.mark.parametrize("status", ["answered", "partial", "unverified", "unanswered"])
def test_question_report_keeps_facts_but_never_independently_publishes_unselected_inference(status):
    _, record, _, _ = prepared(status=status)
    assert FACT in record.detail.report_md
    assert INFERENCE not in record.detail.report_md
    assert "条件推断：" not in record.detail.report_md


def test_selected_inference_is_visible_in_complete_answer_only():
    _, record, _, audit = prepared(selected_inference=True)
    body = record.detail.report_md
    assert body.count(INFERENCE) == 1
    assert "条件推断：" not in body
    assert safe_decision_brief_text(audit.answer_coverage[0].answer) in body
    assert all(
        claim_id in {item.claim.id for item in audit.claims}
        for claim_id in audit.answer_coverage[0].claim_ids
    )


def test_no_question_report_keeps_legacy_inference_observation():
    service, record, snapshot, _ = prepared(questions=False)
    assert FACT in record.detail.report_md and "条件推断：" + INFERENCE in record.detail.report_md
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)


def test_qa_does_not_require_hidden_inference_but_still_replays_its_binding():
    service, record, snapshot, audit = prepared()
    inference = next(item for item in audit.claims if item.claim.kind == "inference")
    clause = INFERENCE + " " + "".join(f"[source:{sid}]" for sid in inference.claim.source_ids)
    record.detail.report_md = record.detail.report_md.replace("- 条件推断：" + clause + "\n\n", "")
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    changed = inference.model_copy(
        update={"claim": inference.claim.model_copy(update={"source_ids": ("other-source",)})}
    )
    record.detail.report_dimension_audits = [
        audit.model_copy(
            update={
                "claims": tuple(changed if item == inference else item for item in audit.claims)
            }
        )
    ]
    reasons = {
        issue.metadata["claim_audit_reason"]
        for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True)
    }
    assert "claim_review_replay_failed" in reasons


@pytest.mark.parametrize("change", ["status", "conclusion", "answer", "duplicate_block"])
def test_qa_rejects_modified_question_presentation(change):
    service, record, snapshot, audit = prepared(selected_inference=True)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    if change == "status":
        record.detail.report_md = record.detail.report_md.replace("— 已回答", "— 尚未核实")
    elif change == "conclusion":
        record.detail.report_md = record.detail.report_md.replace("结论：是", "结论：否")
    elif change == "answer":
        text = safe_decision_brief_text(audit.answer_coverage[0].answer)
        record.detail.report_md = record.detail.report_md.replace("  " + text, "  " + FACT)
    else:
        start = record.detail.report_md.index("#### 问题回答情况")
        block = record.detail.report_md[start:].split("\n\n", 2)
        record.detail.report_md += "\n" + "\n\n".join(block[:2]) + "\n"
    reasons = {
        issue.metadata["claim_audit_reason"]
        for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True)
    }
    assert "published_answer_missing_or_changed" in reasons


def test_visible_fact_removal_still_fails_qa():
    service, record, snapshot, audit = prepared()
    factual = next(item.claim for item in audit.claims if item.claim.kind == "fact")
    clause = FACT + " " + "".join(f"[source:{sid}]" for sid in factual.source_ids)
    record.detail.report_md = record.detail.report_md.replace(clause, "Removed observation.")
    reasons = {
        issue.metadata["claim_audit_reason"]
        for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True)
    }
    assert "published_claim_missing_or_changed" in reasons


def test_qa_requires_subquestion_receipts_for_the_new_review_contract():
    service, record, snapshot, audit = prepared()
    assert not audit.answer_coverage[0].subquestion_bindings
    record.detail.report_dimension_audits = [
        audit.model_copy(update={"answer_review_contract": "subquestion-premises-v1"})
    ]
    reasons = {
        issue.metadata["claim_audit_reason"]
        for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True)
    }
    assert "answer_coverage_incomplete" in reasons


def test_identical_answers_in_distinct_product_sections_are_not_false_duplicates():
    from packages.agents.writer.answer_presentation import question_coverage_matches

    _, record, snapshot, audit = prepared()
    other = audit.model_copy(update={"competitor": "Other Product"})
    record.detail.plan.competitors.append("Other Product")
    record.detail.report_dimension_audits = [audit, other]
    body = render_dimension_report(record.detail, [audit, other], snapshot=snapshot)
    assert question_coverage_matches(
        body, audit, record.detail.output_language, audits=[audit, other]
    )
    assert question_coverage_matches(
        body, other, record.detail.output_language, audits=[audit, other]
    )


def test_qa_rejects_an_extra_decision_appended_inside_an_intact_answer_block():
    service, record, snapshot, audit = prepared(selected_inference=True)
    answer = safe_decision_brief_text(audit.answer_coverage[0].answer)
    line = next(
        line for line in record.detail.report_md.splitlines() if line.startswith("  " + answer)
    )
    record.detail.report_md = record.detail.report_md.replace(line, line + "\n  结论：否")
    reasons = {
        issue.metadata["claim_audit_reason"]
        for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True)
    }
    assert "published_answer_missing_or_changed" in reasons
