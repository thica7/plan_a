"""V3 scheduling and transport doubles; these do not measure semantic accuracy."""

import hashlib
import json

import pytest
from claim_review_fixture import expand_prompt_payload
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_support_selection import append_response


def test_legacy_generation_and_answer_systems_are_byte_compatible():
    from packages.agents.writer.question_atomic_delivery import (
        ANSWER_NAME,
        GENERATION_NAME,
        atomic_system,
    )

    expected = {
        1: "a5c0d0a58490b2a65494742306bc22aa173ffee78c41cda973a9c1d6747016ee",
        2: "f337f7bbe7480f57c8aa5a7d825b44ff8fcd057c5acc1188131d69154ca4c74a",
    }
    for version, digest in expected.items():
        assert (
            hashlib.sha256(
                atomic_system(GENERATION_NAME, "en", generation_projection_version=version).encode()
            ).hexdigest()
            == digest
        )
    assert hashlib.sha256(atomic_system(ANSWER_NAME, "en").encode()).hexdigest() == (
        "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb"
    )


def test_v3_generation_explains_independent_actors_rows_counts_and_billing():
    from packages.agents.writer.question_atomic_delivery import GENERATION_NAME, atomic_system

    current = atomic_system(GENERATION_NAME, "en", generation_projection_version=3)
    for guidance in (
        "independent permission actors",
        "complete permission row",
        "same-unit cap",
        "separate conditional inference",
        "known billing components",
        "permission alone does not entail obligation",
    ):
        assert guidance in current
    assert "independent permission actors" not in atomic_system(GENERATION_NAME, "en")


@pytest.mark.asyncio
@pytest.mark.parametrize("billing", [False, True])
async def test_only_v3_reserves_independent_rules_without_changing_v2_payload(billing):
    from packages.agents.writer.question_atomic_delivery import (
        atomic_question_context,
        parse_atomic_generation,
    )

    texts = (
        [
            "The Standard model includes 30 million CPU milliseconds per month.",
            "Additional CPU time costs $0.02 per million milliseconds.",
            "The plan has a $5 monthly minimum.",
        ]
        if billing
        else [
            "Free organizations support at most 2 users.",
            "Free organizations support at most 2 collections.",
        ]
    )
    question = (
        "Example Product: What are the known monthly bill components?"
        if billing
        else "Example Product：免费组织能满足3名用户使用3个collections吗？"
    )
    case = await atomic_case(texts, question=question)
    service, record, _, _, view, use, packets, _, allowed = case
    args = service, record, view, packets, packets[0]["questions"][0], allowed, use
    legacy = atomic_question_context(*args, generation_projection_version=2)
    current = atomic_question_context(*args, generation_projection_version=3)
    assert all(task["max_claims"] == 1 for task in legacy["generation_tasks"])
    assert all(task["max_claims"] == (3 if billing else 2) for task in current["generation_tasks"])
    assert legacy == atomic_question_context(*args, generation_projection_version=2)
    assert [t["task_id"] for t in current["generation_tasks"]] == [
        t["task_id"] for t in legacy["generation_tasks"]
    ]
    refs = {
        span["quote"]: span["support_ref"]
        for fact in current["evidence_view"]["facts"]
        for span in fact["source_span_candidates"]
    }
    atoms = []
    for task in current["generation_tasks"]:
        chosen = (
            texts if billing else [texts[0 if task["request_property"] == "people_limit" else 1]]
        )
        for text in chosen:
            atoms.append(
                dict(task_id=task["task_id"], text=text, kind="fact", support_refs=[refs[text]])
            )
        if not billing:
            text = chosen[0]
            scenario = (
                "题设3名用户的需求不能由最多支持2名用户的免费组织满足。"
                if task["request_property"] == "people_limit"
                else "题设3个collections的需求不能由最多支持2个collections的免费组织满足。"
            )
            atoms.append(
                dict(
                    task_id=task["task_id"],
                    text=scenario,
                    kind="inference",
                    support_refs=[refs[text]],
                )
            )
    response = json.dumps(
        dict(
            question_plans=[
                dict(
                    question_id=packets[0]["questions"][0]["question_id"],
                    missing_fields=current["question_plan_missing_fields"][0]["missing_fields"],
                    atoms=atoms,
                )
            ]
        )
    )
    claims, gaps, _ = parse_atomic_generation(response, current, view, use)
    assert len(claims) == (3 if billing else 4), gaps
    assert len(claims) <= 8


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_actual_numeric_generation_review_coverage_render_and_replay(monkeypatch, partial):
    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.agents.writer.answer_coverage import coverage_resolution_reasons
    from packages.agents.writer.answer_presentation import question_coverage_matches
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    caps = [
        "Free organization 最多支持 2 名用户（含所有者）。",
        "Free organization 最多支持 2 个 collections。",
    ]
    scenarios = [
        "题设3名用户的需求不能由最多支持2名用户的免费组织满足。",
        "题设3个collections的需求不能由最多支持2个collections的免费组织满足。",
    ]
    numeric_question = "Example Product：免费组织能满足3名用户使用3个collections吗" + (
        "；" if partial else "？"
    )
    question = numeric_question + ("完整账单是多少？" if partial else "")
    case = await atomic_case(caps, question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    raw_outputs = {}

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            refs = {
                span["quote"]: span["support_ref"]
                for fact in payload["evidence_view"]["facts"]
                for span in fact["source_span_candidates"]
            }
            atoms = []
            for task in payload["generation_tasks"]:
                if not task.get("request_property"):
                    continue  # The full bill is not established by these facts.
                index = 0 if task["request_property"] == "people_limit" else 1
                atoms.extend(
                    dict(
                        task_id=task["task_id"],
                        text=text,
                        kind=kind,
                        support_refs=[refs[caps[index]]],
                    )
                    for text, kind in [(caps[index], "fact"), (scenarios[index], "inference")]
                )
            response = dict(
                question_plans=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        missing_fields=payload["question_plan_missing_fields"][0]["missing_fields"],
                        atoms=atoms,
                    )
                ]
            )
        elif kwargs["name"] == atomic.REVIEW_NAME:
            response = dict(reviews=[supported_review(c) for c in payload["claims"]])
        else:
            assert kwargs["name"] == atomic.ANSWER_NAME
            ids = [c["id"] for c in payload["claims"]]
            split = numeric_question.index("使用")
            branches = [
                dict(
                    question_quote=part,
                    claim_ids=[c["id"] for c in payload["claims"] if marker in c["text"]],
                    conclusion="no",
                    relation="upper_bound",
                )
                for part, marker in (
                    (numeric_question[:split], "用户"),
                    (numeric_question[split:], "collections"),
                )
            ]
            if partial:
                branches.append(
                    dict(
                        question_quote="完整账单是多少？",
                        claim_ids=[],
                        conclusion="unknown",
                        relation="unresolved",
                    )
                )
            response = dict(
                version=3,
                answers=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        status="partial" if partial else "answered",
                        claim_ids=ids,
                        resolution="conditional",
                        conclusion="depends" if partial else "no",
                        missing_fields=[],
                        reason="Offline selection fixture.",
                        subquestions=branches,
                    )
                ],
            )
        encoded = json.dumps(response)
        raw_outputs.setdefault(kwargs["name"], []).append(encoded)
        return append_response(service, record, kwargs, encoded)

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
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert len(audited) == 4 and all(c.status == "supported" for c in audited)
    supported = [c.claim for c in audited]
    coverage, _, _ = await atomic.atomic_answer_coverage(
        service,
        record,
        packets[0]["questions"],
        result["compact"],
        supported,
        view,
        use,
        result["gaps"],
    )
    assert coverage[0].status == ("partial" if partial else "answered"), coverage[0].reason
    assert not coverage_resolution_reasons(
        coverage[0],
        [c.model_dump(mode="json") for c in supported],
        facts=view.facts,
        require_subquestions=True,
    )
    audit = ReportDimensionAudit(
        competitor=view.competitor,
        dimension=view.dimension,
        consumption_id=use.id,
        claims=audited,
        answer_coverage=coverage,
    )
    report = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert all(text in report for text in [*caps, *scenarios])
    assert question_coverage_matches(
        report, audit, record.detail.output_language, audits=[audit], detail=record.detail
    )
    branch_lines = [line for line in report.splitlines() if line.startswith("  - ")]
    assert len(branch_lines) == (3 if partial else 2)
    for binding, line in zip(coverage[0].subquestion_bindings, branch_lines, strict=True):
        sources = {
            sid for claim in supported if claim.id in binding.claim_ids for sid in claim.source_ids
        }
        all_sources = {sid for claim in supported for sid in claim.source_ids}
        assert binding.question_quote in line
        assert all(f"[source:{sid}]" in line for sid in sources)
        assert all(f"[source:{sid}]" not in line for sid in all_sources - sources)
    if partial:
        unknown = next(
            line
            for line in report.splitlines()
            if "完整账单是多少？" in line and "结论：尚不能确定" in line
        )
        assert "[source:" not in unknown
    current_use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    restored = atomic.replay_atomic_delivery(service, record.detail, snapshot, current_use, view)
    assert restored["answers"][coverage[0].question_id] == coverage[0]
    assert all(
        span.full_output in raw_outputs[span.name]
        for span in record.detail.trace_spans
        if span.name in raw_outputs
    )
