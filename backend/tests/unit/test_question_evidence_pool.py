"""A ranking shortlist is never the complete set of accepted question originals."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from test_question_retrieval import replace_snapshot, research_case
from test_writer_question_delivery import service_for

from packages.agents.writer import question_retrieval
from packages.orchestrator import question_packets
from packages.research.evidence.snapshot_models import EvidenceConflict


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    monkeypatch.setattr(question_retrieval, "get_local_provider_from_env", lambda kind: None)


def originals(snapshot):
    return tuple(f for f in snapshot.facts if f.field == "evidence_terms")


def pool(packet):
    value = packet["retrieval"].get("evidence_pool")
    assert value is not None, "Question retrieval must retain accepted originals beyond top three."
    assert value["version"] == 1
    return value


async def packets_for(
    quotes, *, question="Example Product: What are visitor board and workspace restrictions?"
):
    detail, snapshot = research_case(quotes, question=question)
    packets = await question_packets.prepare_packets(detail, snapshot, "Example Product", "feature")
    return detail, snapshot, packets


@pytest.mark.asyncio
async def test_low_ranked_rule_retains_original_identity_rank_and_omission_reason():
    lower = (
        "An observer is assigned individually to each board; workspace assignment is unavailable."
    )
    detail, snapshot, packets = await packets_for(
        [
            *(
                f"Visitor board workspace restrictions are described in section {i}."
                for i in range(5)
            ),
            lower,
        ]
    )
    packet = packets[0]
    target = next(f for f in originals(snapshot) if f.quote == lower)
    assert target.id not in packet["selected_fact_ids"]
    evidence_pool = pool(packet)
    assert packet["version"] == 2
    assert set(evidence_pool["fact_ids"]) == {f.id for f in originals(snapshot)}
    candidate = next(
        c for c in evidence_pool["questions"][0]["candidates"] if c["fact_id"] == target.id
    )
    assert candidate["rank"] > 3
    assert candidate["source_id"] == target.source_id
    assert candidate["original_sha256"]
    assert candidate["default_view_omission_reason"] == "priority_cutoff"
    available = question_packets.question_pool_facts(
        detail, snapshot, packet, packet["questions"][0]["question_id"]
    )
    assert target in available and available[-1].quote == lower


@pytest.mark.asyncio
async def test_compound_request_pool_has_all_branches_and_full_question():
    question = (
        "Example Product: Can visitors read, comment, export, share "
        "and manage access across boards?"
    )
    quotes = [
        f"Visitors can {action} across boards only after signing in."
        for action in ("read", "comment", "export", "share", "manage access")
    ]
    detail, snapshot, packets = await packets_for(quotes, question=question)
    row = pool(packets[0])["questions"][0]
    assert row["question"] == question
    assert len(row["candidates"]) == 5
    assert {
        f.quote
        for f in question_packets.question_pool_facts(
            detail, snapshot, packets[0], row["question_id"]
        )
    } == set(quotes)


@pytest.mark.asyncio
async def test_each_question_keeps_the_full_pool_without_spending_another_questions_quota():
    questions = "\n".join(
        f"Example Product: What visitor restrictions apply to workflow {i}?" for i in range(4)
    )
    detail, snapshot, packets = await packets_for(
        [f"Visitors follow restrictions for workflow {i}." for i in range(12)], question=questions
    )
    evidence_pool = pool(packets[0])
    assert len(evidence_pool["questions"]) == 4
    expected = {f.id for f in originals(snapshot)}
    assert all(
        {c["fact_id"] for c in q["candidates"]} == expected for q in evidence_pool["questions"]
    )
    assert all(q["selected_fact_ids"] for q in packets[0]["retrieval"]["questions"])
    assert len(packets[0]["selected_fact_ids"]) <= 8


@pytest.mark.asyncio
async def test_duplicate_originals_keep_both_source_identities_in_pool():
    detail, snapshot = research_case(
        ["Visitors can read boards only after signing in."] * 2,
        question="Example Product: Can visitors read boards after signing in?",
    )
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=tuple(
            fact.model_copy(update={"qualifiers_json": '{"slot":"same"}'})
            for fact in originals(snapshot)
        ),
    )
    packets = await question_packets.prepare_packets(detail, snapshot, "Example Product", "feature")
    evidence_pool = pool(packets[0])
    assert len(evidence_pool["fact_ids"]) == 2
    assert len(packets[0]["selected_fact_ids"]) == 1
    candidates = evidence_pool["questions"][0]["candidates"]
    assert len({c["source_id"] for c in candidates}) == 2
    assert any(c["default_view_omission_reason"] == "equivalent_original" for c in candidates)


@pytest.mark.asyncio
async def test_pool_filters_foreign_stale_conflicting_and_unaccepted_originals():
    detail, snapshot = research_case([f"Visitor board restriction {i}." for i in range(7)])
    facts = originals(snapshot)
    sources = {s.id: s for s in snapshot.sources}
    sources[facts[1].source_id] = sources[facts[1].source_id].model_copy(
        update={"document_workspace_id": "another-workspace"}
    )
    sources[facts[2].source_id] = sources[facts[2].source_id].model_copy(
        update={"document_project_id": "another-project"}
    )
    sources[facts[3].source_id] = sources[facts[3].source_id].model_copy(
        update={"last_verified_at": datetime.now(UTC) - timedelta(days=60)}
    )
    conflict = EvidenceConflict(
        id="conflict",
        competitor="Example Product",
        dimension="feature",
        field="evidence_terms",
        fact_ids=(facts[4].id,),
        source_ids=(facts[4].source_id,),
    )
    snapshot = replace_snapshot(
        detail,
        snapshot,
        sources=tuple(sources.values()),
        conflicts=(conflict,),
        facts=(*facts[:5], facts[5].model_copy(update={"status": "signal"}), facts[6]),
    )
    packets = await question_packets.prepare_packets(detail, snapshot, "Example Product", "feature")
    assert set(pool(packets[0])["fact_ids"]) == {facts[0].id, facts[6].id}
    detail.workspace_id = "foreign"
    with pytest.raises(ValueError, match="scope|identity"):
        question_packets.question_pool_facts(
            detail, snapshot, packets[0], packets[0]["questions"][0]["question_id"]
        )


@pytest.mark.asyncio
async def test_writer_can_reselect_all_pool_originals_using_current_evidence_use():
    quotes = [f"Visitors can inspect board restriction {i}." for i in range(6)]
    detail, snapshot, packets = await packets_for(quotes)
    service, record = service_for(detail)
    packet = packets[0]
    view, use, selected = await service._begin_question_pool_evidence_use(
        record, packet=packet, question_id=packet["questions"][0]["question_id"]
    )
    expected = {f.id for f in originals(snapshot)}
    assert expected <= set(view.fact_ids)
    assert set(use.requested_fact_ids) == expected
    service._validate_evidence_use(record, use)
    prompt = service._question_packet_prompt(record, selected, view.facts)[0]["questions"][0]
    assert set(prompt["fact_ids"]) == expected
    assert prompt["pool_deferred_fact_count"] == 0
    assert prompt["pool_status"] == "available_in_view"
    assert pool(selected[0]) == pool(packet)


@pytest.mark.asyncio
async def test_pool_selection_adds_complete_exception_closure_and_reports_capacity():
    exception = (
        "If members leave a folder, they can keep a copy of its contents. "
        "The copy will no longer sync with the shared folder."
    )
    enormous = "Visitors can read board content. " + "Complete original condition. " * 2000
    detail, snapshot, packets = await packets_for(
        [enormous, exception],
        question="Example Product: If visitors leave a folder, can they still read a copy?",
    )
    packet = packets[0]
    evidence_pool = pool(packet)
    exception_id = next(f.id for f in originals(snapshot) if f.quote == exception)
    large_id = next(f.id for f in originals(snapshot) if f.quote == enormous)
    assert exception_id in evidence_pool["questions"][0]["required_exception_fact_ids"]
    service, record = service_for(detail)
    view, use, selected = await service._begin_question_pool_evidence_use(
        record,
        packet=packet,
        question_id=packet["questions"][0]["question_id"],
        fact_ids=[large_id],
    )
    assert set(use.requested_fact_ids) == {exception_id, large_id}
    assert large_id not in view.fact_ids
    assert exception_id in view.fact_ids
    assert len(view.to_prompt_json().encode()) <= use.max_bytes <= 32768
    prompt = service._question_packet_prompt(record, selected, view.facts)[0]["questions"][0]
    assert prompt["pool_status"] == "deferred_context_budget"
    assert prompt["pool_deferred_fact_count"] == 1
    assert enormous not in view.to_prompt_json()
    service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_rehashed_pool_cannot_authorize_fact_outside_the_current_accepted_scope():
    detail, snapshot, packets = await packets_for(["Visitors can read boards."])
    packet = copy.deepcopy(packets[0])
    evidence_pool = pool(packet)
    evidence_pool["fact_ids"].append("foreign-fact")
    packet["packet_id"] = question_packets.packet_id(packet)
    with pytest.raises(ValueError, match="pool|original|scope"):
        question_packets.question_pool_facts(
            detail, snapshot, packet, packet["questions"][0]["question_id"]
        )
    service, record = service_for(detail)
    with pytest.raises(ValueError, match="pool|original|scope"):
        await service._begin_question_pool_evidence_use(
            record,
            packet=packets[0],
            question_id=packets[0]["questions"][0]["question_id"],
            fact_ids=["foreign-fact"],
        )


@pytest.mark.asyncio
async def test_legacy_packet_and_receipt_replay_still_use_the_legacy_selection():
    detail, snapshot, packets = await packets_for(["Visitors can read boards."])
    packet = copy.deepcopy(packets[0])
    packet.pop("version", None)
    packet["retrieval"].pop("evidence_pool", None)
    packet["packet_id"] = question_packets.packet_id(packet)
    question_packets.validate_packets(detail, snapshot, [packet])
    service, record = service_for(detail)
    view, use = service._begin_evidence_use(
        record,
        agent="writer",
        competitor="Example Product",
        dimension="feature",
        fact_ids=packet["selected_fact_ids"],
    )
    receipt = question_packets.selection_receipt(detail, [packet], use.requested_fact_ids)
    assert receipt["version"] == 1
    use = use.model_copy(
        update={"id": "question-" + use.id + "-" + question_packets.receipt_hash(receipt)}
    )
    question_packets.validate_selection_receipt(detail, snapshot, receipt, use)
    assert set(packet["selected_fact_ids"]) <= set(view.fact_ids)


@pytest.mark.asyncio
async def test_scope_pool_uses_one_credential_with_round_robin_ranking_beyond_model_window(
    monkeypatch,
):
    monkeypatch.setattr(question_retrieval, "CANDIDATE_LIMIT", 4)
    questions = (
        "Example Product: What visitor restrictions apply to board alpha?\n"
        "Example Product: What visitor restrictions apply to board beta?"
    )
    detail, snapshot, packets = await packets_for(
        [
            *(f"Visitor restrictions apply to board alpha section {i}." for i in range(4)),
            "Visitor restrictions apply to board beta.",
            "Each observer is assigned separately per board; a workspace observer is unavailable.",
        ],
        question=questions,
    )
    packet = packets[0]
    evidence_pool = pool(packet)
    assert packet["retrieval"]["candidate_count"] == 4
    assert len(evidence_pool["fact_ids"]) == 6
    assert any(not row["in_ranking_window"] for row in evidence_pool["questions"][0]["candidates"])
    service, record = service_for(detail)
    view, use, selected = await service._begin_question_pool_evidence_use(record, packet=packet)
    assert len(selected[0]["pool_selection"]["question_ids"]) == 2
    assert set(evidence_pool["fact_ids"]) <= set(view.fact_ids)
    assert len(detail.evidence_consumptions) == 1
    assert tuple(use.requested_fact_ids) == tuple(
        f.id for f in question_packets.question_pool_facts(detail, snapshot, packet)
    )
    service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_pool_use_replay_rejects_modified_persisted_pool():
    import json

    from packages.research.evidence.snapshot_models import canonical_json

    detail, _, packets = await packets_for(["Visitors can read boards."])
    service, record = service_for(detail)
    _, use, _ = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    span = next(span for span in detail.trace_spans if span.name == "question_evidence_selection")
    data = json.loads(span.full_output)
    data["packets"][0]["retrieval"]["evidence_pool"]["fact_ids"].append("forged-original")
    span.full_output = canonical_json(data)
    with pytest.raises(ValueError, match="pool|packet|original"):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_large_compound_pool_reserves_each_requested_branch_before_repeated_background():
    question = (
        "Example Product: Can visitors read and comment on board documents, "
        "download, export and vote?"
    )
    branches = [
        "Guests can download a file.",
        "Guests can export a file.",
        "Guests can vote on a card.",
        "Visitors can comment on board documents.",
    ]
    detail, snapshot, packets = await packets_for(
        [
            *(f"Visitors can read board documents in section {i}." for i in range(10)),
            *branches,
        ],
        question=question,
    )
    available = question_packets.question_pool_facts(detail, snapshot, packets[0])
    assert set(branches) <= {fact.quote for fact in available[:5]}
    assert len(available) == 14


@pytest.mark.asyncio
async def test_prompt_metadata_tracks_the_bounded_view_without_copying_the_complete_pool(
    monkeypatch,
):
    from packages.orchestrator import evidence_context
    from packages.research.evidence.snapshot_models import canonical_json

    monkeypatch.setitem(evidence_context._DEPTH_BYTES, "quick", 1600)
    detail, snapshot, packets = await packets_for(
        [f"Visitor board workspace restrictions apply in section {i}." for i in range(40)]
    )
    service, record = service_for(detail)
    view, use, selected = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    prompt = question_packets.prompt_packets(selected, snapshot, view.facts)
    row = prompt[0]["questions"][0]
    assert row["pool_available_fact_count"] == 40
    assert row["pool_deferred_fact_count"] > 0
    assert set(row["fact_ids"]) <= set(view.fact_ids)
    assert len(row["fact_ids"]) < 40
    assert "candidates" not in canonical_json(prompt)
    assert use.view_max_bytes < use.max_bytes
    assert len(canonical_json(prompt).encode()) + view.estimated_bytes <= use.max_bytes


@pytest.mark.asyncio
async def test_pool_larger_than_eight_keeps_the_existing_writer_allowance_without_changing_legacy():
    lower = (
        "Observers are assigned individually per member per board. "
        "Workspace observer assignment is unavailable."
    )
    quotes = [
        f"Visitor board workspace restrictions for section {i}. "
        + "Complete documented condition. " * 8
        for i in range(11)
    ] + [lower]
    detail, snapshot, packets = await packets_for(quotes)
    detail.plan.research_depth = None
    service, record = service_for(detail)
    eligible_ids = packets[0]["retrieval"]["evidence_pool"]["fact_ids"]
    _, legacy_use = service._begin_evidence_use(
        record,
        agent="writer",
        competitor="Example Product",
        dimension="feature",
        fact_ids=eligible_ids,
    )
    view, use, selected = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    assert legacy_use.max_bytes == 16384
    assert use.max_bytes == 32768
    target = next(fact for fact in originals(snapshot) if fact.quote == lower)
    assert target.id in view.fact_ids
    assert any(fact == target for fact in view.facts)
    assert len(view.to_prompt_json().encode()) <= use.view_max_bytes < use.max_bytes
    service._validate_evidence_use(record, use)
    assert selected[0]["pool_selection"]["requested_fact_ids"] == list(use.requested_fact_ids)


@pytest.mark.asyncio
async def test_pool_larger_than_eight_still_defers_whole_originals_beyond_existing_writer_cap():
    enormous = "Visitor board workspace restrictions. " + "Complete condition. " * 2200
    detail, snapshot, packets = await packets_for(
        [
            *(f"Visitor board workspace restrictions for section {i}." for i in range(11)),
            enormous,
        ]
    )
    detail.plan.research_depth = None
    service, record = service_for(detail)
    view, use, selected = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    target = next(fact for fact in originals(snapshot) if fact.quote == enormous)
    assert use.max_bytes == 32768
    assert len(use.requested_fact_ids) == 12
    assert target.id not in view.fact_ids
    assert enormous not in view.to_prompt_json()
    prompt = question_packets.prompt_packets(selected, snapshot, view.facts)[0]["questions"][0]
    assert prompt["pool_status"] == "deferred_context_budget"
    assert prompt["pool_deferred_fact_count"] > 0
    assert view.estimated_bytes <= use.view_max_bytes <= 32768
    service._validate_evidence_use(record, use)
