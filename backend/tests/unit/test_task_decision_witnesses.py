"""Pure decision contracts: real source language, synthetic offline transports."""

from __future__ import annotations

import importlib
import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from claim_review_fixture import supported_review

from packages.agents.writer import question_atomic_delivery as atomic
from packages.research.evidence.answer_coverage_models import AnswerSubquestionBinding
from packages.research.evidence.report_claims import (
    AuditedReportClaim,
    ClaimReview,
    required_claim_checks,
)
from packages.research.evidence.snapshot_models import EvidenceFact
from packages.research.evidence.source_spans import source_span_candidates

MODULE = "packages.agents.writer.task_decision_witnesses"
SOURCE = (
    "Free organizations offer both users all the core features of Password Manager "
    "and secure data sharing in up to two collections."
)
QUESTION = (
    "Bitwarden: 我们都在 2026 年新建了 Bitwarden 账户，并建立一个 Free organization，"
    "想让包括我在内的 3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？"
)
INFERENCE = (
    "由于 Free organization 最多支持两个 collections，而场景要求使用 3 个 collections，"
    "因此该免费组织无法满足 3 个 collections 的共享需求。"
)
RESOURCE_SOURCE = (
    "Because an observer is a board member permission it isn't currently possible "
    "to set a user as an observer at the\nWorkspace\nlevel, and each observer is set "
    "individually per member per board."
)
RESOURCE_QUESTION = (
    "Trello: 假设某 Trello Workspace 已订阅 Premium，管理员把看板 A 上现有协作者"
    "小周的权限改成了 Observer。同一 Workspace 另有看板 B，但题设没有说明小周是否"
    "加入 B、在 B 上的权限，或他属于 Workspace 成员还是哪一种 guest。仅依据所给页面，"
    "逐项回答：A 上这次改权是否自动决定他在 B 的权限；"
    "只凭 A 上的 Observer 标签，能否确定他一定免费或一定计费？"
)
RESOURCE_TASK = "A 上这次改权是否自动决定他在 B 的权限"
RESOURCE_INFERENCE = (
    "看板 A 上的 Observer 权限是按成员、按看板单独设置的，因此仅凭 A 上这次改权"
    "不能确定小周在看板 B 上的权限。"
)


def helper():
    assert importlib.util.find_spec(MODULE) is not None, (
        "decision witness helper is not implemented"
    )
    return importlib.import_module(MODULE)


def make_case(
    *,
    source=SOURCE,
    question=QUESTION,
    text=INFERENCE,
    task_quote="3 个 collections",
    prop="container_limit",
    competitor="Bitwarden",
    parent_quote=None,
    parent_values=None,
    qualifiers=None,
):
    module = helper()
    fact = EvidenceFact(
        id="f",
        semantic_id="sf",
        source_id="s",
        competitor=competitor,
        dimension="feature",
        field="evidence_terms",
        value_json=json.dumps(parent_values if parent_values is not None else [source]),
        quote=parent_quote or source,
        qualifiers_json=json.dumps(qualifiers or {}),
        status="supported",
        confidence=1,
    )
    task = dict(
        task_id="task-current",
        question_id="q",
        question_quote=task_quote,
        focus="source_rule",
        state="planned",
        max_claims=2,
        task_instruction="current task",
    )
    if prop:
        task["request_property"] = prop
    request = dict(
        version=2,
        purpose="request_only_not_evidence",
        parents=[dict(parent_id="p", text=question)],
        bindings=[dict(question_id="q", parent_id="p")],
        unbound_question_ids=[],
    )
    common = dict(
        consumption_id="use",
        snapshot_id="snapshot",
        segment_competitor=competitor,
        dimension="feature",
        questions=[dict(question_id="q", question=question)],
        request_context=request,
    )
    spans = source_span_candidates(fact)
    selected = next((span["quote"] for span in spans if span["quote"] == source), spans[0]["quote"])
    row = dict(
        id=fact.id,
        source_id=fact.source_id,
        competitor=competitor,
        dimension="feature",
        field=fact.field,
        quote=fact.quote,
        value=fact.value,
        qualifiers={k: v for k, v in fact.qualifiers.items() if k != "operations"},
        operation_observations=[],
        operation_support_refs=[],
        source_span_candidates=[dict(quote=selected, support_ref="s1")],
    )
    payload = dict(
        common,
        generation_projection_version=5,
        generation_tasks=[task],
        question_plan_missing_fields=[dict(question_id="q", missing_fields=[])],
        evidence_view=dict(facts=[row]),
    )
    raw = json.dumps(
        dict(
            question_plans=[
                dict(
                    question_id="q",
                    missing_fields=[],
                    atoms=[
                        dict(
                            task_id=task["task_id"],
                            text=text,
                            kind="inference",
                            support_refs=["s1"],
                        )
                    ],
                )
            ]
        )
    )
    view, use = SimpleNamespace(facts=(fact,)), SimpleNamespace(id="use")
    claims, _, plans = atomic.parse_atomic_generation(raw, payload, view, use)
    assert len(claims) == 1, plans
    claim = claims[0]
    review_claim = dict(
        claim.model_dump(mode="json"),
        required_checks=required_claim_checks(claim),
        support_quotes=[binding.quote for binding in claim.source_span_bindings],
    )
    review_payload = dict(
        common,
        review_projection_version=3,
        claims=[review_claim],
        question_answer_plans=plans,
        constraint_context=[],
    )
    review = supported_review(review_claim)
    review["support_witnesses"] = [dict(support_index=0, quote=claim.source_span_bindings[0].quote)]
    review_raw = json.dumps(dict(reviews=[review]))
    reviews = atomic.parse_atomic_reviews(
        review_raw, claims, payload=review_payload, review_projection_version=3
    )
    assert len(reviews) == 1
    spans, dispatches, expected = [], [], {}
    for sid, name, agent, value, output in (
        ("gen", atomic.GENERATION_NAME, "writer", payload, raw),
        ("review", atomic.REVIEW_NAME, "qa", review_payload, review_raw),
    ):
        system = atomic.atomic_system(
            name, "zh-CN", review_projection_version=3, generation_projection_version=5
        )
        span = make_span(sid, name, agent, competitor, system, value, output)
        spans.append(span)
        dispatches.append(
            atomic.dispatch_row(span, question_ids=["q"], claim_ids=[claim.id], fact_ids=[fact.id])
        )
        expected[sid] = (system, deepcopy(value))
    plan = {}
    atomic.merge_generation_plan(plan, plans[0], attempt=0)
    compact = dict(
        generation_projection_version=5,
        review_projection_version=3,
        consumption_id="use",
        snapshot_id="snapshot",
        dispatches=dispatches,
        question_answer_plans=[plan],
    )
    context = module.TaskDecisionContext(
        consumption_id="use",
        snapshot_id="snapshot",
        competitor=competitor,
        dimension="feature",
        questions=tuple(common["questions"]),
        request_context=deepcopy(request),
        facts=(fact,),
        audited_claims=(AuditedReportClaim(claim=claim, status="supported", review=reviews[0]),),
        compact=compact,
        trace_spans=tuple(spans),
        expected_inputs=expected,
    )
    return context


def make_span(sid, name, agent, competitor, system, payload, output):
    from packages.agents.writer.dimension_writer import compact_prompt_json

    return SimpleNamespace(
        id=sid,
        name=name,
        agent=agent,
        kind="llm",
        status="ok",
        subagent=f"{competitor}/feature",
        metadata={"llm_transport_attempts": 1},
        full_input=system + "\n\n\nJSON:\n" + compact_prompt_json(payload),
        full_output=output,
    )


def resource_case(**kwargs):
    return make_case(
        source=RESOURCE_SOURCE,
        question=RESOURCE_QUESTION,
        text=RESOURCE_INFERENCE,
        task_quote=RESOURCE_TASK,
        prop=None,
        competitor="Trello",
        **kwargs,
    )


def answer_case(context, *, fulfilled=True, grounding="supported", conclusion="no",
                projection_version=1):
    module = helper()
    candidates = module.build_decision_candidates(context)
    assert len(candidates) == 1
    candidate = candidates[0]
    payload = dict(
        consumption_id=context.consumption_id,
        snapshot_id=context.snapshot_id,
        segment_competitor=context.competitor,
        dimension=context.dimension,
        questions=list(context.questions),
        request_context=context.request_context,
        answer_review_contract="subquestion-premises-v6",
        decision_candidates=[candidate.review_payload(projection_version=projection_version)],
    )
    if projection_version == 2:
        payload["decision_candidate_projection_version"] = 2
    decision = dict(
        candidate_ref=candidate.candidate_ref,
        task_fulfilled=fulfilled,
        target_grounding=grounding,
        conclusion=conclusion,
        evidence_refs=list(candidate.evidence_refs),
        scenario_refs=list(candidate.scenario_refs),
    )
    output = json.dumps(dict(version=3, answers=[], task_decisions=[decision]))
    system = "Test future independent ANSWER system subquestion-premises-v6."
    span = make_span(
        "answer", atomic.ANSWER_NAME, "qa", context.competitor, system, payload, output
    )
    dispatch = atomic.dispatch_row(
        span,
        question_ids=["q"],
        claim_ids=[candidate.claim_id],
        fact_ids=[f.id for f in context.facts],
    )
    updated = replace(
        context,
        trace_spans=(*context.trace_spans, span),
        expected_inputs={**context.expected_inputs, span.id: (system, deepcopy(payload))},
    )
    return updated, dispatch


def test_real_bw_collections_inference_is_candidate_without_an_extra_cap_fact():
    context = make_case()
    (candidate,) = helper().build_decision_candidates(context)
    assert candidate.witness_kind == "quantity_excess"
    assert candidate.witness == dict(unit="collections", maximum=2, required=3, operation="share")
    assert context.audited_claims[0].claim.kind == "inference"
    assert candidate.review_payload()["claim"]["text"] == INFERENCE
    assert candidate.evidence_refs and candidate.scenario_refs


def test_candidate_v2_projection_keeps_semantics_and_legacy_default():
    (candidate,) = helper().build_decision_candidates(make_case())
    legacy = candidate.review_payload()
    assert legacy == candidate.model_dump(mode="json", exclude={"binding_sha256"})
    projected = candidate.review_payload(projection_version=2)
    assert projected == {k: v for k, v in legacy.items() if k not in {"claim", "sources"}} | {
        "sources": [{k: v for k, v in s.items()
                     if k in {"source_ref", "fact_id", "source_id", "quote"}}
                    for s in legacy["sources"]]}
    assert candidate.review_payload() == legacy


@pytest.mark.parametrize("version", [True, False, 0, 3, "2", 2.0, None])
def test_candidate_projection_version_is_a_known_integer(version):
    (candidate,) = helper().build_decision_candidates(make_case())
    with pytest.raises(ValueError, match="projection"):
        candidate.review_payload(projection_version=version)


def test_decision_selection_policy_requires_explicit_known_wire_selection():
    selector = helper().decision_selection_policy
    assert selector({}) is None
    assert selector({'decision_selection_policy': 'approved_quantity_core-v1'}) == (
        'approved_quantity_core-v1')


@pytest.mark.parametrize('marker', [None, True, False, 0, 1, 1.0, '', [], {},
                                  'approved_quantity_core-v2'])
def test_unknown_decision_selection_policy_is_not_a_qualification(marker):
    with pytest.raises(ValueError, match='selection policy'):
        helper().decision_selection_policy({'decision_selection_policy': marker})


def quantity_core_case(context=None, *, policy='approved_quantity_core-v1', change=None):
    context, dispatch = answer_case(context or make_case(), projection_version=2)
    context = deepcopy(context)
    dispatch = deepcopy(dispatch)
    span = context.trace_spans[-1]
    system, payload = context.expected_inputs[span.id]
    credential, = helper().issue_decision_credentials(context, dispatch)
    if policy != 'absent':
        payload['decision_selection_policy'] = policy
    ids = [credential.claim_id]
    branch = dict(question_quote=context.questions[0]['question'], claim_ids=ids,
                  conclusion='no', relation='upper_bound')
    row = dict(question_id='q', status='answered', resolution='direct', conclusion='no',
               claim_ids=ids, missing_fields=[], reason='Full independent no',
               subquestions=[branch])
    output = json.loads(span.full_output)
    output['answers'] = [row]
    if change:
        change(output, payload)
    from packages.agents.writer.dimension_writer import compact_prompt_json
    span.full_input = system + '\n\n\nJSON:\n' + compact_prompt_json(payload)
    span.full_output = json.dumps(output)
    dispatch.update(full_input_sha256=atomic.digest(span.full_input),
                    full_output_sha256=atomic.digest(span.full_output))
    binding = AnswerSubquestionBinding(
        **output['answers'][0]['subquestions'][0], support_digest='0' * 64)
    return helper().DecisionReview(context, dispatch), binding, output['answers'][0]['claim_ids']


def test_quantity_core_is_recovered_only_from_current_authenticated_answer():
    review, binding, ids = quantity_core_case()
    core = review.approved_quantity_core('q', binding, ids)
    assert len(core) == 1 and core[0].claim_id == ids[0]
    assert core[0].witness_kind == 'quantity_excess'
    assert review.approved_quantity_core('other-question', binding, ids) == ()
    assert review.approved_quantity_core('q', binding, ['invented']) == ()
    assert review.approved_quantity_core('q', binding.model_copy(
        update={'question_quote': '3 个 collections'}), ids) == ()


@pytest.mark.parametrize('policy', ['absent', None, True, 'approved_quantity_core-v2'])
def test_quantity_core_does_not_reinterpret_legacy_or_unknown_policies(policy):
    review, binding, ids = quantity_core_case(policy=policy)
    assert review.approved_quantity_core('q', binding, ids) == ()


@pytest.mark.parametrize('field,value', [('status', 'partial'), ('resolution', 'conditional'),
                                      ('conclusion', 'depends'), ('missing_fields', ['role'])])
def test_quantity_core_requires_the_original_complete_parent_no(field, value):
    def change(output, payload):
        output['answers'][0][field] = value
    review, binding, ids = quantity_core_case(change=change)
    assert review.approved_quantity_core('q', binding, ids) == ()


@pytest.mark.parametrize('change', ['duplicate_parent', 'second_branch', 'unselected'])
def test_quantity_core_cannot_replace_independent_branches_or_original_selection(change):
    def mutate(output, payload):
        row = output['answers'][0]
        if change == 'duplicate_parent':
            output['answers'].append(deepcopy(row))
        elif change == 'second_branch':
            row['subquestions'].append(dict(question_quote='peer', claim_ids=[],
                conclusion='unknown', relation='unresolved'))
        else:
            row['claim_ids'] = row['subquestions'][0]['claim_ids'] = ['another-claim']
    review, binding, ids = quantity_core_case(change=mutate)
    assert review.approved_quantity_core('q', binding, ids) == ()


def with_unclaimed_task(context, *, prop='people_limit', quote='3 个人', focus='source_rule'):
    context = deepcopy(context)
    span = context.trace_spans[0]
    system, payload = context.expected_inputs[span.id]
    payload['generation_tasks'].append(dict(payload['generation_tasks'][0], task_id='unclaimed',
        request_property=prop, question_quote=quote, focus=focus))
    from packages.agents.writer.dimension_writer import compact_prompt_json
    span.full_input = system + '\n\n\nJSON:\n' + compact_prompt_json(payload)
    context.compact['dispatches'][0]['full_input_sha256'] = atomic.digest(span.full_input)
    _, _, parsed = atomic.parse_atomic_generation(span.full_output, payload,
        SimpleNamespace(facts=context.facts), SimpleNamespace(id=context.consumption_id))
    plan = {}
    atomic.merge_generation_plan(plan, parsed[0], attempt=0)
    context.compact['question_answer_plans'] = [plan]
    return context


def test_quantity_core_can_deny_a_joint_request_without_inventing_a_missing_people_claim():
    context = with_unclaimed_task(make_case())
    review, binding, ids = quantity_core_case(context)
    assert len(review.approved_quantity_core('q', binding, ids)) == 1


@pytest.mark.parametrize('prop,quote,focus', [
    ('price', '账单是多少', 'billing_inputs'),
    ('people_limit', '3 个人', 'edit'),
    ('people_limit', '多少人', 'source_rule'),
    ('people_limit', '3 个 collections', 'source_rule'),
    ('container_limit', '3 个人用 3 个 collections', 'source_rule'),
])
def test_quantity_core_checks_even_real_tasks_that_generated_no_claim(prop, quote, focus):
    context = with_unclaimed_task(make_case(), prop=prop, quote=quote, focus=focus)
    assert helper().build_decision_candidates(context)
    review, binding, ids = quantity_core_case(context)
    assert review.approved_quantity_core('q', binding, ids) == ()


@pytest.mark.parametrize('suffix', ['请分别回答人数和集合是否满足。', '请逐项给出两个结论。',
    ' Answer each requirement separately.', ' Answer independently.',
    ' 人数能否满足？集合能否满足？'])
def test_quantity_core_preserves_explicit_independent_quantity_outputs(suffix):
    context = make_case(question=QUESTION + suffix)
    assert helper().build_decision_candidates(context)
    review, binding, ids = quantity_core_case(context)
    assert review.approved_quantity_core('q', binding, ids) == ()


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("case", [make_case, resource_case])
def test_old_and_compact_answer_transports_issue_the_same_bound_credential(case, version):
    context, dispatch = answer_case(case(), projection_version=version)
    (credential,) = helper().issue_decision_credentials(context, dispatch)
    (candidate,) = helper().build_decision_candidates(context)
    assert credential.binding_sha256 == candidate.binding_sha256
    assert helper().verify_decision_credential(credential, deepcopy(context), deepcopy(dispatch))


@pytest.mark.parametrize("marker", [True, False, 0, 1, 3, "2", 2.0, None, "absent"])
def test_compact_answer_cannot_change_or_remove_projection_marker(marker):
    from packages.agents.writer.dimension_writer import compact_prompt_json
    context, dispatch = answer_case(make_case(), projection_version=2)
    span = context.trace_spans[-1]
    system, payload = context.expected_inputs[span.id]
    if marker == "absent":
        payload.pop("decision_candidate_projection_version")
    else:
        payload["decision_candidate_projection_version"] = marker
    span.full_input = system + "\n\n\nJSON:\n" + compact_prompt_json(payload)
    dispatch["full_input_sha256"] = atomic.digest(span.full_input)
    assert helper().issue_decision_credentials(context, dispatch) == ()


@pytest.mark.parametrize("change", ["task", "witness", "source_ref", "source_quote",
                                    "evidence_refs", "scenario_refs", "claim_id"])
def test_compact_projection_still_binds_exact_server_candidate(change):
    from packages.agents.writer.dimension_writer import compact_prompt_json
    context, dispatch = answer_case(make_case(), projection_version=2)
    span = context.trace_spans[-1]
    system, payload = context.expected_inputs[span.id]
    candidate = payload["decision_candidates"][0]
    if change == "task":
        candidate["task"]["question_quote"] = "another task"
    elif change == "witness":
        candidate["witness"]["required"] = 4
    elif change in {"source_ref", "source_quote"}:
        candidate["sources"][0]["source_ref" if change == "source_ref" else "quote"] = "changed"
    else:
        candidate[change] = ["changed"] if change.endswith("refs") else "changed"
    span.full_input = system + "\n\n\nJSON:\n" + compact_prompt_json(payload)
    dispatch["full_input_sha256"] = atomic.digest(span.full_input)
    assert helper().issue_decision_credentials(context, dispatch) == ()


def test_real_trello_non_entailment_is_candidate_but_does_not_assert_runtime_b_permission():
    (candidate,) = helper().build_decision_candidates(resource_case())
    assert candidate.witness_kind == "resource_non_entailment"
    assert candidate.witness["resources"] == ["A", "B"]
    assert candidate.witness["scope"] == "board"


def test_independent_brand_and_number_do_not_require_product_name_patches():
    context = make_case(
        source="Aster Free organizations support secure data sharing in up to four collections.",
        question="Aster: Free organization用7个collections共享数据，能满足吗？",
        text=(
            "Aster Free organization 最多4个collections，因此不能满足7个collections共享数据的需求。"
        ),
        task_quote="7个collections",
        competitor="Aster",
    )
    (candidate,) = helper().build_decision_candidates(context)
    assert (candidate.witness["maximum"], candidate.witness["required"]) == (4, 7)


@pytest.mark.parametrize(
    "source",
    [
        SOURCE.replace("up to two", "at least two"),
        "Start a Free organization to store and securely share data with one other user.",
        "If administrators approve, " + SOURCE,
        SOURCE + " Except administrators may share more.",
        SOURCE.replace("two collections", "two collections per team"),
        SOURCE.replace("two collections", "two collections at a time"),
        SOURCE.replace("two collections", "two collections (active users only)"),
        SOURCE.replace("two collections", "two collections (unknown annotation)"),
        SOURCE.replace("Free organizations", "Paid organizations"),
        SOURCE.replace("data sharing", "data editing"),
        SOURCE.replace("collections", "vaults"),
        "Guests can share data in up to two collections.",
    ],
)
def test_quantity_requires_an_unconditional_same_property_source_cap(source):
    context = make_case(source=source)
    assert helper().build_decision_candidates(context) == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("fact_hash", "0" * 64),
        ("source_id", "other"),
        ("source_path", "value/9"),
        ("start", 1),
        ("end", 1),
        ("quote", "forged"),
        ("span_id", "invented"),
    ],
)
def test_any_source_binding_identity_change_is_rejected(field, value):
    context = make_case()
    audited = context.audited_claims[0]
    changed = audited.claim.model_copy(
        update={
            "source_span_bindings": (
                audited.claim.source_span_bindings[0].model_copy(update={field: value}),
            )
        }
    )
    context = replace(context, audited_claims=(audited.model_copy(update={"claim": changed}),))
    assert helper().build_decision_candidates(context) == ()


def test_missing_current_original_never_uses_a_serialized_span_as_authority():
    assert helper().build_decision_candidates(replace(make_case(), facts=())) == ()


@pytest.mark.parametrize(
    "mutation",
    [
        "question",
        "parent",
        "task",
        "not_dispatched",
        "hash",
        "empty_review",
        "fake_review",
        "review_output",
    ],
)
def test_unbound_current_context_or_transport_is_rejected(mutation):
    context = make_case()
    if mutation == "question":
        context = replace(context, questions=({"question_id": "q", "question": "changed"},))
    elif mutation == "parent":
        context.request_context["parents"][0]["text"] = "different parent"
    elif mutation == "task":
        context.compact["question_answer_plans"][0]["task_results"][0]["task_id"] = "other"
    elif mutation == "not_dispatched":
        context.compact["dispatches"] = context.compact["dispatches"][1:]
    elif mutation == "hash":
        context.compact["dispatches"][0]["full_output_sha256"] = "0" * 64
    elif mutation == "empty_review":
        context = replace(
            context, audited_claims=(context.audited_claims[0].model_copy(update={"review": None}),)
        )
    elif mutation == "fake_review":
        context.trace_spans[1].metadata["llm_transport_attempts"] = 0
    else:
        context.trace_spans[1].full_output = '{"reviews":[]}'
    with pytest.raises(ValueError):
        helper().build_decision_candidates(context)


def test_all_supported_claim_reviews_are_not_a_task_decision_credential():
    context = make_case()
    assert helper().build_decision_candidates(context)
    assert helper().issue_decision_credentials(context, None) == ()


@pytest.mark.parametrize(
    "fulfilled,grounding,conclusion",
    [
        (False, "supported", "no"),
        (True, "unsupported", "no"),
        (True, "supported", "yes"),
        (True, "supported", "unknown"),
    ],
)
def test_independent_answer_must_approve_this_target_and_typed_conclusion(
    fulfilled,
    grounding,
    conclusion,
):
    context, dispatch = answer_case(
        make_case(), fulfilled=fulfilled, grounding=grounding, conclusion=conclusion
    )
    assert helper().issue_decision_credentials(context, dispatch) == ()


@pytest.mark.parametrize("case", [make_case, resource_case])
def test_live_and_replay_rebuild_the_same_credential_and_revalidate_all_current_material(case):
    module = helper()
    context, dispatch = answer_case(case())
    (credential,) = module.issue_decision_credentials(context, dispatch)
    assert module.verify_decision_credential(credential, deepcopy(context), deepcopy(dispatch))
    assert not module.verify_decision_credential(
        credential.model_copy(update={"conclusion": "yes"}), context, dispatch
    )
    assert not module.verify_decision_credential(credential, replace(context, facts=()), dispatch)
    changed = deepcopy(context)
    changed.trace_spans[-1].full_output = '{"version":3,"answers":[],"task_decisions":[]}'
    assert not module.verify_decision_credential(credential, changed, dispatch)
    assert "claim" not in credential.model_dump()


@pytest.mark.parametrize(
    "change",
    [
        "source_ref",
        "scenario_ref",
        "duplicate",
        "old_contract",
        "candidate_ref",
        "self_reported_task",
    ],
)
def test_answer_cannot_create_source_task_or_parent_authority(change):
    context, dispatch = answer_case(make_case())
    span = context.trace_spans[-1]
    output = json.loads(span.full_output)
    decision = output["task_decisions"][0]
    if change == "source_ref":
        decision["evidence_refs"] = ["s-invented"]
    elif change == "scenario_ref":
        decision["scenario_refs"] = ["foreign-parent"]
    elif change == "candidate_ref":
        decision["candidate_ref"] = "invented"
    elif change == "self_reported_task":
        decision["task_id"] = "task-current"
    elif change == "duplicate":
        output["task_decisions"].append(deepcopy(decision))
    else:
        expected = context.expected_inputs[span.id][1]
        expected["answer_review_contract"] = "subquestion-premises-v5"
        span.full_input = (
            context.expected_inputs[span.id][0] + "\n\n\nJSON:\n" + json.dumps(expected)
        )
        dispatch["full_input_sha256"] = atomic.digest(span.full_input)
    span.full_output = json.dumps(output)
    dispatch["full_output_sha256"] = atomic.digest(span.full_output)
    assert helper().issue_decision_credentials(context, dispatch) == ()


@pytest.mark.parametrize(
    "task_quote,text,source",
    [
        (
            "能否确定他一定免费或一定计费？",
            "仅凭看板 A 上的 Observer 标签无法确定该成员一定免费或一定计费。",
            RESOURCE_SOURCE,
        ),
        ("A 上这次改权是否决定他在 A 的权限", RESOURCE_INFERENCE, RESOURCE_SOURCE),
        (RESOURCE_TASK, "小周在 B 上被禁止访问。", RESOURCE_SOURCE),
        (RESOURCE_TASK, RESOURCE_INFERENCE, "Observer is a board permission."),
    ],
)
def test_resource_witness_requires_this_branch_two_resources_and_positive_independent_rule(
    task_quote,
    text,
    source,
):
    context = make_case(
        source=source,
        question=RESOURCE_QUESTION,
        text=text,
        task_quote=task_quote,
        prop=None,
        competitor="Trello",
    )
    assert helper().build_decision_candidates(context) == ()


def test_literal_people_cap_is_supported_but_one_other_user_capability_is_not():
    context = make_case(
        source="Free organizations allow secure data sharing for up to two users.",
        question="Free organization想让包括我在内的3个人共享数据，能满足吗？",
        text="Free organization 最多2名用户，因此不能满足3个人共享数据的需求。",
        task_quote="3个人",
        prop="people_limit",
    )
    (candidate,) = helper().build_decision_candidates(context)
    assert candidate.witness == dict(unit="people", maximum=2, required=3, operation="share")


@pytest.mark.parametrize("mode", ["empty_checks", "unsupported_review", "uncertain_review"])
def test_supported_dto_cannot_override_the_actual_independent_review_checks(mode):
    context = make_case()
    raw = json.loads(context.trace_spans[1].full_output)
    row = raw["reviews"][0]
    if mode == "empty_checks":
        row["checks"] = []
    else:
        row["verdict"] = mode.removesuffix("_review")
    context.trace_spans[1].full_output = json.dumps(raw)
    context.compact["dispatches"][1]["full_output_sha256"] = atomic.digest(
        context.trace_spans[1].full_output
    )
    parsed = ClaimReview.model_validate({k: v for k, v in row.items() if k != "support_witnesses"})
    context = replace(
        context, audited_claims=(context.audited_claims[0].model_copy(update={"review": parsed}),)
    )
    assert helper().build_decision_candidates(context) == ()


def add_repair(context, *, changed_identity=False):
    original_system, original = context.expected_inputs["gen"]
    payload = deepcopy(original)
    payload["generation_tasks"][0]["max_claims"] = 1
    payload["generation_tasks"][0]["advisory_support_refs"] = ["s1"]
    if changed_identity:
        payload["generation_tasks"][0]["question_quote"] = "其他任务"
    payload["generation_repair"] = dict(attempt=1, claim_limit=1, retained_claims=[])
    raw = json.dumps(dict(question_plans=[dict(question_id="q", missing_fields=[], atoms=[])]))
    claims, _, plans = atomic.parse_atomic_generation(
        raw,
        payload,
        SimpleNamespace(facts=context.facts),
        SimpleNamespace(id=context.consumption_id),
    )
    assert not claims
    span = make_span(
        "repair",
        atomic.GENERATION_NAME,
        "writer",
        context.competitor,
        original_system,
        payload,
        raw,
    )
    dispatch = atomic.dispatch_row(
        span, question_ids=["q"], claim_ids=[], fact_ids=["f"], attempt=1
    )
    compact = deepcopy(context.compact)
    compact["dispatches"].append(dispatch)
    atomic.merge_generation_plan(compact["question_answer_plans"][0], plans[0], attempt=1)
    return replace(
        context,
        compact=compact,
        trace_spans=(*context.trace_spans, span),
        expected_inputs={**context.expected_inputs, span.id: (original_system, deepcopy(payload))},
    )


def test_repair_can_change_capacity_and_ranking_but_cannot_change_task_identity():
    context = make_case()
    (before,) = helper().build_decision_candidates(context)
    (after,) = helper().build_decision_candidates(add_repair(context))
    assert before == after
    with pytest.raises(ValueError, match="repair task identity"):
        helper().build_decision_candidates(add_repair(context, changed_identity=True))


def test_a_model_cannot_hide_a_conflicting_decision_behind_duplicate_json_members():
    context, dispatch = answer_case(make_case())
    span = context.trace_spans[-1]
    output = span.full_output
    span.full_output = output.replace(
        '"task_fulfilled": true', '"task_fulfilled": false, "task_fulfilled": true'
    )
    dispatch["full_output_sha256"] = atomic.digest(span.full_output)
    assert helper().issue_decision_credentials(context, dispatch) == ()


def test_narrow_gen_review_contexts_rebuild_in_a_larger_answer_window_with_stable_refs():
    context = resource_case()
    (candidate,) = helper().build_decision_candidates(context)
    request = deepcopy(context.request_context)
    request["parents"].append(dict(parent_id="other-parent", text="Unrelated parent question."))
    request["bindings"].append(dict(question_id="other-q", parent_id="other-parent"))
    widened = replace(
        context,
        request_context=request,
        questions=(*context.questions, dict(question_id="other-q", question="Unrelated question.")),
    )
    (rebuilt,) = helper().build_decision_candidates(widened)
    assert rebuilt == candidate


@pytest.mark.parametrize("factory", [make_case, resource_case])
@pytest.mark.parametrize(
    "kind", ["qualifier", "scope_role", "scope_plan", "parent_quote", "parent_value"]
)
def test_unknown_parent_limit_or_qualifier_cannot_be_dropped_by_selecting_a_clean_span(
    factory, kind
):
    source = SOURCE if factory is make_case else RESOURCE_SOURCE
    kwargs = {}
    if kind == "qualifier":
        kwargs["qualifiers"] = {"population_rule": "active members only"}
    elif kind.startswith("scope_"):
        kwargs["qualifiers"] = {"source_scope": {"context": {kind[6:]: "unknown"}}}
    elif kind == "parent_quote":
        kwargs["parent_quote"] = source + "\n\nIf administrators approve, this rule applies."
    else:
        kwargs["parent_values"] = [source, "Except administrators may synchronize permissions."]
    assert helper().build_decision_candidates(factory(**kwargs)) == ()


@pytest.mark.parametrize(
    "source",
    [
        "If administrators approve, " + RESOURCE_SOURCE,
        "Except for synchronized boards, " + RESOURCE_SOURCE,
        RESOURCE_SOURCE.replace("board", "project"),
        RESOURCE_SOURCE + " Except administrators may synchronize roles.",
    ],
)
def test_resource_rule_keeps_all_conditions_and_the_exact_resource_type(source):
    context = make_case(
        source=source,
        question=RESOURCE_QUESTION,
        text=RESOURCE_INFERENCE,
        task_quote=RESOURCE_TASK,
        prop=None,
        competitor="Trello",
    )
    assert helper().build_decision_candidates(context) == ()


def test_non_entailment_cannot_append_an_explicit_runtime_role_denial():
    context = make_case(
        source=RESOURCE_SOURCE,
        question=RESOURCE_QUESTION,
        text=RESOURCE_INFERENCE + "小周在 B 上不具备 Observer 权限。",
        task_quote=RESOURCE_TASK,
        prop=None,
        competitor="Trello",
    )
    assert helper().build_decision_candidates(context) == ()


@pytest.mark.parametrize("field", ["claim_ids", "fact_ids"])
def test_answer_dispatch_must_include_its_candidate_claim_and_current_original(field):
    context, dispatch = answer_case(make_case())
    dispatch[field] = []
    assert helper().issue_decision_credentials(context, dispatch) == ()


@pytest.mark.parametrize("connector", ["或", "或者", "或是", "or"])
def test_an_alternative_quantity_request_cannot_be_denied_by_one_failing_option(connector):
    context = make_case(
        question=(
            f"Bitwarden: Free organization 想用 3 个 collections {connector} 2 个 collections "
            "共享数据，能满足吗？"
        )
    )
    assert len(context.audited_claims) == 1  # Real GEN5 parser accepted the claim.
    assert helper().build_decision_candidates(context) == ()


@pytest.mark.parametrize(
    "text",
    [
        (
            "由于 Free organization 最多支持4个 collections，而场景要求使用3个 collections，"
            "因此该免费组织无法满足3个 collections的共享需求。"
        ),
        (
            "由于 Free organization 最多支持2个 vaults，而场景要求使用3个 vaults，"
            "因此该免费组织无法满足3个 vaults的共享需求。"
        ),
        (
            "由于 Free organization 最多支持2个 collections，而场景要求使用7个 collections，"
            "因此该免费组织无法满足7个 collections的共享需求。"
        ),
    ],
)
def test_quantity_claim_explicit_counts_and_unit_must_match_source_and_current_task(text):
    context = make_case(text=text)
    assert context.audited_claims[0].claim.text == text
    assert context.audited_claims[0].review.verdict == "supported"
    assert helper().build_decision_candidates(context) == ()


@pytest.mark.parametrize(
    "extra",
    [
        "All board roles are synchronized across every board in a Workspace.",
        "Changes to board A permissions also determine the permissions on board B.",
        "Board membership follows the Workspace propagation policy.",
        "Additional configuration governs role assignment.",
    ],
)
def test_resource_parent_requires_every_additional_member_to_be_understood(extra):
    context = resource_case(parent_values=[RESOURCE_SOURCE, extra])
    assert len(context.audited_claims) == 1
    assert helper().build_decision_candidates(context) == ()


def test_real_trello_parent_members_remain_eligible_without_dropping_them():
    context = resource_case(
        parent_values=[
            "Inviting people by using a shareable link\n.\n" + RESOURCE_SOURCE,
            (
                "Observers are not able to move or edit cards, upload card attachments, "
                "tick the box on a checklist item, and observers can't change board settings."
            ),
            (
                "from the top of the board. Enter the member's username or email address. When you "
                "choose the person to add, the default choice is to add them as regular "
                "board members, but you can click on the dropdown\xa0to change that to 'Observer'."
            ),
        ]
    )
    (candidate,) = helper().build_decision_candidates(context)
    assert candidate.witness_kind == "resource_non_entailment"


@pytest.mark.parametrize(
    "tail",
    [
        "小周无法访问看板 B。",
        "小周在看板 B 上没有访问权限。",
        "小周在 B 上不具备 Observer 权限。",
    ],
)
def test_non_entailment_cannot_carry_a_separate_actual_access_denial(tail):
    context = make_case(
        source=RESOURCE_SOURCE,
        question=RESOURCE_QUESTION,
        text=RESOURCE_INFERENCE + tail,
        task_quote=RESOURCE_TASK,
        prop=None,
        competitor="Trello",
    )
    assert context.audited_claims[0].claim.text.endswith(tail)
    assert helper().build_decision_candidates(context) == ()
