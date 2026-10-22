"""Subquestion receipts bind complete published premises, never review prose."""

import json

import pytest

from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)


def parse(question, claims, branches, *, conclusion="no", status="answered"):
    row = dict(
        question_id="q",
        status=status,
        claim_ids=[c["id"] for c in claims],
        resolution="direct",
        conclusion=conclusion,
        missing_fields=[],
        reason="Reviewed.",
        subquestions=branches,
    )
    return parse_answer_coverage(
        json.dumps({"version": 3, "answers": [row]}),
        [{"question_id": "q", "question": question}],
        {c["id"] for c in claims},
        claims=claims,
        required_binding_version=3,
    )[0]


def branch(text, ids, relation="explicit_negative", conclusion="no"):
    return dict(question_quote=text, claim_ids=ids, relation=relation, conclusion=conclusion)


def test_each_negative_branch_has_its_own_complete_published_premise():
    question = "访客能访问两个共享保险库，或者拥有自己的 Private vault 吗？"
    claims = [
        {"id": "single", "text": "访客不能同时访问两个共享保险库。", "kind": "fact"},
        {"id": "private", "text": "访客没有自己的 Private vault。", "kind": "fact"},
    ]
    result = parse(
        question,
        claims,
        [
            branch("访客能访问两个共享保险库，", ["single"]),
            branch("或者拥有自己的 Private vault 吗？", ["private"]),
        ],
    )
    assert result.status == "answered"
    assert len(result.subquestion_bindings) == 2
    assert not coverage_resolution_reasons(result, claims, required_binding_version=3)


def test_possible_upgrade_cannot_prove_the_second_negative_branch():
    question = "访客能访问两个共享保险库，或者拥有自己的 Private vault 吗？"
    claims = [
        {"id": "single", "text": "访客不能同时访问两个共享保险库。", "kind": "fact"},
        {
            "id": "upgrade",
            "text": "若要获得自己的 Private vault，可以升级为家庭成员。",
            "kind": "fact",
        },
    ]
    result = parse(
        question,
        claims,
        [
            branch("访客能访问两个共享保险库，", ["single"]),
            branch("或者拥有自己的 Private vault 吗？", ["upgrade"]),
        ],
    )
    assert result.status == "unverified" and not result.claim_ids


@pytest.mark.parametrize(
    "branches",
    [
        [branch("能下载吗？", ["deny"])],
        [branch("Example: 能下载吗？能导出吗？", ["unknown"])],
        [
            branch("Example: 能下载吗？", ["deny"]),
            branch("能导出吗？", ["deny"], conclusion="unknown"),
        ],
    ],
)
def test_missing_question_text_unpublished_or_unknown_branch_is_not_complete(branches):
    claims = [{"id": "deny", "text": "访客不能下载附件或导出看板。", "kind": "fact"}]
    result = parse("Example: 能下载吗？能导出吗？", claims, branches)
    assert result.status == "unverified"


def test_permission_not_entailing_duty_is_not_a_universal_no_duty_rule():
    claims = [{"id": "vote", "text": "Observers can vote when voting is enabled.", "kind": "fact"}]
    question = "B 允许投票，是否意味着他必须给每张卡片投票？"
    result = parse(question, claims, [branch(question, ["vote"], "permission_entailment")])
    assert result.status == "answered"
    actual_duty = "他是否必须给每张卡片投票？"
    assert (
        parse(actual_duty, claims, [branch(actual_duty, ["vote"], "permission_entailment")]).status
        == "unverified"
    )


def test_receipt_cannot_be_replayed_after_a_published_premise_is_changed():
    question = "Can guests export boards?"
    claims = [{"id": "deny", "text": "Guests cannot export boards.", "kind": "fact"}]
    result = parse(question, claims, [branch(question, ["deny"])])
    assert result.status == "answered"
    changed = [{**claims[0], "text": "Guests can export boards."}]
    assert "answer_subquestion_binding_changed" in coverage_resolution_reasons(
        result, changed, required_binding_version=3
    )


def test_mixed_yes_no_subquestions_require_qualified_parent_conclusion():
    question = "Can guests download? Can they export?"
    claims = [
        {"id": "yes", "text": "Guests can download attachments.", "kind": "fact"},
        {"id": "no", "text": "Guests cannot export boards.", "kind": "fact"},
    ]
    branches = [
        branch("Can guests download? ", ["yes"], "direct", "yes"),
        branch("Can they export?", ["no"]),
    ]
    assert parse(question, claims, branches, conclusion="yes").status == "unverified"
    assert parse(question, claims, branches, conclusion="depends").status == "answered"


@pytest.mark.parametrize("requested,expected", [(3, "answered"), (2, "unverified")])
def test_numeric_denial_compares_the_same_unit(requested, expected):
    question = f"Can {requested} people use the organization?"
    claims = [{"id": "cap", "text": "Only two people can use the organization.", "kind": "fact"}]
    assert parse(question, claims, [branch(question, ["cap"], "upper_bound")]).status == expected


def test_resource_scope_keeps_reviewed_inference_and_product_rule():
    question = "仅有甲域权限的用户能因此清除乙域缓存吗？"
    claims = [
        {"id": "rule", "text": "该角色仅允许清除特定域名的缓存。", "kind": "fact"},
        {"id": "answer", "text": "因此仅有甲域权限不能清除乙域缓存。", "kind": "inference"},
    ]
    assert (
        parse(question, claims, [branch(question, ["rule", "answer"], "resource_scope")]).status
        == "answered"
    )
    scope_only = [{**claims[0], "text": "该角色仅适用于特定域名。"}]
    assert (
        parse(question, scope_only, [branch(question, ["rule"], "resource_scope")]).status
        == "unverified"
    )


def test_new_review_contract_rejects_missing_receipt_but_legacy_reading_survives():
    question = "Can guests download?"
    claims = [{"id": "yes", "text": "Guests can download attachments.", "kind": "fact"}]
    row = dict(
        question_id="q",
        status="answered",
        claim_ids=["yes"],
        resolution="direct",
        conclusion="yes",
        missing_fields=[],
        reason="Reviewed.",
    )
    data = json.dumps({"version": 3, "answers": [row]})
    args = (data, [{"question_id": "q", "question": question}], {"yes"})
    assert parse_answer_coverage(*args, claims=claims)[0].status == "answered"
    assert (
        parse_answer_coverage(*args, claims=claims, require_subquestions=True)[0].status
        == "unverified"
    )


def test_receipt_survives_json_and_binds_exact_source_identity():
    from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

    question = "Can guests export?"
    claims = [
        {
            "id": "no",
            "text": "Guests cannot export.",
            "kind": "fact",
            "fact_ids": ["fact-a"],
            "source_ids": ["source-a"],
        }
    ]
    result = parse(question, claims, [branch(question, ["no"])])
    restored = ReportAnswerCoverage.model_validate_json(result.model_dump_json())
    assert not coverage_resolution_reasons(restored, claims, require_subquestions=True)
    changed = [{**claims[0], "source_ids": ["source-b"]}]
    assert "answer_subquestion_binding_changed" in coverage_resolution_reasons(restored, changed)


def test_contract_version_changes_existing_writer_artifact_digest():
    from packages.research.evidence.report_claims import ReportDimensionAudit
    from packages.research.evidence.snapshot_models import canonical_json

    audit = ReportDimensionAudit(
        competitor="Example",
        dimension="feature",
        consumption_id="use",
        answer_review_contract="subquestion-premises-v1",
    )
    legacy = audit.model_copy(update={"answer_review_contract": None})
    # EvidenceContextMixin hashes full serialized audits in its writer artifact.
    assert canonical_json(audit.model_dump(mode="json")) != canonical_json(
        legacy.model_dump(mode="json")
    )
    assert "answer_review_contract" not in legacy.model_dump(mode="json")
