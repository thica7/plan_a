"""A correct Guest source rule cannot certify access for a no-longer-Guest actor."""

import pytest
from test_conclusion_publication import publication_case

SOURCE = (
    'Guest accounts are ideal for sharing information with people on a limited basis. '
    'They don’t have their own private vaults and only have access to a single vault, '
    'which you choose.'
)
PACKAGE = 'complete-task-evidence-v1'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    '他当前不再是访客',
    '后来他已升级为家庭成员',
])
@pytest.mark.parametrize('force_answer_no', [False, True])
async def test_current_non_guest_cannot_receive_a_guest_cap_no(
    monkeypatch, change, force_answer_no,
):
    from packages.agents.qa.question_reconciliation import authenticated_answer_delivery
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    def answer(payload, data):
        if force_answer_no:
            for task, row in zip(payload['tasks'], data['task_reviews'], strict=True):
                row.update(outcome='no', support_refs=[c['ref'] for c in task['support_choices']
                                                     if c['primary']])
        return data

    case, result, audit, seen, use = await publication_case(
        monkeypatch, source=SOURCE,
        question=f'Example Product：访客已接受邀请并被确认；{change}；'
                 '他能同时访问两个共享保险库吗？',
        conclusion_contract='structured-conclusions-v2', task_package_contract=PACKAGE,
        answer_hook=answer,
    )
    assert any(row.status == 'supported' for row in audit.claims)
    assert any(p.get('conclusion_candidates') for _, p in seen)
    answer_row = audit.answer_coverage[0]
    assert answer_row.conclusion != 'no'
    assert not any(e['task_cell']['outcome'] == 'no'
                   for e in result['compact']['conclusion_set']['entries'])
    assert '超过该角色' not in case[1].detail.report_md
    assert all(not c['primary'] for name, p in seen if name.endswith('atomic_answer_review')
               for task in p['tasks'] for c in task['support_choices'])
    question = case[6][0]['questions'][0]
    delivered = authenticated_answer_delivery(case[1].detail, case[2], audit, answer_row, question)
    assert delivered is None
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replay['answers'][answer_row.question_id].conclusion != 'no'
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    '',
    '他尚未升级为家庭成员；',
    '他没有升级为家庭成员；',
    '他计划升级为家庭成员；',
    '他已从一个保险库移出并改换到另一个保险库；',
])
async def test_unrealized_upgrade_or_resource_switch_keeps_given_guest_role(monkeypatch, change):
    case, result, audit, _, _ = await publication_case(
        monkeypatch, source=SOURCE,
        question=f'Example Product：访客已接受邀请并被确认；{change}'
                 '他能同时访问两个共享保险库吗？',
        conclusion_contract='structured-conclusions-v2', task_package_contract=PACKAGE,
    )
    assert audit.answer_coverage[0].conclusion == 'no'
    assert any(e['relation'] == 'access_cardinality'
               for e in result['compact']['conclusion_set']['entries'])
    await case[0].aclose()


@pytest.mark.asyncio
async def test_another_explicit_actor_upgrade_does_not_change_this_guest_role(monkeypatch):
    case, _, audit, _, _ = await publication_case(
        monkeypatch, source=SOURCE,
        question='Example Product：Guest Alice已接受邀请并被确认；Bob已升级为家庭成员。'
                 'Alice能同时访问两个共享保险库吗？',
        conclusion_contract='structured-conclusions-v2', task_package_contract=PACKAGE,
    )
    assert audit.answer_coverage[0].conclusion == 'no'
    await case[0].aclose()
