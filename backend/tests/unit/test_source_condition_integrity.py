"""Anonymous source conditions remain attached to repeated capabilities."""

from types import SimpleNamespace

import pytest

from packages.research.evidence.normalization import normalized_feature_fields_from_evidence_items
from packages.research.evidence.report_claims import (
    ReportClaim,
    audit_report_claims,
    claim_rule_reasons,
)
from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json
from packages.research.models import EvidenceItem

CONDITION = (
    "Depending on your Example Suite plan, you can enhance security by setting "
    "a seal for your public canvas"
)
SHORT = "You can also protect your canvas with a seal"


def item(quote, field="short", **updates):
    values = dict(
        competitor="Example Suite",
        dimension="feature",
        field=field,
        value={"status": "supported", "evidence_terms": [quote]},
        source_candidate_id="candidate",
        captured_page_id="capture",
        source_url="https://example.test/help/canvas",
        quote=quote,
        confidence=0.9,
        status="accepted",
    )
    values.update(updates)
    return EvidenceItem(**values)


def normalized(short=None, condition=None):
    short = short or item(SHORT)
    rows = normalized_feature_fields_from_evidence_items(
        [condition or item(CONDITION, "condition"), short]
    )
    return next(row for row in rows if row.slot == short.field)


def observation(row=None):
    row = row or normalized()
    return EvidenceFact(
        id="fact-short",
        semantic_id="semantic-short",
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


def claim(original, text):
    return ReportClaim(
        id="claim",
        text=text,
        kind="fact",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
    )


def reasons(text, original=None):
    original = original or observation()
    return claim_rule_reasons(
        claim(original, text),
        SimpleNamespace(facts=(original,)),
        [SimpleNamespace(allowed_fact_ids=(original.id,))],
    )


def test_repeated_capability_keeps_complete_source_condition_and_item_identity():
    source = item(CONDITION, "condition")
    short = item(SHORT)
    row = normalized(short, source)
    links = row.qualifiers.get("source_condition_links", [])
    assert links and links[0]["quote"] == CONDITION
    assert links[0]["evidence_item_id"] == source.id
    assert links[0]["captured_page_id"] == source.captured_page_id
    assert links[0]["source_url"] == source.source_url
    assert row.evidence_item_ids == [short.id]
    assert row.evidence_quote == SHORT


@pytest.mark.parametrize(
    ("condition", "short"),
    [
        (
            "Depending on your Example Suite subscription, "
            "you can mark your public folio with a watermark",
            "You can also mark your folio with a watermark",
        ),
        (
            "Depending on your Example Suite plan, you can export your public charts",
            "You can also export your charts",
        ),
    ],
)
def test_capability_matching_is_not_a_product_or_password_allowlist(condition, short):
    links = normalized(item(short), item(condition, "condition")).qualifiers.get(
        "source_condition_links", []
    )
    assert links and links[0]["quote"] == condition


@pytest.mark.parametrize(
    "updates",
    [
        {"competitor": "Another Suite"},
        {"source_url": "https://example.test/help/other"},
        {"captured_page_id": "other-capture"},
        {"raw_source_id": "another-source"},
        {"status": "rejected"},
        {"status": "unreviewed"},
        {"dimension": "pricing"},
    ],
)
def test_conditions_do_not_cross_evidence_scope_or_admission(updates):
    short = item(SHORT, raw_source_id="source")
    condition = item(
        CONDITION,
        "condition",
        raw_source_id="source",
        **{key: value for key, value in updates.items() if key != "raw_source_id"},
    )
    if "raw_source_id" in updates:
        condition = condition.model_copy(update=updates)
    assert not normalized(short, condition).qualifiers.get("source_condition_links")


@pytest.mark.parametrize(
    ("condition", "short"),
    [
        (CONDITION, "You can also protect your document with a seal"),
        (CONDITION, "You can also protect your private canvas with a seal"),
        (CONDITION, "You can also protect your canvas with a ribbon"),
        (CONDITION, "You can also reset your canvas seal"),
        (CONDITION, "You can also view your canvas with a seal"),
        (
            "Depending on your Example Suite plan, Auditors can export your public charts",
            "Editors can also export your charts",
        ),
        (
            "Depending on your Example Suite plan, you can export your public charts",
            "You can also edit your charts",
        ),
    ],
)
def test_similar_but_distinct_capabilities_do_not_inherit_conditions(condition, short):
    assert not normalized(item(short), item(condition, "condition")).qualifiers.get(
        "source_condition_links"
    )


@pytest.mark.parametrize("context", ["document_section", "plan", "role"])
def test_explicit_different_section_role_or_plan_does_not_inherit(context):
    short = item(SHORT, metadata={context: "one"})
    source = item(CONDITION, "condition", metadata={context: "two"})
    assert not normalized(short, source).qualifiers.get("source_condition_links")


@pytest.mark.parametrize("context", ["plan", "role", "access_scope"])
def test_different_structured_operation_context_does_not_inherit(context):
    short = item(
        SHORT,
        value={"status": "supported", "evidence_terms": [SHORT], "operations": [{context: "one"}]},
    )
    source = item(
        CONDITION,
        "condition",
        value={
            "status": "supported",
            "evidence_terms": [CONDITION],
            "operations": [{context: "two"}],
        },
    )
    assert not normalized(short, source).qualifiers.get("source_condition_links")


@pytest.mark.parametrize("operations", [None, 7])
def test_malformed_operation_context_cannot_create_a_condition_link(operations):
    source = item(
        CONDITION,
        "condition",
        value={"status": "supported", "evidence_terms": [CONDITION], "operations": operations},
    )
    assert not normalized(item(SHORT), source).qualifiers.get("source_condition_links")


def test_condition_link_preserves_role_plan_pairing_inside_each_operation_branch():
    source_rows = [
        {"role": "Guests", "plan": "Free", "access_scope": "public"},
        {"role": "Members", "plan": "Paid", "access_scope": "public"},
    ]
    short_rows = [
        {"role": "Guests", "plan": "Paid", "access_scope": "public"},
        {"role": "Members", "plan": "Free", "access_scope": "public"},
    ]
    source = item(
        CONDITION,
        "condition",
        value={"status": "supported", "evidence_terms": [CONDITION], "operations": source_rows},
    )
    short = item(
        SHORT, value={"status": "supported", "evidence_terms": [SHORT], "operations": short_rows}
    )
    assert not normalized(short, source).qualifiers.get("source_condition_links")


@pytest.mark.parametrize(
    "tail",
    [
        "you may protect all canvases with a seal.",
        "seal protection is available for all canvases.",
        "all canvases accept a seal.",
    ],
)
@pytest.mark.parametrize("separator", ["; ", ", ", "，"])
def test_qualified_first_sentence_cannot_hide_a_later_unqualified_assertion(tail, separator):
    original = observation()
    text = (
        "Depending on your plan, you can protect your public canvas with a seal" + separator + tail
    )
    candidate = claim(original, text)
    audited = audit_report_claims(
        [candidate],
        [
            dict(
                claim_id=candidate.id,
                verdict="supported",
                reason="The initial statement preserves its source conditions.",
            )
        ],
        SimpleNamespace(facts=(original,)),
        [SimpleNamespace(allowed_fact_ids=(original.id,))],
    )
    assert audited[0].status == "rejected"
    assert "source_plan_condition_omitted_or_changed" in audited[0].rule_reasons


@pytest.mark.parametrize("separator", ["; ", ", "])
def test_standalone_source_tier_clarification_is_not_an_unqualified_capability(separator):
    text = (
        "Depending on your plan, you can protect your public canvas with a seal"
        + separator
        + "The source does not name a specific tier."
    )
    assert not reasons(text)


def test_source_tier_clarification_cannot_hide_a_following_capability():
    text = (
        "Depending on your plan, you can protect your public canvas with a seal; "
        "The source does not name a specific tier, all canvases accept a seal."
    )
    assert "source_plan_condition_omitted_or_changed" in reasons(text)


@pytest.mark.parametrize(
    "text",
    [
        "You can protect your canvas with a seal.",
        "You can protect your public canvas with a seal.",
        "可以为画布设置印记保护。",
        "可以为公开画布设置印记保护。",
        "All plans allow protection of public canvases with a seal.",
        "Depending on your plan, you can protect your canvas with a seal.",
        "可以为所有画布设置印记保护，是否能导出取决于套餐。",
        "可以为公开画布设置印记保护，是否能导出取决于套餐。",
        "Your plan does not determine whether you can protect your public canvas with a seal.",
        "You can protect public canvases with a seal; exports depend on your plan.",
        "Whether you can protect your public canvas with a seal does not depend on your plan.",
        "Depending on your plan, all plans can protect public canvases with a seal.",
    ],
)
def test_claim_cannot_drop_plan_or_public_scope(text):
    assert reasons(text)


@pytest.mark.parametrize(
    "text",
    [
        "Depending on your plan, you can protect your public canvas with a seal.",
        "是否能为公开画布设置印记取决于套餐，原文未指定具体套餐。",
    ],
)
def test_claim_can_preserve_the_source_dependency_without_guessing_a_tier(text):
    assert not reasons(text)


def test_supported_model_review_cannot_override_missing_source_conditions():
    original = observation()
    candidate = claim(original, "可以为画布设置印记保护。")
    audited = audit_report_claims(
        [candidate],
        [
            dict(
                claim_id=candidate.id,
                verdict="supported",
                reason="The shorter quote states the capability.",
            )
        ],
        SimpleNamespace(facts=(original,)),
        [SimpleNamespace(allowed_fact_ids=(original.id,))],
    )
    assert audited[0].status == "rejected"
    assert "source_plan_condition_omitted_or_changed" in audited[0].rule_reasons
    assert "source_public_scope_omitted_or_changed" in audited[0].rule_reasons


@pytest.mark.parametrize(
    "text",
    [
        "Depending on your plan, Aurora plans can protect public canvases with a seal.",
        "Whether you can protect your public canvas with a seal depends on your paid subscription.",
        "是否能为公开画布设置印记取决于付费套餐。",
        "是否能为公开画布设置印记取决于极光套餐。",
        "取决于套餐，公开文档的免费套餐支持添加印章。",
        "取决于套餐，公开画布的付费套餐支持添加印章。",
    ],
)
def test_unknown_source_tier_is_not_replaced_with_an_invented_named_tier(text):
    assert reasons(text)


def test_writer_compaction_and_review_retain_complete_condition_dependencies():
    from packages.agents.writer.dimension_writer import (
        compact_dimension_context,
        compact_prompt_json,
        review_payload,
    )

    original = observation()
    payload, omitted = compact_dimension_context(
        {"segment_competitor": original.competitor, "dimension": "feature"},
        SimpleNamespace(facts=(original,)),
        {original.id},
        max_bytes=8000,
    )
    assert not omitted
    assert CONDITION in compact_prompt_json(payload)
    candidate = claim(
        original, "Depending on your plan, you can protect your public canvas with a seal."
    )
    review = review_payload([candidate], SimpleNamespace(facts=(original,), sources=()))
    assert review["facts"][0]["qualifiers"]["source_condition_links"][0]["quote"] == CONDITION
    assert CONDITION in compact_prompt_json(review)
    small, omitted = compact_dimension_context(
        {"segment_competitor": original.competitor, "dimension": "feature"},
        SimpleNamespace(facts=(original,)),
        {original.id},
        max_bytes=300,
    )
    assert omitted and small["evidence_view"]["facts"] == []


def test_old_unlinked_records_are_read_without_silent_condition_backfill():
    from packages.research.evidence.normalization import normalized_fields_from_source

    row = dict(
        kind="feature",
        competitor="Example Suite",
        dimension="feature",
        slot="old",
        evidence_quote=SHORT,
        evidence_terms=[SHORT],
        qualifiers={"operations": []},
    )
    raw = SimpleNamespace(metadata={"normalized_fields": [row]})
    assert normalized_fields_from_source(raw) == [row]
    original = observation(
        SimpleNamespace(
            competitor="Example Suite",
            evidence_terms=[SHORT],
            evidence_quote=SHORT,
            qualifiers={"operations": []},
            evidence_item_ids=["old-item"],
        )
    )
    assert not reasons("You can protect your canvas with a seal.", original)


def test_snapshot_and_final_rule_replay_preserve_source_condition_receipts():
    from datetime import UTC, datetime

    from test_run_evidence_snapshot import make_detail

    from packages.research.evidence.snapshot import seal_snapshot
    from packages.research.evidence.views import select_evidence_view

    row = normalized()
    detail = make_detail()
    detail.plan.competitors = [row.competitor]
    detail.plan.dimensions = ["feature"]
    source = detail.raw_sources[0]
    source.competitor = row.competitor
    source.dimension = "feature"
    source.url = row.source_url
    source.metadata = {
        "source_material_level": "full_source",
        "last_verified_at": datetime.now(UTC).isoformat(),
        "normalized_fields": [row.model_dump(mode="json")],
    }
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = select_evidence_view(snapshot, agent="qa", max_bytes=16000)
    original = next(value for value in view.facts if value.field == "evidence_terms")
    assert original.qualifiers["source_condition_links"][0]["quote"] == CONDITION
    assert original.evidence_item_ids == tuple(row.evidence_item_ids)
    assert "source_plan_condition_omitted_or_changed" in reasons(
        "可以为公开画布设置印记保护。", original
    )
