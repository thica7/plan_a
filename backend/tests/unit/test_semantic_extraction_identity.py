"""Distinct source extractors retain admitted facts from the same captured page."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from packages.research.evidence import admit_evidence_items, dedupe_by_id
from packages.research.evidence.admission import raw_source_from_capture
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.extraction.semantic import extract_operation_rules, semantic_extraction
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate
from packages.research.pipeline import run_research_pipeline
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


RULE = "Members can edit documents on all plans."
SUPPLEMENT = "Access to archived documents expires after seven days."
BODY = RULE + "\n" + SUPPLEMENT


def source_fixture():
    brief = ResearchBrief(
        run_id="extractor-identity",
        topic="Document permissions",
        competitor="Notion",
        dimension="feature",
        product_category="documents",
        include_trusted_sources=False,
        include_homepage_candidates=False,
        target_source_count=1,
        max_fetches=1,
        max_search_queries=0,
        max_repair_rounds=0,
    )
    candidate = SourceCandidate(
        title="Collaboration in Notion",
        url="https://www.notion.com/help/collaborate-with-people",
        origin="manual",
        competitor=brief.competitor,
        dimension=brief.dimension,
    )
    page = CapturedPage(
        candidate_id=candidate.id,
        requested_url=str(candidate.url),
        final_url=str(candidate.url),
        title=candidate.title,
        text=BODY,
        content_hash="original-source-body",
        status="ok",
        quality_score=.9,
        source_material_level="full_source",
    )
    return brief, candidate, page


def model_selection(brief, page):
    return semantic_extraction(brief, page, {"facts": [{"quote": SUPPLEMENT}]})


@pytest.mark.asyncio
async def test_same_page_source_rule_and_model_supplement_both_reach_snapshot():
    brief, candidate, _ = source_fixture()

    async def fetch(url):
        return SimpleNamespace(
            url=url, title=candidate.title, text=BODY, ok=True, status="ok",
            quality_score=.9, content_hash="original-source-body",
            source_material_level="full_source",
        )

    async def select(active_brief, captured):
        return model_selection(active_brief, captured)

    result = await run_research_pipeline(
        brief, fetch=fetch, seed_candidates=[candidate], semantic_extract=select,
    )
    accepted = {item.quote for item in result.evidence_items if item.status == "accepted"}
    assert {RULE, SUPPLEMENT} <= accepted
    source = raw_source_from_capture(
        brief, candidate, result.captured_pages[0], confidence=.9, snippet=BODY,
        metadata={"normalized_fields": [row.model_dump(mode="json") for row in result.normalized_fields]},
    )
    now = datetime.utcnow()
    detail = RunDetail(
        id=brief.run_id, topic=brief.topic, status="running", execution_mode="real",
        created_at=now, updated_at=now,
        plan=AnalysisPlan(topic=brief.topic, competitors=[brief.competitor], dimensions=["feature"]),
        raw_sources=[source],
    )
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert {RULE, SUPPLEMENT} <= {fact.quote for fact in snapshot.facts if fact.field == "evidence_terms"}


def test_same_extractor_repeats_still_dedupe_without_hiding_other_extractor():
    brief, _, page = source_fixture()
    rule = extract_operation_rules(brief, page)
    model = model_selection(brief, page)
    merged = dedupe_by_id([rule, extract_operation_rules(brief, page), model, model_selection(brief, page)])
    assert len(merged) == 2
    assert {quote.text for result in merged for quote in result.quotes} == {RULE, SUPPLEMENT}


@pytest.mark.parametrize("mutation", ["quote", "offset", "url"])
def test_model_supplement_still_requires_original_source_admission(mutation):
    brief, candidate, page = source_fixture()
    rule = extract_operation_rules(brief, page)
    if mutation == "quote":
        model = semantic_extraction(
            brief, page, {"facts": [{"quote": "Guests can access every archived document forever."}]},
        )
        assert not model.fields
    else:
        model = model_selection(brief, page)
        if mutation == "offset":
            model.quotes[0].start_offset += 1
        else:
            model.quotes[0].source_url = "https://unrelated.example/document"
    merged = dedupe_by_id([rule, model])
    items = admit_evidence_items(merged, brief=brief, captured_pages=[page], candidates=[candidate])
    accepted = {item.quote for item in items if item.status == "accepted"}
    assert RULE in accepted
    assert SUPPLEMENT not in accepted
    assert all(item.quote != "Guests can access every archived document forever." for item in items if item.status == "accepted")


def test_renamed_source_rule_extractor_keeps_value_replay_protection():
    brief, candidate, page = source_fixture()
    rule = extract_operation_rules(brief, page)
    next(iter(rule.fields.values()))["evidence_terms"] = [
        "All users can edit every archived document forever."
    ]
    items = admit_evidence_items([rule], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == "rejected" for item in items)
    assert any("semantic_evidence_not_bound_to_body" in (item.rejection_reason or "") for item in items)
