"""Anonymous regressions for bounded, source-bound exception recovery."""

from types import SimpleNamespace

import pytest
from test_source_exception_closure import ACCESS, AUTH, COPY, EXCEPT, LINK, facts, item

from packages.research.evidence.normalization import normalized_feature_fields_from_evidence_items
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.source_exceptions import (
    claim_source_exception_reasons,
    complete_rule_blocks,
    question_exception_fact_ids,
    source_exception_constraints,
)


def claim(text, originals, *, bound=None):
    bound = bound or originals[:1]
    return SimpleNamespace(
        text=text,
        fact_ids=tuple(f.id for f in bound),
        source_ids=tuple(dict.fromkeys(f.source_id for f in bound)),
    )


def guard(text, originals, *, bound=None):
    candidate = claim(text, originals, bound=bound)
    selected = [f for f in originals if f.id in candidate.fact_ids]
    return claim_source_exception_reasons(candidate, selected, available_facts=originals)


def scoped_pair(**updates):
    updates.setdefault("raw_source_id", "specific-source")
    base, auth = facts(item(ACCESS), item(AUTH, "auth", **updates))
    return [base, auth.model_copy(update={"source_id": "specific-source"})]


@pytest.mark.asyncio
async def test_duplicate_receipts_keep_complete_origins_through_snapshot_retrieval_and_compact():
    from test_question_retrieval import research_case

    from packages.agents.writer.dimension_writer import (
        compact_dimension_context,
        compact_prompt_json,
    )
    from packages.agents.writer.question_retrieval import retrieve_question_facts
    from packages.research.evidence.snapshot import seal_snapshot

    prefix, tail = AUTH.split("\n", 1)
    auth = prefix + "\n" + "x" * (818 - len(prefix) - len(tail) - 3) + ".\n" + tail
    assert len(auth) == 818
    parent = "If members leave the organization, they can retain account access:\n" + auth
    observations = [item(ACCESS)] + [
        item(
            auth if n == 0 else parent,
            f"auth-{n}",
            value={"status": "documented", "evidence_terms": [auth, parent]},
        )
        for n in range(5)
    ]
    normalized = normalized_feature_fields_from_evidence_items(observations)
    receipts = normalized[0].qualifiers["source_exception_links"]
    assert len(receipts) == 1
    assert next(r for r in receipts if r["quote"] == auth)["evidence_item_id"] == observations[1].id
    assert len(normalized) == 6 and {r.evidence_item_ids[0] for r in normalized} == {
        i.id for i in observations
    }
    # Original identities and observations survive; only logical receipts collapse.
    detail, _ = research_case([ACCESS], question="Can removed organization members log in?")
    source = detail.raw_sources[0]
    source.metadata["normalized_fields"] = [r.model_dump(mode="json") for r in normalized]
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert diagnostic["exception_closure_complete"]
    auth_fact = next(f for f in snapshot.facts if f.field == "evidence_terms" and f.quote == auth)
    assert auth_fact.id in selected
    payload, _ = compact_dimension_context(
        {"segment_competitor": "Example Product", "dimension": "feature"},
        SimpleNamespace(facts=tuple(f for f in snapshot.facts if f.id in selected)),
        set(selected),
        questions=[{"question_id": "q", "question": detail.topic}],
    )
    assert auth_fact.id in {f["id"] for f in payload["evidence_view"]["facts"]}
    original_bytes = len(canonical_json(auth_fact.model_dump(mode="json")).encode())
    compact_bytes = len(compact_prompt_json(payload).encode())
    assert original_bytes <= 14000 and compact_bytes <= 14000
    print(
        f"receipt_count={len(receipts)} original_bytes={original_bytes} "
        f"compact_bytes={compact_bytes}"
    )


def test_exception_group_stops_before_procedure_and_keeps_three_branches():
    text = EXCEPT + (
        "\nIf a shared folder contains inactive shared folders, you won’t be able to unshare "
        "the parent folder.\nTo resolve this:\n- Click Show deleted files.\n"
        "- Restore the inactive folders.\n- Proceed with unsharing.\nTo unshare a folder:"
    )
    block = next(b for b in complete_rule_blocks(text) if "except if:" in b)
    assert "To resolve" not in block and "Click" not in block
    rows = source_exception_constraints(facts(item(text))[0])
    row = next(r for r in rows if r["kind"] == "exception_list")
    assert row["branches"] == [
        "The folder contains shared folders",
        "The folder is inside another shared folder",
        "The folder contains inactive shared folders",
    ]


def test_nested_condition_is_not_mistaken_for_procedure_and_unfinished_group_is_rejected():
    complete = EXCEPT + "\n  - If a nested exception applies, you cannot unshare the folder."
    assert complete in complete_rule_blocks(complete)
    incomplete = EXCEPT + "\n  - If another condition applies:"
    assert not any("except if:" in b for b in complete_rule_blocks(incomplete))
    assert not any("except if:" in b for b in complete_rule_blocks(EXCEPT + "\nx" * 1600))


def test_independent_inactive_exception_and_negative_visibility_are_retrieval_requirements():
    inactive = (
        "If a shared folder contains inactive shared folders, "
        "you won’t be able to unshare the parent folder."
    )
    deleted = "If you delete a link, the deactivated link no longer works for anyone."
    originals = facts(item(inactive, "inactive"), item(deleted, "delete"))
    assert source_exception_constraints(originals[0])
    assert set(
        question_exception_fact_ids("我取消共享了文件夹，对方完全看不到了吗？", originals)
    ) == {f.id for f in originals}


def test_cross_document_auth_exception_requires_both_fact_and_source_bindings():
    originals = scoped_pair(
        captured_page_id="specific-capture", source_url="https://example.test/help/specific"
    )
    assert "source_exception_unresolved" in guard(ACCESS, originals)
    assert "source_exception_unresolved" in guard(ACCESS + " " + AUTH, originals)
    assert not guard(ACCESS + " " + AUTH, originals, bound=originals)
    incomplete_binding = claim(ACCESS + " " + AUTH, originals, bound=originals)
    incomplete_binding.source_ids = (originals[0].source_id,)
    assert "source_exception_unresolved" in claim_source_exception_reasons(
        incomplete_binding, originals, available_facts=originals
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"competitor": "Foreign Product"},
        {"quote": AUTH.replace("member accounts", "editor accounts").replace("them", "editors")},
        {"quote": AUTH.replace("organization", "folder")},
        {"quote": AUTH.replace("Removing them", "Deleting them")},
        {"metadata": {"role": "Editors"}},
        {"metadata": {"plan": "Enterprise"}},
    ],
)
def test_cross_document_exception_does_not_borrow_incompatible_scope(updates):
    updates = dict(updates)
    if "quote" in updates:
        quote = updates.pop("quote")
        updates["value"] = {"status": "documented", "evidence_terms": [quote]}
        base, other = facts(item(ACCESS), item(quote, "auth", **updates))
        originals = [base, other.model_copy(update={"source_id": "specific-source"})]
    else:
        originals = scoped_pair(**updates)
    assert not guard(ACCESS, originals)


def test_report_guard_accepts_only_complete_explicit_exception_pair_binding():
    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons

    originals = scoped_pair(
        captured_page_id="specific-capture", source_url="https://example.test/help/specific"
    )
    view = SimpleNamespace(facts=tuple(originals))
    boundary = SimpleNamespace(allowed_fact_ids=tuple(f.id for f in originals))
    candidate = ReportClaim(
        id="claim",
        text=" ".join((ACCESS + " " + AUTH).split()),
        kind="fact",
        competitor="Example Product",
        dimension="feature",
        fact_ids=tuple(f.id for f in originals),
        source_ids=tuple(f.source_id for f in originals),
    )
    assert not claim_rule_reasons(candidate, view, [boundary])
    assert claim_rule_reasons(candidate.model_copy(update={"text": ACCESS}), view, [boundary])
    assert "withheld_or_unseen_fact" in claim_rule_reasons(
        candidate, view, [SimpleNamespace(allowed_fact_ids=(originals[0].id,))]
    )
    unrelated = facts(item("Members can export their vault data.", "export"))[0]
    unrelated = unrelated.model_copy(update={"source_id": "specific-source"})
    assert "feature_claim_multiple_observations" in claim_rule_reasons(
        candidate.model_copy(update={"fact_ids": (originals[0].id, unrelated.id)}),
        SimpleNamespace(facts=(originals[0], unrelated)),
        [SimpleNamespace(allowed_fact_ids=(originals[0].id, unrelated.id))],
    )


def test_exception_binding_candidates_expose_only_stable_source_bound_pairs():
    from packages.research.evidence.source_exceptions import source_exception_bindings

    originals = scoped_pair(
        captured_page_id="specific-capture", source_url="https://example.test/help/specific"
    )
    candidates = source_exception_bindings(originals)
    assert len(candidates) == 1
    pair = candidates[0]
    assert pair["fact_ids"] == [f.id for f in originals]
    assert pair["source_ids"] == [f.source_id for f in originals]
    assert pair["source_exceptions"][0]["quote"] == AUTH
    assert candidates == source_exception_bindings(list(reversed(originals)))
    assert not source_exception_bindings(scoped_pair(metadata={"role": "Editors"}))


def test_atomic_copy_and_link_claims_ignore_other_actions_in_adjacent_context():
    copy, link = facts(
        item(COPY, "copy", value={"status": "documented", "evidence_terms": [COPY, LINK]}),
        item(LINK, "link", value={"status": "documented", "evidence_terms": [COPY, LINK]}),
    )
    copy_text = (
        "当你将成员从文件夹中移除或取消共享文件夹时，你可以选择让他们保留该文件夹的副本，"
        "但该副本将不再与其他账户同步。"
    )
    link_text = "如果共享文件夹内存在共享链接且链接创建者离开该文件夹，查看权限链接仍将保持启用。"
    assert not guard(copy_text, [copy, link])
    assert not guard(link_text, [link, copy])
    assert guard(copy_text.replace("不再与其他账户同步", "仍与其他账户同步"), [copy, link])
    assert guard(copy_text.replace("该文件夹的副本", "公共文档的副本"), [copy, link])
    assert guard(link_text.replace("仍将保持启用", "并非仍将保持启用"), [link, copy])


def test_equivalent_specific_observations_accept_one_bound_complete_witness():
    originals = scoped_pair(
        captured_page_id="specific-capture", source_url="https://example.test/help/specific"
    )
    duplicate = originals[1].model_copy(update={"id": "other-observation"})
    assert not guard(ACCESS + " " + AUTH, [*originals, duplicate], bound=originals)
    different_rule = originals[1].model_copy(
        update={
            "id": "additional-condition",
            "quote": AUTH.replace("unless they", "unless security approves and they"),
            "value_json": canonical_json([]),
            "qualifiers_json": canonical_json(
                {"source_scope": originals[1].qualifiers["source_scope"]}
            ),
        }
    )
    assert "source_exception_unresolved" in guard(
        ACCESS + " " + AUTH, [*originals, different_rule], bound=originals
    )


def test_answer_replays_each_published_claim_with_its_actual_fact_and_source_binding():
    from packages.research.evidence.source_exceptions import answer_source_exception_reasons

    originals = scoped_pair(
        captured_page_id="specific-capture", source_url="https://example.test/help/specific"
    )
    record = SimpleNamespace(
        status="answered",
        claim_ids=("complete",),
        question="Can removed organization members log in?",
        conclusion="depends",
        resolution="conditional",
    )
    published = [
        {
            "id": "complete",
            "text": ACCESS + " " + AUTH,
            "fact_ids": [f.id for f in originals],
            "source_ids": [f.source_id for f in originals],
        }
    ]
    assert not answer_source_exception_reasons(record, published, facts=originals)
    independently_bound = [
        {
            "id": "base",
            "text": ACCESS,
            "fact_ids": [originals[0].id],
            "source_ids": [originals[0].source_id],
        },
        {
            "id": "auth",
            "text": AUTH,
            "fact_ids": [originals[1].id],
            "source_ids": [originals[1].source_id],
        },
    ]
    record.claim_ids = ("base", "auth")
    assert "answer_source_exception_unpublished" in answer_source_exception_reasons(
        record, independently_bound, facts=originals
    )


def test_authentication_rule_belongs_to_its_own_condition_header():
    parent = (
        "If your organization has a claimed domain, Remove is not listed. Instead you can "
        "select Delete to delete the account permanently:\n"
        "Offline devices can cache organization data.\n" + AUTH
    )
    original = facts(item(parent))[0]
    auth_rows = [
        r for r in source_exception_constraints(original) if r["kind"] == "authentication_access"
    ]
    assert {r["quote"] for r in auth_rows} == {AUTH}
    assert parent in complete_rule_blocks(parent)


def test_same_exception_kind_does_not_hide_another_complete_source_scope():
    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons

    weaker = AUTH.replace("SSO with trusted devices", "SSO")
    base, _ = scoped_pair()
    base = base.model_copy(update={"quote": weaker, "value_json": canonical_json([weaker])})
    stronger = scoped_pair()[1]
    candidate = ReportClaim(
        id="claim",
        text=" ".join(weaker.split()),
        kind="fact",
        competitor=base.competitor,
        dimension="feature",
        fact_ids=(base.id,),
        source_ids=(base.source_id,),
    )
    assert "source_exception_unresolved" in claim_rule_reasons(
        candidate,
        SimpleNamespace(facts=(base, stronger)),
        [SimpleNamespace(allowed_fact_ids=(base.id, stronger.id))],
    )


def test_unrecognized_extra_auth_prerequisite_requires_the_complete_original_rule():
    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
    from packages.research.evidence.source_exceptions import verified_exception_binding

    extra = AUTH.replace("unless they", "unless security approves and they")
    base, other = scoped_pair()
    other = other.model_copy(update={"quote": extra, "value_json": canonical_json([extra])})
    originals = [base, other]
    candidate = ReportClaim(
        id="claim",
        text=" ".join((ACCESS + " " + AUTH).split()),
        kind="fact",
        competitor=base.competitor,
        dimension="feature",
        fact_ids=tuple(f.id for f in originals),
        source_ids=tuple(f.source_id for f in originals),
    )
    assert not verified_exception_binding(candidate, originals)
    assert "source_exception_unresolved" in claim_rule_reasons(
        candidate,
        SimpleNamespace(facts=tuple(originals)),
        [SimpleNamespace(allowed_fact_ids=candidate.fact_ids)],
    )
    exact = candidate.model_copy(update={"text": " ".join((ACCESS + " " + extra).split())})
    assert verified_exception_binding(exact, originals)
    assert not claim_rule_reasons(
        exact,
        SimpleNamespace(facts=tuple(originals)),
        [SimpleNamespace(allowed_fact_ids=exact.fact_ids)],
    )


@pytest.mark.parametrize(
    "extra",
    [
        AUTH + " Security approval is also required before removal.",
        AUTH + "\n- Account access is restored only if security approves.",
        AUTH.replace("\n- Removing", "\nSecurity approval is required before removal.\n- Removing"),
        AUTH.replace("trusted devices:", "trusted devices after security approval:"),
    ],
)
def test_every_auth_group_sentence_branch_and_header_must_be_accounted_for(extra):
    from packages.research.evidence.source_exceptions import verified_exception_binding

    base, other = scoped_pair()
    other = other.model_copy(update={"quote": extra, "value_json": canonical_json([extra])})
    originals = [base, other]
    candidate = claim(ACCESS + " " + AUTH, originals, bound=originals)
    assert not verified_exception_binding(candidate, originals)
    assert "source_exception_unresolved" in guard(candidate.text, originals, bound=originals)
    complete = claim(ACCESS + " " + extra, originals, bound=originals)
    assert verified_exception_binding(complete, originals)
    assert not guard(complete.text, originals, bound=originals)


def test_complete_known_auth_explanations_can_keep_the_existing_structural_contract():
    from packages.research.evidence.source_exceptions import verified_exception_binding

    complete = AUTH.replace("their account", "their ExampleCo account") + (
        " \nThese users will not be able to re-join your organization unless the above steps "
        "are taken before they are removed from the organization. If they aren't, each removed "
        "user will be required to delete their account and be issued a new invitation to create "
        "an account and join your organization.\n- Revoking access to the organization, but not "
        "removing them from the organization, will still fully locked them out of their account "
        "until their access to the organization is restored."
    )
    assert len(complete) == 818
    base, other = scoped_pair()
    other = other.model_copy(update={"quote": complete, "value_json": canonical_json([complete])})
    originals = [base, other]
    candidate = claim(ACCESS + " " + AUTH, originals, bound=originals)
    assert verified_exception_binding(candidate, originals)
    assert not guard(candidate.text, originals, bound=originals)
