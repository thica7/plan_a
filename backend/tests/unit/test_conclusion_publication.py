"""The final coverage merge publishes one authenticated semantic revision."""

import json

import pytest
from test_structured_conclusions import CONTRACT, QUESTION, SOURCE


async def publication_case(
    monkeypatch,
    *,
    source=SOURCE,
    question=QUESTION,
    review_status="supported",
    source_qualifiers=None,
    conclusion_contract=CONTRACT,
    decline_operations=(),
    sources=None,
    selected_refs_limit=1,
    source_values=None,
    selected_quote_contains=None,
    output_language="zh-CN",
    task_package_contract=None,
    selection_hook=None,
    review_hook=None,
    generation_hook=None,
    answer_hook=None,
):
    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_clauses import clause_wire_response
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    case = await atomic_case(
        sources or [source],
        question=question,
        source_qualifiers=source_qualifiers,
        source_values=source_values,
    )
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.output_language = output_language
    record.detail.report_answer_boundaries = boundaries
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        seen.append((name, p))
        if name.endswith("support_selection"):
            t = p["tasks"][0]
            refs = [
                s["support_ref"]
                for f in p["evidence_view"]["facts"]
                for s in f["source_span_candidates"]
                if selected_quote_contains is None or selected_quote_contains in s["quote"]
            ]
            if selection_hook is not None:
                refs = selection_hook(p, refs)
            selected = (
                bool(refs)
                and t.get("request_property") != "people_limit"
                and t["focus"] not in decline_operations
            )
            data = dict(
                selections=[
                    dict(
                        task_id=t["task_id"],
                        status="selected" if selected else "insufficient_evidence",
                        binding_kind="span" if selected else None,
                        support_refs=refs[:selected_refs_limit] if selected else [],
                    )
                ]
            )
        elif name == atomic.GENERATION_NAME:
            t = p["generation_tasks"][0]
            candidates = p.get("conclusion_candidates", [])
            if candidates:
                data = dict(
                    version=1,
                    task_id=t["task_id"],
                    status="selected",
                    candidate_ref=candidates[0]["candidate_ref"],
                )
            else:
                data = dict(
                    version=1, task_id=t["task_id"], status="insufficient_evidence", atom=None
                )
            if generation_hook is not None:
                data = generation_hook(p, data)
        elif name == atomic.REVIEW_NAME:
            data = dict(
                reviews=[dict(supported_review(c), verdict=review_status) for c in p["claims"]],
                atomicity=[
                    dict(claim_id=c["id"], predicate_count=1, clauses=[]) for c in p["claims"]
                ],
            )
            data = clause_wire_response(p, data)
            if review_hook is not None:
                data = review_hook(p, data)
        elif name == atomic.ANSWER_NAME:
            data = dict(
                version=1,
                task_reviews=[
                    dict(
                        task_id=t["task_id"],
                        outcome="unknown",
                        support_refs=[],
                        missing_fields=[],
                        reason="Source fact alone is no task verdict.",
                    )
                    for t in p["tasks"]
                ],
            )
            if answer_hook is not None:
                data = answer_hook(p, data)
        else:
            raise AssertionError(name)
        return append_response(service, record, kwargs, json.dumps(data))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        task_execution_policy="selected-task-atoms-v3",
        answer_review_contract="task-outcomes-v1",
        delivery_policy="complete-predicates-v1",
        task_clause_contract="semantic-target-clauses-v2",
        structured_conclusions_contract=conclusion_contract,
        task_package_contract=task_package_contract,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
        authority_claim_ids=result.get('authority_claim_ids', ()),
        capability_claim_ids=result.get('capability_claim_ids', ()),
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, gaps, _ = await service._dimension_question_coverage(
        record, packets[0]["questions"], result["compact"], audited, view, use, ()
    )
    audit = ReportDimensionAudit(
        competitor=view.competitor,
        dimension=view.dimension,
        consumption_id=use.id,
        claims=audited,
        answer_coverage=answers,
        gaps=gaps,
        answer_binding_version=3,
        claim_review_version=3,
        answer_review_contract="task-outcomes-v1",
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"],
    )
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    return case, result, audit, seen, use


@pytest.mark.asyncio
async def test_source_review_then_program_quantity_survives_final_merge_and_cold_replay(
    monkeypatch,
):
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, audit, seen, use = await publication_case(monkeypatch)
    assert all(c.claim.kind == "fact" and c.status == "supported" for c in audit.claims)
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == ("answered", "no")
    bundle = result["compact"].get("conclusion_set")
    assert bundle and bundle["entries"][0]["relation"] == "quantity_upper_bound"
    assert "条件推断" in case[1].detail.report_md and "3" in case[1].detail.report_md
    assert _answer_support(case[1].detail, case[2], audit, answer, case[6][0]["questions"][0])
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    authority = replay["decision_review"][answer.question_id]
    assert authority.matches(answer)
    assert authority.revision_sha256 == bundle["revision_sha256"]
    assert any(name.endswith("atomic_review") for name, _ in seen)


@pytest.mark.asyncio
async def test_final_qa_context_uses_same_revision_actual_observation_and_full_source(monkeypatch):
    from packages.agents.qa.independent_question_review import _question_context, _question_verified

    case, result, audit, _, _ = await publication_case(monkeypatch)
    question = case[6][0]["questions"][0]
    verified = _question_verified(
        case[0], case[1], case[2], question, audit, [], producer_verified=True
    )
    context = _question_context(
        case[0], case[1], case[2], question, audit, verified=verified, producer_verified=True
    )
    assert (
        context.get("conclusion_revision_sha256")
        == result["compact"]["conclusion_set"]["revision_sha256"]
    )
    assert context["support_verified"] and context["publication_matches"]
    assert SOURCE in json.dumps(context, ensure_ascii=False)
    assert "条件推断" in context["visible_observations"]


@pytest.mark.asyncio
async def test_reviewed_cpu_rule_and_missing_input_survive_price_override(monkeypatch):
    from test_writer_question_delivery import billing_original

    quote, conditions, table = billing_original()
    case, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=quote,
        question="Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1])],
    )
    answer = audit.answer_coverage[0]
    assert answer.claim_ids and "CPU" in answer.answer
    assert "cpu_usage" in answer.missing_fields and answer.resolution == "insufficient"
    assert "账单" in answer.answer and "$" not in answer.answer
    assert result["compact"]["conclusion_set"]["entries"][0]["relation"] == "billing_input_gap"
    assert "CPU" in case[1].detail.report_md


@pytest.mark.asyncio
@pytest.mark.parametrize("review_status", ["uncertain", "unsupported"])
async def test_unapproved_source_fact_cannot_publish_derived_conclusion(monkeypatch, review_status):
    _, result, audit, _, _ = await publication_case(monkeypatch, review_status=review_status)
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
async def test_receipt_and_transport_tampering_cannot_self_authenticate(monkeypatch):
    from copy import deepcopy

    from packages.agents.writer.question_atomic_delivery import digest, replay_atomic_delivery

    case, _, audit, _, use = await publication_case(monkeypatch)
    service, record, snapshot, _, view = case[:5]
    mutations = [
        "answer",
        "revision",
        "version",
        "source",
        "review",
        "proposal",
        "task",
        "consumer",
    ]
    for fault in mutations:
        detail = record.detail.model_copy(deep=True)
        receipt_span = next(s for s in detail.trace_spans if s.name == "question_atomic_delivery")
        receipt = json.loads(receipt_span.full_output)
        changed_audit = audit
        if fault in {"answer", "revision", "version", "source"}:
            bundle = receipt["conclusion_set"]
            if fault == "answer":
                bundle["answers"][audit.answer_coverage[0].question_id]["conclusion"] = "yes"
            elif fault == "revision":
                bundle["revision_sha256"] = "0" * 64
            elif fault == "version":
                bundle["contract"] = "structured-conclusions-v999"
            else:
                bundle["entries"][0]["source_fact"]["source_span_bindings"][0]["quote"] = "forged"
            # Even an attacker recomputing all outer receipt hashes grants no authority.
            content = deepcopy(bundle)
            content.pop("revision_sha256")
            if fault != "revision":
                bundle["revision_sha256"] = digest(content)
        elif fault in {"review", "proposal", "task"}:
            name = (
                "dimension_question_atomic_review"
                if fault == "review"
                else "dimension_question_atomic_generation"
            )
            span = next(s for s in detail.trace_spans if s.name == name)
            if fault == "review":
                raw = json.loads(span.full_output)
                raw["reviews"][0]["verdict"] = "uncertain"
                span.full_output = json.dumps(raw)
            elif fault == "proposal":
                raw = json.loads(span.full_output)
                raw["candidate_ref"] = "unknown"
                span.full_output = json.dumps(raw)
            else:
                span.full_input = span.full_input.replace('"container_limit"', '"people_limit"')
            dispatch = next(d for d in receipt["dispatches"] if d["span_id"] == span.id)
            dispatch["full_output_sha256"] = digest(span.full_output)
            dispatch["full_input_sha256"] = digest(span.full_input)
        else:
            detail.workspace_id = "another-workspace"
        receipt_span.full_output = json.dumps(receipt)
        changed_audit = audit.model_copy(update={"question_atomic_receipt_digest": digest(receipt)})
        detail.report_dimension_audits = [changed_audit]
        with pytest.raises((ValueError, RuntimeError)):
            replay_atomic_delivery(service, detail, snapshot, use, view, audit=changed_audit)


@pytest.mark.asyncio
async def test_changed_actual_observation_blocks_support_and_reaches_qa_as_actual_text(monkeypatch):
    from packages.agents.qa.independent_question_review import _question_context
    from packages.agents.qa.question_reconciliation import _answer_support

    case, _, audit, _, _ = await publication_case(monkeypatch)
    question = case[6][0]["questions"][0]
    case[1].detail.report_md = case[1].detail.report_md.replace(
        "超过已核实上限", "没有超过已核实上限", 1
    )
    assert (
        _answer_support(case[1].detail, case[2], audit, audit.answer_coverage[0], question) is None
    )
    context = _question_context(
        case[0], case[1], case[2], question, audit, verified=True, producer_verified=True
    )
    assert not context["support_verified"] and not context["publication_matches"]
    assert "没有超过" in context["visible_observations"]


@pytest.mark.asyncio
async def test_journal_storage_revision_does_not_change_semantic_revision(monkeypatch, tmp_path):
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews
    from packages.memory import RunJournal

    case, result, audit, _, _ = await publication_case(monkeypatch)
    journal = RunJournal(tmp_path / "structured.db")
    revision = journal.save_run(case[1].detail)
    loaded, stored = journal.load_run_snapshot(case[1].detail.id)
    assert revision == stored
    before = len(loaded.trace_spans)
    expected = result["compact"]["conclusion_set"]["revision_sha256"]
    for _ in range(2):
        authority = replay_decision_reviews(loaded, loaded.report_dimension_audits[0])[
            audit.answer_coverage[0].question_id
        ]
        assert authority.revision_sha256 == expected and authority.matches(audit.answer_coverage[0])
    revision2 = journal.save_run(loaded, expected_revision=stored)
    reloaded, _ = journal.load_run_snapshot(loaded.id)
    assert revision2 > stored and len(reloaded.trace_spans) == before
    authority = replay_decision_reviews(reloaded, reloaded.report_dimension_audits[0])[
        audit.answer_coverage[0].question_id
    ]
    assert authority.revision_sha256 == expected


def test_final_qa_keeps_original_protected_system_and_output_capacity():
    from packages.agents.qa.independent_question_review import (
        FINAL_QA_REQUEST_RESERVE,
        INDEPENDENT_SYSTEM_V9,
        MAX_REVIEW_OUTPUT_TOKENS,
        final_review_system,
    )

    system = final_review_system(
        dict(
            question_contexts=dict(
                current=dict(
                    task_semantic_contract="semantic-target-clauses-v2",
                    structured_conclusions_contract=CONTRACT,
                )
            )
        )
    )
    assert len(system.encode()) <= len(INDEPENDENT_SYSTEM_V9.encode()) == 3844
    assert len(system.encode()) + 14000 + 256 + 1600 + 2 <= FINAL_QA_REQUEST_RESERVE
    assert MAX_REVIEW_OUTPUT_TOKENS == 1600 and FINAL_QA_REQUEST_RESERVE == 19702
    assert "structured-conclusions-v1" in system


def test_existing_typed_single_quantity_task_can_derive_local_no():
    from types import SimpleNamespace

    from packages.agents.writer.conclusion_publication import _derived_answer
    from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

    question = "Example：Free organization 能在3个 collections中共享数据吗？"
    candidate = dict(
        relation="quantity_upper_bound",
        task_id="t",
        rule=dict(unit="collections", maximum=2, required=3, operation="share"),
    )
    task = dict(
        task_id="t",
        question_id="q",
        question_quote="3个 collections",
        request_property="container_limit",
        focus="source_rule",
    )
    current = ReportAnswerCoverage(
        question_id="q", question=question, status="unverified", reason="Pending."
    )
    answer, _ = _derived_answer(
        candidate,
        SimpleNamespace(id="c", text="Free组织最多支持2个collections。"),
        current,
        dict(question_id="q", question=question),
        [task],
        "snapshot",
    )
    assert answer.conclusion == "no" and answer.status == "answered"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "given,sufficient",
    [
        ("CPU 总用量为0毫秒", True),
        ("本月 CPU 总用量为40000000毫秒", True),
        ("CPU费用已知为 USD 0", True),
        ("可靠可计费CPU总用量上界为 1 million milliseconds", True),
        ("CPU 总用量为0毫秒或者40000000毫秒", False),
        ("CPU费用已知为 USD 0 或 USD 10", False),
        ("2025年 CPU 总用量为0毫秒", False),
        ("2025年11月 CPU 总用量为0毫秒", False),
        ("CPU 总用量未确认为0毫秒", False),
        ("CPU 总用量为0毫秒（未确认）", False),
        ("CPU 总用量为0毫秒，未确认", False),
        ("不可靠可计费CPU总用量上界为 1 million milliseconds", False),
        ("其他项目 CPU费用已知为 USD 0", False),
    ],
)
async def test_cpu_input_complete_assertion_survives_publication_and_cold_replay(
    monkeypatch,
    given,
    sufficient,
):
    from test_writer_question_delivery import billing_original

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    quote, conditions, table = billing_original()
    quote = quote.replace("20 million included", "20 million CPU milliseconds included per month")
    case, result, audit, seen, use = await publication_case(
        monkeypatch,
        source=quote,
        question="Example Product Compute Paid Standard 本月有2300万次请求，"
        + given
        + "，账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1])],
    )
    (entry,) = result["compact"]["conclusion_set"]["entries"]
    assert entry["candidate"]["rule"]["input_sufficient"] is sufficient
    answer = audit.answer_coverage[0]
    assert ("cpu_usage" not in answer.missing_fields) is sufficient
    assert ("已提供足以确定" in answer.answer) is sufficient
    assert answer.conclusion == "unknown" and answer.resolution == "insufficient"
    assert sum(n.endswith("atomic_generation") for n, _ in seen) == 1
    assert any(n.endswith("atomic_review") for n, _ in seen)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    authority = replay["decision_review"][answer.question_id]
    assert authority.matches(answer)
    assert authority.revision_sha256 == result["compact"]["conclusion_set"]["revision_sha256"]
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_period,input_period,sufficient",
    [
        ("2026年11月", "2026年11月", True),
        ("2026-11", "2026/11", True),
        ("2026年11月", "2026年12月", False),
        ("2026年11月", "2025年11月", False),
        ("本月", "2026年11月", False),
    ],
)
async def test_cpu_calendar_period_is_bound_to_request_not_source_capture(
    monkeypatch,
    requested_period,
    input_period,
    sufficient,
):
    from test_writer_question_delivery import billing_original

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    quote, conditions, table = billing_original()
    question = (
        f"Example Product Compute Paid Standard {requested_period}有2300万次请求，"
        f"{input_period} CPU 总用量为0毫秒，账单准确是多少美元？"
    )
    case, result, audit, _, use = await publication_case(
        monkeypatch,
        source=quote,
        question=question,
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1])],
    )
    entry = result["compact"]["conclusion_set"]["entries"][0]
    answer = audit.answer_coverage[0]
    assert entry["candidate"]["rule"]["input_sufficient"] is sufficient
    assert ("cpu_usage" not in answer.missing_fields) is sufficient
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replay["decision_review"][answer.question_id].matches(answer)
    await case[0].aclose()
