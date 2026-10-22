"""Finite scope rejection must not borrow another predicate's negative word."""

import json

import pytest

from packages.agents.writer.answer_coverage import parse_answer_coverage


def answer(question, claims, branches, *, status="answered", conclusion="no"):
    row = dict(
        question_id="q",
        status=status,
        claim_ids=[claim["id"] for claim in claims],
        resolution="direct",
        conclusion=conclusion,
        missing_fields=[],
        reason="Reviewed.",
        subquestions=branches,
    )
    return parse_answer_coverage(
        json.dumps({"version": 3, "answers": [row]}),
        [{"question_id": "q", "question": question}],
        {claim["id"] for claim in claims},
        claims=claims,
        required_binding_version=3,
        require_subquestions=True,
    )[0]


def branch(question, ids, relation="explicit_negative"):
    return dict(question_quote=question, claim_ids=ids, relation=relation, conclusion="no")


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize(
    "parts,denial,upgrade",
    [
        (
            ("访客能访问两个共享保险库，", "或者拥有自己的 Private vault 吗？"),
            "访客不能同时访问两个共享保险库。",
            "若要获得自己的 Private vault，可以升级为家庭成员。",
        ),
        (
            ("Can guests access two shared vaults, ", "or own a private vault?"),
            "Guests cannot access two shared vaults.",
            "Guests can upgrade to get a private vault.",
        ),
    ],
)
def test_unrelated_negative_cannot_complete_an_unknown_vault_branch(split, parts, denial, upgrade):
    question = "".join(parts)
    claims = [
        {"id": "single", "text": denial, "kind": "fact"},
        {"id": "upgrade", "text": upgrade, "kind": "fact"},
    ]
    branches = (
        [branch(parts[0], ["single"]), branch(parts[1], ["single", "upgrade"])]
        if split
        else [branch(question, ["single", "upgrade"])]
    )
    result = answer(question, claims, branches)
    assert result.status == "unverified"
    assert "answer_subquestion_negative_unproven" in result.reason


@pytest.mark.parametrize(
    "question,denial,affirmative",
    [
        (
            "Can guests access private messages?",
            "Guests cannot access folders.",
            "Members can access private messages.",
        ),
        ("访客能访问私信吗？", "访客不能访问文件夹。", "成员可以访问私信。"),
    ],
)
def test_existing_object_scope_comes_only_from_the_negative_claim(question, denial, affirmative):
    claims = [
        {"id": "deny", "text": denial, "kind": "fact"},
        {"id": "allow", "text": affirmative, "kind": "fact"},
    ]
    assert answer(question, claims, [branch(question, ["deny", "allow"])]).status == "unverified"


@pytest.mark.parametrize(
    "question,cap",
    [
        ("Can 3 people use the organization?", "Not only two people can use the organization."),
        ("3 人能使用这个组织吗？", "这个组织并非仅限2人。"),
        ("Can 3 people use the organization?", "Only two people can use the personal workspace."),
        ("3 人能使用这个组织吗？", "个人工作区最多2人。"),
    ],
)
def test_upper_bound_rejects_negated_limits_and_different_scopes(question, cap):
    claims = [{"id": "cap", "text": cap, "kind": "fact"}]
    assert (
        answer(question, claims, [branch(question, ["cap"], "upper_bound")]).status == "unverified"
    )


@pytest.mark.parametrize(
    "question,cap,affirmative",
    [
        (
            "Can 3 people use the organization?",
            "Only two people can use the personal workspace.",
            "Members can use the organization.",
        ),
        ("3 人能使用这个组织吗？", "个人工作区最多2人。", "成员可以使用这个组织。"),
    ],
)
def test_positive_scope_cannot_repair_an_unrelated_upper_bound(question, cap, affirmative):
    claims = [
        {"id": "cap", "text": cap, "kind": "fact"},
        {"id": "allow", "text": affirmative, "kind": "fact"},
    ]
    assert (
        answer(question, claims, [branch(question, ["cap", "allow"], "upper_bound")]).status
        == "unverified"
    )


@pytest.mark.parametrize(
    "question,premise,relation",
    [
        (
            "Can guests own a private vault?",
            "Guests cannot own a private vault.",
            "explicit_negative",
        ),
        ("访客能拥有私人保险库吗？", "访客没有私人保险库。", "explicit_negative"),
        (
            "Can 3 people use the organization?",
            "Only two people can use the organization.",
            "upper_bound",
        ),
        ("3 人能使用这个组织吗？", "这个组织最多2人。", "upper_bound"),
    ],
)
def test_same_predicate_denial_and_real_same_scope_cap_remain_accepted(question, premise, relation):
    claims = [{"id": "rule", "text": premise, "kind": "fact"}]
    assert answer(question, claims, [branch(question, ["rule"], relation)]).status == "answered"


def test_both_complete_vault_negatives_can_answer_separate_branches():
    parts = ("访客能访问两个共享保险库，", "或者拥有自己的 Private vault 吗？")
    claims = [
        {"id": "single", "text": "访客不能同时访问两个共享保险库。", "kind": "fact"},
        {"id": "private", "text": "访客没有自己的 Private vault。", "kind": "fact"},
    ]
    result = answer(
        "".join(parts), claims, [branch(parts[0], ["single"]), branch(parts[1], ["private"])]
    )
    assert result.status == "answered"


@pytest.mark.parametrize(
    "question,premise",
    [
        ("访客能访问两个容器吗？", "访客只能访问由账户所有者选择的一个容器。"),
        ("Can guests access two vaults?", "Guests may belong to one vault at a time."),
        (
            "Can guests access two vaults?",
            "A guest can only be invited to a single vault at a time.",
        ),
        ("Can 3 collections be used?", "访客最多两个 collections。"),
    ],
)
def test_finite_access_caps_preserve_quantity_scope(question, premise):
    claims = [{"id": "cap", "text": premise, "kind": "fact"}]
    assert answer(question, claims, [branch(question, ["cap"], "upper_bound")]).status == "answered"


@pytest.mark.parametrize(
    "premise",
    [
        "Guests are not limited to one vault at a time.",
        "We recommend that guests use one vault at a time.",
        "If the limited mode is enabled, guests may use one vault at a time.",
        "Guests cannot own private vaults and are not limited to one vault at a time.",
        "If guests do not have private vaults, they may belong to one vault at a time.",
    ],
)
def test_one_at_a_time_is_not_a_cap_when_negated_advisory_or_conditional(premise):
    question = "Can guests access two vaults?"
    claims = [{"id": "cap", "text": premise, "kind": "fact"}]
    assert (
        answer(question, claims, [branch(question, ["cap"], "upper_bound")]).status == "unverified"
    )


def test_a_different_predicates_negative_does_not_erase_a_complete_access_cap():
    question = "Can guests access two vaults?"
    claims = [
        {
            "id": "cap",
            "kind": "fact",
            "text": "Guests do not have private vaults and may belong to one vault at a time.",
        }
    ]
    assert answer(question, claims, [branch(question, ["cap"], "upper_bound")]).status == "answered"


@pytest.mark.parametrize(
    "question,rules",
    [
        (
            "同事只被授予甲资源的资源级角色，没有任何其他授权。他能因此清除乙资源的边缘缓存吗？",
            ["资源级清理角色可清除指定资源的边缘缓存。", "资源级角色仅适用于所分配的某个资源。"],
        ),
        (
            "A colleague has only a resource-scoped purge role for A. "
            "Can this role purge the cache for B?",
            [
                "The resource-scoped purge role can purge the edge cache of its assigned resource.",
                "Resource-scoped roles apply only to their assigned resource.",
            ],
        ),
    ],
)
def test_complete_resource_rules_do_not_require_an_inference_atom(question, rules):
    claims = [{"id": str(index), "text": text, "kind": "fact"} for index, text in enumerate(rules)]
    assert (
        answer(
            question, claims, [branch(question, [c["id"] for c in claims], "resource_scope")]
        ).status
        == "answered"
    )


def test_scope_fact_without_the_requested_operation_remains_insufficient():
    question = "仅有甲域权限的用户能因此清除乙域缓存吗？"
    claims = [{"id": "scope", "text": "该角色仅适用于特定域名。", "kind": "fact"}]
    assert (
        answer(question, claims, [branch(question, ["scope"], "resource_scope")]).status
        == "unverified"
    )


@pytest.mark.parametrize(
    "question,premise",
    [
        (
            "After permanently deleting my account, can I keep my passwords?",
            "Permanently deleting your account removes all associated data including passwords.",
        ),
        ("永久删除账户后，我还能保留密码吗？", "永久删除账户会删除所有相关数据，包括密码。"),
    ],
)
def test_complete_account_destruction_can_deny_retention(question, premise):
    claims = [{"id": "delete", "text": premise, "kind": "fact"}]
    assert (
        answer(question, claims, [branch(question, ["delete"], "destructive_effect")]).status
        == "answered"
    )


@pytest.mark.parametrize(
    "question,premise",
    [
        (
            "After removing a member, can I keep my passwords?",
            "Permanently deleting your account removes all associated data including passwords.",
        ),
        (
            "After permanently deleting my account, can I keep my passwords?",
            "Removing a member removes all associated data including passwords.",
        ),
        (
            "After permanently deleting my account, can I keep my passwords?",
            "Permanently deleting your account removes all notes.",
        ),
        (
            "After permanently deleting my account, can I keep my organization passwords?",
            "Permanently deleting your account removes all personal data including passwords.",
        ),
        (
            "After permanently deleting my account, can I keep my passwords?",
            "If you select purge, permanently deleting your account removes all associated data "
            "including passwords.",
        ),
        (
            "永久删除账户后，我还能保留密码吗？",
            "如果选择清空，永久删除账户会删除所有相关数据，包括密码。",
        ),
        (
            "After permanently deleting my account, can I keep my passwords?",
            "Permanently deleting your account removes all associated data except passwords.",
        ),
        ("永久删除账户后，我还能保留密码吗？", "永久删除账户会删除所有相关数据，密码除外。"),
    ],
)
def test_destructive_effect_rejects_other_actions_objects_and_unresolved_conditions(
    question, premise
):
    from packages.agents.writer.subquestion_premises import _destruction_denies_retention

    assert not _destruction_denies_retention(question, [premise])
    claims = [{"id": "delete", "text": premise, "kind": "fact"}]
    assert (
        answer(question, claims, [branch(question, ["delete"], "destructive_effect")]).status
        == "unverified"
    )


def test_parent_answer_cannot_publish_an_inference_unassigned_to_any_branch():
    question = "Can guests export boards?"
    claims = [
        {"id": "deny", "text": "Guests cannot export boards.", "kind": "fact"},
        {"id": "extra", "text": "Guests cannot access private vaults.", "kind": "inference"},
    ]
    result = answer(question, claims, [branch(question, ["deny"])])
    assert result.status == "unverified"
    assert "answer_subquestion_claims_unassigned" in result.reason


def test_partial_answer_may_keep_an_unknown_branch_without_extra_published_claims():
    parts = ("Can guests export boards? ", "Can they download files?")
    claims = [{"id": "deny", "text": "Guests cannot export boards.", "kind": "fact"}]
    unknown = dict(
        question_quote=parts[1], claim_ids=[], relation="unresolved", conclusion="unknown"
    )
    result = answer(
        "".join(parts),
        claims,
        [branch(parts[0], ["deny"]), unknown],
        status="partial",
        conclusion="depends",
    )
    assert result.status == "partial"
