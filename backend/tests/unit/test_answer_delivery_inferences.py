"""Offline production parse/guard/render regressions, not live semantic evidence."""

import json

import pytest

from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.agents.writer.subquestion_premises import _counts


def decision(question, claims, branches, *, status="answered", conclusion="no"):
    row = dict(
        question_id="q",
        status=status,
        claim_ids=[c["id"] for c in claims],
        resolution="conditional",
        conclusion=conclusion,
        missing_fields=[],
        reason="Offline independently reviewed input fixture.",
        subquestions=branches,
    )
    return parse_answer_coverage(
        json.dumps(dict(version=3, answers=[row])),
        [dict(question_id="q", question=question)],
        {c["id"] for c in claims},
        claims=claims,
        required_binding_version=3,
        require_subquestions=True,
    )[0]


def branch(question, ids, *, relation="upper_bound", conclusion="no"):
    return dict(question_quote=question, claim_ids=ids, relation=relation, conclusion=conclusion)


@pytest.mark.parametrize(
    "cap",
    [
        "Free organization 最多支持 2 名用户（含所有者）。",
        "免费组织最多可支持 2 名用户。",
        "免费组织至多允许 2 名用户。",
        "免费组织最多容纳 2 名用户。",
        "免费组织的用户上限为 2 名用户。",
        "免费组织的用户数量不超过 2 名用户。",
        "A free organization supports at most 2 users.",
    ],
)
def test_complete_stated_caps_resolve_same_unit_request(cap):
    assert _counts(cap, upper=True) == {"people": [2]}
    question = "免费组织能满足 3 名用户的需求吗？"
    claims = [dict(id="cap", text=cap, kind="fact")]
    result = decision(question, claims, [branch(question, ["cap"])])
    assert result.status == "answered", result.reason
    assert result.answer == cap
    assert not coverage_resolution_reasons(result, claims, require_subquestions=True)


@pytest.mark.parametrize(
    "cap",
    [
        "建议免费组织最多支持 2 名用户。",
        "免费组织并非最多支持 2 名用户。",
        "免费组织不是不超过 2 名用户。",
        "如果启用附加限制，免费组织最多支持 2 名用户。",
        "仅当关闭扩容时，免费组织最多支持 2 名用户。",
        "假设免费组织最多支持 2 名用户。",
        "免费组织最多支持 2 个 collections。",
        "免费工作区最多支持 2 名用户。",
    ],
)
def test_caps_with_unknown_conditions_other_units_or_objects_cannot_prove_no(cap):
    question = "免费组织能满足 3 名用户的需求吗？"
    claims = [dict(id="cap", text=cap, kind="fact")]
    result = decision(question, claims, [branch(question, ["cap"])])
    assert result.status == "unverified"
    assert not result.claim_ids and not result.answer


def test_reviewed_nonautomatic_scope_inference_is_a_visible_negative_premise():
    question = "看板 A 的这次权限变更会自动决定小周在看板 B 的权限吗？"
    text = "看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。"
    claims = [dict(id="inference", text=text, kind="inference")]
    result = decision(
        question, claims, [branch(question, ["inference"], relation="explicit_negative")]
    )
    assert result.status == "answered", result.reason
    assert result.answer == text
    assert not coverage_resolution_reasons(result, claims, require_subquestions=True)


@pytest.mark.parametrize(
    "text",
    [
        "无法确认看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。",
        "并非看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。",
        "如果两块看板没有同步规则，看板 A 的变更不会自动决定看板 B 的权限。",
        "看板 A 的这次权限变更不会自动决定小周在文件夹 B 的权限。",
        "建议看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。",
        "不能说看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。",
        "在未启用同步规则的条件下，看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。",
        "看板 A 的这次权限变更不会自动决定小周在看板 C 的权限。",
    ],
)
def test_unconfirmed_conditional_outer_negation_or_other_object_is_not_scope_denial(text):
    question = "看板 A 的这次权限变更会自动决定小周在看板 B 的权限吗？"
    claims = [dict(id="inference", text=text, kind="inference")]
    result = decision(
        question, claims, [branch(question, ["inference"], relation="explicit_negative")]
    )
    assert result.status == "unverified"


def test_nonautomatic_inference_keeps_an_exact_explicit_request_condition():
    from packages.agents.writer.subquestion_premises import _explicit_negative_text

    condition = "在未启用同步规则的条件下，"
    question = condition + "看板 A 的这次权限变更会自动决定小周在看板 B 的权限吗？"
    text = condition + "看板 A 的这次权限变更不会自动决定小周在看板 B 的权限。"
    claims = [dict(id="inference", text=text, kind="inference")]
    result = decision(
        question, claims, [branch(question, ["inference"], relation="explicit_negative")]
    )
    assert result.status == "answered", result.reason
    assert result.answer == text
    assert not _explicit_negative_text(text)


@pytest.mark.parametrize("person", ["同事 C", "Alice"])
def test_named_resource_check_does_not_treat_person_names_as_resource_labels(person):
    question = f"看板 A 的这次权限变更会自动决定{person}在看板 B 的权限吗？"
    text = f"看板 A 的这次权限变更不会自动决定{person}在看板 B 的权限。"
    claims = [dict(id="inference", text=text, kind="inference")]
    result = decision(
        question, claims, [branch(question, ["inference"], relation="explicit_negative")]
    )
    assert result.status == "answered", result.reason


def test_generic_nonautomatic_rule_does_not_need_to_repeat_scenario_resource_labels():
    question = "看板 A 的这次权限变更会自动决定小周在看板 B 的权限吗？"
    text = "某块看板的权限变更不会自动决定另一块看板的权限。"
    claims = [dict(id="rule", text=text, kind="fact")]
    result = decision(question, claims, [branch(question, ["rule"], relation="explicit_negative")])
    assert result.status == "answered", result.reason


def test_explicit_resource_list_does_not_lose_its_second_named_item():
    question = "看板 A 和 B 的权限会自动决定彼此吗？"
    text = "看板 A 的权限不会自动决定看板 B 的权限。"
    claims = [dict(id="inference", text=text, kind="inference")]
    result = decision(
        question, claims, [branch(question, ["inference"], relation="explicit_negative")]
    )
    assert result.status == "answered", result.reason


def test_same_unit_rules_and_reviewed_scenario_denial_keep_complete_selected_texts():
    question = "免费组织能满足 3 名用户使用 3 个 collections 的需求吗？"
    texts = [
        "Free organization 最多支持 2 名用户（含所有者）。",
        "Free organization 最多支持 2 个 collections。",
        "因此，题设 3 名用户使用 3 个 collections 的需求不能由免费组织满足。",
    ]
    claims = [
        dict(id=f"c{i}", text=text, kind="inference" if i == 2 else "fact")
        for i, text in enumerate(texts)
    ]
    result = decision(question, claims, [branch(question, ["c0", "c1", "c2"])])
    assert result.status == "answered", result.reason
    assert result.answer == "\n".join(texts)


def test_known_branch_survives_partial_without_borrowing_a_sibling_claim():
    question = "免费组织能满足 3 名用户吗？完整账单是多少？"
    cap = "Free organization 最多支持 2 名用户（含所有者）。"
    claims = [dict(id="cap", text=cap, kind="fact")]
    branches = [
        branch("免费组织能满足 3 名用户吗？", ["cap"]),
        branch("完整账单是多少？", [], relation="unresolved", conclusion="unknown"),
    ]
    result = decision(question, claims, branches, status="partial", conclusion="depends")
    assert result.status == "partial", result.reason
    assert result.answer == cap and result.claim_ids == ("cap",)
    assert result.subquestion_bindings[1].conclusion == "unknown"
    borrowed = decision(
        question,
        claims,
        [
            branches[0],
            branch("完整账单是多少？", ["cap"], relation="unresolved", conclusion="unknown"),
        ],
        status="answered",
        conclusion="depends",
    )
    assert borrowed.status == "unverified"


def presentation_audit(result, claims):
    from packages.research.evidence.report_claims import (
        AuditedReportClaim,
        ReportClaim,
        ReportDimensionAudit,
    )

    published = [
        AuditedReportClaim(
            claim=ReportClaim(**c, competitor="Example Product", dimension="feature"),
            status="supported",
        )
        for c in claims
    ]
    return ReportDimensionAudit(
        competitor="Example Product",
        dimension="feature",
        consumption_id="offline-use",
        claims=published,
        answer_coverage=[result],
    )


def published_rows(rows):
    return [
        dict(row, fact_ids=["fact-" + row["id"]], source_ids=["source-" + row["id"]])
        for row in rows
    ]


@pytest.mark.parametrize(
    "language,known,unknown",
    [
        ("zh-CN", "结论：否", "结论：尚不能确定"),
        ("en", "Conclusion: no", "Conclusion: unresolved"),
    ],
)
def test_partial_render_identifies_known_and_unknown_exact_branches(language, known, unknown):
    from packages.agents.writer.answer_presentation import (
        question_coverage_lines,
        question_coverage_matches,
    )

    parts = ["免费组织能满足 3 名用户吗？", "完整账单是多少？"]
    claims = published_rows(
        [dict(id="cap", text="Free organization 最多支持 2 名用户（含所有者）。", kind="fact")]
    )
    result = decision(
        "".join(parts),
        claims,
        [
            branch(parts[0], ["cap"]),
            branch(parts[1], [], relation="unresolved", conclusion="unknown"),
        ],
        status="partial",
        conclusion="depends",
    )
    audit = presentation_audit(result, claims)
    block = "\n".join(question_coverage_lines(audit, language))
    assert any(parts[0] in line and known in line for line in block.splitlines())
    assert any(parts[1] in line and unknown in line for line in block.splitlines())
    assert claims[0]["text"] in block
    report = (
        f"### Example Product — {'功能' if language.startswith('zh') else 'feature'}\n\n{block}\n"
    )
    assert question_coverage_matches(report, audit, language, audits=[audit])
    assert not question_coverage_matches(
        report.replace(unknown, known), audit, language, audits=[audit]
    )


def test_branch_render_never_borrows_peer_citations_or_changed_receipts():
    from packages.agents.writer.answer_presentation import question_coverage_lines

    parts = ["访客能下载附件吗？", "访客能导出看板吗？"]
    claims = published_rows(
        [
            dict(id="download", text="访客可以下载附件。", kind="fact"),
            dict(id="export", text="访客不能导出看板。", kind="fact"),
        ]
    )
    result = decision(
        "".join(parts),
        claims,
        [
            branch(parts[0], ["download"], relation="direct", conclusion="yes"),
            branch(parts[1], ["export"], relation="explicit_negative"),
        ],
        conclusion="depends",
    )
    audit = presentation_audit(result, claims)
    lines = question_coverage_lines(audit, "zh-CN")
    decisions = [line for line in lines if any(part in line for part in parts) and "结论" in line]
    assert len(decisions) == 2
    assert all("source-export" not in line for line in decisions if parts[0] in line)
    assert all("source-download" not in line for line in decisions if parts[1] in line)
    changed = result.model_copy(
        update={
            "subquestion_bindings": (
                result.subquestion_bindings[0].model_copy(update={"conclusion": "no"}),
                result.subquestion_bindings[1],
            )
        }
    )
    tampered = audit.model_copy(update={"answer_coverage": (changed,)})
    assert not any(
        parts[0] in line and "结论：否" in line
        for line in question_coverage_lines(tampered, "zh-CN")
    )
