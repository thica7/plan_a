from __future__ import annotations

import pytest

from packages.business_intel.entity_resolver import is_trusted_url_for_competitor
from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.discovery import trusted_registry_candidates
from packages.research.evidence import admit_evidence_items
from packages.research.extraction import extract_page
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate


def feature_fixture(text, *, competitor="Notion", title="Collaboration in Notion", url=None):
    url = url or "https://www.notion.com/help/collaborate-with-people"
    brief = ResearchBrief(
        run_id="offline-collector", topic="产品功能调研", competitor=competitor,
        dimension="feature", product_category="文档协作", target_source_count=1,
    )
    candidate = SourceCandidate(
        title=title, url=url, origin="web_search", competitor=competitor, dimension="feature",
    )
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=url, final_url=url, status="ok",
        title=title, text=text, quality_score=.9, content_hash="fixture",
    )
    return brief, candidate, page


def accepted_capabilities(brief, candidate, page, extraction=None):
    items = admit_evidence_items(
        [extraction or extract_page(brief, page)], brief=brief,
        captured_pages=[page], candidates=[candidate],
    )
    return [item for item in items if item.status == "accepted"]


def test_feature_subject_allows_coordinated_product_components():
    brief, candidate, page = feature_fixture(
        "Notion pages and comments support simultaneous editing for distributed teams."
    )
    assert accepted_capabilities(brief, candidate, page)


@pytest.mark.parametrize('text', ['Can I comment on a specific cell within a row?', 'Can I copy a link to a specific comment thread?'])
def test_document_questions_are_not_product_capabilities(text):
    brief, candidate, page = feature_fixture(text)
    assert not accepted_capabilities(brief, candidate, page)


def test_deterministic_document_fact_keeps_captured_access_restrictions():
    from packages.research.extraction.feature import extract_generic_capabilities
    text = 'Add comments\nYou can add comments to shared pages in this workspace.\nAccess rules\nRequires edit access.'
    brief, candidate, page = feature_fixture(text)
    page.metadata['document_headings'] = [(2, 'Add comments'), (2, 'Access rules')]
    result = extract_generic_capabilities(brief, page)
    assert result.fields
    assert 'Requires edit access.' in result.fields['capability_1']['evidence_terms']
    assert accepted_capabilities(brief, candidate, page, result)


def test_feature_subject_allows_coordinated_component_acronyms():
    brief, candidate, page = feature_fixture(
        "Notion pages and API support exporting structured database records for external tools."
    )
    assert accepted_capabilities(brief, candidate, page)


def test_registered_document_title_can_be_localized():
    brief, candidate, page = feature_fixture(
        "你可以与团队成员共同编辑页面并分享评论内容", title="Notion 团队协作指南",
    )
    assert accepted_capabilities(brief, candidate, page)


def test_registered_document_title_can_change_without_changing_product():
    brief, candidate, page = feature_fixture(
        "You can create shared document workflows with tables and comments.",
        competitor="Coda", title="What's new in Coda", url="https://coda.io/product/whats-new",
    )
    assert accepted_capabilities(brief, candidate, page)


def test_chinese_quote_uses_same_minimum_in_quality_and_admission():
    brief, candidate, page = feature_fixture(
        "洁净家支持多人同时编辑和评论共享文档", competitor="洁净家", title="洁净家功能",
        url="https://example.com/features",
    )
    assert 18 <= len(page.text) < 24
    assert accepted_capabilities(brief, candidate, page)


@pytest.mark.parametrize("text", [
    "Supports simultaneous editing of shared pages by multiple team members.",
    "You can edit shared pages together with other members of your workspace.",
])
def test_official_document_can_bind_subjectless_capability_to_product(text):
    brief, candidate, page = feature_fixture(text)
    extraction = extract_page(brief, page)
    items = accepted_capabilities(brief, candidate, page, extraction)
    assert items
    quote = extraction.quotes[0]
    assert page.text[quote.start_offset:quote.end_offset] == quote.text
    assert quote.source_url == page.final_url
    assert evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=items, ledger=[],
    ).passed


@pytest.mark.parametrize("updates", [
    {"final_url": "https://notion.com.evil.example/help/collaborate-with-people"},
    {"final_url": "https://review.example/notion"},
    {"title": "Notion vs Figma feature comparison"},
    {"title": "Customer stories: Notion in a consulting firm"},
    {"text": "Figma supports sharing design files and comments with other team members."},
    {"text": "Notion and Figma support simultaneous editing by multiple team members."},
    {"text": "Notion pages and Figma support simultaneous editing by multiple team members."},
    {"text": "Notion pages and Jira support simultaneous editing by multiple team members."},
    {"text": "Notion pages and AcmePro support simultaneous editing by multiple team members."},
    {"text": "You cannot edit shared pages together with other members of your workspace."},
    {"text": "You can’t edit shared pages together with other members of your workspace."},
    {"text": "You can no longer edit shared pages together with other members of your workspace."},
    {"text": "Figma is a design application. It supports sharing editable documents with your teammates."},
    {"text": "Features for knowledge management and project collaboration"},
    {"text": '"You can edit shared pages together with other members of your workspace."'},
    {"title": "Notion help", "final_url": "https://www.notion.com/customers/example"},
    {"title": "Notion Calendar documentation"},
])
def test_document_subject_binding_does_not_leak_to_other_products_or_quotes(updates):
    brief, candidate, page = feature_fixture(
        "You can edit shared pages together with other members of your workspace."
    )
    page = page.model_copy(update=updates)
    assert not accepted_capabilities(brief, candidate, page)


@pytest.mark.parametrize("mutation", ["text", "offset", "url", "value"])
def test_generic_capability_admission_rechecks_captured_body(mutation):
    brief, candidate, page = feature_fixture(
        "Notion supports simultaneous editing of shared documents with your teammates."
    )
    extraction = extract_page(brief, page)
    assert extraction.quotes
    if mutation == "text":
        extraction.quotes[0].text = "Notion supports exporting every document to an invented format."
    elif mutation == "offset":
        extraction.quotes[0].start_offset = 4
    elif mutation == "url":
        extraction.quotes[0].source_url = "https://www.figma.com/features"
    else:
        extraction.fields["capability_1"]["evidence_terms"] = ["invented feature"]
    assert not accepted_capabilities(brief, candidate, page, extraction)


def test_admission_reparse_preserves_target_product_scope():
    brief, candidate, page = feature_fixture(
        "Notion supports importing design files from Figma. "
        "Notion supports document comments and shared page editing."
    )
    brief.product_name = "Figma"
    items = accepted_capabilities(brief, candidate, page)
    assert len(items) == 1
    assert "document comments" in items[0].quote


def test_product_sibling_is_not_resolved_as_registered_product():
    from packages.business_intel.entity_resolver import resolve_competitor_identity

    assert resolve_competitor_identity("Notion Calendar") is None


def test_shared_vendor_domain_does_not_bind_other_product_document():
    brief, candidate, page = feature_fixture(
        "You can create issue boards and manage team assignments within your workspace.",
        competitor="Confluence", title="Jira workflow guide", url="https://support.atlassian.com/jira/docs/workflows/",
    )
    assert not accepted_capabilities(brief, candidate, page)


def test_official_integration_document_does_not_bind_foreign_product_to_current_product():
    brief, candidate, page = feature_fixture(
        "You can create issue boards and manage team assignments within your workspace.",
        competitor="Confluence", title="Connect Jira to Confluence",
        url="https://support.atlassian.com/jira/docs/connect-jira-to-confluence/",
    )
    assert not accepted_capabilities(brief, candidate, page)


@pytest.mark.parametrize("competitor,domain", [
    ("Notion", "notion.com"), ("Figma", "figma.com"),
    ("Coda", "coda.io"), ("Confluence", "atlassian.com"),
])
@pytest.mark.parametrize("dimension", ["feature", "pricing"])
def test_general_product_has_official_discovery_seeds(competitor, domain, dimension):
    brief = ResearchBrief(
        run_id="offline-seeds", topic="产品调研", competitor=competitor,
        dimension=dimension, product_category="团队软件",
    )
    seeds = trusted_registry_candidates(brief)
    assert any(candidate.dimension == dimension for candidate in seeds)
    assert all(is_trusted_url_for_competitor(competitor, candidate.url) for candidate in seeds)
    assert not is_trusted_url_for_competitor(competitor, f"https://{domain}.evil.example")
