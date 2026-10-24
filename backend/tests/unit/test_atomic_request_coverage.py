"""Finite request coverage and exact selected-support boundaries, not an NLI score."""

import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.question_allocation import _request_units
from packages.agents.writer.task_protocol import fallback_tasks, parse_tasks, task_atom_reasons

GUEST = (
    "1Password: 在 Families 中，访客已接受邀请并被确认。"
    "他能同时加入两个共享保险库，或者拥有自己的 Private vault 吗？"
)


def test_alternative_requested_predicates_are_separate_exact_fragments():
    units = _request_units(GUEST)
    assert len(units) == 2
    assert all(unit in GUEST for unit in units)
    assert "两个共享保险库" in units[0]
    assert "Private vault" in units[1]
    tasks = fallback_tasks([dict(question_id="q", question=GUEST)], "scope")
    assert [t["question_quote"] for t in tasks] == units


@pytest.mark.parametrize("partial", [False, True])
def test_broad_or_incomplete_model_plan_cannot_swallow_known_subrequests(partial):
    quote = "他能同时加入两个共享保险库" if partial else GUEST
    questions = [dict(question_id="q", question=GUEST)]
    tasks = parse_tasks(
        json.dumps({"tasks": [dict(question_id="q", question_quote=quote, focus="source_rule")]}),
        questions,
        "scope",
    )
    assert len(tasks) == 2
    assert any("Private vault" in t["question_quote"] for t in tasks)
    assert (
        parse_tasks(
            json.dumps(
                {
                    "tasks": [
                        dict(
                            question_id=t["question_id"],
                            question_quote=t["question_quote"],
                            focus=t["focus"],
                        )
                        for t in tasks
                    ]
                }
            ),
            questions,
            "scope",
        )
        == tasks
    )


def test_omitted_known_action_is_added_but_does_not_duplicate_model_fragment():
    tasks = parse_tasks(
        json.dumps({"tasks": [dict(question_id="q", question_quote="下载附件", focus="download")]}),
        [dict(question_id="q", question="能下载附件并导出看板吗？")],
        "scope",
    )
    assert [t["focus"] for t in tasks] == ["download", "export"]


@pytest.mark.parametrize(
    "question,fragment,focus",
    [
        ("能下载附件吗？能下载工作区报告吗？", "能下载", "download"),
        ("能否拥有私人库？能否加入两个共享库？", "能否", "source_rule"),
    ],
)
def test_shared_short_fragment_cannot_cover_multiple_distinct_requests(question, fragment, focus):
    tasks = parse_tasks(
        json.dumps(
            {
                "tasks": [
                    dict(
                        question_id="q",
                        question_quote=fragment,
                        focus=focus,
                    )
                ]
            }
        ),
        [dict(question_id="q", question=question)],
        "scope",
    )
    assert [t["question_quote"] for t in tasks] == _request_units(question)


def test_rule_discovered_overflow_is_explicit_beyond_model_plan_row_limit():
    question = "".join(f"能下载文件{i}吗？" for i in range(49))
    tasks = fallback_tasks([dict(question_id="q", question=question)], "scope")
    assert len(tasks) == 49
    assert sum(task["state"] == "planned" for task in tasks) == 12
    assert tasks[-1]["reason"] == "task_capacity_exceeded"


@pytest.mark.parametrize(
    "question",
    [
        "只有登录或者获邀才能访问吗？",
        "只有拥有付费套餐，或者已获管理员批准，才能导出吗？",
        "Can users download after editing or voting?",
        "只要他可以登录，或者拥有管理员邀请，就能导出吗？",
        "他能下载文件，只要已付费，或者拥有管理员邀请吗？",
    ],
)
def test_alternative_conditions_are_never_promoted_to_independent_requests(question):
    assert _request_units(question) == [question]


def test_declarative_permission_scenario_is_not_a_new_requested_predicate():
    assert _request_units("访客可以评论；能导出吗？") == ["能导出吗？"]


def test_split_chinese_request_keeps_its_inherited_action_focus():
    question = "他能下载附件，或者拥有自己的 Private vault 吗？"
    tasks = fallback_tasks([dict(question_id="q", question=question)], "scope")
    assert [task["focus"] for task in tasks] == ["download", "source_rule"]
    assert task_atom_reasons(tasks[0], "访客可以导出看板。") == ("task_predicate_not_addressed",)


def test_three_explicit_requests_keep_each_previously_recognized_coordination():
    question = "他能拥有自己的私人库，或者拥有一个共享库，或者拥有第二个共享库吗？"
    tasks = fallback_tasks([dict(question_id="q", question=question)], "scope")
    assert len(tasks) == 3
    assert all("，" not in task["question_quote"] for task in tasks)


def test_output_explanation_instruction_does_not_create_a_second_obligation_task():
    from packages.agents.writer.question_allocation import question_atom_tasks

    question = (
        "B 允许投票，是否意味着他必须给每张卡片投票？"
        "请将可以执行的操作、启用条件与是否存在强制义务分别说明。"
    )
    tasks = question_atom_tasks([dict(question_id="q", question=question)])
    assert len(tasks) == 1
    assert tasks[0]["request"] == "是否意味着他必须给每张卡片投票？"


@pytest.mark.parametrize(
    "focus,text",
    [
        ("export", "Observer 可以下载卡片附件并导出看板。"),
        ("export", "Observers can download attachments and can export boards."),
        ("source_rule", "Observer 可以下载卡片附件并导出看板。"),
    ],
)
def test_sibling_assertion_is_rejected_on_either_side_of_target(focus, text):
    assert "task_contains_sibling_predicate" in task_atom_reasons(dict(focus=focus), text)


@pytest.mark.parametrize("focus", ["download", "export", "source_rule"])
@pytest.mark.parametrize(
    "text",
    [
        "Observer 可以下载附件；并且可以导出看板。",
        "Observers can download attachments; and can export boards.",
    ],
)
def test_separate_assertion_sentences_still_form_a_compound_task(focus, text):
    assert "task_contains_sibling_predicate" in task_atom_reasons(dict(focus=focus), text)


@pytest.mark.parametrize(
    "text",
    [
        "Observer 可以导出投票结果。",
        "Observer 先投票后才能导出。",
    ],
)
def test_action_object_and_prerequisite_do_not_become_sibling_assertions(text):
    assert not task_atom_reasons(dict(focus="export"), text)


@pytest.mark.parametrize(
    "selected",
    [
        "Observer is a board member permission.",
        "Observer permissions cannot be set at Workspace level.",
    ],
)
@pytest.mark.parametrize(
    "text",
    [
        "Observer 是看板成员权限，而非成员类型。",
        "Observer 是看板成员权限，而非成员身份类型。",
    ],
)
def test_unselected_parent_denial_cannot_support_an_added_classification(selected, text):
    from test_literal_non_operation import fact
    from test_source_span_binding import parse_bound, spans

    from packages.research.evidence.report_claims import claim_rule_reasons

    original = fact(quote=selected, value=[selected, "Observer is not a membership type."])
    span = next(s for s in spans(original) if s["quote"] == selected)
    claims, gaps = parse_bound(original, text, [span])
    assert claims and not gaps
    reasons = claim_rule_reasons(
        claims[0],
        SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])],
    )
    assert "classification_denial_outside_support" in reasons


@pytest.mark.parametrize(
    "quote,text",
    [
        ("Observer is not a membership type.", "Observer 不是成员类型。"),
        ("Observer cannot be set at Workspace level.", "Observer 不能在 Workspace 层级设置。"),
    ],
)
def test_matching_denial_and_scope_negation_remain_for_semantic_review(quote, text):
    from test_literal_non_operation import fact
    from test_source_span_binding import parse_bound

    from packages.research.evidence.report_claims import claim_rule_reasons

    original = fact(quote=quote)
    claims, gaps = parse_bound(original, text)
    assert claims and not gaps
    assert "classification_denial_outside_support" not in claim_rule_reasons(
        claims[0],
        SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])],
    )
