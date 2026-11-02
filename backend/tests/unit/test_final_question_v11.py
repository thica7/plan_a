"""Question-scoped publication QA keeps global authentication and legacy wires."""

import copy
import hashlib
import json

import pytest
from test_conclusion_publication import publication_case
from test_final_question_reconciliation import reviewed
from test_independent_final_question_qa import (
    context_for,
    payload_from,
    receipt,
    traced_model_double,
)
from test_structured_conclusions import QUESTION, SOURCE

from packages.agents.qa import independent_question_review as qa
from packages.agents.qa.question_reconciliation import reconcile_question_findings

V10 = "independent_questions_v10"
V11 = "independent_questions_v11"


async def two_question_case(monkeypatch):
    case, result, audit, _, use = await publication_case(
        monkeypatch,
        source=SOURCE,
        question=(QUESTION + "\nExample Product：准备把离职同事删掉，他保存的密码还会留下吗？"),
        conclusion_contract="structured-conclusions-v2",
    )
    service, record = case[:2]
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    assert any(a.conclusion == "no" for a in audit.answer_coverage)
    assert any(a.resolution == "clarification" for a in audit.answer_coverage)
    assert service._final_qa_producer_verified(record, case[2])
    return case, result, audit


def test_v11_has_new_identity_without_changing_v10_system_or_reserve():
    assert qa.PROTOCOL == V11
    assert qa.INDEPENDENT_SYSTEM_V10.startswith("Independent final question QA v10.")
    assert hashlib.sha256(qa.INDEPENDENT_SYSTEM_V10.encode()).hexdigest() == (
        "9fa257efb328ecc0de3eff10ea35ab229f06416022cb2bcafb1f828cbadc8063"
    )
    assert qa.review_byte_limit(V10) == qa.review_byte_limit(V11) == 14000
    assert qa.FINAL_QA_REQUEST_RESERVE == 19702
    assert len(qa.INDEPENDENT_SYSTEM.encode()) <= 3844


@pytest.mark.asyncio
async def test_current_clarification_does_not_review_sibling_quantity_observations(monkeypatch):
    case, _, audit = await two_question_case(monkeypatch)
    service, record = case[:2]
    seen = []

    async def model(_record, **kwargs):
        payload = payload_from(kwargs)
        seen.append(payload)
        response = json.loads(reviewed(payload))
        for row, review in zip(payload["findings"], response["reviews"], strict=True):
            current = context_for(payload, row)
            if current["answer"]["resolution"] == "clarification":
                assert current["visible_observations"] == ""
                assert current["claims"] == current["selected_source_context"] == []
                assert "actual_action" in current["answer"]["missing_fields"]
                review["disposition"] = "current_limitation"
                review["delivery_gaps"] = []
            else:
                assert "2" in current["visible_observations"]
                assert "3" in current["visible_observations"]
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    assert not await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    assert seen and output["planned_issue_ids"] == output["valid_review_issue_ids"]
    assert any(a.status == "partial" for a in audit.answer_coverage)
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["extra", "source", "derived"])
async def test_scoped_observations_never_hide_bad_global_publication(monkeypatch, kind):
    from packages.agents.writer.conclusion_publication import observations_match
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    case, _, audit = await two_question_case(monkeypatch)
    service, record = case[:2]
    authorities = replay_decision_reviews(record.detail, audit)
    assert observations_match(record.detail, audit, authorities)
    if kind == "extra":
        record.detail.report_md = record.detail.report_md.replace(
            "#### 问题回答情况", "- 所有账户必须永久删除密码。\n\n#### 问题回答情况"
        )
    elif kind == "source":
        claim = next(c.claim for c in audit.claims if c.status == "supported")
        record.detail.report_md = record.detail.report_md.replace(claim.text, "所有组织上限为999。")
    else:
        record.detail.report_md = record.detail.report_md.replace(
            "超过已核实上限", "没有超过已核实上限"
        )
    assert not observations_match(record.detail, audit, authorities)

    async def model(_record, **kwargs):
        return reviewed(payload_from(kwargs), "superseded")

    traced_model_double(monkeypatch, service, model)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert receipt(record.detail)["blocked_question_ids"]
    await service.aclose()


def test_historical_and_current_response_shapes_are_explicit_and_isolated():
    current = dict(verification_target="supported_sourced_limitation_delivery")
    historical = dict(verification_target="complete_finding_resolution")
    current_system = qa.final_review_system(dict(findings=[current]))
    historical_system = qa.final_review_system(dict(findings=[historical]))
    assert "delivery_gaps is required" in current_system
    assert "Historical response: superseded|keep; omit delivery_gaps" in historical_system
    assert "current_limitation is not a historical verdict" in historical_system
    assert current_system != historical_system
    assert len(current_system.encode()) <= 3844 and len(historical_system.encode()) <= 3844


def test_v11_wire_removes_only_duplicate_prose_and_producer_witnesses():
    from packages.agents.qa.question_review_transport import final_review_batches

    quote = "A complete quoted rule with a condition and an exception."
    row = dict(
        issue_id="issue",
        question_id="q",
        question="Full original question?",
        answer=dict(
            question_id="q",
            question="Full original question?",
            answer="Visible result.",
            reason="Producer reason",
            claim_ids=["c"],
            status="answered",
            conclusion="no",
            resolution="direct",
            missing_fields=[],
            evidence_spans=[dict(claim_id="c", quote="Rule.")],
        ),
        visible_answer="Visible result.",
        visible_observations="- Rule.",
        claims=[dict(id="c", text="Rule.", source_span_bindings=[dict(quote=quote)])],
        selected_source_context=[
            dict(quote=quote, value=[quote], qualifiers=dict(exception="complete"))
        ],
        review_scope=dict(kind="current_question"),
        verification_target="complete_finding_resolution",
        independent_question_check=True,
        structured_conclusions=dict(
            contract="structured-conclusions-v2", revision_sha256="r", entries=[]
        ),
    )
    original = copy.deepcopy(row)
    batches, omitted = final_review_batches(
        [row], "basis", max_bytes=14000, max_batches=1, protocol=V11
    )
    assert not omitted
    projected = batches[0]["findings"][0]
    assert "answer" not in projected["answer"] and "reason" not in projected["answer"]
    assert projected["visible_answer"] == row["visible_answer"]
    assert projected["claims"] == row["claims"]
    assert projected["selected_source_context"] == row["selected_source_context"]
    assert row == original
    old, omitted = final_review_batches(
        [row], "basis", max_bytes=14000, max_batches=1, protocol=V10
    )
    assert not omitted and old[0]["findings"][0] == original
    assert (
        hashlib.sha256(json.dumps(row, sort_keys=True).encode()).digest()
        == hashlib.sha256(json.dumps(original, sort_keys=True).encode()).digest()
    )


@pytest.mark.asyncio
async def test_one_source_can_support_two_own_questions_without_sharing_deductions(monkeypatch):
    from packages.agents.writer.conclusion_publication import question_observation_scope
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    case, _, audit, _, _ = await publication_case(
        monkeypatch,
        source=SOURCE,
        conclusion_contract="structured-conclusions-v2",
        question=QUESTION + "\n" + QUESTION.replace("3 个 collections", "4 个 collections"),
    )
    assert len(audit.answer_coverage) == 2
    authorities = replay_decision_reviews(case[1].detail, audit)
    for answer in audit.answer_coverage:
        text, claims = question_observation_scope(
            case[1].detail, audit, answer.question_id, authorities
        )
        assert answer.conclusion == "no" and claims
        count = "4" if "4 个 collections" in answer.question else "3"
        assert f"请求的 {count} collections" in text
        assert f"请求的 {'3' if count == '4' else '4'} collections" not in text
    await case[0].aclose()


@pytest.mark.asyncio
async def test_scope_rejects_ambiguous_issued_task_ownership(monkeypatch):
    from packages.agents.writer.conclusion_publication import question_observation_scope
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    case, _, audit = await two_question_case(monkeypatch)
    authorities = replay_decision_reviews(case[1].detail, audit)
    answer = next(a for a in audit.answer_coverage if a.conclusion == "no")
    authority = authorities[answer.question_id]
    dispatch = next(
        d
        for d in authority.context.compact["dispatches"]
        if d["name"] == "dimension_question_atomic_generation" and d["claim_ids"]
    )
    dispatch["question_ids"].append("foreign-question")
    with pytest.raises(ValueError, match="ambiguous question ownership"):
        question_observation_scope(case[1].detail, audit, answer.question_id, authorities)
    await case[0].aclose()


@pytest.mark.asyncio
async def test_quote_current_delivery_and_historical_keep_use_distinct_shapes(monkeypatch):
    from packages.schema.models import QCIssue, RedoScope

    quote = (
        "How do I get pricing for Integrated Shield?\nIntegrated Shield pricing is tailored "
        "to your organization’s needs and the capabilities you require. Contact our sales "
        "team to discuss your environment and receive a quote."
    )
    case, _, audit, _, use = await publication_case(
        monkeypatch,
        source=quote,
        conclusion_contract="structured-conclusions-v2",
        question="Example Product Integrated Shield：300 名员工使用一年，人民币含税总价是多少？",
    )
    service, record = case[:2]
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    answer = audit.answer_coverage[0]
    original = QCIssue(
        id="historical-quote",
        severity="blocker",
        detected_by="reflector",
        target_agent="writer",
        target_competitor=audit.competitor,
        field_path="answer_coverage",
        problem=answer.question_id + ": The exact tax-inclusive total remains unavailable.",
        metadata={"question_id": answer.question_id},
        redo_scope=RedoScope(kind="writer_only", rationale="Review the entire original finding."),
    )
    seen = []

    async def model(_record, **kwargs):
        payload = payload_from(kwargs)
        response = json.loads(reviewed(payload))
        for row, review in zip(payload["findings"], response["reviews"], strict=True):
            current = context_for(payload, row)
            assert any(source["quote"] == quote for source in current["selected_source_context"])
            assert "300" in current["request_context"]["parents"][0]["text"]
            assert "一年" in current["request_context"]["parents"][0]["text"]
            if row["review_scope"]["kind"] == "historical_finding":
                assert "Historical response: superseded|keep" in kwargs["system"]
                assert "delivery_obligations" not in row
                review.update(
                    disposition="keep",
                    finding_fully_addressed=False,
                    remaining_gaps=["Exact total is still unavailable."],
                )
                assert "delivery_gaps" not in review
                seen.append(row)
            else:
                review["disposition"] = "current_limitation"
                review["delivery_gaps"] = []
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    issues = await reconcile_question_findings(service, record, [original], evidence_issues=[])
    output = receipt(record.detail)
    assert original in issues and output["planned_issue_ids"] == output["valid_review_issue_ids"]
    assert seen and output["question_review_states"][answer.question_id] == "current_limitation"
    historical = seen[0]
    response = json.loads(
        reviewed(dict(version=1, basis_hash="old", findings=[historical]), "current_limitation")
    )
    response["reviews"][0]["delivery_gaps"] = []
    for protocol in (V10, V11):
        parsed = qa._batch_response(
            json.dumps(response), "old", {original.id: historical}, protocol=protocol
        )
        assert parsed.invalid_issue_ids == [original.id] and not parsed.reviews
    await service.aclose()


@pytest.mark.asyncio
async def test_v10_actual_wire_and_cache_remain_replayable_under_fresh_v11(monkeypatch):
    from packages.agents.qa.question_review_transport import dumps, final_review_batches

    case, _, audit = await two_question_case(monkeypatch)
    service, record, snapshot = case[:3]

    async def model(_record, **kwargs):
        payload = payload_from(kwargs)
        response = json.loads(reviewed(payload))
        for row, review in zip(payload["findings"], response["reviews"], strict=True):
            if context_for(payload, row)["answer"]["resolution"] == "clarification":
                review.update(disposition="current_limitation", delivery_gaps=[])
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    local = next(s for s in reversed(record.detail.trace_spans) if s.name == qa.RECEIPT_NAME)
    question = next(q for q in case[6][0]["questions"] if "删掉" in q["question"])
    context = qa._question_context(
        service,
        record,
        snapshot,
        question,
        audit,
        verified=True,
        producer_verified=True,
        protocol=V10,
    )
    assert "collections" in context["visible_observations"]
    current_rows = json.loads(local.full_input)["findings"]
    row = copy.deepcopy(
        next(r for r in current_rows if r["question_id"] == question["question_id"])
    )
    row.update(context)
    by_id = {row["issue_id"]: row}
    batches, omitted = final_review_batches(
        [row], "old-basis", max_bytes=14000, max_batches=1, protocol=V10
    )
    assert not omitted
    bound = copy.deepcopy(
        next(
            b for b in receipt(record.detail)["batch_receipts"] if row["issue_id"] in b["issue_ids"]
        )
    )
    span = next(s for s in record.detail.trace_spans if s.id == bound["span_id"])
    span.full_input = (
        qa.final_review_system(batches[0], protocol=V10) + "\n\n\nJSON:\n" + dumps(batches[0])
    )
    span.full_output = reviewed(batches[0], "current_limitation")
    bound.update(
        full_input_sha256=hashlib.sha256(span.full_input.encode()).hexdigest(),
        full_output_sha256=hashlib.sha256(span.full_output.encode()).hexdigest(),
    )
    local.metadata["basis_hash"] = "old-basis"
    local.full_output = json.dumps(dict(mode=V10, batch_receipts=[bound]))
    before = record.detail.model_dump(mode="json")
    assert set(qa._cache(record.detail, "old-basis", by_id, protocol=V10)[0]) == set(by_id)
    assert not qa._cache(record.detail, "old-basis", by_id)[0]
    assert record.detail.model_dump(mode="json") == before
    await service.aclose()
