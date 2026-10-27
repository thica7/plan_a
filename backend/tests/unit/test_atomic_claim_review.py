"""Selected-support isolation and authenticated atomic review protocol checks."""

import json

import pytest
from claim_review_fixture import supported_review
from test_question_atomic_delivery import atomic_case, execute


@pytest.mark.asyncio
async def test_actual_review_isolates_one_claim_and_only_upstream_identities(monkeypatch):
    from test_writer_artifact_consumption import record_upstream

    case = await atomic_case()
    record_upstream(case[0], case[1])
    result, seen = await execute(case, monkeypatch)
    batches = seen["dimension_question_atomic_review"]
    assert len(batches) == 3
    for payload in batches:
        assert len(payload["claims"]) == 1
        assert payload["review_projection_version"] == 3
        assert (
            not {"upstream_analysis", "comparison_assessment", "reflection_constraints"}
            & payload.keys()
        )
        assert set(payload["upstream_identity_refs"]) == {
            "upstream_analysis",
            "comparison_assessment",
            "reflection_constraints",
        }
        assert all("content" not in ref for ref in payload["upstream_identity_refs"].values())
    assert result["compact"]["review_projection_version"] == 3
    receipt = next(
        json.loads(s.full_output)
        for s in case[1].detail.trace_spans
        if s.name == "question_atomic_delivery"
    )
    assert receipt["review_projection_version"] == 3


@pytest.mark.asyncio
async def test_supported_review_without_selected_support_witness_is_not_accepted(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    case = await atomic_case(["Guests have no personal area."])
    result, _ = await execute(case, monkeypatch)
    claim = result["claims"][0]
    row = supported_review({**claim.model_dump(mode="json"), "required_checks": []})
    assert parse_atomic_reviews(json.dumps(dict(reviews=[row])), [claim]) == []


@pytest.mark.parametrize(
    "witness,selected,valid",
    [
        (
            {"support_index": 0, "quote": "download attachments"},
            ["Observers cannot edit cards or upload attachments."],
            False,
        ),
        ({"support_index": True, "quote": "download"}, ["may download"], False),
        ({"support_index": -1, "quote": "download"}, ["may download"], False),
        ({"support_index": 1, "quote": "download"}, ["may download"], False),
        ({"support_index": 0.0, "quote": "download"}, ["may download"], False),
        ({"support_index": 0, "quote": ""}, ["may download"], False),
        ({"support_index": 0, "quote": " "}, ["may download"], False),
        ({"support_index": 0, "quote": "may  download"}, ["may download"], False),
        ({"support_index": 0, "quote": "MAY DOWNLOAD"}, ["may download"], False),
        (
            {"support_index": 0, "quote": "download attachments"},
            ["Observers may download attachments after approval and sign-in unless locked."],
            True,
        ),
        ({"support_index": 0, "quote": "download", "extra": "ignored"}, ["may download"], False),
    ],
)
def test_witness_is_exact_nonempty_and_bound_to_selected_index(witness, selected, valid):
    from packages.agents.writer.atomic_claim_review import selected_support_witness_valid

    assert selected_support_witness_valid(witness, selected) is valid


def selected_payload(quotes):
    return {
        "review_projection_version": 2,
        "claims": [
            {
                "id": "download",
                "text": "Observers may download attachments.",
                "required_checks": [],
                "support_quotes": quotes,
            }
        ],
        "request_context": {"parents": [{"text": "Observers can download the requested file."}]},
    }


@pytest.mark.parametrize(
    "witnesses",
    [
        None,
        [],
        [{"support_index": 0, "quote": "download attachments"}],
        [{"support_index": True, "quote": "upload"}],
        [{"support_index": 4, "quote": "upload"}],
        [{"support_index": 0, "quote": ""}],
        [{"support_index": 0, "quote": "Observers can download the requested file."}],
    ],
)
def test_positive_review_cannot_use_same_page_sibling_parent_or_missing_witness(witnesses):
    from types import SimpleNamespace

    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    payload = selected_payload(["Observers cannot edit cards or upload attachments."])
    row = supported_review(payload["claims"][0])
    if witnesses is not None:
        row["support_witnesses"] = witnesses
    assert (
        parse_atomic_reviews(
            json.dumps({"reviews": [row]}), [SimpleNamespace(id="download")], payload=payload
        )
        == []
    )


@pytest.mark.parametrize("verdict", ["supported", "unsupported", "uncertain"])
def test_conditioned_support_keeps_full_input_and_witness_only_extends_new_parser(verdict):
    from types import SimpleNamespace

    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    full = "Observers may download attachments after approval and sign-in unless locked."
    payload = selected_payload([full])
    row = supported_review(payload["claims"][0])
    row["verdict"] = verdict
    if verdict == "supported":
        row["support_witnesses"] = [{"support_index": 0, "quote": "download attachments"}]
    parsed = parse_atomic_reviews(
        json.dumps({"reviews": [row]}), [SimpleNamespace(id="download")], payload=payload
    )
    assert len(parsed) == 1 and parsed[0].verdict == verdict
    assert payload["claims"][0]["support_quotes"] == [full]


def test_every_selected_support_has_a_witness():
    from types import SimpleNamespace

    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    payload = selected_payload(
        ["Guests may export after approval.", "Export is blocked when locked."]
    )
    row = supported_review(payload["claims"][0])
    row["support_witnesses"] = [{"support_index": 0, "quote": "export after approval"}]
    assert (
        parse_atomic_reviews(
            json.dumps({"reviews": [row]}), [SimpleNamespace(id="download")], payload=payload
        )
        == []
    )
    row["support_witnesses"].append({"support_index": 1, "quote": "blocked when locked"})
    assert (
        len(
            parse_atomic_reviews(
                json.dumps({"reviews": [row]}), [SimpleNamespace(id="download")], payload=payload
            )
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["delete", "downgrade", "bool", "unknown", "system", "hash", "identity"]
)
async def test_review_receipt_version_system_and_hash_tampering_are_rejected(monkeypatch, change):
    from packages.agents.writer import question_atomic_delivery as atomic

    case = await atomic_case()
    service, record, snapshot, _, view, use, *_ = case
    from test_writer_artifact_consumption import record_upstream

    record_upstream(service, record)
    await execute(case, monkeypatch)
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(d for d in receipt["dispatches"] if d["name"] == atomic.REVIEW_NAME)
    span = next(s for s in record.detail.trace_spans if s.id == dispatch["span_id"])
    if change == "delete":
        receipt.pop("review_projection_version")
    elif change in {"downgrade", "bool", "unknown"}:
        receipt["review_projection_version"] = {"downgrade": 1, "bool": True, "unknown": 99}[change]
    elif change == "system":
        _, user = span.full_input.split("\nJSON:\n", 1)
        span.full_input = (
            atomic.atomic_system(
                atomic.REVIEW_NAME, record.detail.output_language, review_projection_version=1
            )
            + "\n\n\nJSON:\n"
            + user
        )
        dispatch["full_input_sha256"] = atomic.digest(span.full_input)
    elif change == "hash":
        dispatch["full_output_sha256"] = "changed"
    else:
        from claim_review_fixture import expand_prompt_payload

        system, raw = span.full_input.split("\nJSON:\n", 1)
        payload = expand_prompt_payload(json.loads(raw))
        payload["upstream_identity_refs"]["upstream_analysis"]["producer_hash"] = "changed"
        span.full_input = system + "\nJSON:\n" + json.dumps(payload)
        dispatch["full_input_sha256"] = atomic.digest(span.full_input)
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises((ValueError, RuntimeError)):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)


@pytest.mark.asyncio
async def test_legacy_v1_two_claim_payload_and_original_system_replay(monkeypatch):
    from packages.agents.writer import question_atomic_delivery as atomic

    case = await atomic_case()
    service, record, snapshot, _, view, use, packets, *_ = case
    from test_writer_artifact_consumption import record_upstream

    record_upstream(service, record)
    result, _ = await execute(case, monkeypatch, review_projection_version=2,
                              generation_projection_version=2)
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    receipt.pop("review_projection_version")
    plans = [
        dict(
            question_id=p["question_id"],
            claim_ids=p["claim_ids"],
            missing_fields=p["missing_fields"],
        )
        for p in receipt["question_answer_plans"]
    ]
    metadata = atomic.handoff_context(service, record, view, packets[0]["questions"], use)
    batches, omitted = atomic.atomic_review_batches(
        result["claims"],
        view,
        packets[0]["questions"],
        plans,
        metadata,
        max_bytes=14000,
        review_projection_version=1,
    )
    assert not omitted and [len(b["claims"]) for b in batches] == [2, 1]
    assert all(
        key in batches[0]
        for key in ("upstream_analysis", "comparison_assessment", "reflection_constraints")
    )
    assert "review_projection_version" not in batches[0]
    from packages.agents.writer.dimension_writer import compact_prompt_json, review_payload
    from packages.agents.writer.question_repair import REPAIR_REVIEW_SYSTEM

    # Construct the historical transport shape independently of the new
    # projection helper, retaining the original two-claim body and SYSTEM.
    legacy_batches = [
        dict(
            review_payload(
                rows, view, review_version=3, questions=packets[0]["questions"], plans=plans
            ),
            **metadata,
            question_answer_plans=plans,
        )
        for rows in (result["claims"][:2], result["claims"][2:])
    ]
    assert batches == legacy_batches
    legacy_system = atomic.SYSTEM_IDENTITY + REPAIR_REVIEW_SYSTEM
    assert (
        atomic.atomic_system(
            atomic.REVIEW_NAME, record.detail.output_language, review_projection_version=1
        )
        == legacy_system
    )

    spans = [s for s in record.detail.trace_spans if s.name == atomic.REVIEW_NAME]
    dispatches = [d for d in receipt["dispatches"] if d["name"] != atomic.REVIEW_NAME]
    for batch, span in zip(legacy_batches, spans[: len(legacy_batches)], strict=True):
        span.full_input = legacy_system + "\n\n\nJSON:\n" + compact_prompt_json(batch)
        span.full_output = json.dumps({"reviews": [supported_review(c) for c in batch["claims"]]})
        dispatches.append(
            atomic.dispatch_row(
                span,
                question_ids=[q["question_id"] for q in batch["questions"]],
                claim_ids=[c["id"] for c in batch["claims"]],
                fact_ids={fid for c in batch["claims"] for fid in c["fact_ids"]},
            )
        )
    receipt["dispatches"] = dispatches
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert len(replay["reviews"]) == len(result["claims"]) == 3


@pytest.mark.asyncio
async def test_same_original_sibling_and_advisory_cannot_supply_download_witness():
    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.evidence.source_spans import (
        ReportSourceSpanBinding,
        source_span_candidates,
    )

    positive = "Observers may view boards and download attachments after approval and sign-in."
    negative = "Observers cannot edit cards or upload attachments unless granted an editor role."
    case = await atomic_case(
        [positive + "\n\n" + negative],
        question="Example Product: Can observers download attachments?",
    )
    service, record, _, _, view, use, packets, *_ = case
    fact = next(f for f in view.facts if f.field == "evidence_terms")
    spans = source_span_candidates(fact)
    claims = [
        ReportClaim(
            id=cid,
            text=text,
            kind="fact",
            competitor=view.competitor,
            dimension=view.dimension,
            fact_ids=(fact.id,),
            source_ids=(fact.source_id,),
            source_span_bindings=(
                ReportSourceSpanBinding.model_validate(
                    next(span for span in spans if span["quote"] == support)
                ),
            ),
        )
        for cid, text, support in (
            ("read", "Observers may view boards.", positive),
            ("download", "Observers may download attachments.", negative),
        )
    ]
    questions = packets[0]["questions"]
    plans = [
        dict(
            question_id=questions[0]["question_id"],
            claim_ids=[c.id for c in claims],
            missing_fields=[],
        )
    ]
    metadata = atomic.handoff_context(service, record, view, questions, use)
    metadata["upstream_analysis"] = dict(
        kind="analyst",
        competitor=view.competitor,
        dimension=view.dimension,
        snapshot_id=view.snapshot_id,
        producer_hash="identity-only",
        content={"claims": [{"claim": positive, "source_ids": [fact.source_id]}]},
    )
    batches, omitted = atomic.atomic_review_batches(
        claims, view, questions, plans, metadata, max_bytes=14000
    )
    assert not omitted and len(batches) == 2
    download = batches[1]
    assert download["claims"][0]["support_quotes"] == [negative]
    assert positive not in json.dumps(download)
    assert download["request_context"] == metadata["request_context"]
    row = supported_review(download["claims"][0])
    row["support_witnesses"] = [{"support_index": 0, "quote": "download attachments"}]
    assert (
        atomic.parse_atomic_reviews(json.dumps({"reviews": [row]}), [claims[1]], payload=download)
        == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_review", ["wrong_witness", "missing_witness", "no_transport", "timeout"]
)
@pytest.mark.parametrize("generation_version", [None, 4], ids=["current_default", "legacy_gen4"])
async def test_bad_review_retains_other_independent_reviews_in_execution_and_replay(
    monkeypatch, bad_review, generation_version
):
    from test_question_atomic_delivery import atomic_model

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case()
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    normal_seen = {}
    normal = atomic_model(service, normal_seen)
    damaged = False

    async def model(record, **kwargs):
        nonlocal damaged
        if kwargs["name"] != atomic.REVIEW_NAME or damaged:
            return await normal(record, **kwargs)
        damaged = True
        if bad_review == "timeout":
            raise TimeoutError("offline review timeout")
        response = await normal(record, **kwargs)
        span = record.detail.trace_spans[-1]
        if bad_review == "no_transport":
            span.metadata["llm_transport_attempts"] = 0
            return response
        raw = json.loads(response)
        if bad_review == "wrong_witness":
            raw["reviews"][0]["support_witnesses"][0]["quote"] = "Borrowed parent assertion."
        else:
            raw["reviews"][0].pop("support_witnesses")
        span.full_output = json.dumps(raw)
        return span.full_output

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        **({} if generation_version is None else {
            "generation_projection_version": generation_version}),
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    current = generation_version is None
    repaired = current and bad_review in {"wrong_witness", "missing_witness"}
    assert result["compact"]["generation_projection_version"] == (5 if current else 4)
    assert len(normal_seen[atomic.GENERATION_NAME]) == (2 if repaired else 1)
    assert len(result["claims"]) == (4 if repaired else 3)
    assert sum(c.status == "supported" for c in audited) == (3 if repaired else 2)
    assert result["claims"][0].id not in {row.claim_id for row in result["reviews"]}
    claims_by_id = {claim.id: claim for claim in result["claims"]}
    for payload in normal_seen[atomic.REVIEW_NAME]:
        assert len(payload["claims"]) == 1 and payload["review_projection_version"] == 3
        claim = payload["claims"][0]
        assert claim["support_quotes"] == [
            binding.quote for binding in claims_by_id[claim["id"]].source_span_bindings
        ]
    if repaired:
        repair = normal_seen[atomic.GENERATION_NAME][1]["generation_repair"]
        kept = result["claims"][1:3]
        assert repair["retained_claim_ids"] == [claim.id for claim in kept]
        assert [row["text"] for row in repair["retained_claims"]] == [claim.text for claim in kept]
        assert "retained_claim_duplicate" in result["gaps"]
        assert result["claims"][3].text == result["claims"][0].text
        assert result["claims"][3].id not in {claim.id for claim in result["claims"][:3]}
        assert normal_seen[atomic.REVIEW_NAME][-1]["claims"][0]["id"] == result["claims"][3].id
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
    assert len(replay["reviews"]) == (3 if repaired else 2)


def test_single_claim_projection_retains_complete_operation_conditions_and_required_checks():
    from types import SimpleNamespace

    from test_operation_actor_conditions import original_and_claim

    from packages.agents.writer.atomic_claim_review import atomic_review_payload
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews
    from packages.research.evidence.report_claims import (
        required_claim_checks,
        required_operation_checks,
    )

    quote = "Guests can edit boards shared with them."
    condition = (
        "Guests must sign in and obtain approval before editing boards "
        "unless an owner unlocks them."
    )
    original, claim = original_and_claim(
        quote, quote=quote, condition=condition, competitor="Example Product"
    )
    assert any(p["quote"] == condition for p in claim.operation_binding.prerequisites)
    plans = [dict(question_id="q", claim_ids=[claim.id], missing_fields=[])]
    payload = atomic_review_payload(
        [claim],
        SimpleNamespace(facts=[original], sources=[]),
        [{"question_id": "q", "question": "Can guests edit boards?"}],
        plans,
        {"request_context": {"parents": [{"text": "Guest A has approval and has signed in."}]}},
    )
    assert payload["claims"][0]["support_quotes"] == [claim.operation_binding.operation_quote]
    binding = payload["claims"][0]["operation_binding"]
    assert condition in binding["condition_evidence"]
    assert any(p["quote"] == condition for p in binding["prerequisites"])
    assert payload["claims"][0]["required_checks"] == [
        *required_operation_checks(claim.operation_binding),
        *required_claim_checks(claim),
    ]
    row = supported_review(payload["claims"][0])
    row["support_witnesses"] = [{"support_index": 0, "quote": "edit boards"}]
    assert len(parse_atomic_reviews(json.dumps({"reviews": [row]}), [claim], payload=payload)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("independent", [False, True])
@pytest.mark.parametrize("generation_version", [None, 4], ids=["current_default", "legacy_gen4"])
async def test_actual_download_review_never_receives_unselected_temporal_permission(
    monkeypatch, independent, generation_version
):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic

    permission = "In accounts created before March 8, 2024, Observers may download attachments."
    selected = (
        "Observers may vote on cards."
        if independent
        else "Observers cannot edit cards or upload attachments unless granted an editor role."
    )
    assertion = selected if independent else permission
    case = await atomic_case(
        [permission + "\n\n" + selected],
        question=(
            "Example Product: Can Observers download attachments or vote on cards "
            "in an account created before March 8, 2024?"
        ),
    )
    service, record, snapshot, context, view, use, packets, boundaries, allowed = case
    seen, generations = [], []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            generations.append(payload)
            candidate = next(
                span
                for row in payload["evidence_view"]["facts"]
                for span in row["source_span_candidates"]
                if span["quote"] == selected
            )
            response = question_plan_response(
                payload,
                [dict(text=assertion, kind="fact", support_refs=[candidate["support_ref"]])],
            )
        else:
            assert kwargs["name"] == atomic.REVIEW_NAME
            seen.append(payload)
            row = supported_review(payload["claims"][0])
            row["support_witnesses"] = [
                {"support_index": 0, "quote": "vote" if independent else "attachments"}
            ]
            response = json.dumps({"reviews": [row]})
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service,
        record,
        context,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        **({} if generation_version is None else {
            "generation_projection_version": generation_version}),
    )
    current = generation_version is None
    attempts = 2 if current and not independent else 1
    assert result["compact"]["generation_projection_version"] == (5 if current else 4)
    assert len(generations) == (2 if current else 1)
    assert len(seen) == len(result["claims"]) == attempts
    assert len({claim.id for claim in result["claims"]}) == attempts
    if current and independent:
        # The failed download task cannot borrow the already retained vote
        # atom. Its invalid resubmission receives no additional review.
        repair = generations[1]["generation_repair"]
        assert repair["retained_claim_ids"] == [result["claims"][0].id]
        assert repair["retained_claims"][0]["text"] == selected
        assert "generation_task_invalid" in result["gaps"]
    for payload in seen:
        assert len(payload["claims"]) == 1 and payload["review_projection_version"] == 3
        assert payload["claims"][0]["support_quotes"] == [selected]
        # No source-context member may carry the unselected permission,
        # including the separately reviewed attempt1 candidate.
        context_only = {key: value for key, value in payload.items() if key != "claims"}
        assert permission not in json.dumps(context_only)
        temporal = payload["constraint_context"][0]["temporal_conditions"]
        assert temporal and all(row["requires_complete_support"] != independent for row in temporal)
    assert len(result["reviews"]) == int(independent)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hiding_place", ["unused_table", "nested_table"])
async def test_v2_review_replay_rejects_hidden_unused_text_with_updated_dispatch_hash(
    monkeypatch, hiding_place
):
    from packages.agents.writer import question_atomic_delivery as atomic

    case = await atomic_case()
    service, record, snapshot, _, view, use, *_ = case
    await execute(case, monkeypatch)
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(row for row in receipt["dispatches"] if row["name"] == atomic.REVIEW_NAME)
    span = next(s for s in record.detail.trace_spans if s.id == dispatch["span_id"])
    system, raw = span.full_input.split("\nJSON:\n", 1)
    body = json.loads(raw)
    hidden = "Observers may download attachments after approval."
    if hiding_place == "unused_table":
        body.setdefault("text_sets", {})["unused_sibling"] = hidden
    else:
        body["claims"][0]["text_sets"] = {"unused_sibling": hidden}
    span.full_input = system + "\nJSON:\n" + json.dumps(body)
    dispatch["full_input_sha256"] = atomic.digest(span.full_input)
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises((ValueError, RuntimeError)):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)


def test_unselected_unknown_restriction_keeps_identity_and_blocks_positive_review():
    from types import SimpleNamespace

    from test_source_span_binding import fact, parse_bound

    from packages.agents.writer.atomic_claim_review import atomic_review_payload
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews
    from packages.research.evidence.snapshot_models import canonical_json

    selected = "Organizations own all collections."
    external = "Guests may download attachments if X and Y unless Z."
    original = fact(quote=selected, value=[selected])
    original = original.model_copy(
        update={
            "qualifiers_json": canonical_json(
                {"source_condition_links": [{"kind": "future_condition", "quote": external}]}
            )
        }
    )
    claims, _ = parse_bound(original, selected)
    assert len(claims) == 1
    payload = atomic_review_payload(
        claims,
        SimpleNamespace(facts=[original], sources=[]),
        [{"question_id": "q", "question": "Who owns collections?"}],
        [{"question_id": "q", "claim_ids": [claims[0].id], "missing_fields": []}],
        {},
    )
    assert external not in json.dumps(payload)
    assert payload["constraint_context"][0]["qualifiers"]["source_condition_links"]
    row = supported_review(payload["claims"][0])
    row["support_witnesses"] = [{"support_index": 0, "quote": "own all collections"}]
    assert parse_atomic_reviews(json.dumps({"reviews": [row]}), claims, payload=payload) == []


@pytest.mark.parametrize(
    "condition",
    [
        (
            "In accounts created before March 8, 2024, Observers may download attachments "
            "if X and Y unless locked."
        ),
        (
            "If members leave a folder, they can keep a copy of the folder "
            "but it will no longer sync with other accounts."
        ),
    ],
)
def test_complete_selected_temporal_and_exception_originals_remain_exact(condition):
    from types import SimpleNamespace

    from test_source_span_binding import fact, parse_bound

    from packages.agents.writer.atomic_claim_review import atomic_review_payload
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    original = fact(quote=condition, value=[condition])
    claims, _ = parse_bound(original, condition)
    assert len(claims) == 1
    payload = atomic_review_payload(
        claims,
        SimpleNamespace(facts=[original], sources=[]),
        [{"question_id": "q", "question": "What is the applicable conditional rule?"}],
        [{"question_id": "q", "claim_ids": [claims[0].id], "missing_fields": []}],
        {},
    )
    restrictions = payload["constraint_context"][0]
    rows = [*restrictions["temporal_conditions"], *restrictions["source_exceptions"]]
    assert rows and all(row.get("quote") == condition for row in rows)
    row = supported_review(payload["claims"][0])
    row["support_witnesses"] = [{"support_index": 0, "quote": condition}]
    assert len(parse_atomic_reviews(json.dumps({"reviews": [row]}), claims, payload=payload)) == 1


def test_unrelated_copy_exception_does_not_supply_prose_or_block_independent_vote_support():
    from types import SimpleNamespace

    from test_source_span_binding import fact, parse_bound, spans

    from packages.agents.writer.atomic_claim_review import atomic_review_payload
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    selected = "Observers may vote on cards."
    sibling = (
        "If members leave a folder, they can keep a copy of the folder "
        "but it will no longer sync with other accounts."
    )
    original = fact(quote=sibling + "\n\n" + selected, value=[sibling, selected])
    selected_spans = [span for span in spans(original) if span["quote"] == selected]
    claims, _ = parse_bound(original, selected, selected_spans)
    assert len(claims) == 1
    payload = atomic_review_payload(
        claims,
        SimpleNamespace(facts=[original], sources=[]),
        [{"question_id": "q", "question": "May Observers vote on cards?"}],
        [{"question_id": "q", "claim_ids": [claims[0].id], "missing_fields": []}],
        {},
    )
    assert sibling not in json.dumps(payload)
    restrictions = payload["constraint_context"][0]["source_exceptions"]
    assert restrictions and not any(r.get("requires_complete_support") for r in restrictions)
    row = supported_review(payload["claims"][0])
    row["support_witnesses"] = [{"support_index": 0, "quote": "vote on cards"}]
    assert len(parse_atomic_reviews(json.dumps({"reviews": [row]}), claims, payload=payload)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_action,selected_action",
    [
        ("download files", "download attachments"),
        ("download attached files", "download files"),
        ("remove files", "delete files"),
    ],
)
@pytest.mark.parametrize("generation_version", [None, 4], ids=["current_default", "legacy_gen4"])
async def test_action_alias_or_object_wording_does_not_prove_temporal_independence(
    monkeypatch, source_action, selected_action, generation_version
):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import audit_report_claims

    restriction = f"In accounts created before March 8, 2024, Observers may {source_action}."
    selected = f"Observers may {selected_action}."
    case = await atomic_case(
        [restriction + "\n\n" + selected],
        question=f"Example Product: May Observers {selected_action}?",
    )
    service, record, snapshot, context, view, use, packets, boundaries, allowed = case
    seen, generations = [], []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            generations.append(payload)
            support = next(
                span
                for row in payload["evidence_view"]["facts"]
                for span in row["source_span_candidates"]
                if span["quote"] == selected
            )
            response = question_plan_response(
                payload, [dict(text=selected, kind="fact", support_refs=[support["support_ref"]])]
            )
        else:
            assert kwargs["name"] == atomic.REVIEW_NAME
            seen.append(payload)
            row = supported_review(payload["claims"][0])
            row["support_witnesses"] = [{"support_index": 0, "quote": selected_action}]
            response = json.dumps({"reviews": [row]})
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
        service,
        record,
        context,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        **({} if generation_version is None else {
            "generation_projection_version": generation_version}),
    )
    current = generation_version is None
    attempts = 2 if current else 1
    assert result["compact"]["generation_projection_version"] == (5 if current else 4)
    assert len(generations) == len(result["claims"]) == len(seen) == attempts
    assert len({claim.id for claim in result["claims"]}) == attempts
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"]
    assert not result["reviews"] and not replay["reviews"]
    assert all(row.status != "supported" for row in audited)
    for payload in seen:
        assert len(payload["claims"]) == 1 and payload["review_projection_version"] == 3
        assert payload["claims"][0]["support_quotes"] == [selected]
        assert restriction not in json.dumps(payload)
        temporal = payload["constraint_context"][0]["temporal_conditions"]
        assert temporal and all(row["requires_complete_support"] for row in temporal)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "links",
    [
        {"kind": "future_condition", "quote": "Unknown external condition."},
        [{"kind": "future_condition", "quote": "Unknown external condition."}],
        None,
        False,
        0,
        "",
        {},
        "Unknown external condition.",
        [None],
        [False],
        [0],
        ["Unknown external condition."],
        [[]],
    ],
)
async def test_unknown_condition_json_shapes_fail_locally_without_interrupting_peer(
    monkeypatch, links
):
    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import audit_report_claims

    texts = ["Guests have no personal area.", "Guests require an account invitation."]
    case = await atomic_case(
        texts,
        question=(
            "Example Product: Do guests have a personal area "
            "or require an account invitation?"
        ),
        source_qualifiers=[{"source_condition_links": links}, {}],
    )
    service, record, snapshot, _, view, use, *_ = case
    result, seen = await execute(case, monkeypatch)
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        case[7],
        available_facts=view.facts,
        review_version=3,
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert len(result["claims"]) == 2
    assert len(result["reviews"]) == len(replay["reviews"]) == 1
    assert [row.claim.text for row in audited if row.status == "supported"] == [texts[1]]
    payload = next(row for row in seen[atomic.REVIEW_NAME] if row["claims"][0]["text"] == texts[0])
    projected = payload["constraint_context"][0]["qualifiers"]["source_condition_links"]
    assert projected and all(row["requires_complete_support"] for row in projected)
    assert all(len(row["restriction_sha256"]) == 64 for row in projected)
