"""Finite v2 source relations use the real SELECT, source review and publication."""

import json

import pytest
from test_conclusion_publication import publication_case

V2 = "structured-conclusions-v2"
CAPABILITIES = (
    "Reviewers are board members that are able to view a board and the cards within the board, "
    "download card attachments, comment and vote on cards (if that is enabled for the board), "
    "and export the board."
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,question,relation,needle",
    [
        (
            "Visitor accounts are ideal for sharing information with people on a limited basis. "
            "They don’t have their own private vaults and only have access to "
            "a single vault, which you choose.",
            "Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？",
            "access_cardinality",
            "2",
        ),
        (
            CAPABILITIES,
            "Example Product：Reviewer 能否下载卡片附件并导出看板？",
            "atomic_operation",
            "下载",
        ),
        (
            CAPABILITIES,
            "Example Product：允许 Reviewer 投票是否意味着必须投票？",
            "modal_non_entailment",
            "必须",
        ),
        (
            "Because a reviewer is a board member permission it isn't "
            "currently possible to set a user "
            "as a reviewer at the Workspace level, and each reviewer is set "
            "individually per member per board.",
            "Example Product：能否在 Workspace 层级统一设置 Reviewer？",
            "role_scope_level",
            "Workspace",
        ),
        (
            "How do I get pricing for Integrated Shield?\nIntegrated Shield "
            "pricing is tailored to your "
            "organization’s needs and the capabilities you require. Contact "
            "our sales team to discuss "
            "your environment and receive a quote.",
            "Example Product Integrated Shield：300 名员工使用一年，人民币含税总价是多少？",
            "sales_scoped_quote",
            "报价",
        ),
    ],
)
async def test_v2_reviewed_relation_reaches_frozen_report_and_cold_authority(
    monkeypatch, source, question, relation, needle
):
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, audit, seen, use = await publication_case(
        monkeypatch, source=source, question=question, conclusion_contract=V2
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert any(e["relation"] == relation for e in entries)
    assert needle.casefold() in case[1].detail.report_md.casefold()
    assert all(e["source_review"]["verdict"] == "supported" for e in entries)
    assert result["compact"]["conclusion_set"]["contract"] == V2
    assert any(name.endswith("atomic_review") for name, _ in seen)
    answer = audit.answer_coverage[0]
    assert (
        _answer_support(case[1].detail, case[2], audit, answer, case[6][0]["questions"][0])
        is not None
    )
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    authority = replay["decision_review"][answer.question_id]
    assert authority.matches(answer)
    assert authority.question_projection()["contract"] == V2
    assert authority.revision_sha256 == result["compact"]["conclusion_set"]["revision_sha256"]
    assert json.dumps(source, ensure_ascii=False)[1:-1] in json.dumps(seen, ensure_ascii=False)


@pytest.mark.asyncio
async def test_v2_current_access_does_not_reuse_an_invitation_maximum(monkeypatch):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source="Visitor accounts can only be invited to a single vault.",
        question="Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
async def test_v2_independent_download_and_export_cells_do_not_overwrite_each_other(monkeypatch):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Reviewer 能否下载卡片附件并导出看板？",
        conclusion_contract=V2,
    )
    answer = audit.answer_coverage[0]
    assert answer.status == "answered" and answer.conclusion == "yes"
    assert len(result["compact"]["conclusion_set"]["entries"]) == 2
    assert len(answer.claim_ids) == 2
    assert len({b.question_quote for b in answer.subquestion_bindings}) == 2


@pytest.mark.asyncio
async def test_v2_download_declined_export_yes_keeps_unknown_sibling_and_distinct_labels(
    monkeypatch,
):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Reviewer 能否下载卡片附件并导出看板？",
        conclusion_contract=V2,
        decline_operations=("download",),
    )
    answer = audit.answer_coverage[0]
    assert answer.status == "partial" and answer.conclusion != "yes"
    assert len(result["compact"]["conclusion_set"]["entries"]) == 1
    assert [(b.question_quote, b.conclusion) for b in answer.subquestion_bindings] == [
        ("下载卡片附件", "unknown"),
        ("导出看板", "yes"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,other_roles,expected",
    [
        ("other.example", "没有任何其他角色", "no"),
        ("example.com", "没有任何其他角色", None),
        ("sub.example.com", "没有任何其他角色", None),
        ("other.example.com", "没有任何其他角色", None),
        ("other.example", "其他角色未知", None),
    ],
)
async def test_v2_domain_scope_is_bounded_to_explicit_only_grant(
    monkeypatch, target, other_roles, expected
):
    source = (
        "| Storage Cache Purger | Grants access to purge the edge cache "
        "for a specific domain and allows the reading of zone settings. |"
    )
    question = (
        "Example Product：同事只被授予 example.com 的 Storage Cache Purger 角色，"
        f"{other_roles}。他能清除 {target} 的边缘缓存吗？"
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch, source=source, question=question, conclusion_contract=V2
    )
    decisions = [e["task_cell"]["outcome"] for e in result["compact"]["conclusion_set"]["entries"]]
    assert ("no" in decisions) == (expected == "no")
    if expected is None:
        assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
async def test_v2_vote_configuration_is_per_resource_and_permission_is_not_duty(monkeypatch):
    question = (
        "Example Product：小林在看板 C 和 D 都是 "
        "Reviewer；C 未启用投票，D 已启用投票。分别判断他能在 "
        "C、D 投票吗？"
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch, source=CAPABILITIES, question=question, conclusion_contract=V2
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert {
        e["task_cell"]["resource"]: e["task_cell"]["outcome"]
        for e in entries
        if e["task_cell"]["resource"]
    } == {"C": "no", "D": "yes"}
    assert audit.answer_coverage[0].status == "answered"
    assert audit.answer_coverage[0].conclusion == "depends"


@pytest.mark.asyncio
async def test_v2_sufficient_condition_does_not_deny_its_false_antecedent(monkeypatch):
    source = "Reviewers can vote on cards if card voting is enabled for the board."
    question = (
        "Example Product：小林在看板 C 和 D 都是 "
        "Reviewer；C 未启用投票，D 已启用投票。分别判断他能在 "
        "C、D 投票吗？"
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch, source=source, question=question, conclusion_contract=V2
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert not any(
        e["task_cell"]["resource"] == "C" and e["task_cell"]["outcome"] == "no" for e in entries
    )
    assert audit.answer_coverage[0].status == "partial"


@pytest.mark.asyncio
async def test_v2_per_resource_configuration_does_not_invent_unknown_peer_role(monkeypatch):
    source = (
        "Because a reviewer is a board member permission it isn't "
        "currently possible to set a user as a reviewer at the Workspace "
        "level, and each reviewer is set individually per member per "
        "board."
    )
    question = "Example Product：小林在看板 C 是 Reviewer；C 上这次改权是否自动决定他在 D 的权限？"
    _, result, audit, _, _ = await publication_case(
        monkeypatch, source=source, question=question, conclusion_contract=V2
    )
    assert (
        result["compact"]["conclusion_set"]["entries"][0]["relation"]
        == "per_resource_configuration"
    )
    assert audit.answer_coverage[0].conclusion == "no"
    assert "实际角色仍须单独核实" in audit.answer_coverage[0].answer


@pytest.mark.asyncio
async def test_v2_unapproved_source_never_publishes_derived_access_denial(monkeypatch):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source="Visitor accounts are ideal for sharing information with people "
        "on a limited basis. They don’t have their own private vaults and "
        "only have access to a single vault, which you choose.",
        question="Example Product：Visitor 已接受邀请且已确认，能否同时访问 2 个 vaults？",
        conclusion_contract=V2,
        review_status="uncertain",
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
async def test_v2_sales_quote_is_authenticated_limitation_with_its_own_typed_qa_target(monkeypatch):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import (
        context_for,
        payload_from,
        receipt,
        traced_model_double,
    )

    from packages.agents.qa.question_reconciliation import (
        authenticated_answer_delivery,
        reconcile_question_findings,
    )

    source = (
        "How do I get pricing for Integrated Shield?\nIntegrated Shield "
        "pricing is tailored to your "
        "organization’s needs and the capabilities you require. Contact our sales team to discuss "
        "your environment and receive a quote."
    )
    case, result, audit, producer_seen, use = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product Integrated Shield：300 名员工使用一年，人民币含税总价是多少？",
        conclusion_contract=V2,
    )
    review_payload = next(p for name, p in producer_seen if name.endswith("atomic_review"))
    assert "说明环境后获取" in review_payload["claims"][0]["text"]
    assert review_payload["typed_source_relation"]["rule"]["provider"] == "official_sales"
    assert (
        review_payload["typed_source_relation"]["rule"]["workflow"]
        == "discuss_environment_and_receive_quote"
    )
    assert any(
        "audits all typed_source_relation fields" in span.full_input
        for span in case[1].detail.trace_spans
        if span.name.endswith("atomic_review")
    )
    from copy import deepcopy

    from packages.agents.writer.selected_task_delivery import parse_generation

    proposal = deepcopy(next(p for name, p in producer_seen if name.endswith("atomic_generation")))
    candidate = proposal["conclusion_candidates"][0]
    candidate["rule"]["workflow"] = "wrong_or_unreviewed_workflow"
    with pytest.raises(ValueError, match="candidates_changed"):
        parse_generation(
            json.dumps(
                dict(
                    version=1,
                    task_id=candidate["task_id"],
                    status="selected",
                    candidate_ref=candidate["candidate_ref"],
                )
            ),
            proposal,
            case[4],
            case[5],
        )
    service, record, snapshot = case[:3]
    question = case[6][0]["questions"][0]
    answer = audit.answer_coverage[0]
    assert answer.missing_fields == ("official_scoped_quote",)
    assert "cpu_usage" not in answer.missing_fields
    assert (
        authenticated_answer_delivery(record.detail, snapshot, audit, answer, question)
        == "supported_sourced_limitation"
    )
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    assert service._final_qa_producer_verified(record, snapshot)
    seen = []

    async def model(_record, **kwargs):
        payload = payload_from(kwargs)
        seen.append(payload)
        candidate = context_for(payload, payload["findings"][0])
        assert candidate["verification_target"] == "supported_sourced_limitation_delivery"
        assert candidate["structured_conclusions_contract"] == V2
        assert (
            candidate["conclusion_revision_sha256"]
            == result["compact"]["conclusion_set"]["revision_sha256"]
        )
        assert candidate["pending_inputs"] == ["pending_input:official_scoped_quote"]
        assert all("cpu_usage" not in o["ref"] for o in candidate["delivery_obligations"])
        assert len(kwargs["user"].encode()) <= 14000
        assert len(kwargs["system"].encode()) <= 3844
        response = json.loads(reviewed(payload, "current_limitation"))
        for row in response["reviews"]:
            row["delivery_gaps"] = []
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    assert not await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert seen
    assert receipt(record.detail)["valid_review_issue_ids"]
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "given", ["不能断言他没有其他角色", "如果没有任何其他角色", "并非没有其他角色"]
)
async def test_v2_scope_does_not_promote_unknown_or_conditional_role_exclusions(monkeypatch, given):
    source = (
        "| Storage Cache Purger | Grants access to purge the edge cache "
        "for a specific domain and allows the reading of zone settings. |"
    )
    _, result, _, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question=(
            "Example Product：同事只被授予 example.com 的 Storage Cache Purger 角色，"
            f"{given}。他能清除 other.example 的边缘缓存吗？"
        ),
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]


@pytest.mark.asyncio
async def test_v2_access_does_not_turn_unconfirmed_lifecycle_into_given_confirmation(monkeypatch):
    source = (
        "Guest accounts are ideal for sharing information with people on "
        "a limited basis. They don’t have their own private vaults and "
        "only have access to a single vault, which you choose."
    )
    _, result, _, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product：访客已接受邀请但尚未确认，能否同时访问 2 个 vaults？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,expected",
    [
        ("Domain-scoped roles apply for a given domain within an account.", True),
        ("Domain-scoped roles also apply to all domains within an account.", False),
        ("Roles can be delegated to other accounts without restrictions.", False),
    ],
)
async def test_v2_actual_paired_selection_keeps_one_complete_primary_relation(
    monkeypatch, scope, expected
):
    primary = (
        "| Storage Cache Purger | Grants access to purge the edge cache "
        "for a specific domain and allows the reading of zone settings. |"
    )
    case, result, _, seen, _ = await publication_case(
        monkeypatch,
        sources=[primary, scope],
        question="Example Product：同事只被授予 example.com 的 Storage Cache Purger "
        "角色，没有任何其他角色。他能清除 other.example 的边缘缓存吗？",
        conclusion_contract=V2,
        selected_refs_limit=2,
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert bool(entries) is expected
    if expected:
        assert any(
            len(p["task_support_selections"][0]["support_refs"]) == 2
            for name, p in seen
            if name.endswith("atomic_generation")
        )
        assert all(len(e["source_fact"]["fact_ids"]) == 1 for e in entries)
        assert all(len(e["candidate"]["support_refs"]) == 1 for e in entries)
        assert "other.example" in case[1].detail.report_md


@pytest.mark.asyncio
async def test_v2_billable_examples_do_not_invent_free_status_or_actual_membership(monkeypatch):
    source = (
        "There are no limits to how many reviewers you can have on a "
        "board, and a reviewer can be a billable Workspace member, or "
        "multi-board guest"
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product：小周是 Reviewer；仅凭该权限标签能否确定他一定免费或一定计费？",
        conclusion_contract=V2,
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert entries and entries[0]["relation"] == "role_billing_input_gap"
    answer = audit.answer_coverage[0]
    assert answer.conclusion == "unknown" and answer.status == "partial"
    assert answer.missing_fields == ("actual_membership_type",)
    assert "无法核实实际收费身份" in answer.answer
    assert "是免费" not in answer.answer


@pytest.mark.asyncio
async def test_v2_other_resource_role_and_unknown_configuration_do_not_supply_permission(
    monkeypatch,
):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：小林在看板 D 是 "
        "Reviewer；C 已启用投票，D 已启用投票。分别判断他能在 "
        "C、D 投票吗？",
        conclusion_contract=V2,
    )
    entries = result["compact"]["conclusion_set"]["entries"]
    assert not any(e["task_cell"]["resource"] == "C" for e in entries)
    assert audit.answer_coverage[0].status == "partial"


@pytest.mark.asyncio
async def test_v2_one_access_no_does_not_short_circuit_independent_private_branch(monkeypatch):
    _, _, audit, _, _ = await publication_case(
        monkeypatch,
        source="Guest accounts are ideal for sharing information with people on "
        "a limited basis. They don’t have their own private vaults and "
        "only have access to a single vault, which you choose.",
        question="Example Product：访客已接受邀请并被确认。他能同时加入两"
        "个共享保险库，或者拥有自己的 Private vault 吗？",
        conclusion_contract=V2,
    )
    answer = audit.answer_coverage[0]
    assert answer.status == "partial" and answer.conclusion != "no"
    assert any(b.conclusion == "unknown" for b in answer.subquestion_bindings)


@pytest.mark.asyncio
async def test_v2_journal_cas_keeps_semantic_revision_and_authenticates_tampering(
    monkeypatch, tmp_path
):
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews
    from packages.memory import RunJournal

    case, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Reviewer 能否下载卡片附件并导出看板？",
        conclusion_contract=V2,
    )
    journal = RunJournal(tmp_path / "permissions.db")
    revision = journal.save_run(case[1].detail)
    loaded, stored = journal.load_run_snapshot(case[1].detail.id)
    assert revision == stored
    expected = result["compact"]["conclusion_set"]["revision_sha256"]
    authority = replay_decision_reviews(loaded, loaded.report_dimension_audits[0])[
        audit.answer_coverage[0].question_id
    ]
    assert authority.revision_sha256 == expected
    next_revision = journal.save_run(loaded, expected_revision=stored)
    assert next_revision > revision
    reloaded = journal.load_run(loaded.id)
    assert (
        replay_decision_reviews(reloaded, reloaded.report_dimension_audits[0])[
            audit.answer_coverage[0].question_id
        ].revision_sha256
        == expected
    )
    for fault in ("source", "task", "snapshot", "selector", "candidate", "quote"):
        changed = reloaded.model_copy(deep=True)
        span = next(s for s in changed.trace_spans if s.name.endswith("atomic_generation"))
        prefix, wire = span.full_input.split("\nJSON:\n", 1)
        raw = json.loads(wire)
        if fault == "selector":
            raw["structured_conclusions_contract"] = "structured-conclusions-v1"
        elif fault == "candidate":
            response = json.loads(span.full_output)
            response["candidate_ref"] = "unselected-candidate"
            span.full_output = json.dumps(response)
        elif fault == "snapshot":
            raw["snapshot_id"] = "another-snapshot"
        else:
            raw["conclusion_candidates"][0][
                {"source": "source_binding_sha256", "task": "task_id", "quote": "source_fact_text"}[
                    fault
                ]
            ] = "tampered"
        span.full_input = prefix + "\nJSON:\n" + json.dumps(raw)
        with pytest.raises((ValueError, RuntimeError)):
            replay_decision_reviews(changed, changed.report_dimension_audits[0])
    await case[0].aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["invalid_json", "decline"])
async def test_v2_bad_generation_is_local_and_peer_remains_authenticated(monkeypatch, fault):
    import test_task_support_selection as transport

    original = transport.append_response

    def respond(service, record, kwargs, response):
        if kwargs["name"].endswith("atomic_generation"):
            from claim_review_fixture import expand_prompt_payload

            payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
            if payload["generation_tasks"][0]["focus"] == "download":
                if fault == "invalid_json":
                    response = "{"
                else:
                    raw = json.loads(response)
                    raw.update(status="insufficient_evidence", candidate_ref=None)
                    response = json.dumps(raw)
        return original(service, record, kwargs, response)

    monkeypatch.setattr(transport, "append_response", respond)
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Reviewer 能否下载卡片附件并导出看板？",
        conclusion_contract=V2,
    )
    assert len(result["compact"]["conclusion_set"]["entries"]) == 1
    assert audit.answer_coverage[0].status == "partial"
    assert [
        (b.question_quote, b.conclusion) for b in audit.answer_coverage[0].subquestion_bindings
    ] == [("下载卡片附件", "unknown"), ("导出看板", "yes")]


@pytest.mark.asyncio
async def test_v2_typed_qa_cannot_ignore_audit_answer_version_mismatch(monkeypatch):
    from packages.agents.qa.question_reconciliation import (
        _answer_support,
        authenticated_answer_delivery,
    )

    case, _, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Reviewer 能否下载卡片附件并导出看板？",
        conclusion_contract=V2,
    )
    mismatched = audit.model_copy(update={"answer_binding_version": 2})
    answer = audit.answer_coverage[0]
    question = case[6][0]["questions"][0]
    assert _answer_support(case[1].detail, case[2], mismatched, answer, question) is None
    assert (
        authenticated_answer_delivery(case[1].detail, case[2], mismatched, answer, question) is None
    )


@pytest.mark.asyncio
async def test_v2_selected_value_keeps_full_lifecycle_parent_restrictions(monkeypatch):
    primary = (
        "Share a vault with a guest\nGuests have to accept their "
        "invitation and be confirmed before you can share a vault with "
        "them. "
        "After you’ve confirmed a guest, you can\nadd them to a "
        "vault\nand\nmanage their access to it\n, like you would a family "
        "member.\n"
        "A guest can only be invited to a single vault at a time, but you "
        "can remove them from one vault, then add them to a different one."
    )
    access = (
        "Guest accounts are ideal for sharing information with people on a limited basis. "
        "They don’t have their own private vaults and only have access to "
        "a single vault, which you choose. Consider inviting:"
    )
    _, result, audit, seen, _ = await publication_case(
        monkeypatch,
        source=primary,
        source_values=[[primary, access, "Your accountant, who needs your financial information."]],
        question="Example Product：在 Household "
        "套餐中，访客已接受邀请并被确认。他能同时加入两个共享保险库吗？",
        conclusion_contract=V2,
        selected_quote_contains="only have access",
    )
    assert any(
        e["relation"] == "access_cardinality"
        for e in result["compact"]["conclusion_set"]["entries"]
    )
    assert audit.answer_coverage[0].conclusion == "no"
    review_payload = next(p for name, p in seen if name.endswith("atomic_review"))
    generation = next(p for name, p in seen if name.endswith("atomic_generation"))
    assert json.dumps(primary, ensure_ascii=False)[1:-1] in json.dumps(
        generation, ensure_ascii=False
    )
    assert review_payload["claims"][0]["support_quotes"] == [
        access.removesuffix(" Consider inviting:")
    ]
    assert "constraint_context" in review_payload


@pytest.mark.asyncio
async def test_v2_actual_configuration_frame_and_full_parent_members_remain_bound(monkeypatch):
    classification = (
        "Because a reviewer is a board member permission and not a membership\ntype\n"
        ", a board admin in a Premium Workspace can set both Workspace "
        "members and guests as a reviewer on a board."
    )
    parent = CAPABILITIES + "\nReviewers are not able to edit cards.\n" + classification
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=classification,
        source_values=[[parent, "Reviewers are not able to edit cards."]],
        selected_quote_contains="Reviewers are board members",
        question="Example Product：假设 Workspace 已订阅 Premium，小林已分别被设为看板 C 和 D 的 "
        "Reviewer；C 未启用卡片投票，D 已启用且允许该 "
        "Reviewer 投票。逐项判断：小林能在 C、D 投票吗？",
        conclusion_contract=V2,
    )
    assert audit.answer_coverage[0].status == "answered"
    assert {
        e["task_cell"]["resource"]: e["task_cell"]["outcome"]
        for e in result["compact"]["conclusion_set"]["entries"]
        if e["task_cell"]["resource"]
    } == {"C": "no", "D": "yes"}


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["current_limitation", "keep"])
async def test_v2_membership_limitation_has_independent_qa_and_can_keep_source_objection(
    monkeypatch, verdict
):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import (
        context_for,
        payload_from,
        receipt,
        traced_model_double,
    )

    from packages.agents.qa.question_reconciliation import (
        authenticated_answer_delivery,
        reconcile_question_findings,
    )

    source = (
        "Because a reviewer is a board member permission and not a membership type, "
        "a board admin in a Premium Workspace can set both Workspace "
        "members and guests as a reviewer on a board."
    )
    case, _, audit, _, use = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product：小周是 Reviewer；仅凭该权限标签能否确定他一定免费或一定计费？",
        conclusion_contract=V2,
    )
    service, record, snapshot = case[:3]
    answer = audit.answer_coverage[0]
    question = case[6][0]["questions"][0]
    assert (
        authenticated_answer_delivery(record.detail, snapshot, audit, answer, question)
        == "supported_sourced_limitation"
    )
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )

    async def model(_record, **kwargs):
        payload = payload_from(kwargs)
        context = context_for(payload, payload["findings"][0])
        assert context["verification_target"] == "supported_sourced_limitation_delivery"
        assert context["pending_inputs"] == ["pending_input:actual_membership_type"]
        assert context["blocked_outputs"] == ["blocked_output:actual_billing_status"]
        response = json.loads(reviewed(payload, verdict))
        for row in response["reviews"]:
            row["delivery_gaps"] = []
            if verdict == "keep":
                row.update(
                    finding_fully_addressed=False,
                    remaining_gaps=["Independent source objection."],
                    delivery_gaps=[
                        dict(kind="wrong_source", obligation_ref="claim:" + answer.claim_ids[0])
                    ],
                )
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    issues = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert bool(issues) is (verdict == "keep")
    assert receipt(record.detail)["valid_review_issue_ids"]
    await service.aclose()


@pytest.mark.asyncio
async def test_v2_full_parent_sources_and_three_task_qa_fit_unchanged_wire_budget(monkeypatch):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import payload_from, receipt, traced_model_double

    from packages.agents.qa.question_reconciliation import reconcile_question_findings

    classification = (
        "Because a reviewer is a board member permission and not a membership\ntype\n"
        ", a board admin in a Premium "
        "Workspace can set both Workspace "
        "members and guests as a reviewer "
        "on a board."
    )
    denied = (
        "Reviewers are not able to move or "
        "edit cards, upload card "
        "attachments, tick the box on a "
        "checklist item, and reviewers "
        "can't change board settings."
    )
    billing = (
        "There are no limits to how many "
        "reviewers you can have on a board, "
        "and a reviewer can be a billable "
        "Workspace member, or\nmulti-board "
        "guest"
    )
    parent = "\n".join([CAPABILITIES, denied, classification, billing])
    case, _, _, _, use = await publication_case(
        monkeypatch,
        source=classification,
        source_values=[[parent, denied]],
        selected_quote_contains="Reviewers are board members",
        question=(
            "Example Product：假设 Workspace 已订阅 "
            "Premium，小林已分别被设为看板 C 和 D 的 "
            "Reviewer；"
            "C 未启用卡片投票，D 已启用且允许该 Reviewer 投票。仅依据所给页面逐项判断："
            "小林能在 C、D 投票吗？他能下载 C 的卡片附件并导出 C 吗？"
            "D 允许投票，是否意味着他必须给每张卡片投票？请分别说明操作、启用条件与强制义务。"
        ),
        conclusion_contract=V2,
    )
    service, record, _ = case[:3]
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    seen = []

    async def model(_record, **kwargs):
        seen.append(kwargs)
        assert len(kwargs["user"].encode()) <= 14000
        assert len(kwargs["system"].encode()) <= 3844
        return reviewed(payload_from(kwargs), "superseded")

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert seen, "Complete originals must fit without dropping the whole independent review."
    qa_receipt = receipt(record.detail)
    assert (
        qa_receipt["planned_issue_ids"]
        == qa_receipt["sent_issue_ids"]
        == qa_receipt["valid_review_issue_ids"]
    )
    assert not qa_receipt["unsent_issue_ids"]
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "language,expected",
    [
        ("zh-CN", "Reviewer 看板成员可下载卡片附件。"),
        ("en-US", "Reviewer board members can download card attachments."),
    ],
)
async def test_v2_public_source_assertion_language_is_reviewed_before_render(
    monkeypatch, language, expected
):
    case, result, audit, seen, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Reviewer 能否下载卡片附件？",
        conclusion_contract=V2,
        output_language=language,
    )
    assert result["compact"]["conclusion_set"]["entries"][0]["source_fact"]["text"] == expected
    assert audit.claims[0].claim.text == expected
    assert expected in case[1].detail.report_md
    assert (
        next(p for name, p in seen if name.endswith("atomic_review"))["claims"][0]["text"]
        == expected
    )


@pytest.mark.asyncio
async def test_v2_guest_lifecycle_cannot_be_borrowed_for_another_actor_role(monkeypatch):
    source = (
        "Guest accounts are ideal for "
        "sharing information with people on "
        "a limited basis. They don’t have "
        "their own private vaults and only "
        "have access to a single vault, "
        "which you choose."
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product：Guest "
        "Bob已接受邀请并被确认。Member Alice能同时访问两个 "
        "vaults 吗？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
async def test_v2_resource_grant_cannot_be_borrowed_from_another_actor(monkeypatch):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Bob在看板 C 是 "
        "Reviewer；Alice在看板 D 是 "
        "Reviewer。Alice能下载 C 的卡片附件并导出 C 吗？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "yes"


@pytest.mark.asyncio
async def test_v2_domain_grant_cannot_be_borrowed_from_another_actor(monkeypatch):
    source = (
        "| Storage Cache Purger | Grants "
        "access to purge the edge cache for "
        "a specific domain and allows the "
        "reading of zone settings. |"
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product：Bob只被授予 "
        "example.com 的 Storage Cache Purger "
        "角色，没有任何其他角色。Alice能清除 other.example "
        "的边缘缓存吗？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].conclusion != "no"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cta", ["", "Contact our support team to discuss your environment and receive a quote."]
)
async def test_v2_sales_workflow_must_be_present_in_reviewed_original(monkeypatch, cta):
    source = (
        "Integrated Shield pricing is "
        "tailored to your organization’s "
        "needs and the capabilities you "
        "require. " + cta
    )
    _, result, _, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question="Example Product Integrated Shield：人民币含税总价是多少？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]


@pytest.mark.asyncio
async def test_v2_ambiguous_pronoun_does_not_choose_one_of_two_actors(monkeypatch):
    _, result, _, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Bob在看板 C 是 "
        "Reviewer；Alice在看板 D 是 Member。他能下载 "
        "C 的卡片附件并导出 C 吗？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]


@pytest.mark.asyncio
async def test_v2_generic_voting_rule_does_not_answer_unknown_named_actor(monkeypatch):
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question="Example Product：Bob在看板 C 是 Reviewer。Alice能投票吗？",
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].status != "answered"


@pytest.mark.asyncio
async def test_original_role_change_membership_frame_publishes_and_sends_limitation_to_qa(
    monkeypatch,
):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import (
        context_for,
        payload_from,
        receipt,
        traced_model_double,
    )

    from packages.agents.qa.question_reconciliation import (
        authenticated_answer_delivery,
        reconcile_question_findings,
    )

    source = (
        "There are no limits to how many observers you can have on a board, "
        "and an observer can be a billable Workspace member, or multi-board guest"
    )
    question = (
        "Example Product：管理员把看板 A 上现有协作者小周的权限改成了 Observer。"
        "只凭 A 上的 Observer 标签，能否确定他一定免费或一定计费？"
    )
    case, result, audit, _, use = await publication_case(
        monkeypatch, source=source, question=question, conclusion_contract=V2
    )
    answer = audit.answer_coverage[0]
    entries = result["compact"]["conclusion_set"]["entries"]
    assert entries and entries[0]["relation"] == "role_billing_input_gap"
    binding = entries[0]["task_cell"]["request_binding"]
    assert binding["actor"] == "小周" and binding["resource"] == "A"
    assert answer.status == "partial" and answer.conclusion == "unknown"
    assert answer.missing_fields == ("actual_membership_type",)
    service, record, snapshot = case[:3]
    q = case[6][0]["questions"][0]
    assert (
        authenticated_answer_delivery(record.detail, snapshot, audit, answer, q)
        == "supported_sourced_limitation"
    )
    service._record_evidence_artifact(
        record,
        kind="writer",
        payload=service._writer_evidence_artifact_payload(record.detail),
        uses=[use],
    )
    seen = []

    async def model(_record, **kwargs):
        payload = payload_from(kwargs)
        current = context_for(payload, payload["findings"][0])
        assert current["verification_target"] == "supported_sourced_limitation_delivery"
        seen.append(current)
        response = json.loads(reviewed(payload, "current_limitation"))
        for row in response["reviews"]:
            row["delivery_gaps"] = []
        return json.dumps(response)

    traced_model_double(monkeypatch, service, model)
    assert not await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert seen and receipt(record.detail)["valid_review_issue_ids"]
    await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("label,recipient", [("B", "他"), ("A", "管理员"), ("A", "Alice")])
async def test_role_change_label_cannot_supply_another_resource_or_operator(
    monkeypatch, label, recipient
):
    source = (
        "There are no limits to how many reviewers you can have on a board, "
        "and a reviewer can be a billable Workspace member, or multi-board guest"
    )
    _, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question=(
            "Example Product：管理员把看板 A 上现有协作者Bob的权限改成了 Reviewer。"
            f"只凭 {label} 上的 Reviewer 标签，能否确定{recipient}一定免费或一定计费？"
        ),
        conclusion_contract=V2,
    )
    assert not result["compact"]["conclusion_set"]["entries"]
    assert audit.answer_coverage[0].status != "answered"


@pytest.mark.asyncio
@pytest.mark.parametrize("other", ["Bob的其他角色未知", "Bob还有其他角色"])
async def test_quality_other_actor_exclusion_cannot_close_bobs_grant(monkeypatch, other):
    source = (
        "| Storage Cache Purger | Grants access to purge the edge cache "
        "for a specific domain and allows the reading of zone settings. |"
    )
    case, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question=(
            "Example Product：Bob只被授予 example.com 的 Storage Cache Purger 角色；"
            f"{other}。Alice是 Member，没有任何其他角色。"
            "Bob能清除 other.example 的边缘缓存吗？"
        ),
        conclusion_contract=V2,
    )
    assert any(c.status == "supported" for c in audit.claims)
    assert not any(
        e["relation"] == "permission_scope" and e["task_cell"]["outcome"] == "no"
        for e in result["compact"]["conclusion_set"]["entries"]
    )
    assert "且无其他角色的题设内该授权不提供" not in case[1].detail.report_md


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "后来管理员已取消小林在 C 的 Reviewer 角色",
        "小林当前在 C 不是 Reviewer",
        "小林在 C 的 Reviewer 角色未知",
    ],
)
async def test_quality_current_role_negative_or_unknown_cannot_publish_permission(
    monkeypatch, change
):
    from packages.agents.qa.question_reconciliation import authenticated_answer_delivery

    case, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=CAPABILITIES,
        question=(
            f"Example Product：小林在看板 C 是 Reviewer；{change}。"
            "小林能下载 C 的卡片附件并导出 C 吗？"
        ),
        conclusion_contract=V2,
    )
    answer = audit.answer_coverage[0]
    assert any(c.status == "supported" for c in audit.claims)
    assert not any(
        e["task_cell"]["outcome"] == "yes" for e in result["compact"]["conclusion_set"]["entries"]
    )
    assert (answer.status, answer.conclusion) != ("answered", "yes")
    assert (
        authenticated_answer_delivery(
            case[1].detail, case[2], audit, answer, case[6][0]["questions"][0]
        )
        != "supported_answer"
    )


@pytest.mark.asyncio
async def test_quality_given_membership_is_not_a_missing_input_or_certified_limitation(monkeypatch):
    from packages.agents.qa.question_reconciliation import authenticated_answer_delivery

    source = (
        "There are no limits to how many reviewers you can have on a board, "
        "and a reviewer can be a billable Workspace member, or multi-board guest"
    )
    case, _, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question=(
            "Example Product：小周是 Reviewer；小周实际为 billable Workspace member。"
            "仅凭该权限标签能否确定他一定免费或一定计费？"
        ),
        conclusion_contract=V2,
    )
    answer = audit.answer_coverage[0]
    assert any(c.status == "supported" for c in audit.claims)
    assert "actual_membership_type" not in answer.missing_fields
    assert (
        authenticated_answer_delivery(
            case[1].detail, case[2], audit, answer, case[6][0]["questions"][0]
        )
        != "supported_sourced_limitation"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity_actor,membership,expected",
    [("小周", "未知", True), ("小周", "未确认", True), ("小周", "unknown", True),
     ("小李", "未知", False)],
)
async def test_unknown_membership_remains_a_missing_input_and_sourced_limitation(
    monkeypatch, identity_actor, membership, expected
):
    from packages.agents.qa.question_reconciliation import authenticated_answer_delivery

    source = (
        "There are no limits to how many reviewers you can have on a board, "
        "and a reviewer can be a billable Workspace member, or multi-board guest"
    )
    case, result, audit, _, _ = await publication_case(
        monkeypatch,
        source=source,
        question=(
            f"Example Product：小周是 Reviewer；{identity_actor}实际成员身份为{membership}。"
            "仅凭该权限标签能否确定他一定免费或一定计费？"
        ),
        conclusion_contract=V2,
    )
    answer = audit.answer_coverage[0]
    assert any(c.status == "supported" for c in audit.claims)
    entries = result["compact"]["conclusion_set"]["entries"]
    if not expected:
        assert not entries
        assert authenticated_answer_delivery(
            case[1].detail, case[2], audit, answer, case[6][0]["questions"][0]
        ) != "supported_sourced_limitation"
        return
    assert entries and entries[0]["relation"] == "role_billing_input_gap"
    assert answer.missing_fields == ("actual_membership_type",)
    assert answer.status == "partial" and answer.conclusion == "unknown"
    assert (
        authenticated_answer_delivery(
            case[1].detail, case[2], audit, answer, case[6][0]["questions"][0]
        )
        == "supported_sourced_limitation"
    )
