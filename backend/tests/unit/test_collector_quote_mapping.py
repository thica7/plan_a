"""Collector layout recovery must retain the exact captured body through storage."""

import hashlib

import pytest

from packages.research.evidence import admit_evidence_items
from packages.research.evidence.admission import raw_sources_from_research_result
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.extraction import semantic
from packages.research.models import (
    CapturedPage,
    ResearchBrief,
    ResearchQuestion,
    ResearchResult,
    SourceCandidate,
)

# Minimal captured HTML display shape; no local archive dependency.
BODY = (
    "Add an observer to a board\n"
    "Workspaces that subscribe to\n"
    "Trello Premium\n"
    "can add Observers to boards within their\xa0Workspace.\n"
    "Observers are board members that are able to view a board and the cards "
    "within the board,\xa0download card attachments,\xa0comment and vote on cards "
    "(if that is enabled for the board), and export the board.\n"
    "Observers are not able to move or edit cards, upload card attachments, "
    "tick the box on a checklist item, and observers can't change board "
    "settings.\n"
    "Because an observer is a board member permission and not a membership\n"
    "type\n"
    ", a board admin in a Premium Workspace can set both\xa0Workspace\xa0members "
    "and guests as an observer on a board.\n"
    "There are no limits to how many observers you can have on a board, and "
    "an observer can be a billable\xa0Workspace\xa0member, or\n"
    "multi-board guest\n"
    ", or a non-billable single-board guest.\n"
    "To understand if an Observer is billable, check out the page\n"
    "How billing works with Trello Premium and Standard\n"
    ".\n"
    "Add an observer\n"
    "To add someone to your board as an observer, click\n"
    "Share\n"
    "from the top of the board. Enter the member's username or email address."
    " When you choose the person to add, the default choice is to add them as"
    " regular board members, but you can click on the dropdown\xa0to change that"
    " to 'Observer'.\n"
    "You can also generate a sharable link which will add all users who use "
    "it to your board as an Observer. You can learn more about this at\n"
    "Inviting people by using a shareable link\n"
    ".\n"
    "Because an observer is a board member permission it isn't currently "
    "possible to set a user as an observer at the\n"
    "Workspace\n"
    "level, and each observer is set individually per member per board.\n"
    "Change a member's permissions to observer\n"
    "To change a current board member’s permissions to observer, click the\n"
    "Share\n"
    "button from the top of the board, then select the drop-down next to "
    "their name and avatar and select\n"
    "Observer\n"
    ". Please note that only Workspace admins and board admins can change a "
    "board member’s status to observer."
)
QUOTES = [
    (
        "Observers are board members that are able to view a board and the cards "
        "within the board, download card attachments, comment and vote on cards "
        "(if that is enabled for the board), and export the board."
    ),
    (
        "Observers are not able to move or edit cards, upload card attachments, "
        "tick the box on a checklist item, and observers can't change board "
        "settings."
    ),
    (
        "Because an observer is a board member permission and not a membership "
        "type, a board admin in a Premium Workspace can set both Workspace "
        "members and guests as an observer on a board."
    ),
    (
        "There are no limits to how many observers you can have on a board, and "
        "an observer can be a billable Workspace member, or multi-board guest, or"
        " a non-billable single-board guest."
    ),
    (
        "Because an observer is a board member permission it isn't currently "
        "possible to set a user as an observer at the Workspace level, and each "
        "observer is set individually per member per board."
    ),
    (
        "To change a current board member’s permissions to observer, click the "
        "Share button from the top of the board, then select the drop-down next "
        "to their name and avatar and select Observer. Please note that only "
        "Workspace admins and board admins can change a board member’s status to "
        "observer."
    ),
]


def trello_source():
    url = "https://support.atlassian.com/trello/docs/adding-observers-to-boards/"
    brief = ResearchBrief(
        run_id="collector-layout",
        topic="Observer permissions and billing",
        competitor="Trello",
        dimension="feature",
        product_category="documents",
        questions=[
            ResearchQuestion(question_id="q1", question="Can Observers vote, export and edit?"),
            ResearchQuestion(
                question_id="q2", question="Who can assign the role and is it billable?"
            ),
        ],
    )
    candidate = SourceCandidate(
        title="Add an observer to a board | Trello | Atlassian Support",
        url=url,
        origin="manual",
        competitor="Trello",
        dimension="feature",
    )
    page = CapturedPage(
        candidate_id=candidate.id,
        requested_url=url,
        final_url=url,
        title=candidate.title,
        text=BODY,
        markdown=BODY,
        status="ok",
        status_code=200,
        quality_score=0.9,
        content_hash=hashlib.sha256(BODY.encode()).hexdigest()[:16],
        source_material_level="full_source",
        fetch_method="basic_httpx",
        metadata={
            "document_headings": [
                (1, "Add an observer to a board"),
                (2, "Add an observer"),
                (2, "Change a member's permissions to observer"),
            ]
        },
    )
    from packages.research.capture.official import verify_registered_capture

    page.metadata["official_source_verification"] = verify_registered_capture("Trello", page)
    return brief, candidate, page


def admitted(brief, candidate, page, quotes):
    extraction = semantic.semantic_extraction(
        brief, page, {"facts": [{"quote": q} for q in quotes]}
    )
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    return extraction, items


def test_html_display_layout_recovers_six_complete_original_quotes_and_admits_them():
    brief, candidate, page = trello_source()
    extraction, items = admitted(brief, candidate, page, QUOTES)
    assert len(extraction.quotes) == len(items) == 6
    assert all(item.status == "accepted" for item in items)
    for original, quote, diagnostic in zip(
        QUOTES, extraction.quotes, extraction.metadata["proposal_diagnostics"], strict=True
    ):
        assert quote.text == page.text[quote.start_offset : quote.end_offset]
        assert diagnostic["original_quote"] == original
        assert diagnostic["quote_anchor"]["quote"] == quote.text
        assert diagnostic["verified_field_ids"] == [quote.field]
    assert extraction.quotes[0].text != QUOTES[0]
    assert "\ntype\n," in extraction.quotes[2].text
    assert "Observer\n. Please note that only" in extraction.quotes[5].text
    # The introductory subscription condition remains source text in every affected rule.
    assert any(
        "Trello Premium" in term
        for value in extraction.fields.values()
        for term in value["evidence_terms"]
    )


@pytest.mark.asyncio
async def test_recovered_quotes_reach_real_rawsource_sqlite_and_snapshot(tmp_path, monkeypatch):
    from test_agent_evidence_alignment import InputReplay

    from packages.knowledge.repository import KnowledgeRepository
    from packages.research.evidence.snapshot import seal_snapshot

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "canonical.sqlite"))
    monkeypatch.setenv("KB_RETRIEVAL_MODE", "sparse")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "none")
    brief, candidate, page = trello_source()
    extraction, items = admitted(brief, candidate, page, QUOTES)
    assert len(items) == 6 and all(item.status == "accepted" for item in items)
    research = ResearchResult(
        brief=brief,
        candidates=[candidate],
        captured_pages=[page],
        extractions=[extraction],
        evidence_items=items,
        normalized_fields=normalized_fields_from_evidence_items(items),
    )
    sources = raw_sources_from_research_result(
        brief,
        research,
        batch_sources=[],
        target_source_count=1,
        requires_accepted_evidence=True,
        source_exists=lambda *_: False,
        confidence_for_source=lambda *_: 0.8,
        fallback_snippet=lambda capture: capture.text,
    )
    assert len(sources) == 1
    service = InputReplay(tmp_path)
    detail = service.record.detail
    detail.raw_sources = sources
    detail.plan.competitors, detail.plan.dimensions = ["Trello"], ["feature"]
    await service._persist_captured_sources_to_kb(service.record, detail, sources, research)
    assert sources[0].metadata["kb_full_source_ingest_status"] == "stored"
    async with KnowledgeRepository() as repo:
        document = await repo.get_document(sources[0].metadata["kb_document_id"])
    assert document.text == BODY
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={document.id: document})
    stored = {fact.quote for fact in snapshot.facts if fact.field == "evidence_terms"}
    assert {quote.text for quote in extraction.quotes} <= stored


@pytest.mark.parametrize("mutation", ["word", "negation", "number", "role", "punctuation"])
def test_layout_recovery_never_changes_substantive_characters(mutation):
    brief, candidate, page = trello_source()
    replacements = {
        "word": ("download", "upload"),
        "negation": ("not able", "able"),
        "number": ("a board", "2 boards"),
        "role": ("Observers", "Admins"),
        "punctuation": (", comment and vote", "; comment and vote"),
    }
    index = 1 if mutation == "negation" else 0
    before, after = replacements[mutation]
    forged = QUOTES[index].replace(before, after)
    extraction, items = admitted(brief, candidate, page, [forged])
    assert not extraction.quotes and not items
    assert extraction.metadata["proposal_diagnostics"][0]["reason"] == "not_original"


@pytest.mark.parametrize(
    "raw,proposal",
    [
        ("Members can not edit shared pages.", "Members cannot edit shared pages."),
        ("Members can edit a b document.", "Members can edit ab document."),
        ("Members can edit 1\n.5 shared pages.", "Members can edit 1.5 shared pages."),
        ("Members can edit 1\n,000 shared pages.", "Members can edit 1,000 shared pages."),
        ("Members can edit pages until 2026-\n10-25.", "Members can edit pages until 2026-10-25."),
        ("Members can edit project_\nalpha pages.", "Members can edit project_alpha pages."),
        (
            "Members can edit shared pages.\nGuests cannot edit shared pages.",
            "Members can edit shared pages. Guests cannot edit shared pages.",
        ),
        ("Members can edit\n\nshared pages.", "Members can edit shared pages."),
        ("Only Premium members can edit\nshared pages.", "Members can edit shared pages."),
    ],
)
def test_layout_recovery_keeps_word_numeric_and_original_block_boundaries(raw, proposal):
    from test_semantic_extraction import fixture

    brief, candidate, page = fixture(raw)
    extraction, items = admitted(brief, candidate, page, [proposal])
    assert not extraction.quotes and not items


@pytest.mark.parametrize("change", ["duplicate", "heading", "window", "incomplete", "code", "html"])
def test_layout_recovery_requires_unique_complete_prose_in_the_actual_window(change, monkeypatch):
    from test_semantic_extraction import fixture

    raw = "Members can edit\nshared pages on all plans."
    proposal = "Members can edit shared pages on all plans."
    if change == "duplicate":
        raw += "\n\n" + raw
    elif change == "incomplete":
        raw = "Only Premium members can edit\nshared pages on all plans."
    elif change == "code":
        raw = "```\n" + raw + "\n```"
    elif change == "html":
        raw = "<div>\n" + raw + "\n</div>"
    brief, candidate, page = fixture(raw)
    if change == "heading":
        page.metadata["document_headings"] = [(2, "shared pages on all plans.")]
    elif change == "window":
        monkeypatch.setattr(semantic, "_semantic_window", lambda *_: (0, raw.splitlines()[0]))
    page.metadata["safe_quote_mapping"] = True  # Untrusted metadata grants nothing.
    extraction, items = admitted(brief, candidate, page, [proposal])
    assert not extraction.quotes and not items


@pytest.mark.parametrize("mutation", ["quote", "offset", "value", "body"])
def test_recovered_quote_admission_independently_rechecks_original_source(mutation):
    brief, candidate, page = trello_source()
    extraction, _ = admitted(brief, candidate, page, [QUOTES[0]])
    assert extraction.quotes
    if mutation == "quote":
        extraction.quotes[0].text = QUOTES[0]
    elif mutation == "offset":
        extraction.quotes[0].start_offset += 1
    elif mutation == "value":
        next(iter(extraction.fields.values()))["conditions"] = ["Available to everyone."]
    else:
        page.text = page.text.replace("download", "upload")
        page.markdown = page.text
    extraction.metadata["source_mapping_verified"] = True
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert items and all(item.status == "rejected" for item in items)


def versioned_delivery_fixture(monkeypatch, *, legacy):
    """Reproduce a v1 receipt with a rejected layout proposal and an accepted quote."""
    import json
    from types import SimpleNamespace

    from packages.knowledge.models import KnowledgeDocument
    from packages.research.models import ExtractionResult
    from packages.research.question_delivery import _build_question_delivery

    brief, candidate, page = trello_source()
    payload = {"facts": [{"quote": q} for q in QUOTES]}
    if legacy:
        # The previous implementation had no display recovery. Retain that
        # original recipe, including its five rejected proposals and v1 ID.
        with monkeypatch.context() as old:
            old.setattr(semantic, "_restore_display_quote", lambda _b, _w, quote, _p: quote)
            extraction = semantic.semantic_extraction(brief, page, payload)
        extraction.extractor_version = "question-focus-v1:" + semantic.semantic_focus_signature(
            brief, page
        )
        rebuilt = ExtractionResult.model_validate({**extraction.model_dump(), "id": ""})
        diagnostics = extraction.metadata["proposal_diagnostics"]
        fingerprint = hashlib.sha256(
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:12]
        extraction.id = rebuilt.id + "-" + fingerprint
    else:
        extraction = semantic.semantic_extraction(brief, page, payload)
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert len(items) == (1 if legacy else 6)
    assert all(item.status == "accepted" for item in items)
    research = ResearchResult(
        brief=brief,
        candidates=[candidate],
        captured_pages=[page],
        extractions=[extraction],
        evidence_items=items,
        normalized_fields=normalized_fields_from_evidence_items(items),
    )
    sources = raw_sources_from_research_result(
        brief,
        research,
        batch_sources=[],
        target_source_count=1,
        requires_accepted_evidence=True,
        source_exists=lambda *_: False,
        confidence_for_source=lambda *_: 0.8,
        fallback_snippet=lambda capture: capture.text,
    )
    document = KnowledgeDocument(
        id="layout-replay-document",
        source_type="webpage_verified",
        title=page.title,
        url=page.final_url,
        text=page.text,
        content_hash=hashlib.sha256(page.text.encode()).hexdigest()[:16],
        fetched_at=page.captured_at,
        workspace_id="layout-workspace",
        project_id="layout-project",
        competitor=brief.competitor,
        dimension=brief.dimension,
        metadata=dict(sources[0].metadata),
    )
    sources[0].metadata.update(
        kb_document_id=document.id,
        kb_document_version=document.version,
        kb_document_content_hash=document.content_hash,
    )
    detail = SimpleNamespace(
        id=brief.run_id,
        workspace_id=document.workspace_id,
        project_id=document.project_id,
        topic=brief.topic,
        raw_sources=sources,
        trace_spans=[],
        plan=SimpleNamespace(competitors=[brief.competitor], dimensions=[brief.dimension]),
    )
    capsule = _build_question_delivery(detail, brief, research, sources, [])
    return detail, brief, capsule, document


@pytest.mark.parametrize("legacy", [True, False])
def test_receipt_replay_retains_the_server_extraction_mapping_version(monkeypatch, legacy):
    from packages.research.question_delivery import _replay_question_delivery

    detail, brief, capsule, document = versioned_delivery_fixture(monkeypatch, legacy=legacy)
    recipe = capsule["recipes"][0]
    if not legacy:
        assert recipe["extractor_version"].startswith("question-focus-v3:")
    replay = _replay_question_delivery(
        detail, capsule, {document.id: document}, authorized_brief=brief
    )
    assert replay["verified_item_ids"] == [item["id"] for item in capsule["items"]]
    assert all(not row["reasons"] for row in replay["item_results"])
    assert len(replay["verified_item_ids"]) == (1 if legacy else 6)


def test_metadata_cannot_downgrade_mapping_or_grant_an_unknown_version():
    brief, candidate, page = trello_source()
    page.metadata["extractor_version"] = "question-focus-v1"
    extraction, items = admitted(brief, candidate, page, [QUOTES[0]])
    assert extraction.extractor_version.startswith("question-focus-v3:")
    assert items and all(item.status == "accepted" for item in items)
    extraction.metadata["extractor_version"] = extraction.extractor_version
    extraction.extractor_version = "unsupported-mapping:" + semantic.semantic_focus_signature(
        brief, page
    )
    rejected = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert rejected and all(item.status == "rejected" for item in rejected)


def test_legacy_mapping_keeps_existing_markdown_recovery():
    from test_semantic_extraction import fixture

    raw = r"Members can edit shared documents\."
    brief, candidate, page = fixture(raw)
    page.metadata.update(
        document_structure_format="provider_markdown_v1",
        document_headings=[],
        document_heading_anchors=[],
    )
    version = "question-focus-v1:" + semantic.semantic_focus_signature(brief, page)
    extraction = semantic.semantic_extraction(
        brief,
        page,
        {"facts": [{"quote": "Members can edit shared documents."}]},
        extractor_version=version,
    )
    assert extraction.extractor_version == version
    assert extraction.quotes[0].text == raw
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert items and all(item.status == "accepted" for item in items)
