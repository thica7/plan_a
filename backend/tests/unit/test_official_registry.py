import hashlib
import json
from pathlib import Path

import pytest

from packages.business_intel.entity_resolver import (
    is_trusted_url_for_competitor, resolve_competitor_identity,
)
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate
from packages.tools.evidence_fetch import EvidenceFetchResult


def registration():
    return {"product": "Novel Desk", "aliases": ["ND Workspace"], "documents": [{
        "title": "Novel Desk permissions", "url": "https://docs.noveldesk.example/permissions?id=1",
        "dimension": "feature", "reviewed_by": "operator", "reviewed_at": "2026-10-16T01:50:40Z",
        "review_basis": "Official document explicitly confirmed by product owner.",
    }]}


def test_generic_registration_requires_no_product_specific_code(tmp_path):
    from packages.business_intel.official_registry import load_registry
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([registration()]))
    records = load_registry(path)
    assert records[0].product == "Novel Desk"
    assert records[0].documents[0].reviewed_by == "operator"


@pytest.mark.parametrize("field,value", [
    ("reviewed_by", ""), ("reviewed_at", "yesterday"), ("reviewed_at", "2026-10-16"),
    ("review_basis", ""), ("url", "http://docs.example/a"),
    ("url", "https://user:password@docs.example/a"), ("url", "https://127.0.0.1/a"),
    ("url", "https://localhost/a"), ("url", "https://docs.example/a#part"),
    ("url", "https://docs.example:444/a"),
])
def test_registry_rejects_invalid_review_or_url(tmp_path, field, value):
    from packages.business_intel.official_registry import load_registry
    item = registration()
    item["documents"][0][field] = value
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([item]))
    with pytest.raises(ValueError):
        load_registry(path)


def test_registry_rejects_alias_collision(tmp_path):
    from packages.business_intel.official_registry import load_registry
    other = registration() | {"product": "Another product", "aliases": ["novel desk"]}
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([registration(), other]))
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(path)


def test_registry_rejects_duplicate_json_key_and_document(tmp_path):
    from packages.business_intel.official_registry import load_registry
    path = tmp_path / "sources.json"
    path.write_text('[{"product":"A","product":"B"}]')
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(path)
    row = registration()
    row["documents"].append(row["documents"][0].copy())
    path.write_text(json.dumps([row]))
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(path)


def test_document_registration_does_not_verify_a_homepage_or_other_query():
    from packages.business_intel.homepage import verify_homepage
    assert not verify_homepage("Miro", "https://help.miro.com").verified
    url = "https://support.zoom.com/hc/pb/article?id=zm_kb&sysparm_article=KB0062540"
    assert is_trusted_url_for_competitor("Zoom", url)
    assert not is_trusted_url_for_competitor("Zoom", url.replace("KB0062540", "KB9999999"))


def test_dynamic_names_do_not_change_lowercase_verb_mentions():
    from packages.business_intel.entity_resolver import resolve_identity_mention
    assert resolve_competitor_identity("zoom")
    assert resolve_identity_mention("zoom") is None
    assert resolve_identity_mention("Zoom").canonical_name == "Zoom"


def test_sentence_initial_zoom_instruction_is_not_a_foreign_product():
    from packages.business_intel.entity_resolver import resolve_identity_mention
    assert resolve_identity_mention("Zoom", context="Zoom in to see the page.") is None
    assert resolve_identity_mention("Zoom", context="Zoom supports local recording.")


def test_registration_cannot_collide_with_a_builtin_alias(tmp_path):
    from packages.business_intel.official_registry import load_registry
    row = registration() | {"aliases": ["notion"]}
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps([row]))
    with pytest.raises(ValueError, match='built-in'):
        load_registry(path)


def test_current_registration_exact_product_url_and_query_scope():
    identity = resolve_competitor_identity("Miro")
    assert identity and identity.canonical_name == "Miro"
    url = "https://help.miro.com/hc/en-us/articles/360012524559-Collaboration-with-Visitors"
    assert is_trusted_url_for_competitor("Miro", url)
    assert not is_trusted_url_for_competitor("Miro AI", url)
    assert not is_trusted_url_for_competitor("Miro", url + "?other=1")
    assert not is_trusted_url_for_competitor("Miro", "https://help.miro.com/unknown")
    assert not is_trusted_url_for_competitor("Airtable", url)


def fixture():
    url = "https://help.miro.com/hc/en-us/articles/360012524559-Collaboration-with-Visitors"
    text = "Visitors can edit the board only on paid and Education plans. " * 3
    candidate = SourceCandidate(title="Miro Visitors", url=url, origin="trusted_registry",
                                competitor="Miro", dimension="feature")
    captured = CapturedPage(candidate_id=candidate.id, requested_url=url, final_url=url,
        title="Collaboration with Visitors – Miro Help Center", status="ok", text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest()[:16], source_material_level="full_source",
        quality_score=.9, status_code=200, fetch_method="basic_httpx")
    return candidate, captured


def test_actual_capture_verification_is_not_just_registry_membership():
    from packages.research.capture.official import verify_registered_capture
    _, page = fixture()
    receipt = verify_registered_capture("Miro", page)
    assert receipt["status"] == "verified"
    assert receipt["content_sha256"] == hashlib.sha256(page.text.encode()).hexdigest()
    assert receipt["reviewed_by"] == "project_user"


@pytest.mark.parametrize("mutation", [
    {"final_url": "https://help.miro.com/unknown"}, {"final_url": "https://evil.example/article"},
    {"final_url": "https://help.miro.com/hc/en-us/articles/360012524559-Collaboration-with-Visitors?x=1"},
    {"requested_url": "https://evil.example/redirect"}, {"title": "Other product permissions"},
    {"source_material_level": "unknown"}, {"content_hash": "wrong"},
    {"status": "failed"}, {"status_code": 403}, {"quality_score": .1},
    {"text": ""}, {"fetch_method": "model_summary"},
])
def test_registered_capture_rejects_unverified_material(mutation):
    from packages.research.capture.official import verify_registered_capture
    _, page = fixture()
    assert verify_registered_capture("Miro", page.model_copy(update=mutation))["status"] == "rejected"


@pytest.mark.asyncio
async def test_typed_fetch_receipt_reaches_semantic_entry():
    from packages.research.capture import capture_candidate
    from packages.research.extraction.semantic import semantic_page_allowed
    candidate, expected = fixture()
    async def fetch(url):
        return EvidenceFetchResult(url=url, ok=True, title=expected.title, text=expected.text,
            content_hash=expected.content_hash, source_material_level="full_source", quality_score=.9,
            status_code=200, text_length=len(expected.text))
    page = await capture_candidate(candidate, fetch)
    assert page.metadata["official_source_verification"]["status"] == "verified"
    brief = ResearchBrief(run_id="registered", competitor="Miro", dimension="feature",
                           topic="编辑及评论权限", product_category="协作")
    assert semantic_page_allowed(brief, page)
    assert not semantic_page_allowed(brief, page.model_copy(update={"source_material_level": "unknown"}))


@pytest.mark.asyncio
async def test_untyped_fetch_cannot_forge_full_source_or_receipt():
    from types import SimpleNamespace
    from packages.research.capture import capture_candidate
    candidate, expected = fixture()
    async def fetch(url):
        return SimpleNamespace(url=url, ok=True, title=expected.title, text=expected.text,
            content_hash=expected.content_hash, quality_score=.9, source_material_level="full_source",
            capture_metadata={"official_source_verification": {"status": "verified"}})
    page = await capture_candidate(candidate, fetch)
    assert page.status == "rejected"
    assert page.metadata["official_source_verification"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_missing_real_title_cannot_use_candidate_title():
    from packages.research.capture import capture_candidate
    candidate, expected = fixture()
    async def fetch(url):
        return EvidenceFetchResult(url=url, ok=True, title="", text=expected.text,
            content_hash=expected.content_hash, source_material_level="full_source", quality_score=.9,
            status_code=200)
    page = await capture_candidate(candidate, fetch)
    assert not page.title
    assert page.status == "rejected"


def test_foreign_cache_rebind_cannot_reuse_verified_receipt():
    from packages.research.capture.cache import CaptureCache
    from packages.research.capture.official import verify_registered_capture
    candidate, page = fixture()
    page.metadata['official_source_verification'] = verify_registered_capture('Miro', page)
    cache = CaptureCache()
    cache.put(candidate, page)
    other = candidate.model_copy(update={"competitor": "Airtable", "id": "foreign"})
    rebound = cache.get(other)
    assert rebound.status == 'rejected'
    assert rebound.metadata['official_source_verification']['product'] == 'Airtable'


def test_comparison_title_not_a_product_permission_document():
    from packages.research.extraction.semantic import semantic_page_allowed
    _, page = fixture()
    page.title = 'Miro comparison review'
    brief = ResearchBrief(run_id='comparison', topic='权限', competitor='Miro', dimension='feature', product_category='协作')
    assert not semantic_page_allowed(brief, page)
