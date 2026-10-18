"""Anonymous examples of complete, source-bound exception closure."""

import json
from types import SimpleNamespace

import pytest

from packages.research.evidence.normalization import normalized_feature_fields_from_evidence_items
from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json
from packages.research.models import EvidenceItem

ACCESS = (
    "Removing a member from your organization does not delete their account. "
    "Removed members can still access their personally-owned vault items."
)
AUTH = (
    "For member accounts that do not have master passwords "
    "as a result of SSO with trusted devices:\n"
    "- Removing them from your organization eliminates all access to their account unless they "
    "were previously assigned a master password using account recovery and they log in with "
    "that master password at least once before being removed."
)
UNSHARE = (
    "When you unshare a folder, the files are permanently deleted from each member's account "
    "and removed from linked devices when the desktop app syncs again."
)
COPY = (
    "When you remove a member from a folder or unshare a folder, you can choose to let them "
    "keep a copy of that folder, but it'll no longer sync with other accounts."
)
LINK = (
    "If there are shared links in a shared folder and the link creator leaves the folder, "
    "the view access links will still be enabled."
)
DELETE_LINK = "If you delete a link, the deactivated link no longer works for anyone."
EXCEPT = (
    "If you're the owner of a shared folder, you can unshare the folder at any time, except if:\n"
    "- The folder contains shared folders\n"
    "You can set user permissions, but cannot unshare specific files inside the folder.\n"
    "- The folder is inside another shared folder\n"
    "Move the subfolder out of the parent folder before unsharing it.\n"
    "- The folder contains inactive shared folders"
)


def item(quote, field="base", **updates):
    values = dict(
        competitor="Example Product",
        dimension="feature",
        field=field,
        value={"status": "documented", "evidence_terms": [quote]},
        source_candidate_id="candidate",
        captured_page_id="capture",
        source_url="https://example.test/help/rules",
        raw_source_id="source",
        quote=quote,
        confidence=0.9,
        status="accepted",
    )
    values.update(updates)
    return EvidenceItem(**values)


def facts(*items):
    rows = normalized_feature_fields_from_evidence_items(items)
    return [
        EvidenceFact(
            id=f"fact-{row.slot}",
            semantic_id=f"semantic-{row.slot}",
            source_id="source",
            competitor=row.competitor,
            dimension="feature",
            field="evidence_terms",
            value_json=canonical_json(row.evidence_terms),
            quote=row.evidence_quote,
            qualifiers_json=canonical_json(row.qualifiers),
            evidence_item_ids=tuple(row.evidence_item_ids),
            status="supported",
            confidence=0.9,
        )
        for row in rows
    ]


def reasons(text, originals):
    original = originals[0]
    candidate = ReportClaim(
        id="claim",
        text=" ".join(text.split()),
        kind="fact",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
    )
    return claim_rule_reasons(
        candidate,
        SimpleNamespace(facts=tuple(originals)),
        [SimpleNamespace(allowed_fact_ids=(original.id,))],
    )


def test_authentication_exception_binds_to_access_guarantee_and_replays_both_prerequisites():
    originals = facts(item(ACCESS), item(AUTH, "auth"))
    links = originals[0].qualifiers.get("source_exception_links", [])
    assert links and links[0]["evidence_item_id"] == item(AUTH, "auth").id
    assert links[0]["quote"] == AUTH
    assert "source_exception_omitted_or_changed" in reasons(ACCESS, originals)
    for text in (
        "Removed members retain access unless SSO applies; account recovery is required.",
        "SSO trusted device accounts retain access after logging in before removal.",
    ):
        assert "source_exception_omitted_or_changed" in reasons(text, originals)
    assert not reasons(ACCESS + " " + AUTH, originals)


def test_authentication_does_not_constrain_a_pure_data_retention_claim():
    originals = facts(item(ACCESS), item(AUTH, "auth"))
    assert not reasons(
        "Removing a member does not delete their personally-owned vault data.", originals
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"competitor": "Other Product"},
        {"captured_page_id": "other"},
        {"raw_source_id": "other"},
        {"source_url": "https://example.test/other"},
        {"metadata": {"document_section": "other"}},
        {"metadata": {"role": "Editors"}},
        {"status": "rejected"},
    ],
)
def test_receipts_do_not_cross_source_capture_section_role_or_admission(updates):
    assert not facts(item(ACCESS), item(AUTH, "auth", **updates))[0].qualifiers.get(
        "source_exception_links"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Deleting a member account permanently deletes all data.",
        "When you remove a member from a folder, they lose access to that folder.",
        "Removing editors from an organization does not delete their account; "
        "editors retain access.",
    ],
)
def test_receipts_do_not_cross_action_object_or_subject(quote):
    assert not facts(item(quote), item(AUTH, "auth"))[0].qualifiers.get("source_exception_links")


def test_copy_and_sync_remain_separate_required_outcomes():
    originals = facts(item(UNSHARE), item(COPY, "copy"))
    assert "source_exception_omitted_or_changed" in reasons(UNSHARE, originals)
    assert "source_exception_omitted_or_changed" in reasons(
        UNSHARE + " Users keep a copy.", originals
    )
    assert not reasons(UNSHARE + " " + COPY, originals)


def test_except_list_must_preserve_all_three_independent_branches():
    originals = facts(item(EXCEPT))
    incomplete = EXCEPT[: EXCEPT.index("- The folder is inside")]
    assert "source_exception_omitted_or_changed" in reasons(incomplete, originals)
    assert not reasons(EXCEPT, originals)


def test_semantic_retains_an_818_character_complete_conditional_group():
    from test_semantic_extraction import fixture

    from packages.research.extraction.semantic import semantic_extraction

    prefix = "For member accounts using trusted devices without master passwords:\n"
    tail = " " + AUTH.split("\n", 1)[1]
    quote = prefix + "Details remain source context. " * 13 + tail
    quote = prefix + ("x" * (818 - len(prefix) - len(tail) - 2)) + ".\n" + tail
    assert len(quote) == 818
    brief, _, page = fixture(quote)
    result = semantic_extraction(brief, page, {"facts": [{"quote": quote}]})
    assert result.quotes and result.quotes[0].text == quote
    assert quote in next(iter(result.fields.values()))["conditions"]


def test_semantic_captures_whole_except_list_with_interleaved_explanations():
    from test_semantic_extraction import fixture

    from packages.research.extraction.semantic import semantic_extraction

    brief, _, page = fixture(EXCEPT)
    result = semantic_extraction(brief, page, {"facts": [{"quote": EXCEPT.splitlines()[0]}]})
    assert result.quotes
    assert EXCEPT in next(iter(result.fields.values()))["evidence_terms"]


def test_incomplete_except_prefix_cannot_publish_without_fabricating_missing_branches():
    originals = facts(item(EXCEPT.splitlines()[0]))
    assert "source_exception_unresolved" in reasons(EXCEPT.splitlines()[0], originals)


@pytest.mark.asyncio
async def test_retrieval_closes_independent_copy_and_link_branches_past_near_duplicates():
    from test_question_retrieval import research_case

    from packages.agents.writer.question_retrieval import retrieve_question_facts

    quotes = [UNSHARE + f" This is observation {index}." for index in range(4)]
    detail, snapshot = research_case(
        [*quotes, COPY, LINK, DELETE_LINK],
        question="If I unshare a folder or remove a member, can they still access a copy or link?",
    )
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    selected_quotes = {fact.quote for fact in snapshot.facts if fact.id in selected}
    assert {COPY, LINK, DELETE_LINK} <= selected_quotes
    assert len(selected) <= 8
    assert "missing_exception_fact_ids" in diagnostic["questions"][0]


def coverage(question, texts, *, resolution="conditional", conclusion="yes", reason="supported"):
    from packages.agents.writer.answer_coverage import parse_answer_coverage

    claims = [{"id": f"c{i}", "text": text} for i, text in enumerate(texts)]
    payload = {
        "version": 2,
        "answers": [
            {
                "question_id": "q",
                "status": "answered",
                "claim_ids": [c["id"] for c in claims],
                "resolution": resolution,
                "conclusion": conclusion,
                "missing_fields": [],
                "reason": reason,
            }
        ],
    }
    return parse_answer_coverage(
        json.dumps(payload),
        [{"question_id": "q", "question": question}],
        {c["id"] for c in claims},
        claims=claims,
    )[0]


def test_conditional_label_or_reason_cannot_close_unknown_action_copy_and_access_paths():
    record = coverage(
        "我取消共享了文件夹，对方现在完全看不到了吗？", [UNSHARE], reason=COPY + LINK + DELETE_LINK
    )
    assert record.status == "unverified"


def test_ambiguous_removal_needs_published_branches_and_an_actual_clarification():
    record = coverage(
        "把成员删掉后，他的密码还会留下吗？",
        [ACCESS],
        resolution="conditional",
        conclusion="depends",
    )
    assert record.status == "unverified"


@pytest.mark.asyncio
async def test_exception_closure_over_eight_or_byte_budget_records_missing_original_ids(
    monkeypatch,
):
    from test_question_retrieval import research_case

    from packages.agents.writer import question_retrieval

    quotes = [
        f"Owners can unshare a folder, except if:\n- The folder has restriction {i}."
        for i in range(10)
    ]
    detail, snapshot = research_case(quotes, question="Can owners unshare a folder?")
    for budget in (14000, 500):
        monkeypatch.setattr(
            question_retrieval, "EXCEPTION_CLOSURE_MAX_BYTES", budget, raising=False
        )
        selected, diagnostic = await question_retrieval.retrieve_question_facts(
            detail, snapshot, "Example Product", "feature", mode="lexical"
        )
        assert len(selected) <= 8
        row = diagnostic["questions"][0]
        assert row["missing_exception_fact_ids"]
        assert diagnostic["exception_closure_complete"] is False
        assert diagnostic["selected_original_bytes"] <= budget


def test_writer_input_exposes_required_exception_branches_and_clarification_inputs():
    from packages.agents.writer.dimension_writer import compact_dimension_context

    originals = facts(item(UNSHARE), item(COPY, "copy"), item(LINK, "link"))
    payload, _ = compact_dimension_context(
        {"segment_competitor": "Example Product", "dimension": "feature"},
        SimpleNamespace(facts=tuple(originals)),
        {f.id for f in originals},
        max_bytes=14000,
        questions=[{"question_id": "q", "question": "取消共享后，对方完全看不到文件夹了吗？"}],
    )
    assert payload["required_clarifications"][0]["missing_fields"]
    assert any(row.get("source_exceptions") for row in payload["evidence_view"]["facts"])


def test_all_supported_model_decisions_still_replay_original_exceptions_in_answer_guard():
    from packages.agents.writer.answer_coverage import coverage_resolution_reasons
    from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

    originals = facts(item(UNSHARE), item(COPY, "copy"))
    claims = [{"id": "c", "text": UNSHARE, "fact_ids": [originals[0].id]}]
    record = ReportAnswerCoverage(
        question_id="q",
        question="When I unshare a folder, what happens to copies?",
        status="answered",
        claim_ids=("c",),
        reason="all supported",
        resolution="conditional",
        conclusion="depends",
        answer=UNSHARE,
        evidence_spans=[{"claim_id": "c", "quote": UNSHARE}],
        binding_version=2,
    )
    assert "answer_source_exception_unpublished" in coverage_resolution_reasons(
        record, claims, facts=originals
    )


def test_conditional_group_over_budget_is_reported_without_partial_admission():
    from test_semantic_extraction import fixture

    from packages.research.extraction.semantic import semantic_extraction

    quote = EXCEPT.splitlines()[0]
    body = quote + "\n" + "- The folder contains an unrelated restriction.\n" * 50
    brief, _, page = fixture(body)
    result = semantic_extraction(brief, page, {"facts": [{"quote": quote}]})
    assert not result.fields
    assert "source_condition_context_budget_exceeded" in result.metadata["source_condition_gaps"]


@pytest.mark.parametrize(
    "quote",
    [
        "Deleting an account or organization is permanent, cannot be undone or restored, "
        "and will delete all associated vault data.",
        "Deleting an account permanently deletes all associated data and cannot be undone.",
    ],
)
def test_complete_account_lifecycle_rule_survives_deterministic_admission_and_source_quality(quote):
    from test_semantic_extraction import fixture

    from packages.research.evidence.admission import admit_evidence_items, source_quality_problem
    from packages.research.extraction.semantic import extract_operation_rules
    from packages.schema.models import RawSource

    brief, candidate, page = fixture(quote)
    brief = brief.model_copy(
        update={
            "questions": [SimpleNamespace(question_id="q", question="删掉账户后，数据还在吗？")]
        }
    )
    result = extract_operation_rules(brief, page)
    assert result.quotes and result.quotes[0].text == quote
    admitted = admit_evidence_items(
        [result], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert admitted and admitted[0].status == "accepted"
    source = RawSource(
        id="lifecycle",
        competitor=brief.competitor,
        dimension="feature",
        source_type="webpage_verified",
        title=page.title,
        url=page.final_url,
        snippet=quote,
        content_hash="lifecycle",
        confidence=0.8,
    )
    assert source_quality_problem(source) is None


def test_lifecycle_navigation_or_unqualified_deletion_is_not_an_admission_signal():
    from packages.research.extraction.semantic import source_rule_text_signal

    assert not source_rule_text_signal("Delete account. Account removal. Restore. Help.")


@pytest.mark.parametrize(
    "text",
    [
        "For SSO accounts without master passwords using trusted devices, removing members "
        "eliminates account access unless account recovery or they log in before removal.",
        "For SSO accounts without master passwords using trusted devices, removed members "
        "still retain account access unless account recovery and they log in before removal.",
        "SSO users lose account access unless account recovery and they log in before removal.",
    ],
)
def test_authentication_keywords_cannot_replace_scope_and_conjunction_or_reverse_outcome(text):
    assert "source_exception_omitted_or_changed" in reasons(
        text, facts(item(ACCESS), item(AUTH, "auth"))
    )


def test_operation_role_context_differences_do_not_create_receipts():
    base = item(
        UNSHARE,
        value={
            "status": "documented",
            "evidence_terms": [UNSHARE],
            "operations": [{"role": "Owners", "operation": "unshare", "effect": "allowed"}],
        },
    )
    other = item(
        COPY,
        "copy",
        value={
            "status": "documented",
            "evidence_terms": [COPY],
            "operations": [{"role": "Editors", "operation": "unshare", "effect": "allowed"}],
        },
    )
    assert not facts(base, other)[0].qualifiers.get("source_exception_links")


def test_complete_published_branches_and_clarification_can_answer_ambiguous_removal():
    text = (
        "Removing members does not delete their account or vault data. "
        "For SSO with trusted devices, "
        "accounts without master passwords lose access unless account recovery assigned a master "
        "password and they log in with that master password at least once before removal. "
        "Deleting an account permanently deletes vault data. "
        "Please clarify which action you chose, data ownership, "
        "retained copy choice and access path?"
    )
    record = coverage(
        "把成员删掉后，他的密码还会留下吗？",
        [text],
        resolution="clarification",
        conclusion="depends",
    )
    assert record.status == "answered" and record.answer == text


def test_conditional_group_uses_verified_heading_boundaries_before_unrelated_section():
    from test_semantic_extraction import fixture

    from packages.research.extraction.semantic import semantic_extraction

    prefix = AUTH.splitlines()[0] + "\n"
    tail = "\n" + AUTH.splitlines()[1]
    quote = prefix + "x" * (818 - len(prefix) - len(tail) - 1) + "." + tail
    brief, _, page = fixture("Account access\n" + quote + "\nOther rules\n" + "Data rules. " * 160)
    page = page.model_copy(
        update={"metadata": {"document_headings": [(2, "Account access"), (2, "Other rules")]}}
    )
    result = semantic_extraction(brief, page, {"facts": [{"quote": quote}]})
    assert result.quotes and result.quotes[0].text == quote


def test_explicit_action_copy_choice_and_access_path_do_not_request_known_inputs():
    from packages.research.evidence.source_exceptions import required_question_clarifications

    question = (
        "I own the entire folder and chose unshare. I did not allow members to keep a copy "
        "and no shared links exist. After the desktop app syncs, can former members access "
        "the folder through their account?"
    )
    assert not required_question_clarifications([{"question_id": "q", "question": question}])
    record = coverage(
        question,
        [
            "Former members cannot access the unshared folder through their account "
            "once the desktop app syncs."
        ],
        resolution="direct",
        conclusion="no",
    )
    assert record.status == "answered"


def test_explicit_personal_account_deletion_does_not_become_generic_ambiguous_removal():
    from packages.research.evidence.source_exceptions import required_question_clarifications

    question = "我把自己的个人账户永久删掉了，个人 vault 数据还会留下吗？"
    assert not required_question_clarifications([{"question_id": "q", "question": question}])


@pytest.mark.parametrize(
    "changed",
    [
        AUTH.replace("eliminates all access", "does not eliminate all access"),
        AUTH.replace("account recovery", "failed account recovery"),
        AUTH.replace("member accounts", "editor accounts"),
        COPY.replace("you can choose", "you cannot choose"),
        COPY.replace("folder", "public document"),
        "It is not true that " + DELETE_LINK,
        EXCEPT.replace("- The folder", "- It is not true that the folder"),
    ],
)
def test_exception_predicates_reject_negation_role_and_object_changes(changed):
    source = (
        AUTH
        if "master passwords" in changed
        else COPY
        if "copy" in changed
        else (EXCEPT if "except if:" in changed else DELETE_LINK)
    )
    originals = facts(item(source))
    assert reasons(changed, originals)
    assert not reasons(source, originals)


@pytest.mark.parametrize("verb", ["log in", "sign in"])
def test_authentication_exception_applies_to_english_login_guarantees(verb):
    originals = facts(item(ACCESS), item(AUTH, "auth"))
    assert reasons(f"Removed members can still {verb} after removal.", originals)
    assert not reasons("Removing members does not delete their saved vault data.", originals)


@pytest.mark.parametrize(
    "change",
    [
        {"captured_page_id": "foreign-capture"},
        {"source_url": "https://foreign.test/rules"},
        {"raw_source_id": "foreign-source"},
        {"evidence_item_id": "never-admitted"},
        {"events": [["delete", "link"]]},
    ],
)
def test_foreign_or_forged_receipts_do_not_constrain_an_unrelated_valid_claim(change):
    base = facts(item(ACCESS))[0]
    genuine = facts(item(ACCESS), item(AUTH, "auth"))[0]
    link = genuine.qualifiers["source_exception_links"][0]
    assert link["evidence_item_id"] == item(AUTH, "auth").id
    forged = {**link, **change}
    qualifiers = base.qualifiers | {"source_exception_links": [forged]}
    original = base.model_copy(update={"qualifiers_json": canonical_json(qualifiers)})
    assert not reasons(ACCESS, [original])


def branch_selection(clarification):
    from packages.agents.writer.answer_coverage import parse_answer_coverage

    originals = facts(
        item(UNSHARE), item(COPY, "copy"), item(LINK, "link"), item(DELETE_LINK, "delete")
    )
    texts = [UNSHARE + " " + COPY, LINK, DELETE_LINK, clarification]
    claims = [
        {"id": f"c{i}", "text": text, "fact_ids": [originals[[0, 2, 3, 0][i]].id]}
        for i, text in enumerate(texts)
    ]
    payload = {
        "version": 2,
        "answers": [
            {
                "question_id": "q",
                "status": "answered",
                "claim_ids": [c["id"] for c in claims],
                "reason": "all supported",
                "resolution": "clarification",
                "conclusion": "depends",
                "missing_fields": [],
            }
        ],
    }
    return parse_answer_coverage(
        json.dumps(payload),
        [
            {
                "question_id": "q",
                "question": "我取消共享了，之前拿到文件的人现在就完全看不到文件夹了吗？",
            }
        ],
        {c["id"] for c in claims},
        claims=claims,
        facts=originals,
    )[0]


def test_unrelated_clarification_cannot_close_real_source_branches():
    assert branch_selection("Please confirm the folder color?").status == "unverified"
    assert (
        branch_selection(
            "Please confirm the actual action, data ownership, "
            "retained copy choice and access path?"
        ).status
        == "answered"
    )


def test_unrelated_conditional_sentence_cannot_substitute_for_source_branches():
    record = coverage(
        "我取消共享了，对方还能看到文件夹吗？",
        [
            "If the folder is blue, please confirm the actual action, data ownership, "
            "retained copy choice and access path?"
        ],
        resolution="clarification",
        conclusion="depends",
    )
    assert record.status == "unverified"


def test_semantic_prompt_authorizes_only_complete_bounded_exception_groups_above_800():
    from packages.research.extraction.semantic import SEMANTIC_SYSTEM

    assert "32-800" in SEMANTIC_SYSTEM
    assert "1600" in SEMANTIC_SYSTEM
    assert "complete" in SEMANTIC_SYSTEM and "list" in SEMANTIC_SYSTEM


def test_complete_auth_group_is_available_to_deterministic_selection_without_a_model_call():
    from test_semantic_extraction import fixture

    from packages.research.extraction.semantic import extract_operation_rules

    prefix = AUTH.splitlines()[0] + "\n"
    tail = "\n" + AUTH.splitlines()[1]
    quote = prefix + "x" * (818 - len(prefix) - len(tail) - 1) + "." + tail
    brief, _, page = fixture(quote)
    brief = brief.model_copy(
        update={
            "questions": [
                SimpleNamespace(
                    question_id="q",
                    question="Can removed members log in to their account after removal?",
                )
            ]
        }
    )
    result = extract_operation_rules(brief, page)
    assert any(row.text == quote for row in result.quotes)


def test_known_scope_with_unknown_auth_outcome_is_explicitly_unresolved():
    changed = AUTH.replace("eliminates all access", "transmutes account access")
    assert "source_exception_unresolved" in reasons(changed, facts(item(AUTH)))


def test_valid_receipt_origin_outside_the_view_remains_an_explicit_closure_gap():
    original = facts(item(ACCESS), item(AUTH, "auth"))[0]
    assert "source_exception_unresolved" in reasons(ACCESS, [original])


def test_complete_chinese_auth_prerequisites_preserve_member_scope_and_access_outcome():
    text = (
        "对于通过 SSO 受信任设备而没有主密码的成员账户，移除组织成员会失去对账户的访问，"
        "除非已通过账户恢复分配主密码，并且在移除前用该主密码至少登录一次。"
    )
    assert not reasons(text, facts(item(ACCESS), item(AUTH, "auth")))


def test_chinese_copy_link_branches_and_actual_clarification_can_be_published():
    from packages.agents.writer.answer_coverage import parse_answer_coverage

    originals = facts(
        item(UNSHARE), item(COPY, "copy"), item(LINK, "link"), item(DELETE_LINK, "delete")
    )
    texts = [
        "取消共享文件夹后，文件从成员账户中永久删除，并在桌面应用再次同步时从关联设备移除。"
        "移除文件夹成员或取消共享文件夹时，可以选择让成员保留文件夹副本，但副本不再同步其他账户。",
        "如果共享文件夹中有共享链接，链接创建者离开文件夹后，查看链接仍然有效。",
        "删除链接后，该停用链接不再有效。",
        "请确认具体操作、数据归属、是否保留文件夹副本，以及访问路径和共享链接。",
    ]
    claims = [
        {"id": f"c{i}", "text": text, "fact_ids": [originals[[0, 2, 3, 0][i]].id]}
        for i, text in enumerate(texts)
    ]
    payload = {
        "version": 2,
        "answers": [
            {
                "question_id": "q",
                "status": "answered",
                "claim_ids": [c["id"] for c in claims],
                "reason": "全部支持",
                "resolution": "clarification",
                "conclusion": "depends",
                "missing_fields": [],
            }
        ],
    }
    record = parse_answer_coverage(
        json.dumps(payload),
        [
            {
                "question_id": "q",
                "question": "我取消共享了，之前拿到文件的人现在就完全看不到文件夹了吗？",
            }
        ],
        {c["id"] for c in claims},
        claims=claims,
        facts=originals,
        require_v2=True,
    )[0]
    assert record.status == "answered" and record.answer == "\n".join(texts)


@pytest.mark.parametrize(
    "changed, originals",
    [
        (
            COPY.replace("that folder", "a public document"),
            lambda: facts(item(UNSHARE), item(COPY, "copy")),
        ),
        (
            AUTH.replace("from your organization", "from your folder"),
            lambda: facts(item(ACCESS), item(AUTH, "auth")),
        ),
    ],
)
def test_exception_effect_and_action_objects_cannot_be_replaced_independently(changed, originals):
    assert reasons(changed, originals())


def test_chinese_login_prerequisite_cannot_contain_internal_negation():
    text = (
        "对于通过 SSO 受信任设备而没有主密码的成员账户，移除组织成员会失去对账户的访问，"
        "除非已通过账户恢复分配主密码，并且在移除前用该主密码从未登录。"
    )
    assert reasons(text, facts(item(ACCESS), item(AUTH, "auth")))


@pytest.mark.parametrize(
    "changed",
    [
        AUTH.replace("they log in with that master password", "they log in using SSO"),
        AUTH.replace(
            "were previously assigned a master password using account recovery",
            "previously completed account recovery",
        ),
        AUTH.replace(
            "were previously assigned a master password using account recovery",
            "were previously assigned a recovery code using account recovery",
        ),
    ],
)
def test_recovery_and_login_must_bind_the_same_source_master_password(changed):
    assert reasons(changed, facts(item(ACCESS), item(AUTH, "auth")))


def test_stopped_sync_must_retain_the_source_object_and_reject_the_opposite_outcome():
    changed = COPY.replace(
        "no longer sync with other accounts", "no longer sync with unrelated devices"
    )
    changed += " It will sync with other accounts."
    assert reasons(changed, facts(item(UNSHARE), item(COPY, "copy")))
