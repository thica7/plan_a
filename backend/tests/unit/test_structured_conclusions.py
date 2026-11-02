"""Finite source facts precede program conclusions; model text is never authority."""

import json

import pytest

CONTRACT = "structured-conclusions-v1"
SOURCE = (
    "Free organizations offer both users all the core features of Password Manager "
    "and secure data sharing in up to 2 collections."
)
QUESTION = "Example Product：Free organization 能否让 3 人在 3 个 collections 中安全共享数据？"


async def selected_payload(*, source=SOURCE, question=QUESTION):
    from test_question_atomic_delivery import atomic_case

    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.selected_task_delivery import (
        candidate_context,
        generation_context,
        selection_context,
    )
    from packages.research.question_scope import research_questions

    case = await atomic_case([source], question=question)
    service, record, _, _, view, use, packets, _, allowed = case
    q = research_questions(record.detail, view.competitor, view.dimension)[0]
    tasks = generation_tasks(q, f"{view.competitor}/{view.dimension}")
    task = next(t for t in tasks if t.get("request_property") == "container_limit")
    candidate = candidate_context(
        service,
        record,
        view,
        packets,
        q,
        allowed,
        use,
        task["task_id"],
        execution_policy="selected-task-atoms-v3",
        task_clause_contract="semantic-target-clauses-v2",
    )
    candidate["structured_conclusions_contract"] = CONTRACT
    _, choices = selection_context(candidate, view)
    ref = next(iter(choices))
    selections = {task["task_id"]: dict(state="selected", binding_kind="span", support_refs=[ref])}
    return case, generation_context(candidate, selections, choices, service, record, packets)


@pytest.mark.asyncio
async def test_selected_quantity_builds_server_candidate_and_gen_can_only_select_it():
    from packages.agents.writer.selected_task_delivery import parse_generation

    case, payload = await selected_payload()
    candidates = payload.get("conclusion_candidates", [])
    assert len(candidates) == 1, "Selected cap must become a server-owned candidate before GEN"
    candidate = candidates[0]
    assert candidate["relation"] == "quantity_upper_bound"
    assert candidate["rule"] == dict(unit="collections", maximum=2, required=3, operation="share")
    assert "3" not in candidate["source_fact_text"]
    response = json.dumps(
        dict(
            version=1,
            task_id=candidate["task_id"],
            status="selected",
            candidate_ref=candidate["candidate_ref"],
        )
    )
    claims, _, _ = parse_generation(response, payload, case[4], case[5])
    assert len(claims) == 1 and claims[0].kind == "fact"
    assert claims[0].text == candidate["source_fact_text"]


@pytest.mark.asyncio
async def test_model_cannot_supply_text_verdict_numbers_versions_refs_or_ambiguous_json():
    from copy import deepcopy

    from packages.agents.writer.selected_task_delivery import parse_generation

    case, payload = await selected_payload()
    candidate = payload["conclusion_candidates"][0]
    good = dict(
        version=1,
        task_id=candidate["task_id"],
        status="selected",
        candidate_ref=candidate["candidate_ref"],
    )
    mutations = [
        dict(good, **{key: value})
        for key, value in [
            ("text", "No"),
            ("verdict", "supported"),
            ("verified", True),
            ("maximum", 999),
            ("version", True),
            ("task_id", "foreign"),
            ("candidate_ref", "unknown"),
            ("candidate_ref", [candidate["candidate_ref"]]),
            ("status", "generated"),
            ("status", []),
            ("status", {}),
            ("candidate_ref", {}),
            ("candidate_ref", True),
        ]
    ]
    invalid = [json.dumps(row) for row in mutations]
    invalid += [
        json.dumps(good) + " {}",
        '{"version":1,"version":1}',
        "[]",
        json.dumps(dict(good, candidate_ref=None)),
    ]
    for raw in invalid:
        with pytest.raises(ValueError):
            parse_generation(raw, payload, case[4], case[5])
    for field in ("rule", "task_id", "source_binding_sha256", "snapshot_id"):
        bad = deepcopy(payload)
        bad["conclusion_candidates"][0][field] = "tampered"
        with pytest.raises(ValueError):
            parse_generation(json.dumps(good), bad, case[4], case[5])
    declined = dict(good, status="insufficient_evidence", candidate_ref=None)
    claims, _, _ = parse_generation(json.dumps(declined), payload, case[4], case[5])
    assert not claims


@pytest.mark.asyncio
async def test_quantity_rejects_descriptive_counts_conditions_units_plan_or_and_below_cap():
    from copy import deepcopy

    from packages.agents.writer.structured_conclusions import build_candidates

    _, payload = await selected_payload()
    for source in [
        SOURCE.replace("up to 2", "2"),
        SOURCE + " If support approves.",
        SOURCE.replace("Free organizations", "Enterprise organizations"),
        SOURCE.replace("2 collections", "2 users"),
    ]:
        changed = deepcopy(payload)
        row = changed["evidence_view"]["facts"][0]
        row.update(quote=source, value=[source])
        row["source_span_candidates"][0]["quote"] = source
        changed["task_support_selections"][0]["supports"][0]["quote"] = source
        assert not build_candidates(changed), source
    for question in [
        QUESTION.replace("3 个", "1 个"),
        QUESTION + " Or Enterprise?",
        QUESTION.replace("Free organization", "Enterprise organization"),
    ]:
        changed = deepcopy(payload)
        changed["request_context"]["parents"][0]["text"] = question
        if "1 个" in question:
            changed["generation_tasks"][0]["question_quote"] = "1 个 collections"
        assert not build_candidates(changed), question
    changed = deepcopy(payload)
    changed["generation_tasks"][0].pop("request_property")
    assert not build_candidates(changed)
    changed = deepcopy(payload)
    changed["request_context"]["bindings"][0]["question_id"] = "another-question"
    assert not build_candidates(changed)


@pytest.mark.asyncio
async def test_fresh_selector_preserves_existing_scope_and_legacy_system():
    from types import SimpleNamespace

    from packages.agents.writer.selected_task_delivery import task_system
    from packages.agents.writer.structured_conclusions import fresh_contract

    scope = "Example/feature"
    assert fresh_contract(SimpleNamespace(trace_spans=[]), scope) == "structured-conclusions-v2"
    for value in (None, CONTRACT):
        receipt = dict(
            task_execution_policy="selected-task-atoms-v3",
            task_clause_contract="semantic-target-clauses-v2",
        )
        if value:
            receipt["structured_conclusions_contract"] = value
        span = SimpleNamespace(
            subagent=scope, name="question_atomic_delivery", full_output=json.dumps(receipt)
        )
        assert fresh_contract(SimpleNamespace(trace_spans=[span]), scope) == value
    legacy = task_system(
        "dimension_question_atomic_generation",
        "zh-CN",
        "selected-task-atoms-v3",
        "semantic-target-clauses-v2",
    )
    assert legacy == task_system(
        "dimension_question_atomic_generation",
        "zh-CN",
        "selected-task-atoms-v3",
        "semantic-target-clauses-v2",
        None,
    )
    assert "candidate_ref" not in legacy


@pytest.mark.asyncio
async def test_billing_candidates_keep_complete_selected_cpu_cell_and_reject_other_cells():
    from copy import deepcopy

    from test_task_target_delivery import target_case

    from packages.agents.writer.structured_conclusions import build_candidates

    _, _, payload = await target_case(semantic_contract=True)
    payload["structured_conclusions_contract"] = CONTRACT
    candidates = build_candidates(payload)
    assert len(candidates) == 1 and candidates[0]["relation"] == "billing_input_gap"
    candidate = candidates[0]
    assert candidate["rule"]["meter"] == "cpu_time"
    assert "$" not in candidate["source_fact_text"] and "Max" not in candidate["source_fact_text"]
    original = payload["evidence_view"]["facts"][0]["quote"]
    assert "CPU" in original
    for source in [
        original.replace("$0.03", "$0"),
        original.replace("$0.03", "-$0.02"),
        original.replace("CPU milliseconds", "requests"),
        original.replace("$0.03", "No charge $0.02"),
        original.replace("Standard", "Unknown"),
        "CPU time max of 5 minutes per invocation.",
    ]:
        bad = deepcopy(payload)
        row = bad["evidence_view"]["facts"][0]
        row.update(quote=source, value=[source])
        row["source_span_candidates"][0]["quote"] = source
        bad["task_support_selections"][0]["supports"][0]["quote"] = source
        assert not build_candidates(bad), source
    bad = deepcopy(payload)
    bad["evidence_view"]["facts"][0]["qualifiers"].pop("table_context")
    assert not build_candidates(bad)


@pytest.mark.asyncio
async def test_sufficient_cpu_input_is_total_fee_or_reliable_same_period_bound():
    from types import SimpleNamespace

    from test_task_target_delivery import target_case

    from packages.agents.writer.structured_conclusions import cpu_cost_input_sufficient

    _, _, payload = await target_case(semantic_contract=True)
    row = payload["evidence_view"]["facts"][0]
    fact = SimpleNamespace(**{k: row[k] for k in ("quote", "value", "qualifiers")})
    fact.quote = fact.quote.replace(
        "20 million included", "20 million CPU milliseconds included per month"
    )
    base = "Example Product Compute Paid Standard 本月有2300万次请求，"
    for given in [
        "CPU 总用量为0毫秒",
        "CPU total usage is 30000000 ms",
        "CPU费用已知为 USD 0",
        "可靠可计费CPU总用量上界为 1 million milliseconds",
    ]:
        assert cpu_cost_input_sufficient(base + given, fact), given
    for given in [
        "每次调用 CPU limit为5分钟",
        "可靠可计费CPU总用量上界为 100 billion milliseconds",
        "可能CPU 总用量为0毫秒",
        "上月 CPU 总用量为0毫秒",
        "其他项目 CPU 费用已知为 USD 0",
        "可靠单次CPU总用量上界为1毫秒",
    ]:
        assert not cpu_cost_input_sufficient(base + given, fact), given


@pytest.mark.asyncio
async def test_new_source_fact_uses_output_language_without_changing_original():
    _, payload = await selected_payload()
    candidate = payload["conclusion_candidates"][0]
    assert "最多支持" in candidate["source_fact_text"]
    assert "collections" in candidate["source_fact_text"]
    assert payload["task_support_selections"][0]["supports"][0]["quote"] == SOURCE


def test_unknown_or_mixed_saved_selector_fails_closed_before_resuming():
    from types import SimpleNamespace

    from packages.agents.writer.structured_conclusions import fresh_contract

    def span(value):
        payload = dict(
            task_execution_policy="selected-task-atoms-v3",
            task_clause_contract="semantic-target-clauses-v2",
        )
        if value is not None:
            payload["structured_conclusions_contract"] = value
        return SimpleNamespace(
            name="question_atomic_delivery",
            subagent="Example/feature",
            full_output=json.dumps(payload),
        )

    for spans in [[span("unknown")], [span(None), span(CONTRACT)], [span(True)]]:
        with pytest.raises(ValueError):
            fresh_contract(SimpleNamespace(trace_spans=spans), "Example/feature")
