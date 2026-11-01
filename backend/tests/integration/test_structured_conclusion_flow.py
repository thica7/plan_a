"""Offline adapters only: real source review, publication, QA and journal replay."""

import json

import pytest
from test_conclusion_publication import publication_case


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["superseded", "keep"])
async def test_independent_final_qa_checks_same_revision_and_can_block(monkeypatch, verdict):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import (
        context_for,
        payload_from,
        receipt,
        traced_model_double,
    )

    from packages.agents.qa.question_reconciliation import reconcile_question_findings

    case, result, audit, _, use = await publication_case(monkeypatch)
    service, record, snapshot = case[:3]
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    assert service._final_qa_producer_verified(record, snapshot)
    seen = []

    async def model(record, **kwargs):
        p = payload_from(kwargs)
        seen.append(p)
        current = context_for(p, p["findings"][0])
        assert current["support_verified"] and current["publication_matches"]
        assert (
            current["conclusion_revision_sha256"]
            == result["compact"]["conclusion_set"]["revision_sha256"]
        )
        assert "条件推断" in current["visible_observations"]
        assert current["selected_source_context"][0]["quote"]
        assert len(kwargs["user"].encode()) <= 14000
        answer = json.loads(reviewed(p, verdict))
        if verdict == "keep":
            answer["reviews"][0].update(
                finding_fully_addressed=False,
                remaining_gaps=["Independent QA retains a source/condition objection."],
            )
        return json.dumps(answer)

    traced_model_double(monkeypatch, service, model)
    issues = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(seen) == 1
    output = receipt(record.detail)
    assert output["valid_review_issue_ids"] == output["planned_issue_ids"]
    assert bool(issues) == (verdict == "keep")
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(seen) == 1, "Unchanged same-revision QA must replay its actual transport"
    assert audit.answer_coverage[0].conclusion == "no"


async def mixed_publication_case(monkeypatch, *, publish_inferences):
    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_structured_conclusions import CONTRACT, QUESTION, SOURCE
    from test_task_clauses import clause_wire_response
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    question = QUESTION + "\nExample Product：小林在看板 A 和 B 都是 Observer；A 未启用投票，"
    question += "B 已启用投票。分别判断他能在 A、B 投票吗？"
    case = await atomic_case(
        [SOURCE, "Observers can vote on cards if card voting is enabled."], question=question
    )
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        seen.append((name, p))
        if name.endswith("support_selection"):
            task = p["tasks"][0]
            refs = [
                s["support_ref"]
                for f in p["evidence_view"]["facts"]
                for s in f["source_span_candidates"]
                if ("collections" in s["quote"]) == bool(task.get("request_property"))
            ]
            chosen = bool(refs) and task.get("request_property") != "people_limit"
            data = dict(
                selections=[
                    dict(
                        task_id=task["task_id"],
                        status="selected" if chosen else "insufficient_evidence",
                        binding_kind="span" if chosen else None,
                        support_refs=refs[:1] if chosen else [],
                    )
                ]
            )
        elif name == atomic.GENERATION_NAME:
            task = p["generation_tasks"][0]
            candidates = p.get("conclusion_candidates", [])
            if candidates:
                data = dict(
                    version=1,
                    task_id=task["task_id"],
                    status="selected",
                    candidate_ref=candidates[0]["candidate_ref"],
                )
            else:
                text = (
                    "看板 A 未启用卡片投票，因此小林在 A 上不能投票。"
                    if task.get("resource") == "A"
                    else "小林作为看板 B 的 Observer，因 B 已启用卡片投票，故可对 B 的卡片投票。"
                    if task.get("resource") == "B"
                    else p["task_support_selections"][0]["supports"][0]["quote"]
                )
                data = dict(
                    version=1,
                    task_id=task["task_id"],
                    status="generated",
                    atom=dict(
                        text=text,
                        kind="inference" if task.get("resource") else "fact",
                        support_refs=p["task_support_selections"][0]["support_refs"],
                    ),
                )
        elif name == atomic.REVIEW_NAME:
            data = clause_wire_response(
                p,
                dict(
                    reviews=[supported_review(c) for c in p["claims"]],
                    atomicity=[
                        dict(claim_id=c["id"], predicate_count=1, clauses=[]) for c in p["claims"]
                    ],
                ),
            )
        elif name == atomic.ANSWER_NAME:
            rows = []
            for task in p["tasks"]:
                outcome = (
                    "no"
                    if task.get("resource") == "A"
                    else "yes"
                    if task.get("resource") == "B"
                    else "rule"
                )
                chosen = publish_inferences and bool(task["support_choices"])
                rows.append(
                    dict(
                        task_id=task["task_id"],
                        outcome=outcome if chosen else "unknown",
                        support_refs=[r["ref"] for r in task["support_choices"] if r["primary"]]
                        if chosen
                        else [],
                        missing_fields=[],
                        reason="Independent task review.",
                    )
                )
            data = dict(version=1, task_reviews=rows)
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
        structured_conclusions_contract=CONTRACT,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
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
    return case, result, audit, seen


@pytest.mark.asyncio
@pytest.mark.parametrize("publish_inferences", [False, True])
async def test_mixed_scope_uses_one_observation_projection_with_tamper_controls(
    monkeypatch,
    publish_inferences,
):
    from packages.agents.qa.independent_question_review import _question_context
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.answer_presentation import observation_claims
    from packages.agents.writer.conclusion_publication import observations_match
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    case, result, audit, seen = await mixed_publication_case(
        monkeypatch, publish_inferences=publish_inferences
    )
    service, record, snapshot = case[:3]
    assert len(result["compact"]["conclusion_set"]["entries"]) == 1
    assert [a.status for a in audit.claims] == ["supported"] * 4
    inferences = [a for a in audit.claims if a.claim.kind == "inference"]
    assert len(inferences) == 2
    projected = {a.claim.id for a in observation_claims(record.detail, audit)}
    assert all((a.claim.id in projected) is publish_inferences for a in inferences)
    assert bool(audit.answer_coverage[1].claim_ids) is publish_inferences
    authorities = replay_decision_reviews(record.detail, audit)
    answer = audit.answer_coverage[0]
    assert authorities[answer.question_id].matches(answer)
    assert observations_match(record.detail, audit, authorities)
    question = case[6][0]["questions"][0]
    assert _answer_support(record.detail, snapshot, audit, answer, question)
    context = _question_context(
        service, record, snapshot, question, audit, verified=True, producer_verified=True
    )
    assert context["publication_matches"] and context["support_verified"]
    original = record.detail.report_md
    for changed in [
        original.replace("超过已核实上限", "没有超过已核实上限", 1),
        original.replace("#### 问题回答情况", "- 额外未发表推论。\n\n#### 问题回答情况", 1),
    ]:
        record.detail.report_md = changed
        assert not observations_match(record.detail, audit, authorities)
        assert _answer_support(record.detail, snapshot, audit, answer, question) is None
    record.detail.report_md = original
    assert any(name.endswith("atomic_review") for name, _ in seen)
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["extra", "status_list", "bool_version", "decline", "first_bad", "first_bad_json"]
)
async def test_rejected_typed_generation_is_local_and_valid_repair_can_publish(monkeypatch, fault):
    import test_task_support_selection as transport

    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    actual = transport.append_response
    attempts = []

    def response(service, record, kwargs, raw):
        data = json.loads(raw)
        if kwargs["name"].endswith("atomic_generation") and "candidate_ref" in data:
            attempts.append(data.copy())
            if fault == "extra" or fault == "first_bad" and len(attempts) == 1:
                data["answer"] = "Untrusted extra text."
            elif fault == "status_list":
                data["status"] = []
            elif fault == "bool_version":
                data["version"] = True
            elif fault == "decline":
                data.update(status="insufficient_evidence", candidate_ref=None)
            raw = json.dumps(data)
            if fault == "first_bad_json" and len(attempts) == 1:
                raw += " {}"
        return actual(service, record, kwargs, raw)

    monkeypatch.setattr(transport, "append_response", response)
    case, result, audit, _ = await mixed_publication_case(monkeypatch, publish_inferences=True)
    assert attempts and audit.answer_coverage[1].status == "answered"
    assert bool(result["compact"]["conclusion_set"]["entries"]) is (
        fault in {"first_bad", "first_bad_json"}
    )
    authorities = replay_decision_reviews(case[1].detail, audit)
    assert all(authorities[a.question_id].matches(a) for a in audit.answer_coverage)
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["support_selection", "atomic_generation", "atomic_review", "atomic_answer_review"]
)
@pytest.mark.parametrize("fault", ["duplicate", "multiple_roots", "json_value", "deep"])
async def test_new_scope_bad_raw_is_authenticated_local_failure_not_peer_loss(
    monkeypatch, stage, fault
):
    import test_question_atomic_delivery as cases
    import test_task_support_selection as transport
    from claim_review_fixture import expand_prompt_payload

    from packages.agents.writer.question_atomic_delivery import digest, replay_decision_reviews

    actual_case, actual_response = cases.atomic_case, transport.append_response
    corrupted = []

    async def peer_first(*args, **kwargs):
        first, second = kwargs["question"].split("\n", 1)
        kwargs["question"] = second + "\n" + first
        return await actual_case(*args, **kwargs)

    def response(service, record, kwargs, raw):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        tasks = p.get("generation_tasks") or p.get("tasks") or [p.get("task_context", {})]
        if kwargs["name"].endswith(stage) and any(
            t.get("request_property") == "container_limit" for t in tasks
        ):
            assert sum(s.name.endswith("atomic_review") for s in record.detail.trace_spans) >= 2
            duplicate_key = next(iter(json.loads(raw)))
            raw = (
                raw[:-1] + ',"' + duplicate_key + '":null}'
                if fault == "duplicate"
                else raw + " {}"
                if fault == "multiple_roots"
                else "[]"
            )
            if fault == "deep":
                raw = '{"unknown":' + "[" * 1100 + "0" + "]" * 1100 + "}"
            corrupted.append(raw)
        return actual_response(service, record, kwargs, raw)

    monkeypatch.setattr(cases, "atomic_case", peer_first)
    monkeypatch.setattr(transport, "append_response", response)
    case, result, audit, _ = await mixed_publication_case(monkeypatch, publish_inferences=True)
    assert corrupted and audit.answer_coverage[0].status == "answered"
    assert bool(result["compact"]["conclusion_set"]["entries"]) is (stage == "atomic_answer_review")
    failures = [d for d in result["compact"]["dispatches"] if d.get("structured_response_failure")]
    assert len(failures) == len(corrupted)
    for dispatch in failures:
        span = next(s for s in case[1].detail.trace_spans if s.id == dispatch["span_id"])
        assert span.full_output in corrupted and span.status == "ok"
        assert span.metadata["llm_transport_attempts"] == 1
        assert digest(span.full_output) == dispatch["full_output_sha256"]
        assert dispatch["structured_response_failure"] == json.loads(
            span.metadata["structured_response_failure_json"]
        )
    from packages.memory import RunJournal

    journal = RunJournal.in_memory()
    journal.save_run(case[1].detail)
    loaded = journal.load_run(case[1].detail.id)
    authorities = replay_decision_reviews(loaded, loaded.report_dimension_audits[0])
    assert all(authorities[a.question_id].matches(a) for a in audit.answer_coverage)
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["clarification", "all_deferred"])
async def test_actual_writer_zero_dispatch_validates_before_freeze_and_cold_replays(
    monkeypatch, mode
):
    from dataclasses import replace

    from test_question_atomic_delivery import atomic_case

    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    question = (
        "Example Product：我们准备把离职同事删掉，他保存的密码之后还会留下吗？"
        if mode == "clarification"
        else "Example Product：访客能导出文档吗？"
    )
    case = await atomic_case(
        ["Deleting an account permanently deletes all vault data."], question=question
    )
    service, record = case[:2]
    service._settings = replace(
        service._settings, writer_question_atomic_enabled=True, run_llm_max_tokens=1
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError("This actual local path has no admitted LLM request")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    record.detail.report_md = await service._writer_dimension_report_inner(record)
    audit = record.detail.report_dimension_audits[0]
    use = next(u for u in record.detail.evidence_consumptions if u.id == audit.consumption_id)
    assert use.status in {"validated", "reused"}
    receipt = json.loads(
        next(
            s.full_output for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
        )
    )
    assert receipt["dispatches"] == [] and receipt["conclusion_set"]["entries"] == []
    answer = audit.answer_coverage[0]
    assert answer.conclusion == ("depends" if mode == "clarification" else "unknown")
    assert answer.resolution == ("clarification" if mode == "clarification" else "unresolved")
    assert not answer.claim_ids and not answer.evidence_spans
    if mode == "clarification":
        from packages.agents.writer.request_clarification import server_clarification_answer

        assert answer == server_clarification_answer(case[6][0]["questions"][0])
        assert answer.status == "partial"
    assert replay_decision_reviews(record.detail, audit)[answer.question_id].matches(answer)
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["raw", "dispatch_witness", "span_witness", "missing_witness", "native", "claim_ids"]
)
async def test_persisted_failure_witness_cannot_self_authorize_tampering(
    monkeypatch, tmp_path, fault
):
    import test_task_support_selection as transport

    from packages.agents.writer.question_atomic_delivery import digest, replay_decision_reviews
    from packages.memory import RunJournal

    actual = transport.append_response

    def response(service, record, kwargs, raw):
        if kwargs["name"].endswith("atomic_generation") and "candidate_ref" in json.loads(raw):
            raw += " {}"
        return actual(service, record, kwargs, raw)

    monkeypatch.setattr(transport, "append_response", response)
    case, result, audit, _ = await mixed_publication_case(monkeypatch, publish_inferences=True)
    journal = RunJournal(tmp_path / "failure.db")
    journal.save_run(case[1].detail)
    loaded = journal.load_run(case[1].detail.id)
    assert replay_decision_reviews(loaded, loaded.report_dimension_audits[0])
    receipt_span = next(s for s in loaded.trace_spans if s.name == "question_atomic_delivery")
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(d for d in receipt["dispatches"] if d.get("structured_response_failure"))
    span = next(s for s in loaded.trace_spans if s.id == dispatch["span_id"])
    if fault == "raw":
        span.full_output = span.full_output.rsplit(" {}", 1)[0]
        dispatch["full_output_sha256"] = digest(span.full_output)
    elif fault == "dispatch_witness":
        dispatch["structured_response_failure"]["output_sha256"] = "0" * 64
    elif fault == "span_witness":
        span.metadata["structured_response_failure_json"] = '{"reason":"self-reported"}'
    elif fault == "missing_witness":
        dispatch.pop("structured_response_failure")
        span.metadata.pop("structured_response_failure_json")
    elif fault == "native":
        span.metadata["response_transport_identity"] = "0" * 64
        dispatch["native_transport"]["response_transport_identity"] = "0" * 64
    else:
        dispatch["claim_ids"] = [audit.claims[0].claim.id]
    receipt_span.full_output = json.dumps(receipt)
    changed = loaded.report_dimension_audits[0].model_copy(
        update={"question_atomic_receipt_digest": digest(receipt)}
    )
    loaded.report_dimension_audits = [changed]
    with pytest.raises(ValueError):
        replay_decision_reviews(loaded, changed)
    assert not result["compact"]["conclusion_set"]["entries"]
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["use", "source"])
async def test_zero_dispatch_freeze_rejects_invalid_evidence_through_real_guards(
    monkeypatch, fault
):
    from test_question_atomic_delivery import atomic_case

    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    case = await atomic_case(
        ["Deleting an account permanently deletes all vault data."],
        question="Example Product：我们准备把离职同事删掉，他保存的密码之后还会留下吗？",
    )
    service, record, _, selected, view, use, packets, boundaries, allowed = case

    async def forbidden(*args, **kwargs):
        raise AssertionError("Canonical local clarification must not call an LLM")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    result = await execute_question_atomic_delivery(
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
        task_clause_contract="semantic-target-clauses-v2",
        structured_conclusions_contract="structured-conclusions-v1",
    )
    if fault == "use":
        use = use.model_copy(update={"workspace_id": "foreign"})
    else:
        record.detail.evidence_inputs_dirty = True
    with pytest.raises(ValueError, match="evidence"):
        await service._dimension_question_coverage(
            record, packets[0]["questions"], result["compact"], (), view, use, ()
        )
    assert "conclusion_set" not in result["compact"]
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape", ["shallow_field", "deep_field", "deep_unclosed", "deep_array", "repair"]
)
async def test_deep_raw_stays_local_with_real_peer_journal_and_tamper_checks(
    monkeypatch, tmp_path, shape
):
    import test_question_atomic_delivery as cases
    import test_task_support_selection as transport

    from packages.agents.writer.question_atomic_delivery import digest, replay_decision_reviews
    from packages.memory import RunJournal

    actual_case, actual_response = cases.atomic_case, transport.append_response
    bad = []

    async def peer_first(*args, **kwargs):
        first, second = kwargs["question"].split("\n", 1)
        kwargs["question"] = second + "\n" + first
        return await actual_case(*args, **kwargs)

    def response(service, record, kwargs, raw):
        data = json.loads(raw)
        if (
            kwargs["name"].endswith("atomic_generation")
            and "candidate_ref" in data
            and not (shape == "repair" and bad)
        ):
            assert sum(s.name.endswith("atomic_review") for s in record.detail.trace_spans) >= 3
            depth = 1 if shape == "shallow_field" else 1100
            nested = "[" * depth + "0"
            if shape != "deep_unclosed":
                nested += "]" * depth
            raw = (
                nested
                if shape == "deep_array"
                else json.dumps({"version": 1, "task_id": data["task_id"], "status": "selected"})[
                    :-1
                ]
                + ',"candidate_ref":'
                + nested
                + ("" if shape == "deep_unclosed" else "}")
            )
            assert len(raw.encode()) < 2500 and kwargs["max_output_tokens"] == 1600
            bad.append(raw)
        return actual_response(service, record, kwargs, raw)

    monkeypatch.setattr(cases, "atomic_case", peer_first)
    monkeypatch.setattr(transport, "append_response", response)
    case, result, audit, _ = await mixed_publication_case(monkeypatch, publish_inferences=True)
    assert bad and audit.answer_coverage[0].status == "answered"
    assert bool(result["compact"]["conclusion_set"]["entries"]) is (shape == "repair")
    failures = [d for d in result["compact"]["dispatches"] if d.get("structured_response_failure")]
    assert len(failures) == (0 if shape == "shallow_field" else len(bad))
    for dispatch in failures:
        span = next(s for s in case[1].detail.trace_spans if s.id == dispatch["span_id"])
        assert span.full_output in bad and span.status == "ok"
        witness = dispatch["structured_response_failure"]
        assert witness["output_sha256"] == digest(span.full_output)
        assert witness == json.loads(span.metadata["structured_response_failure_json"])
    journal = RunJournal(tmp_path / "deep.db")
    journal.save_run(case[1].detail)
    loaded = journal.load_run(case[1].detail.id)
    authority = replay_decision_reviews(loaded, loaded.report_dimension_audits[0])
    assert all(authority[a.question_id].matches(a) for a in audit.answer_coverage)
    if failures:
        receipt_span = next(s for s in loaded.trace_spans if s.name == "question_atomic_delivery")
        receipt = json.loads(receipt_span.full_output)
        dispatch = next(d for d in receipt["dispatches"] if d.get("structured_response_failure"))
        span = next(s for s in loaded.trace_spans if s.id == dispatch["span_id"])
        span.full_output = "{}"
        dispatch["full_output_sha256"] = digest(span.full_output)
        receipt_span.full_output = json.dumps(receipt)
        changed = loaded.report_dimension_audits[0].model_copy(
            update={"question_atomic_receipt_digest": digest(receipt)}
        )
        loaded.report_dimension_audits = [changed]
        with pytest.raises(ValueError):
            replay_decision_reviews(loaded, changed)
    await case[0].aclose()
