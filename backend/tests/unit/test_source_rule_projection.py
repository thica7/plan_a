"""Captured rule projection regressions; model verdict fixtures prove only gates."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from claim_review_fixture import supported_review
from test_literal_non_operation import candidates, draft, fact

from packages.agents.writer.dimension_writer import (
    operation_claim_selection,
    parse_claim_drafts,
    review_payload,
)
from packages.research.evidence.report_claims import (
    ReportClaim,
    audit_report_claims,
    claim_operations,
    current_feature_binding_reasons,
)
from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json
from packages.research.evidence.source_spans import projected_source_facts, source_span_candidates

CAPTURED = json.loads(
    (Path(__file__).with_name("fixtures") / "source_rule_projection_v33.json").read_text()
)


def parse_span(original, text, span):
    return parse_claim_drafts(
        json.dumps({"claims": [draft(original, text, source_span_ids=[span["span_id"]])]}),
        candidates(original),
        {original.id},
        "rule-projection",
        source_facts=[original],
        span_candidates={span["span_id"]: span},
    )


def audit(original, claim, verdict="supported"):
    view = SimpleNamespace(facts=[original], sources=[])
    review = supported_review(review_payload([claim], view, review_version=3)["claims"][0])
    review["verdict"] = verdict
    return audit_report_claims(
        [claim], [review], view, [SimpleNamespace(allowed_fact_ids=[original.id])], review_version=3
    )[0]


def test_actual_guest_rule_before_optional_examples_keeps_exact_original_coordinates_and_negation():
    row = CAPTURED[0]
    original = EvidenceFact.model_validate(row["fact"])
    rule = original.value[1].removesuffix(" Consider inviting:")
    selected = [span for span in source_span_candidates(original) if span["quote"] == rule]
    assert len(selected) == 1, "The complete captured guest restriction must be selectable."
    span = selected[0]
    assert span["source_path"] == "value/1" and span["start"] == 0 and span["end"] == len(rule)
    assert original.value[1][span["start"] : span["end"]] == span["quote"]
    assert (
        span["fact_hash"]
        == hashlib.sha256(canonical_json(original.model_dump(mode="json")).encode()).hexdigest()
    )
    assert "They don’t have their own private vaults" in rule
    claims, gaps = parse_span(original, row["writer_atom"]["text"], span)
    assert len(claims) == 1 and not gaps
    assert audit(original, claims[0]).status == "supported"
    assert audit(original, claims[0], "unsupported").status == "rejected"
    projected, reasons = projected_source_facts(claims[0], [original])
    assert not reasons and projected[0].quote == rule


@pytest.mark.parametrize("row", CAPTURED[1:], ids=lambda row: row["case"])
def test_actual_role_scope_claim_reaches_review_without_six_planned_operations(row):
    original = EvidenceFact.model_validate(row["fact"])
    span = next(
        span for span in source_span_candidates(original) if span["quote"] == original.quote
    )
    # The captured compact transport carries coordinates; its full quote is in
    # the original fact already sent alongside these candidates.
    assert any(
        all(sent.get(key) == span[key] for key in ("span_id", "source_path", "start", "end"))
        and sent["support_ref"] == row["writer_atom"]["support_refs"][0]
        for sent in row["sent_source_spans"]
    ), "The actual writer already received this support."
    claims, gaps = parse_span(original, row["writer_atom"]["text"], span)
    assert len(claims) == 1 and not gaps
    assert not current_feature_binding_reasons(claims[0])
    assert audit(original, claims[0]).status == "supported"
    assert audit(original, claims[0], "uncertain").status == "rejected"
    assert (
        operation_claim_selection(
            claims,
            SimpleNamespace(facts=[original]),
            ("edit",),
            {original.id},
            fact_targets={original.id: ["edit"]},
        )
        == claims
    )


@pytest.mark.parametrize(
    "intro", ["Consider inviting:", "For example:", "Examples include:", "例如："]
)
def test_optional_example_intro_retains_complete_anonymous_rule_and_prerequisite(intro):
    rule = "Guests do not own private storage and can join only after an owner confirms them."
    original = fact(quote=rule + " " + intro)
    choices = source_span_candidates(original)
    assert [row["quote"] for row in choices] == [rule]
    assert choices[0]["start"] == 0 and choices[0]["end"] == len(rule)


def test_optional_examples_do_not_split_wrapped_subject_and_negative_rule():
    rule = (
        "Guest accounts are intended for limited access.\n"
        "They do not own private storage and belong to one vault only after confirmation."
    )
    original = fact(quote=rule + "\nConsider inviting:")
    assert [span["quote"] for span in source_span_candidates(original)] == [rule]


@pytest.mark.parametrize("suffix", ["", "\nConsider inviting:"])
def test_optional_intro_never_cuts_mandatory_condition_list(suffix):
    rule = (
        "Guests can join only when all following conditions hold:\n"
        "- An owner confirms them.\n- The guest accepts the invitation."
    )
    original = fact(quote=rule + suffix)
    choices = source_span_candidates(original)
    assert [row["quote"] for row in choices] == [rule]


@pytest.mark.parametrize(
    "text",
    [
        "Guests can join. Required conditions:",
        "Guests can join only if:\nConsider inviting:",
        "Guests can join only if all of the following hold:",
        "Guests can join under these conditions:",
        "Guests can join only when all of the following conditions hold. For example:",
        "Only the following roles can join. Examples include:",
    ],
)
def test_unfinished_required_conditions_do_not_become_optional_examples(text):
    assert not source_span_candidates(fact(quote=text))


@pytest.mark.parametrize("separator", [" ", "\n"])
@pytest.mark.parametrize(
    "prefix",
    [
        "Only the following roles can join.",
        "Guests can join only when all of these conditions hold.",
        "只有以下角色可以加入。",
    ],
)
def test_earlier_forward_list_reference_cannot_hide_behind_a_later_complete_sentence(
    separator, prefix
):
    text = separator.join([prefix, "All other roles are excluded.", "Examples include:"])
    assert not source_span_candidates(fact(quote=text))


def test_a_later_list_header_cannot_resolve_an_earlier_sentence_forward_reference():
    text = (
        "Only the following roles can join. Other requirements:\n"
        "- All users confirm their identity.\nExamples include:"
    )
    assert not source_span_candidates(fact(quote=text))


@pytest.mark.parametrize(
    "prefix", ["If approved, ", "When approved, ", "After confirmation, ", "If approved "]
)
@pytest.mark.parametrize(
    "predicate,operation",
    [("members edit documents.", "edit"), ("members can set permissions.", "manage_access")],
)
def test_front_condition_cannot_hide_a_bare_or_permission_setting_operation(
    prefix, predicate, operation
):
    text = prefix + predicate
    assert operation in claim_operations(text)
    original = fact(quote="Roles apply to one domain.")
    span = source_span_candidates(original)[0]
    claims, gaps = parse_span(original, text, span)
    assert not claims and "operation_binding_required" in gaps
    persisted = ReportClaim(
        id="conditional-unbound", **draft(original, text), source_span_bindings=[span]
    )
    result = audit(original, persisted)
    assert result.status == "rejected" and "operation_binding_required" in result.rule_reasons


@pytest.mark.parametrize(
    "text",
    [
        "If members can edit documents, the role applies to one domain.",
        "If administrators can set permissions, the role applies to one domain.",
    ],
)
def test_front_condition_action_does_not_turn_a_role_scope_assertion_into_an_operation(text):
    original = fact(quote=text)
    assert not claim_operations(text)
    claims, gaps = parse_span(original, text, source_span_candidates(original)[0])
    assert claims and not gaps


@pytest.mark.parametrize(
    "text",
    [
        "角色只适用于指定域名。",
        "该角色授予清除指定域名边缘缓存的权限。",
        "This role applies to one domain only.",
        "Domain-scoped permissions apply to a specified domain.",
    ],
)
def test_anonymous_role_scope_claims_are_not_operation_planning_requests(text):
    original = fact(quote=text)
    claims, gaps = parse_span(original, text, source_span_candidates(original)[0])
    assert claims and not gaps
    assert audit(original, claims[0]).status == "supported"


@pytest.mark.parametrize(
    "text",
    [
        "角色可以编辑文档。",
        "角色可以分享文档。",
        "成员必须编辑文档。",
        "Members edit documents.",
        "Members share documents.",
        "Members can manage access to documents.",
        "成员管理访问权限。",
        "If an administrator approves, members can edit documents.",
        "如果管理员批准，成员可以分享文档。",
        "角色范围限于一个域名。成员可以编辑文档。",
        "The role applies to one domain; members can share documents.",
        "该角色可以清除缓存，也可以管理文档访问权限。",
    ],
)
def test_role_words_and_conditions_cannot_bypass_explicit_operation_binding(text):
    original = fact(quote="Roles apply to one domain.")
    span = source_span_candidates(original)[0]
    claims, gaps = parse_span(original, text, span)
    assert not claims and "operation_binding_required" in gaps
    persisted = ReportClaim(
        id="unbound-operation", **draft(original, text), source_span_bindings=[span]
    )
    result = audit(original, persisted)
    assert result.status == "rejected" and "operation_binding_required" in result.rule_reasons


@pytest.mark.parametrize("change", ["negation", "condition", "offset"])
def test_recovered_optional_rule_cannot_bind_a_tampered_or_shortened_span(change):
    rule = "Guests do not own private storage and can join only after confirmation."
    original = fact(quote=rule + " Consider inviting:")
    choices = source_span_candidates(original)
    assert choices
    forged = dict(choices[0])
    if change == "negation":
        forged["quote"] = rule.replace("do not own", "own")
    elif change == "condition":
        forged["quote"] = rule.replace(" only after confirmation", "")
        forged["end"] = len(forged["quote"])
    else:
        forged["start"] += 1
    claims, gaps = parse_span(original, rule, forged)
    assert not claims and "claim_candidate_invalid" in gaps
    persisted = ReportClaim(
        id="tampered-span", **draft(original, rule), source_span_bindings=[forged]
    )
    assert projected_source_facts(persisted, [original])[1] == ("source_span_binding_mismatch",)


def test_actual_role_span_remains_subject_to_full_assertion_review():
    row = CAPTURED[1]
    original = EvidenceFact.model_validate(row["fact"])
    span = next(
        span for span in source_span_candidates(original) if span["quote"] == original.quote
    )
    claims, gaps = parse_span(original, "此角色的清缓存权限适用于所有域名。", span)
    assert claims and not gaps
    assert audit(original, claims[0], "unsupported").status == "rejected"
