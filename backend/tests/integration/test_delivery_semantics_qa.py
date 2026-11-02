"""Real producer authority distinguishes delivered limitations from unknown facts."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_conclusion_publication import publication_case
from test_final_question_reconciliation import reviewed
from test_independent_final_question_qa import (
    context_for,
    payload_from,
    receipt,
    traced_model_double,
)

from packages.agents.qa import independent_question_review as qa
from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.qa.question_context import CORE_GAP, EXCEPTION_GAP, question_context_blocks
from packages.agents.qa.question_reconciliation import reconcile_question_findings
from packages.schema.models import QCIssue, RedoScope


async def delivery_case(monkeypatch, kind):
    if kind == "clarification":
        from test_question_atomic_delivery import atomic_case

        case = await atomic_case(
            ["Deleting an account permanently deletes all vault data."],
            question="Example Product：我们准备把离职同事删掉，他保存的密码之后还会留下吗？",
        )
        service, record = case[:2]
        settings = service._settings
        service._settings = replace(
            settings, writer_question_atomic_enabled=True, run_llm_max_tokens=1
        )

        async def forbidden(*args, **kwargs):
            raise AssertionError("Canonical clarification needs no model")

        monkeypatch.setattr(service, "_trace_llm_text", forbidden)
        record.detail.report_md = await service._writer_dimension_report_inner(record)
        service._settings = replace(settings, writer_question_atomic_enabled=True)
        audit = record.detail.report_dimension_audits[0]
        use = next(u for u in record.detail.evidence_consumptions if u.id == audit.consumption_id)
    else:
        kwargs = {}
        if kind == "billing":
            from test_writer_question_delivery import billing_original

            quote, conditions, table = billing_original()
            kwargs = dict(
                source=quote,
                question=(
                    "Example Product Compute Paid Standard 本月有1500万次请求，账单准确是多少美元？"
                ),
                source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1])],
            )
        case, _, audit, _, use = await publication_case(monkeypatch, **kwargs)
    service, record, snapshot = case[:3]
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    assert service._final_qa_producer_verified(record, snapshot)
    return case, audit, use


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["quantity", "billing", "clarification"])
async def test_authenticated_complete_delivery_closes_only_heuristic_core_gap(monkeypatch, kind):
    case, audit, use = await delivery_case(monkeypatch, kind)
    service, record, snapshot, _, view = case[:5]
    assert not question_context_blocks(
        service, record.detail, snapshot, use, view, [CORE_GAP], set()
    )
    assert question_context_blocks(
        service, record.detail, snapshot, use, view, [EXCEPTION_GAP], set()
    )
    assert question_context_blocks(
        service, record.detail, snapshot, use, view, [CORE_GAP, "question_evidence_missing"], set()
    )
    if kind == "billing":
        assert audit.answer_coverage[0].missing_fields and "CPU" in audit.answer_coverage[0].answer
        assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    await service.aclose()


@pytest.mark.asyncio
async def test_reviewed_cpu_limitation_passes_real_citation_audit(monkeypatch):
    case, _, _ = await delivery_case(monkeypatch, "billing")
    assert not audit_dimension_claims(case[0], case[1], case[2], producer_verified=True)
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["quantity", "billing"])
async def test_authenticated_delivery_cannot_bypass_audit_answer_version_mismatch(
    monkeypatch, kind
):
    from packages.agents.qa.independent_question_review import _question_context, _question_verified
    from packages.agents.qa.question_reconciliation import (
        _answer_support,
        authenticated_answer_delivery,
    )

    case, audit, use = await delivery_case(monkeypatch, kind)
    service, record, snapshot = case[:3]
    answer = audit.answer_coverage[0]
    original_answer = answer.model_dump(mode="json")
    assert audit.answer_binding_version == answer.binding_version == 3
    changed = audit.model_copy(update={"answer_binding_version": 2})
    record.detail.report_dimension_audits = [changed]
    # Re-record through production provenance: source review, answer and actual
    # producer transports remain unchanged; only the aggregate version differs.
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    assert service._final_qa_producer_verified(record, snapshot)
    assert answer.model_dump(mode="json") == original_answer
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(i.metadata.get("claim_audit_reason") == "answer_coverage_incomplete" for i in issues)
    question = case[6][0]["questions"][0]
    assert _answer_support(record.detail, snapshot, changed, answer, question) is None
    assert authenticated_answer_delivery(record.detail, snapshot, changed, answer, question) is None
    context = _question_context(
        service,
        record,
        snapshot,
        question,
        changed,
        verified=_question_verified(
            service, record, snapshot, question, changed, issues, producer_verified=True
        ),
        producer_verified=True,
    )
    assert not context["support_verified"]
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,target",
    [
        ("billing", "supported_billing_limitation_delivery"),
        ("clarification", "canonical_clarification_delivery"),
    ],
)
@pytest.mark.parametrize("verdict", ["current_limitation", "keep"])
async def test_independent_qa_reviews_complete_delivery_and_preserves_fact_state(
    monkeypatch, kind, target, verdict
):
    case, audit, _ = await delivery_case(monkeypatch, kind)
    service, record = case[:2]
    answer = audit.answer_coverage[0]
    before = answer.model_dump(mode="json")
    calls = []

    async def model(record, **kwargs):
        p = payload_from(kwargs)
        calls.append(p)
        row = p["findings"][0]
        context = context_for(p, row)
        assert context["support_verified"] and context["publication_matches"]
        assert row["verification_target"] == target
        assert "independent_questions_v11" == qa.PROTOCOL
        assert "Pending user inputs are not delivery omissions" in kwargs["system"]
        assert "all known selected pricing rules visible" not in kwargs["system"]
        result = json.loads(reviewed(p, verdict))
        result["reviews"][0]["delivery_gaps"] = []
        if verdict == "keep":
            result["reviews"][0].update(
                finding_fully_addressed=False,
                remaining_gaps=["A selected rule condition is omitted."],
                delivery_gaps=[dict(kind="unsupported_premise", obligation_ref="question")],
            )
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    issues = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert bool(issues) == (verdict == "keep")
    assert (
        receipt(record.detail)["valid_review_issue_ids"]
        == receipt(record.detail)["planned_issue_ids"]
    )
    assert answer.model_dump(mode="json") == before and answer.status == "partial"
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,ref",
    [
        ("clarification", "pending_input:actual_action"),
        ("clarification", "blocked_output:retention_behavior"),
        ("billing", "pending_input:cpu_usage"),
        ("billing", "blocked_output:exact_total"),
    ],
)
async def test_pending_inputs_or_dependent_outputs_are_invalid_gaps_not_passed(
    monkeypatch, kind, ref
):
    case, audit, _ = await delivery_case(monkeypatch, kind)
    service, record = case[:2]
    calls = []

    async def model(record, **kwargs):
        p = payload_from(kwargs)
        calls.append(p)
        result = json.loads(reviewed(p, "keep"))
        result["reviews"][0].update(
            finding_fully_addressed=False,
            remaining_gaps=["Pending user input is still missing."],
            delivery_gaps=[dict(kind="unanswered_branch", obligation_ref=ref)],
        )
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    for _ in range(3):
        assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    assert len(calls) == 2
    assert output["valid_review_issue_ids"] == output["passed_question_ids"] == []
    assert output["model_unreviewed_issue_ids"] == output["retry_exhausted_issue_ids"]
    assert output["question_review_states"][audit.answer_coverage[0].question_id] == "pending"
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,gap,ref_prefix",
    [
        ("billing", "wrong_source", "claim:"),
        ("billing", "condition_omitted", "claim:"),
        ("clarification", "input_already_given", "clarification:"),
    ],
)
async def test_independent_source_condition_and_necessity_objections_remain_valid_keep(
    monkeypatch, kind, gap, ref_prefix
):
    case, _, _ = await delivery_case(monkeypatch, kind)
    service, record = case[:2]
    calls = []

    async def model(record, **kwargs):
        p = payload_from(kwargs)
        calls.append(p)
        row = p["findings"][0]
        ref = next(o["ref"] for o in row["delivery_obligations"] if o["ref"].startswith(ref_prefix))
        result = json.loads(reviewed(p, "keep"))
        result["reviews"][0].update(
            finding_fully_addressed=False,
            remaining_gaps=["Independent scope objection."],
            delivery_gaps=[dict(kind=gap, obligation_ref=ref)],
        )
        return json.dumps(result)

    traced_model_double(monkeypatch, service, model)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    assert len(calls) == 1
    assert output["valid_review_issue_ids"] == output["planned_issue_ids"]
    assert not output["passed_question_ids"]
    await service.aclose()


@pytest.mark.asyncio
async def test_billing_delivery_cannot_clear_historical_source_or_other_branch(monkeypatch):
    case, audit, _ = await delivery_case(monkeypatch, "billing")
    service, record = case[:2]
    qid = audit.answer_coverage[0].question_id
    originals = [
        QCIssue(
            id=kind,
            severity="blocker",
            detected_by="reflector",
            target_agent="writer",
            target_competitor=audit.competitor,
            field_path="answer_coverage",
            problem=problem,
            metadata={"question_id": qid} if kind != "unmapped" else {},
            redo_scope=RedoScope(kind="writer_only", rationale="Review original scope."),
        )
        for kind, problem in [
            ("source", qid + ": source document missing and CPU rule unsupported."),
            (
                "cross-domain",
                qid + ": billing and Resource Purge alpha.test to beta.test are unanswered.",
            ),
            ("unmapped", "An unmapped mixed original request is unanswered."),
        ]
    ]

    async def model(record, **kwargs):
        p = payload_from(kwargs)
        for row in p["findings"]:
            if not row.get("independent_question_check"):
                assert row["verification_target"] == "complete_finding_resolution"
                assert row["review_scope"] == {"kind": "historical_finding"}
        return reviewed(p, "current_limitation")

    traced_model_double(monkeypatch, service, model)
    result = await reconcile_question_findings(service, record, originals, evidence_issues=[])
    assert {i.id for i in originals} <= {i.id for i in result}
    await service.aclose()


@pytest.mark.asyncio
async def test_v9_actual_review_remains_replayable_without_v10_upgrade(monkeypatch):
    from copy import deepcopy

    from packages.agents.qa.question_review_transport import dumps, final_review_batches

    case, _, _ = await delivery_case(monkeypatch, "clarification")
    service, record = case[:2]

    async def model(record, **kwargs):
        return reviewed(payload_from(kwargs), "current_limitation")

    traced_model_double(monkeypatch, service, model)
    assert not await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    local = record.detail.trace_spans[-1]
    rows = json.loads(local.full_input)["findings"]
    old_rows = [
        {
            k: v
            for k, v in row.items()
            if k not in {"delivery_obligations", "pending_inputs", "blocked_outputs"}
        }
        for row in rows
    ]
    by_id = {row["issue_id"]: row for row in old_rows}
    batches, omitted = final_review_batches(
        old_rows, "old-basis", max_bytes=14000, max_batches=1, protocol="independent_questions_v9"
    )
    assert not omitted
    bound = deepcopy(output["batch_receipts"][0])
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    span.full_input = (
        qa.final_review_system(batches[0], protocol="independent_questions_v9")
        + "\n\n\nJSON:\n"
        + dumps(batches[0])
    )
    span.full_output = reviewed(batches[0], "current_limitation")
    bound.update(
        full_input_sha256=hashlib.sha256(span.full_input.encode()).hexdigest(),
        full_output_sha256=hashlib.sha256(span.full_output.encode()).hexdigest(),
    )
    local.metadata["basis_hash"] = "old-basis"
    local.full_output = json.dumps(dict(mode="independent_questions_v9", batch_receipts=[bound]))
    before = record.detail.model_dump(mode="json")
    cached = qa._cache(record.detail, "old-basis", by_id, protocol="independent_questions_v9")
    assert set(cached[0]) == set(by_id)
    assert qa._affirmative(
        next(iter(cached[0].values())), old_rows[0], protocol="independent_questions_v9"
    )
    assert qa._cache(record.detail, "old-basis", by_id)[0] == {}
    assert record.detail.model_dump(mode="json") == before
    await service.aclose()


def test_new_protocol_keeps_v9_system_and_byte_identity():
    assert qa.PROTOCOL == "independent_questions_v11"
    assert len(qa.INDEPENDENT_SYSTEM_V9.encode()) == 3844
    assert hashlib.sha256(qa.INDEPENDENT_SYSTEM_V9.encode()).hexdigest() == (
        "87555b3a2c06b73cbb74a78495eb63762766c83bf1648ff49576243e241270da"
    )
    assert qa.review_byte_limit("independent_questions_v9") == 14000
    assert len(qa.INDEPENDENT_SYSTEM.encode()) <= 3844
    assert qa.MAX_REVIEW_OUTPUT_TOKENS == 1600
    assert qa.FINAL_QA_REQUEST_RESERVE == 19702
