"""Fresh complete task packages keep selection, source review and delivery aligned."""

import pytest
from test_conclusion_publication import publication_case

PACKAGE = "complete-task-evidence-v1"
SCOPE = "Domain-scoped roles apply for a given domain within an account."
ROLE = (
    "| Storage Cache Purger | Grants access to purge the edge cache "
    "for a specific domain and allows the reading of zone settings. |"
)
ACCESS = (
    "Visitor accounts are ideal for sharing information with people on a limited basis. "
    "They don’t have their own private vaults and only have access to a single vault, "
    "which you choose."
)
UPGRADE = (
    "Promote a guest to a family member. If you want to give a guest more access to your "
    "account, including their own Private vault and access to more than one shared vault, "
    "you can promote them from guest to family member."
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "weak,complete,question,relation",
    [
        (SCOPE, ROLE,
         "Example Product：同事只被授予 example.com 的 Storage Cache Purger 角色，"
         "没有任何其他角色。他能清除 other.example 的边缘缓存吗？", "permission_scope"),
        (UPGRADE, ACCESS,
         "Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？",
         "access_cardinality"),
    ],
)
async def test_incomplete_selected_relation_reselects_before_generation_and_publishes(
    monkeypatch, weak, complete, question, relation
):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    def select(payload, _refs):
        quote = weak if payload["task_attempt"] == 0 else complete
        return [s["support_ref"] for f in payload["evidence_view"]["facts"]
                for s in f["source_span_candidates"] if s["quote"] == quote]

    case, result, audit, seen, use = await publication_case(
        monkeypatch, sources=[weak, complete], question=question,
        conclusion_contract="structured-conclusions-v2", task_package_contract=PACKAGE,
        selection_hook=select,
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert any(e["relation"] == relation and e["task_cell"]["outcome"] == "no" for e in entries)
    generations = [p for n, p in seen if n.endswith("atomic_generation")
                   and (relation != "permission_scope"
                        or p["generation_tasks"][0]["focus"] == "purge_cache")]
    assert generations and all(p["task_attempt"] == 1 for p in generations)
    assert all(p["task_package_contract"] == PACKAGE for _, p in seen)
    for name, payload in seen:
        if name.endswith('support_selection'):
            required = payload['task_predicates'][0].get('required_relation_refs')
            if required is not None:
                assert {s['support_ref'] for f in payload['evidence_view']['facts']
                        for s in f.get('source_span_candidates', ())} <= set(required)
    assert audit.answer_coverage[0].conclusion == "no"
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replay["decision_review"][audit.answer_coverage[0].question_id].matches(
        audit.answer_coverage[0]
    )
    budget = case[0]._run_llm_budget(case[1])
    phase = f'answer:{case[4].competitor}/{case[4].dimension}'
    assert budget.delivery_reserves[phase] == budget.delivery_charged.get(phase, 0)


@pytest.mark.asyncio
async def test_upgrade_only_never_enters_current_access_generation(monkeypatch):
    _, result, audit, seen, _ = await publication_case(
        monkeypatch, source=UPGRADE,
        question="Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？",
        conclusion_contract="structured-conclusions-v2", task_package_contract=PACKAGE,
    )
    assert not any(n.endswith("atomic_generation") for n, _ in seen)
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_verdict", ["unsupported", "uncertain", "invalid", "supported"])
async def test_clause_failure_cannot_hide_source_review_state_for_reuse(
    monkeypatch, source_verdict,
):
    def review(payload, data):
        if payload.get("task_context") and not mutated:
            mutated.append(True)
            data["atomicity"] = []
            if source_verdict == "invalid":
                data["reviews"] = []
            else:
                data["reviews"][0]["verdict"] = source_verdict
        return data

    mutated = []
    _, _, _, seen, _ = await publication_case(
        monkeypatch, source=ACCESS,
        question="Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？",
        conclusion_contract="structured-conclusions-v2", task_package_contract=PACKAGE,
        review_hook=review,
    )
    repaired = [p for name, p in seen if name.endswith("atomic_generation")
                and p["task_attempt"] == 1]
    assert repaired
    feedback = repaired[0]["repair_feedback"]
    assert feedback["source_review_state"] == source_verdict
    assert ("selection_reuse" in repaired[0]) == (source_verdict == "supported")
    if source_verdict == "supported":
        assert repaired[0]["selection_reuse"]["source_review"]["full_output_sha256"]
    else:
        assert feedback["directive"]["action"] == "reselect"


@pytest.mark.asyncio
@pytest.mark.parametrize('package', [None, PACKAGE])
async def test_qa_source_context_matches_the_complete_reviewed_projection_not_unselected_values(
    monkeypatch, package,
):
    from packages.agents.qa.independent_question_review import _question_context, _question_verified

    unrelated = 'Separate navigation guidance is not a current-access rule.'
    case, _, audit, seen, _ = await publication_case(
        monkeypatch, source=ACCESS, source_values=[[ACCESS, unrelated]],
        question='Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？',
        conclusion_contract='structured-conclusions-v2', task_package_contract=package,
        selected_quote_contains='only have access',
    )
    service, record, snapshot = case[:3]
    question = case[6][0]['questions'][0]
    verified = _question_verified(service, record, snapshot, question, audit, [],
                                 producer_verified=True)
    context = _question_context(service, record, snapshot, question, audit, verified=verified,
                                producer_verified=True)
    assert context['support_verified'] and context['publication_matches']
    selected = context['selected_source_context']
    review = next(p for name, p in seen if name.endswith('atomic_review'))
    if package:
        assert context['task_package_contract'] == package
        assert [r['quote'] for r in selected] == review['claims'][0]['support_quotes']
        assert all(r['value'] == [r['quote']] for r in selected)
        assert selected[0]['reviewed_constraints'] == review['constraint_context']
        assert unrelated not in str(selected)
    else:
        assert 'task_package_contract' not in context
        assert unrelated in str(selected)
    await service.aclose()


@pytest.mark.asyncio
async def test_full_flow_keeps_the_existing_authenticated_closed_authority_rule(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    source = ('Please note that only Workspace admins and board admins can change '
              'a board member’s status to observer.')

    def generate(p, _data):
        return dict(version=1, task_id=p['generation_tasks'][0]['task_id'], status='generated',
                    atom=dict(text='只有 Workspace 管理员和看板管理员才能把看板现有成员的权限状态'
                              '改为 Observer。', kind='fact',
                              support_refs=p['task_support_selections'][0]['support_refs']))

    def answer(p, data):
        for task, row in zip(p['tasks'], data['task_reviews'], strict=True):
            row.update(outcome='rule', support_refs=[c['ref'] for c in task['support_choices']
                                                    if c['primary']])
        return data

    case, _, audit, _, use = await publication_case(
        monkeypatch, source=source, question='Example Product：谁有权把看板现有成员改为 Observer？',
        conclusion_contract='structured-conclusions-v2', task_package_contract=PACKAGE,
        generation_hook=generate, answer_hook=answer,
    )
    assert all(c.status == 'supported' for c in audit.claims)
    assert audit.answer_coverage[0].status == 'answered'
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replay['answers'][audit.answer_coverage[0].question_id] == audit.answer_coverage[0]
