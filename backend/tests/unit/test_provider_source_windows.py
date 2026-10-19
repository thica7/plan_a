"""Anonymous provider representations retain source coordinates and local conditions."""

import hashlib
import json
from datetime import UTC, datetime

import pytest
import test_question_semantic_focus as source_fixtures
from test_deepseek_search import install_response
from test_deepseek_web_api import web_settings

from packages.agents.writer.answer_coverage import question_fact_ids
from packages.crawler.policy import SSRFGuard
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository
from packages.research.evidence import admit_evidence_items
from packages.research.evidence.admission import raw_sources_from_research_result
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view
from packages.research.extraction import semantic
from packages.research.extraction.structured_evidence import extract_structured_evidence
from packages.research.models import ResearchResult
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, DecisionBrief
from packages.tools import evidence_fetch
from packages.tools.deepseek_fetch import deepseek_fetch_page
from packages.tools.fetch_page import FetchPageResult

source = source_fixtures.source
QUESTION = "Can visitors edit the shared collection?"
PARENT = "If you created the workspace, you can invite visitors and share a collection with them."
DENIAL = "Visitors do not have private collections and can only access one shared collection."
QUOTE = "Confirmed visitors can edit the shared collection."
EXCEPTION = (
    "Visitors can edit content except:\n- Archived collections cannot be edited.\n"
    "- Locked records require owner permission.\nThese limits also apply to imported records."
)
BODY = (
    "\\# Visitor collections\n\n"
    + DENIAL
    + "\n\n"
    + PARENT
    + "\n\n\\#\\# Share a collection\n\n"
    + QUOTE
    + "\n\n"
    + EXCEPTION
    + "\n\n"
    + "\\#\\# Other settings\n\n"
    + "\n\n".join(f"Only managers can configure unrelated option {i}." for i in range(8))
)


async def provider(monkeypatch, body=BODY):
    async def resolve(self, hostname, port):
        return {"8.8.8.8"}

    monkeypatch.setattr(SSRFGuard, "resolve", resolve)
    install_response(monkeypatch, {"title": "Example Suite plans", "content": body})
    return await deepseek_fetch_page(
        "https://docs.example-suite.test/plans", settings=web_settings()
    )


async def captured(source, monkeypatch, body=BODY):
    result = await provider(monkeypatch, body)
    brief, candidate, page = source(
        result.text, questions=(QUESTION,), headings=result.capture_metadata["document_headings"]
    )
    page.metadata.update(result.capture_metadata)
    page.fetch_method = result.fetch_method
    page.status_code = result.status_code
    page.captured_at = result.captured_at
    return result, brief, candidate, page


@pytest.mark.asyncio
async def test_escaped_provider_headings_have_raw_coordinates_and_explicit_representation(
    source, monkeypatch
):
    result, brief, _, page = await captured(source, monkeypatch)
    assert result.text == BODY
    assert page.metadata.get("document_structure_format") == "provider_markdown_v1"
    assert "capture_structure_version" not in page.metadata
    anchors = page.metadata["document_heading_anchors"]
    assert len(anchors) == 3
    assert all(anchor["representation"] == "escaped_markdown" for anchor in anchors)
    assert all("source_path" not in anchor for anchor in anchors)
    assert all(BODY[a["start"] : a["end"]] == a["title"] for a in anchors)
    assert all(a["content_sha256"] == hashlib.sha256(BODY.encode()).hexdigest() for a in anchors)
    assert semantic._heading_resolution(BODY, page)["valid"]
    window = semantic.semantic_body_window(brief, page)
    assert QUOTE in window and window in BODY and len(window) <= semantic.MAX_INPUT_CHARS


@pytest.mark.asyncio
async def test_scoped_parent_permission_denial_and_complete_exception_reach_writer(
    source, monkeypatch, tmp_path
):
    _, brief, candidate, page = await captured(source, monkeypatch)
    extraction = semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]})
    assert extraction.fields, extraction.metadata["proposal_diagnostics"]
    value = next(iter(extraction.fields.values()))
    assert all(term in value["conditions"] for term in [DENIAL, PARENT, EXCEPTION])
    assert not any("unrelated option" in term for term in value["evidence_terms"])
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert items and all(item.status == "accepted" for item in items)
    normalized = normalized_fields_from_evidence_items(items)
    assert all(term in str(normalized[0].model_dump()) for term in [DENIAL, PARENT])
    research = ResearchResult(
        brief=brief,
        candidates=[candidate],
        captured_pages=[page],
        extractions=[extraction],
        evidence_items=items,
        normalized_fields=normalized,
    )
    sources = raw_sources_from_research_result(
        brief,
        research,
        batch_sources=[],
        target_source_count=1,
        requires_accepted_evidence=True,
        source_exists=lambda *_: False,
        confidence_for_source=lambda *_: 0.9,
        fallback_snippet=lambda capture: capture.text,
    )
    now = datetime.now(UTC)
    document = DocumentCreate(
        workspace_id="default-workspace",
        title=page.title,
        url=str(page.final_url),
        source_type="webpage_verified",
        competitor=brief.competitor,
        dimension="feature",
        text=page.text,
        fetched_at=now,
        last_verified_at=now,
        metadata=page.metadata,
    )
    async with KnowledgeRepository(str(tmp_path / "canonical.sqlite")) as repository:
        stored = await repository.upsert_document(document, page.content_hash)
        loaded = await repository.get_document(stored.id)
    sources[0].metadata.update(
        kb_document_id=loaded.id,
        kb_document_version=loaded.version,
        kb_document_content_hash=loaded.content_hash,
    )
    detail = RunDetail(
        id=brief.run_id,
        topic=brief.topic,
        status="running",
        execution_mode="real",
        created_at=now,
        updated_at=now,
        raw_sources=sources,
        plan=AnalysisPlan(
            topic=brief.topic,
            competitors=[brief.competitor],
            dimensions=["feature"],
            decision_brief=DecisionBrief(decision_question=QUESTION),
        ),
    )
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={loaded.id: loaded})
    ids = question_fact_ids(detail, snapshot, brief.competitor, "feature")
    view = select_evidence_view(
        snapshot, agent="writer", competitor=brief.competitor, dimension="feature", fact_ids=ids
    )
    facts = [fact for fact in view.facts if fact.field == "evidence_terms"]
    assert facts and facts[0].quote == QUOTE
    terms = json.loads(facts[0].value_json)
    assert all(term in terms for term in [DENIAL, PARENT, EXCEPTION])
    prompt = view.to_prompt_json()
    assert "unrelated option" not in prompt
    assert all(term in prompt for term in [DENIAL, PARENT, "imported records"])
    # Exercise the actual Writer request builder and dispatch observation. The
    # provider boundary is local; no network or model is used in this test.
    from test_writer_question_delivery import service_for

    from packages.llm.doubao_client import LLMUsage
    from packages.llm.execution_budget import current_llm_execution
    from packages.research.question_delivery import _build_question_delivery

    service, record = service_for(detail)
    capsule = _build_question_delivery(detail, brief, research, sources, [])
    service._trace_local_tool(
        record,
        agent="collector",
        subagent="fixture",
        name="clean_research_pipeline",
        input_text="{}",
        output_text=json.dumps({"question_delivery_v1": capsule}),
    )
    sent = []

    async def local_provider(*, system, user):
        current_llm_execution.get().reserve_transport()
        payload = json.loads(user.split("\nJSON:\n", 1)[1])
        if "evidence_view" in payload:
            sent.append(payload)
        return '{"claims":[]}'

    monkeypatch.setattr(service._llm, "complete_text", local_provider)
    monkeypatch.setattr(
        service._llm,
        "consume_last_usage",
        lambda: LLMUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110),
    )
    await service._writer_dimension_report_inner(record)
    assert sent

    def resolve(value, payload):
        if isinstance(value, dict) and set(value) == {"text_ref"}:
            return payload["text_sets"][value["text_ref"]]
        if isinstance(value, dict):
            return {key: resolve(child, payload) for key, child in value.items()}
        if isinstance(value, list):
            return [resolve(child, payload) for child in value]
        return value

    row = next(
        row for row in resolve(sent[0]["evidence_view"]["facts"], sent[0]) if row["quote"] == QUOTE
    )
    assert all(term in row["value"] for term in [DENIAL, PARENT, EXCEPTION])
    assert row["qualifiers"] == {
        key: value for key, value in facts[0].qualifiers.items() if key != "operations"
    }
    dispatched = [
        json.loads(span.full_output)
        for span in detail.trace_spans
        if span.name == "question_delivery_writer_dispatch"
    ]
    assert dispatched and dispatched[0]["status"] == "dispatch_succeeded"
    assert not dispatched[0]["omitted_fact_ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["hash", "offset", "missing", "representation", "format", "html", "html_unknown", "fence"],
)
async def test_escaped_heading_identity_cannot_be_forged_or_relabelled(source, monkeypatch, change):
    _, brief, _, page = await captured(source, monkeypatch)
    assert page.metadata["document_heading_anchors"], "No structural identities to validate"
    if change == "hash":
        page.text += "\nChanged content."
    elif change == "offset":
        page.metadata["document_heading_anchors"][1]["start"] += 1
    elif change == "missing":
        page.metadata["document_heading_anchors"].pop()
    elif change == "representation":
        page.metadata["document_heading_anchors"][1]["representation"] = "markdown"
    elif change == "format":
        page.metadata.pop("document_structure_format")
    elif change in {"html", "html_unknown"}:
        page.metadata.update(
            capture_structure_version=1 if change == "html" else 2, content_root="main"
        )
    else:
        page.text = "```\n" + page.text + "\n```"
        for anchor in page.metadata["document_heading_anchors"]:
            anchor.update(
                start=anchor["start"] + 4,
                end=anchor["end"] + 4,
                content_sha256=hashlib.sha256(page.text.encode()).hexdigest(),
            )
    assert not semantic._heading_resolution(page.text, page)["valid"]
    assert not semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields


@pytest.mark.asyncio
@pytest.mark.parametrize("fence", ["```", r"\`\`\`", "~~~", r"\~\~\~"])
async def test_provider_fenced_pseudo_titles_do_not_become_headings(monkeypatch, fence):
    body = "\\# Visitor collections\n\n" + QUOTE + "\n\n" + fence + "\n\\#\\# Fake title\n" + fence
    result = await provider(monkeypatch, body + "\n\n" + DENIAL)
    assert [a["title"] for a in result.capture_metadata["document_heading_anchors"]] == [
        "Visitor collections"
    ]


@pytest.mark.asyncio
async def test_provider_keeps_previous_html_diagnostics_out_of_current_fact_identity(
    source, monkeypatch
):
    upgraded = await provider(monkeypatch)
    old_quote = "Visitors can export collections without approval."
    old = {
        "kind": "details",
        "element_id": "old",
        "question": "Can visitors export?",
        "quote": old_quote,
        "quote_start": 0,
        "status": "incomplete",
        "reason": "answer_not_captured",
    }
    basic = FetchPageResult(
        url=upgraded.url,
        ok=True,
        title="Example Suite plans",
        text="Old HTML",
        content_hash="old-hash",
        capture_metadata={
            "capture_structure_version": 1,
            "capture_incomplete": True,
            "capture_gaps": ["heading_source_boundary_unbound", "answer_not_captured"],
            "disclosures": [old],
        },
    )
    result = evidence_fetch._retain_capture_gaps(upgraded, basic)
    metadata = result.capture_metadata
    assert metadata.get("previous_capture_diagnostics") == basic.capture_metadata
    assert metadata.get("capture_incomplete") is True
    assert "answer_not_captured" in metadata.get("capture_gaps", [])
    assert "heading_source_boundary_unbound" not in metadata.get("capture_gaps", [])
    assert metadata.get("disclosures", []) == []
    assert "capture_structure_version" not in metadata
    brief, _, page = source(
        result.text, questions=(QUESTION,), headings=metadata["document_headings"]
    )
    page.metadata.update(metadata)
    page.fetch_method = result.fetch_method
    page.status_code = result.status_code
    page.captured_at = result.captured_at
    assert semantic._heading_resolution(page.text, page)["valid"]
    assert semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields
    assert old_quote not in [
        quote.text for quote in extract_structured_evidence(brief, page).quotes
    ]
    assert upgraded.status_code is None and metadata["origin_status"] == "unknown"
    assert metadata["provider_retrieval_receipt"]["provider_api_status"] == 200


@pytest.mark.asyncio
async def test_nested_current_section_keeps_parent_intro_without_sibling_limits(
    source, monkeypatch
):
    parent = "Only invited visitors can access shared collections."
    current = "Editing requires confirmation from the collection owner."
    body = (
        "\\# Guide\n\n"
        + DENIAL
        + "\n\n\\#\\# Collection permissions\n\n"
        + parent
        + "\n\n\\#\\#\\# Edit content\n\n"
        + QUOTE
        + "\n\n"
        + current
        + "\n\n\\#\\#\\# Configure unrelated settings\n\n"
        + "\n\n".join(f"Only administrators can modify unrelated setting {i}." for i in range(7))
    )
    _, brief, _, page = await captured(source, monkeypatch, body)
    result = semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]})
    assert result.fields, result.metadata["proposal_diagnostics"]
    value = next(iter(result.fields.values()))
    assert all(term in value["conditions"] for term in [DENIAL, parent, current])
    assert not any("unrelated setting" in term for term in value["evidence_terms"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denial",
    ["Visitors do not have private collections.", "Visitors don’t have private collections."],
)
async def test_parent_denial_without_exclusivity_is_retained(source, monkeypatch, denial):
    body = BODY.replace(DENIAL, denial)
    _, brief, _, page = await captured(source, monkeypatch, body)
    extraction = semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]})
    assert extraction.fields
    assert denial in next(iter(extraction.fields.values()))["conditions"]


@pytest.mark.asyncio
async def test_provider_missing_previous_complete_answer_remains_a_gap(monkeypatch):
    result = await provider(monkeypatch)
    old = {
        "kind": "details",
        "element_id": "quote-only",
        "question": "How is tax calculated?",
        "status": "complete",
        "quote": "Sales staff must confirm local taxes before providing an exact quote.",
    }
    basic = FetchPageResult(
        url=result.url,
        ok=True,
        title="Example Suite plans",
        text=old["quote"],
        content_hash="old",
        capture_metadata={
            "capture_structure_version": 1,
            "capture_incomplete": True,
            "capture_gaps": ["heading_source_boundary_unbound"],
            "disclosures": [old],
        },
    )
    metadata = evidence_fetch._retain_capture_gaps(result, basic).capture_metadata
    assert metadata["capture_incomplete"] is True
    assert "previous_disclosure_not_captured" in metadata["capture_gaps"]
    assert metadata.get("disclosures", []) == []
    assert metadata["previous_capture_diagnostics"]["disclosures"] == [old]


@pytest.mark.asyncio
async def test_current_section_keeps_invitation_prerequisite_for_later_quote(source, monkeypatch):
    prerequisite = (
        "Visitors have to accept their invitation and be confirmed before content can be shared."
    )
    body = BODY.replace(QUOTE, prerequisite + "\n\n" + QUOTE)
    _, brief, _, page = await captured(source, monkeypatch, body)
    result = semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]})
    assert result.fields
    assert prerequisite in next(iter(result.fields.values()))["conditions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("length,accepted", [(1000, True), (1700, False)])
async def test_parent_conditional_block_uses_existing_complete_rule_budget(
    source, monkeypatch, length, accepted
):
    parent = PARENT + " Complete owner authorization remains required." * (length // 45)
    body = BODY.replace(PARENT, parent)
    _, brief, _, page = await captured(source, monkeypatch, body)
    result = semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]})
    assert bool(result.fields) is accepted
    if accepted:
        assert parent in next(iter(result.fields.values()))["conditions"]
    else:
        assert result.metadata["proposal_diagnostics"][0]["reason"] == "condition_capacity"


@pytest.mark.asyncio
async def test_long_current_section_keeps_earlier_prerequisite(source, monkeypatch):
    prerequisite = "Visitors have to accept their invitation before content can be shared."
    body = (
        "\\# Guide\n\n\\#\\# Shared collections\n\n"
        + prerequisite
        + "\n\n"
        + "This paragraph explains how collaboration works in the collection.\n\n" * 35
        + QUOTE
    )
    _, brief, _, page = await captured(source, monkeypatch, body)
    result = semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]})
    assert result.fields
    assert prerequisite in next(iter(result.fields.values()))["conditions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["document_headings", "document_heading_anchors"])
async def test_declared_provider_format_requires_every_identity_collection(source, monkeypatch, missing):
    _, brief, _, page = await captured(source, monkeypatch)
    page.metadata.pop(missing)
    assert not semantic._heading_resolution(page.text, page)["valid"]
    assert not semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/html/main/h2", None])
async def test_provider_cannot_use_dom_path_to_validate_fenced_plain_text(source, monkeypatch, path):
    body = "\\# Visitor collections\n\n```text\nForged section\n```\n\n" + QUOTE + "\n\n" + DENIAL
    _, brief, _, page = await captured(source, monkeypatch, body)
    title = "Forged section"
    start = body.index(title)
    page.metadata["document_headings"] = [(2, title)]
    page.metadata["document_heading_anchors"] = [
        dict(
            level=2, title=title, start=start, end=start + len(title), occurrence=1,
            content_sha256=hashlib.sha256(body.encode()).hexdigest(),
            representation="markdown", source_path=path,
        )
    ]
    assert not semantic._heading_resolution(body, page)["valid"]
    assert not semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unknown_format", "missing_representation"])
async def test_declared_plain_markdown_provider_cannot_downgrade_identity(source, monkeypatch, change):
    body = "# Visitor collections\n\n" + DENIAL + "\n\n## Edit collection\n\n" + QUOTE
    _, brief, _, page = await captured(source, monkeypatch, body)
    assert semantic._heading_resolution(body, page)["valid"]
    if change == "unknown_format":
        page.metadata["document_structure_format"] = "provider_markdown_v2"
    else:
        page.metadata["document_heading_anchors"][0].pop("representation")
    assert not semantic._heading_resolution(body, page)["valid"]
    assert not semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields


@pytest.mark.asyncio
async def test_legacy_plain_markdown_without_provider_protocol_remains_valid(source, monkeypatch):
    body = "# Visitor collections\n\n" + DENIAL + "\n\n## Edit collection\n\n" + QUOTE
    _, brief, _, page = await captured(source, monkeypatch, body)
    page.metadata.pop("document_structure_format")
    for anchor in page.metadata["document_heading_anchors"]:
        anchor.pop("representation")
    assert semantic._heading_resolution(body, page)["valid"]
    assert semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields


@pytest.mark.asyncio
async def test_price_upgrade_keeps_complete_basic_faq_diagnostic_when_current_answer_is_missing(monkeypatch):
    upgraded = await provider(monkeypatch)
    old = {
        "kind": "details", "element_id": "quote-only", "question": "How is tax calculated?",
        "status": "complete",
        "quote": "Sales staff must confirm local taxes before providing an exact quote.",
    }
    metadata = {
        "capture_structure_version": 1, "content_root": "main", "capture_incomplete": False,
        "capture_gaps": [], "disclosures": [old],
    }

    async def basic(url, **kwargs):
        return FetchPageResult(
            url=url, ok=True, title="Example Suite plans",
            text=old["quote"] + " Additional public documentation." * 6,
            status_code=200, content_hash="old", capture_metadata=metadata,
        )

    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    result = await evidence_fetch.fetch_evidence_page(
        upgraded.url, deepseek_settings=web_settings(), require_price_content=True,
    )
    assert result.fetch_method == "deepseek_web_fetch"
    assert result.capture_metadata["previous_capture_diagnostics"] == metadata
    assert result.capture_metadata["capture_incomplete"] is True
    assert "previous_disclosure_not_captured" in result.capture_metadata["capture_gaps"]
    assert result.capture_metadata.get("disclosures", []) == []
    assert old["quote"] not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [[], {}, ["markdown"], {"value": "escaped_markdown"}])
async def test_non_string_provider_representation_rejects_native_json_replay(source, monkeypatch, value):
    from packages.research.models import CapturedPage

    _, brief, _, original = await captured(source, monkeypatch)
    record = json.loads(original.model_dump_json())
    record["metadata"]["document_heading_anchors"][0]["representation"] = value
    page = CapturedPage.model_validate(record)
    assert not extract_structured_evidence(brief, page).fields
    assert semantic.semantic_body_window(brief, page) == ""
    assert not semantic.semantic_extraction(brief, page, {"facts": [{"quote": QUOTE}]}).fields
