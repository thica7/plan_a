from types import SimpleNamespace

import pytest

from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json


def fact(product, quote, *, slot, status="supported", qualifiers=None):
    return EvidenceFact(id=f"{product}-{slot}", semantic_id=f"semantic-{product}-{slot}", source_id=f"source-{product}", competitor=product, dimension="feature", field="evidence_terms", value_json=canonical_json([quote]), quote=quote, qualifiers_json=canonical_json({"slot": slot, **(qualifiers or {})}), status=status, confidence=.9)


def test_different_observation_slots_align_same_documented_capability():
    from packages.research.evidence.capabilities import capability_alignment
    facts = [fact("Notion", "You can add comments to a page.", slot="semantic_capability_a"), fact("Confluence", "Users can comment on shared documents.", slot="capability_5")]
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-Notion", "source-Confluence")), ["Notion", "Confluence"])
    row = next(row for row in rows if row["capability_key"] == "comments")
    assert row["comparison_status"] == "comparable"
    assert row["product_statuses"] == {"Notion": "documented", "Confluence": "documented"}
    assert row["evidence_by_product"]["Notion"]["fact_ids"] == [facts[0].id]


def test_page_name_formula_is_not_shared_editing_or_comments():
    from packages.research.evidence.capabilities import capability_keys
    assert capability_keys(fact("Coda", "You can set a page name via an action formula.", slot="capability_1")) == ("automation",)
    assert "shared_editing" in capability_keys(fact("Notion", "Multiple people can edit the same page in real time.", slot="x"))


def test_comments_and_mentions_are_separate_capabilities():
    from packages.research.evidence.capabilities import capability_keys
    assert capability_keys(fact("Notion", "You can mention a teammate to notify them.", slot="x")) == ("mentions",)
    assert capability_keys(fact("Notion", "You can comment and mention a teammate.", slot="x")) == ("comments", "mentions")


def test_negative_signal_and_unseen_evidence_do_not_create_support():
    from packages.research.evidence.capabilities import capability_keys, capability_alignment
    assert capability_keys(fact("Notion", "You cannot add comments.", slot="x")) == ()
    assert capability_keys(fact("Notion", "You can add comments.", slot="x", status="signal")) == ()
    rows = capability_alignment(SimpleNamespace(facts=[fact("Notion", "You can add comments.", slot="x")], source_ids=()), ["Notion"])
    assert rows == []


def test_partial_and_conditional_coverage_does_not_imply_superiority():
    from packages.research.evidence.capabilities import capability_alignment
    facts = [fact("Notion", "You can add comments; requires a paid plan.", slot="x")]
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-Notion",)), ["Notion", "Coda"])
    assert rows[0]["comparison_status"] == "insufficient_evidence"
    assert rows[0]["product_statuses"] == {"Notion": "documented_with_conditions", "Coda": "unknown"}
    facts.append(fact("Coda", "You can add comments.", slot="y"))
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-Notion", "source-Coda")), ["Notion", "Coda"])
    assert rows[0]["comparison_status"] == "needs_condition_review"


def test_conditions_retained_outside_quote_require_review():
    from packages.research.evidence.capabilities import capability_alignment
    restricted = fact("Notion", "You can add comments to a page.", slot="x")
    restricted = restricted.model_copy(update={"value_json": canonical_json([restricted.quote, "Available on Enterprise plans."])})
    facts = [restricted, fact("Coda", "You can add comments to a page.", slot="y")]
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-Notion", "source-Coda")), ["Notion", "Coda"])
    assert rows[0]["comparison_status"] == "needs_condition_review"
    assert rows[0]["product_statuses"]["Notion"] == "documented_with_conditions"


def test_other_role_action_restriction_does_not_erase_comment_permission():
    from packages.research.evidence.capabilities import capability_keys, capability_conditioned
    original = fact('Notion', 'Can comment: People can comment on a page; they cannot edit or share content.', slot='x')
    assert 'comments' in capability_keys(original)
    assert capability_conditioned(original)


def test_repeated_classification_keeps_product_scope_and_changed_fact_distinct():
    from packages.research.evidence.capabilities import capability_keys
    original = fact('Coda', 'Docs supports real-time co-editing and comments with AcmeCloud.', slot='x')
    assert {'shared_editing', 'comments'} <= set(capability_keys(original, ['Coda']))
    assert capability_keys(original, ['Coda', 'AcmeCloud']) == ()
    assert capability_keys(original.model_copy(update={'status': 'signal'}), ['Coda']) == ()
    denied = original.model_copy(update={'quote': 'Docs does not support comments.', 'value_json': canonical_json(['Docs does not support comments.'])})
    assert capability_keys(denied, ['Coda']) == ()
    assert 'comments' in capability_keys(original, ['Coda'])


def test_edit_access_is_a_permission_boundary():
    from packages.research.evidence.capabilities import capability_keys
    assert 'permissions' in capability_keys(fact('Coda','Can edit access allows editing the doc content.',slot='x'))


@pytest.mark.parametrize("quote", [
    "Comments are unavailable in this workspace.",
    "Comments are not enabled in this workspace.",
    "No comments are supported in this workspace.",
])
def test_negative_descriptions_do_not_establish_positive_support(quote):
    from packages.research.evidence.capabilities import capability_keys
    assert capability_keys(fact("Notion", quote, slot="x")) == ()


def test_other_product_in_shared_quote_is_not_assigned_to_target():
    from packages.research.evidence.capabilities import capability_alignment
    facts = [fact("Notion", "Coda provides comments. Notion users can edit pages.", slot="x"),
             fact("Coda", "You can add comments to a page.", slot="y")]
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-Notion", "source-Coda")), ["Notion", "Coda"])
    assert rows[0]["product_statuses"]["Notion"] == "unknown"


def test_unregistered_product_names_in_shared_quote_are_also_rejected():
    from packages.research.evidence.capabilities import capability_alignment
    facts = [fact("产品甲", "产品乙支持评论。产品甲支持编辑页面。", slot="x"),
             fact("产品乙", "产品乙支持评论。", slot="y")]
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-产品甲", "source-产品乙")), ["产品甲", "产品乙"])
    assert rows[0]["product_statuses"]["产品甲"] == "unknown"


def test_metadata_fields_cannot_restore_capability_denied_by_content():
    from packages.research.evidence.capabilities import capability_alignment
    original = fact("Notion", "You can add comments to a page.", slot="x")
    denied = original.model_copy(update={"value_json": canonical_json([original.quote, "Comments are unavailable in this workspace."])})
    metadata = [original.model_copy(update={"id": f"Notion-{field}", "field": field, "value_json": canonical_json(value)})
                for field, value in (("slot", "x"), ("support_level", "documented"))]
    facts = [denied, *metadata, fact("Coda", "You can add comments.", slot="y")]
    rows = capability_alignment(SimpleNamespace(facts=facts, source_ids=("source-Notion", "source-Coda")), ["Notion", "Coda"])
    assert rows[0]["product_statuses"]["Notion"] == "unknown"


@pytest.mark.parametrize("quote, body, expected", [
    ("You can add comments to a page in the workspace.", "You can add comments to a page in the workspace.\nAvailable on Enterprise plans.", "documented_with_conditions"),
    ("Comments are unavailable in this workspace.", "Comments are unavailable in this workspace.", "unknown"),
    ("You can add comments to a page in the workspace.", "You can add comments to a page in the workspace.\nComments are unavailable in this workspace.", "unknown"),
])
def test_semantic_admission_snapshot_alignment_preserves_conditions(quote, body, expected):
    from hashlib import sha256
    from test_stage_evidence_views import distributed_detail
    from packages.business_intel.entity_resolver import resolve_competitor_identity
    from packages.research.evidence.admission import admit_evidence_items, raw_source_from_capture
    from packages.research.evidence.capabilities import capability_alignment
    from packages.research.evidence.normalization import normalized_fields_as_dicts, normalized_fields_from_evidence_items
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.research.evidence.views import select_evidence_view
    from packages.research.extraction.semantic import semantic_extraction
    from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ["Notion", "Coda"]
    detail.raw_sources = []
    positive = "You can add comments to a page in the workspace."
    for product in detail.plan.competitors:
        url = resolve_competitor_identity(product).sources_by_dimension["feature"][0].url
        brief = ResearchBrief(run_id=detail.id, topic="协作", competitor=product, dimension="feature", product_category="文档")
        candidate = SourceCandidate(title=f"{product} collaboration documentation", url=url, origin="web_search", competitor=product, dimension="feature")
        text, selected = (body, quote) if product == "Notion" else (positive, positive)
        page = CapturedPage(candidate_id=candidate.id, requested_url=str(candidate.url), final_url=str(candidate.url), status="ok", title=candidate.title, text=text, quality_score=.9, content_hash=sha256(text.encode()).hexdigest())
        result = semantic_extraction(brief, page, {"facts": [{"quote": selected}]})
        items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
        assert len(items) == 1 and items[0].status == "accepted"
        detail.raw_sources.append(raw_source_from_capture(brief, candidate, page, confidence=.9, snippet=selected, metadata={"normalized_fields": normalized_fields_as_dicts(normalized_fields_from_evidence_items(items))}))
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view = select_evidence_view(snapshot, agent="comparator", max_bytes=16384)
    row = next(row for row in capability_alignment(view, detail.plan.competitors) if row["capability_key"] == "comments")
    assert row["product_statuses"] == {"Notion": expected, "Coda": "documented"}
    assert row["comparison_status"] != "comparable"


@pytest.mark.parametrize("scope", ["product", "source", "missing_source"])
def test_prompt_keeps_snapshot_product_scope_when_other_product_is_omitted(scope):
    import json
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.research.evidence.views import select_evidence_view
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ["产品甲", "产品乙"]
    detail.raw_sources = detail.raw_sources[:2]
    for source, product in zip(detail.raw_sources, detail.plan.competitors):
        source.competitor = product
        source.covered_competitors = [product]
        row = source.metadata["normalized_fields"][0]
        row["competitor"] = product
        row["evidence_quote"] = "产品乙支持评论。产品甲支持编辑页面。" if product == "产品甲" else "产品乙支持评论。"
        row["evidence_terms"] = [row["evidence_quote"]]
        source.metadata["normalized_fields"] = [row]
    if scope == "missing_source":
        detail.raw_sources = detail.raw_sources[:1]
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    selection = {"competitor": "产品甲"} if scope == "product" else {"source_ids": [detail.raw_sources[0].id]}
    view = select_evidence_view(snapshot, agent="analyst", max_bytes=8192, **selection)
    assert {fact.competitor for fact in view.facts} == {"产品甲"}
    assert set(view.comparison_products) == set(detail.plan.competitors)
    payload = json.loads(view.to_prompt_json())
    assert all(not fact.get("capability_keys") for fact in payload["facts"])
    replay = select_evidence_view(snapshot, agent="analyst", max_bytes=8192, **selection)
    assert replay.dependency_hash == view.dependency_hash


def test_without_leaving_document_is_not_a_negation_of_coediting_or_comments():
    from packages.research.evidence.capabilities import capability_keys
    positive=fact('Coda','Docs supports real-time co-editing and threaded comments, so teams can decide without leaving the doc.',slot='coedit')
    assert {'shared_editing','comments'} <= set(capability_keys(positive))
    assert 'comments' not in capability_keys(fact('Coda','The workspace is provided without comments.',slot='no-comments'))
