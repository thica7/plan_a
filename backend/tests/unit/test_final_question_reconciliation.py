"""A final semantic receipt may replace a historical question finding only."""

import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from claim_review_fixture import (
    answer_response,
    expand_prompt_payload,
    question_plan_response,
    sent_source_atom,
    supported_review,
)
from pydantic import HttpUrl, TypeAdapter
from question_review_fixture import review_payload as decode_review_payload
from test_question_retrieval import research_case
from test_writer_question_delivery import service_for

from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.schema.models import DecisionBrief, ReflectionRecord

QUESTION = (
    "Example Product: Only the Resource Purge role on alpha.test is granted, "
    "with no other grants. Can it purge the edge cache of beta.test?"
)
QUOTE = (
    "| Resource Purge | Grants access to purge the edge cache for a specific domain "
    "and allows the reading of zone settings. |"
)
CLAIM = "Resource Purge 角色授予清除特定域边缘缓存的权限。"
OLD = "Q1: no explicit negative rule confirms that a role on alpha.test cannot purge beta.test."


def api():
    try:
        return importlib.import_module(
            "packages.agents.qa.question_reconciliation"
        ).reconcile_question_findings
    except ModuleNotFoundError:
        pytest.fail("final question reconciliation is not implemented")


def test_unscoped_question_ordinal_cannot_choose_between_products():
    api()
    from packages.agents.qa.question_reconciliation import _question_id

    questions = {
        "first": ({}, SimpleNamespace(competitor="Alpha", dimension="feature")),
        "second": ({}, SimpleNamespace(competitor="Beta", dimension="feature")),
    }
    issue = SimpleNamespace(
        problem="Q1: the requested rule is missing.", metadata={}, target_competitor=None
    )
    assert _question_id(issue, questions) is None


def test_explicit_question_id_cannot_conflict_with_issue_product_scope():
    api()
    from packages.agents.qa.question_reconciliation import _question_id

    questions = {
        "explicit-question": ({}, SimpleNamespace(competitor="Alpha", dimension="feature"))
    }
    issue = SimpleNamespace(
        problem="explicit-question requires review.", metadata={}, target_competitor="Beta"
    )
    assert _question_id(issue, questions) is None


async def scope_case(monkeypatch, *, reflections=True):
    detail, _ = research_case([QUOTE], question=QUESTION)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=QUESTION)
    detail.reflections = (
        [ReflectionRecord(iteration=1, gate_status="block", blocking_gaps=[OLD])]
        if reflections else []
    )
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)

    async def writer(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_writer":
            row = next(
                row for row in payload["evidence_view"]["facts"] if row["field"] == "evidence_terms"
            )
            return question_plan_response(payload, [sent_source_atom(row, CLAIM)])
        if kwargs["name"] == "dimension_claim_review":
            return json.dumps({"reviews": [supported_review(row) for row in payload["claims"]]})
        assert kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}
        return answer_response(
            payload,
            {
                "version": 3,
                "answers": [
                    dict(
                        question_id=q["question_id"],
                        status="answered",
                        resolution="direct",
                        conclusion="no",
                        claim_ids=[row["id"] for row in payload["claims"]],
                        missing_fields=[],
                        reason="The precise assigned resource limits this role.",
                    )
                    for q in payload["questions"]
                ],
            },
            relation="resource_scope",
        )

    monkeypatch.setattr(service, "_trace_llm_text", writer)
    await service._real_writer_step(record)
    assert service._final_qa_producer_verified(record, current_snapshot(detail))
    assert detail.report_dimension_audits[0].answer_coverage[0].status == "answered"
    return detail, service, record


def reviewed(payload, disposition="superseded"):
    return json.dumps(
        {
            "version": 1,
            "basis_hash": payload["basis_hash"],
            "reviews": [
                dict(
                    issue_id=row["issue_id"],
                    question_id=row["question_id"],
                    disposition=disposition,
                    support_digest=row["support_digest"],
                    claim_ids=row["answer"]["claim_ids"],
                    finding_fully_addressed=True,
                    remaining_gaps=[],
                    reason="The exact reviewed resource scope resolves this historical objection.",
                )
                for row in payload["findings"]
            ],
        }
    )


def finding_context(payload, row):
    return {**row, **payload.get("question_contexts", {}).get(row.get("context_id"), {})}


@pytest.mark.asyncio
async def test_experimental_final_qa_diagnoses_integrity_gaps_without_clearing_them(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    service._settings = service._settings.__class__(writer_task_execution_enabled=True)
    issues = service._build_reflector_qa_issues(detail)
    calls = []

    async def model(record, **kwargs):
        assert kwargs['name'] == 'final_question_reconciliation'
        payload = decode_review_payload(kwargs['user'].split('\nJSON:\n', 1)[1])
        calls.append(payload)
        assert payload['findings'][0]['diagnostic_only'] is True
        context = finding_context(payload, payload['findings'][0])
        assert context['question'] == QUESTION
        assert context['request_context']['parents'][0]['text'] == QUESTION
        return reviewed(payload)

    from test_independent_final_question_qa import traced_model_double
    traced_model_double(monkeypatch, service, model)
    result = await api()(service, record, issues, evidence_issues=issues)
    assert len(calls) == 1
    assert result[:len(issues)] == issues
    assert len(result) == len(issues) + 1
    assert result[-1].metadata['issue_kind'] == 'independent_final_question'
    assert result[-1].severity == 'blocker'
    assert json.loads(detail.trace_spans[-1].full_output)['model_review'] is not None


@pytest.mark.asyncio
async def test_experimental_final_qa_includes_gaps_beside_eligible_findings(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    service._settings = service._settings.__class__(writer_task_execution_enabled=True)
    issues = service._build_reflector_qa_issues(detail)
    issues.append(issues[0].model_copy(update={
        'id': 'mixed-source-finding', 'problem': 'Q1: source missing for this condition.'}))
    calls = []

    async def model(record, **kwargs):
        payload = decode_review_payload(kwargs['user'].split('\nJSON:\n', 1)[1])
        calls.append(payload)
        return reviewed(payload)

    from test_independent_final_question_qa import traced_model_double
    traced_model_double(monkeypatch, service, model)
    result = await api()(service, record, issues, evidence_issues=[])
    assert len(calls) == 1
    rows = [row for batch in calls for row in batch['findings']]
    assert len(rows) == 3
    assert calls[0]['findings'][0]['independent_question_check'] is True
    assert next(row for row in rows
                if row['issue_id'] == issues[1].id)['diagnostic_only'] is True
    assert len(result) == 1 and result[0].id == issues[1].id


@pytest.mark.asyncio
async def test_task_diagnostic_excludes_another_questions_visible_claims(monkeypatch):
    from dataclasses import replace

    detail, service, record = await scope_case(monkeypatch)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    issues = service._build_reflector_qa_issues(detail)
    existing = detail.report_dimension_audits[0]
    claim = existing.claims[0]
    # An unrelated visible observation must not be copied into every question's QA envelope.
    unrelated = claim.model_copy(update={'claim': claim.claim.model_copy(update={
        'id': 'unrelated-claim', 'text': 'Unrelated subject. ' * 200})})
    detail.report_dimension_audits[0] = existing.model_copy(update={
        'claims': (*existing.claims, unrelated)})
    seen = []

    async def model(record, **kwargs):
        payload = decode_review_payload(kwargs['user'].split('\nJSON:\n', 1)[1])
        seen.extend(c['id'] for r in payload['findings']
                    for c in finding_context(payload, r).get('claims', []))
        return reviewed(payload)

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await api()(service, record, issues, evidence_issues=['integrity problem'])
    assert 'unrelated-claim' not in seen
    assert claim.claim.id in seen


@pytest.mark.asyncio
async def test_final_scope_no_reconciles_old_blocker_with_receipt_and_keeps_history(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    history = detail.reflections[-1].model_dump_json()
    issues = service._build_reflector_qa_issues(detail)
    assert any(row.severity == "blocker" for row in issues)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        assert kwargs["name"] == "final_question_reconciliation"
        payload = decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])
        assert payload["findings"][0]["finding"] == OLD
        assert payload["findings"][0]["answer"]["conclusion"] == "no"
        assert payload["findings"][0]["claims"][0]["source_span_bindings"]
        return reviewed(payload)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await api()(service, record, issues, evidence_issues=[])
    assert not result and len(calls) == 1
    assert detail.reflections[-1].model_dump_json() == history
    receipt = next(
        row
        for row in reversed(detail.trace_spans)
        if row.name == "final_question_reconciliation_receipt"
    )
    payload = json.loads(receipt.full_output)
    assert payload["reviews"][0]["disposition"] == "superseded"
    assert payload["reviews"][0]["issue_id"] == issues[0].id
    assert payload["snapshot_id"] == detail.evidence_snapshot_id
    assert payload["basis_hash"] and payload["writer_payload_hash"]
    assert await api()(service, record, issues, evidence_issues=[]) == []
    assert len(calls) == 1  # The same final receipt is replayed without another call.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "unavailable",
        "bad_digest",
        "unknown_issue",
        "missing_review",
        "extra_gap",
        "false_confirmation",
        "bad_claim",
        "current_limitation",
    ],
)
async def test_no_affirmative_complete_receipt_keeps_the_original_blocker(monkeypatch, change):
    detail, service, record = await scope_case(monkeypatch)
    issues = service._build_reflector_qa_issues(detail)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        if change == "unavailable":
            raise RuntimeError("offline unavailable")
        payload = decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])
        response = json.loads(reviewed(payload))
        row = response["reviews"][0]
        if change == "bad_digest":
            row["support_digest"] = "0" * 64
        elif change == "unknown_issue":
            row["issue_id"] = "another-issue"
        elif change == "missing_review":
            response["reviews"] = []
        elif change == "extra_gap":
            row["remaining_gaps"] = ["The second branch is still missing."]
        elif change == "false_confirmation":
            row["finding_fully_addressed"] = False
        elif change == "bad_claim":
            row["claim_ids"] = ["not-published"]
        elif change == "current_limitation":
            row["disposition"] = "current_limitation"
        return json.dumps(response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    assert await api()(service, record, issues, evidence_issues=[]) == issues
    assert len(calls) == 1
    receipt = json.loads(detail.trace_spans[-1].full_output)
    decision = receipt["reviews"][0]
    answer = detail.report_dimension_audits[0].answer_coverage[0]
    assert decision["question_id"] == answer.question_id
    assert decision["claim_ids"] and decision["support_digest"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["citation", "structure", "mixed", "unmapped", "unreviewed", "tampered"]
)
async def test_current_integrity_or_nonquestion_findings_never_call_a_model_to_clear_them(
    monkeypatch, change
):
    detail, service, record = await scope_case(monkeypatch)
    if change == "structure":
        detail.reflections[-1].blocking_gaps = [
            "Missing comparison cell for Example Product / feature."
        ]
    elif change == "mixed":
        detail.reflections[-1].blocking_gaps = [OLD + " The comparison matrix is missing."]
    elif change == "unmapped":
        detail.reflections[-1].blocking_gaps = ["An unknown remaining gap requires review."]
    elif change in {"unreviewed", "tampered"}:
        audit = detail.report_dimension_audits[0]
        answer = audit.answer_coverage[0]
        if change == "unreviewed":
            answer = answer.model_copy(update={"subquestion_bindings": ()})
        else:
            answer = answer.model_copy(update={"answer": "The role can access every domain."})
        detail.report_dimension_audits = [audit.model_copy(update={"answer_coverage": (answer,)})]
    issues = service._build_reflector_qa_issues(detail)

    async def forbidden(*args, **kwargs):
        pytest.fail("An unauthenticated/nonquestion finding must remain without a model call")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    assert (
        await api()(service, record, issues, evidence_issues=issues if change == "citation" else [])
        == issues
    )


@pytest.mark.asyncio
async def test_final_question_review_rejects_changed_report_or_writer_dependencies(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    issues = service._build_reflector_qa_issues(detail)

    async def model(record, **kwargs):
        payload = decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])
        detail.report_md += "\nChanged during review."
        return reviewed(payload)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    with pytest.raises(EvidenceUseRejectedError, match="changed"):
        await api()(service, record, issues, evidence_issues=[])


@pytest.mark.asyncio
async def test_real_final_qa_entry_reconciles_instead_of_copying_old_question_blocker(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)

    async def model(record, **kwargs):
        payload = decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])
        return reviewed(payload)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_qa_step(record)
    assert not [issue for issue in detail.qa_findings if issue.detected_by == "reflector"]
    assert detail.reflections[-1].blocking_gaps == [OLD]


@pytest.mark.asyncio
async def test_safe_missing_quote_remains_an_explicit_current_limitation(monkeypatch):
    question = "Example Product Pro 套餐本月准确人民币报价是多少？"
    detail, _ = research_case(["Members can format documents."], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.topic = detail.plan.topic = question
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    detail.reflections = [
        ReflectionRecord(
            iteration=1,
            gate_status="block",
            blocking_gaps=["Q1: the exact price is unsupported and must not be invented."],
        )
    ]
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)

    async def forbidden(*args, **kwargs):
        pytest.fail("Pure missing quote must not need a writer model call")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    await service._real_writer_step(record)
    answer = detail.report_dimension_audits[0].answer_coverage[0]
    assert answer.resolution == "insufficient"
    assert service._final_qa_producer_verified(record, current_snapshot(detail))

    async def model(record, **kwargs):
        payload = decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])
        return reviewed(payload, "current_limitation")

    monkeypatch.setattr(service, "_trace_llm_text", model)
    issues = service._build_reflector_qa_issues(detail)
    result = await api()(service, record, issues, evidence_issues=[])
    assert len(result) == 1 and result[0].severity == "info"
    assert "historical objection" not in result[0].problem
    assert result[0].metadata["historical_problem"] == issues[0].problem
    assert detail.report_dimension_audits[0].answer_coverage[0] == answer


@pytest.mark.asyncio
async def test_oversized_final_reconciliation_context_keeps_findings_without_a_call(monkeypatch):
    detail, service, record = await scope_case(monkeypatch)
    module = importlib.import_module("packages.agents.qa.question_reconciliation")
    monkeypatch.setattr(module, "MAX_REVIEW_BYTES", 1)

    async def forbidden(*args, **kwargs):
        pytest.fail("Oversized reconciliation context must not dispatch")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    issues = service._build_reflector_qa_issues(detail)
    assert await api()(service, record, issues, evidence_issues=[]) == issues


@pytest.mark.asyncio
async def test_task_final_qa_packs_whole_findings_and_keeps_unsent_ones(monkeypatch):
    from dataclasses import replace
    detail, service, record = await scope_case(monkeypatch)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    original = service._build_reflector_qa_issues(detail)[0]
    large = original.model_copy(update={
        'id': 'oversized-finding', 'problem': 'Q1: ' + 'diagnostic ' * 1000})
    calls = []

    async def model(record, **kwargs):
        assert len(kwargs['user'].encode()) <= 8192
        payload = decode_review_payload(kwargs['user'].split('\nJSON:\n', 1)[1])
        qid = detail.report_dimension_audits[0].answer_coverage[0].question_id
        assert [row['issue_id'] for row in payload['findings']] == [
            f"final-question-{qid}", original.id]
        first = payload['findings'][0]
        context = payload.get('question_contexts', {}).get(first.get('context_id'), first)
        assert context['claims'][0]['source_span_bindings']
        calls.append(payload)
        return reviewed(payload)

    from test_independent_final_question_qa import traced_model_double
    traced_model_double(monkeypatch, service, model)
    result = await api()(service, record, [original, large], evidence_issues=[])
    assert [row.id for row in result] == [large.id]
    assert len(calls) == 1
    assert 'final_qa:run' in service._run_llm_budget(record).delivery_finished


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finding",
    [
        "Q1: The permission answer is unsupported, "
        "and the report citation points to the wrong source.",
        "Q1: the permission answer is unsupported, and the required source document is missing.",
        "Q1: 当前回答缺少原文引用，且来源链接已经失效。",
    ],
)
async def test_mixed_source_or_citation_findings_cannot_be_retired_by_semantic_review(
    monkeypatch, finding
):
    monkeypatch.setitem(scope_case.__globals__, "OLD", finding)
    detail, service, record = await scope_case(monkeypatch)
    issues = service._build_reflector_qa_issues(detail)
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs)
        payload = decode_review_payload(kwargs["user"].split("\nJSON:\n", 1)[1])
        return reviewed(payload)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    assert await api()(service, record, issues, evidence_issues=[]) == issues
    assert not calls
