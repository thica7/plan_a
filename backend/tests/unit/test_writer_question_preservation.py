"""Complete question observations survive bounded Writer views and compaction."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_question_retrieval import research_case

from packages.agents.comparator.logic import ComparatorAgentMixin
from packages.agents.writer.dimension_writer import (
    compact_dimension_context,
    compact_prompt_json,
    operation_claim_selection,
    parse_claim_drafts,
)
from packages.orchestrator.evidence_context import EvidenceContextMixin
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.snapshot_models import EvidenceConsumption, EvidenceFact
from packages.research.evidence.views import select_evidence_view
from packages.research.question_scope import research_questions

PRODUCT = "Example Product"
QUESTION = (
    "Example Product: How many collections does Free plan include, "
    "and who owns the records?"
)
SELECTED = {"segment_competitor": PRODUCT, "dimension": "feature"}


class EvidenceHarness(EvidenceContextMixin, ComparatorAgentMixin):
    _settings = SimpleNamespace(run_llm_max_tokens=1600)

    def _persist_run(self, run_id):
        pass


def preservation_case():
    quotes = [
        f"Observation {number}: Free plan has 2 collections, whose owner is the team. "
        + "Original complete eligibility condition applies to authenticated team members. " * 10
        for number in range(6)
    ]
    detail, _ = research_case(quotes, question=QUESTION)
    for number, source in enumerate(detail.raw_sources):
        source.title = f"Documentation section {number}. " + "Original source identity. " * 10
        source.url = f"https://example-product.test/section-{number}/" + "documentation-" * 30
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    ids = tuple(fact.id for fact in snapshot.facts if fact.field == "evidence_terms")
    return SimpleNamespace(detail=detail, evidence_origin=None), snapshot, ids


def original_fact(number, quote):
    return EvidenceFact(
        id=f"anonymous-{number}", semantic_id=f"observation-{number}",
        source_id=f"source-{number}", competitor=PRODUCT, dimension="feature",
        field="evidence_terms", value_json=json.dumps([quote]), quote=quote,
        status="supported", confidence=0.9,
    )


@pytest.mark.parametrize("payload_bytes", [14000, 18000])
def test_requested_observations_reserve_whole_support_without_shortening_conditions(payload_bytes):
    record, snapshot, ids = preservation_case()
    before = snapshot.model_dump_json()
    view, use = EvidenceHarness()._begin_evidence_use(
        record, agent="writer", competitor=PRODUCT, dimension="feature", fact_ids=ids,
    )
    assert set(ids) <= set(view.fact_ids)
    assert view.max_bytes == use.max_bytes == 32768
    assert view.estimated_bytes <= 32768
    for item in {item for fact in view.facts for item in fact.evidence_item_ids}:
        assert {fact.id for fact in view.facts if item in fact.evidence_item_ids} == {
            fact.id for fact in snapshot.facts if item in fact.evidence_item_ids
        }
    questions = research_questions(record.detail, PRODUCT, "feature")
    question_bytes = len(json.dumps({"questions": questions}, ensure_ascii=False).encode()) + 16
    compact, omitted = compact_dimension_context(
        SELECTED, view, set(ids), max_bytes=payload_bytes - question_bytes, questions=questions,
    )
    compact["questions"] = questions
    sent = {row["id"] for row in compact["evidence_view"]["facts"]}
    # Six complete originals plus legal readable support cost more than 14KB.
    # Dropping all references to preserve six uncitable rows is not delivery.
    if payload_bytes == 18000:
        assert sent == set(ids) and not omitted
    else:
        assert sent and sent < set(ids) and omitted
    assert len(compact_prompt_json(compact).encode()) <= payload_bytes
    from packages.agents.writer.dimension_writer import _support_ref_catalog
    catalog = _support_ref_catalog(compact, view.facts, sent)
    originals = {fact.id: fact for fact in snapshot.facts}
    for row in compact["evidence_view"]["facts"]:
        assert row["quote"] == originals[row["id"]].quote
        assert row["value"] == originals[row["id"]].value
        assert row["qualifiers"] == originals[row["id"]].qualifiers
        assert row["source_span_candidates"]
        assert all(span["support_ref"] in catalog for span in row["source_span_candidates"])
    assert snapshot.model_dump_json() == before


def test_small_view_reports_omission_and_never_sends_half_an_observation():
    _, snapshot, ids = preservation_case()
    view = select_evidence_view(
        snapshot, agent="writer", competitor=PRODUCT, dimension="feature",
        fact_ids=ids, max_bytes=16384,
    )
    assert set(ids) - set(view.fact_ids)
    assert "context_budget_exceeded" in {gap.reason for gap in view.gaps}
    assert view.estimated_bytes <= 16384
    for fact in view.facts:
        observed = {row.id for row in view.facts
                    if row.evidence_item_ids == fact.evidence_item_ids}
        assert observed == {
            row.id for row in snapshot.facts if row.evidence_item_ids == fact.evidence_item_ids
        }


def test_small_compact_budget_reports_whole_observation_omission():
    record, snapshot, ids = preservation_case()
    view, _ = EvidenceHarness()._begin_evidence_use(
        record, agent="writer", competitor=PRODUCT, dimension="feature", fact_ids=ids,
    )
    payload, omitted = compact_dimension_context(SELECTED, view, set(ids), max_bytes=4000)
    assert omitted
    assert len(payload["evidence_view"]["facts"]) < len(ids)
    assert len(compact_prompt_json(payload).encode()) <= 4000
    originals = {fact.id: fact for fact in snapshot.facts}
    for row in payload["evidence_view"]["facts"]:
        assert row["quote"] == originals[row["id"]].quote
        assert row["value"] == originals[row["id"]].value


@pytest.mark.parametrize("case", ["analyst", "unscoped", "no_question", "too_many", "empty"])
def test_extra_local_budget_is_only_for_bounded_writer_question_facts(case):
    record, snapshot, ids = preservation_case()
    service = EvidenceHarness()
    arguments = dict(agent="writer", competitor=PRODUCT, dimension="feature", fact_ids=ids)
    if case == "analyst":
        arguments["agent"] = "analyst"
        service._settings = SimpleNamespace(run_llm_max_tokens=0)
    elif case == "unscoped":
        arguments["competitor"] = None
    elif case == "no_question":
        record.detail.topic = "Product research"
    elif case == "too_many":
        arguments["fact_ids"] = tuple(fact.id for fact in snapshot.facts)[:9]
    else:
        arguments["fact_ids"] = ()
    view, use = service._begin_evidence_use(record, **arguments)
    assert view.max_bytes == use.max_bytes == 16384


@pytest.mark.parametrize("topic_operations", [(), ("edit",)])
def test_quantity_and_ownership_question_keeps_unrelated_operation_types(topic_operations):
    facts = (
        original_fact(1, "Members can share collections on Free plan, "
                      "which includes 2 collections."),
        original_fact(2, "Organization records belong to the team. "
                      "Members can create items in collections."),
        original_fact(3, "My Items contains individually owned records. Members can view items."),
    )
    payload, omitted = compact_dimension_context(
        SELECTED, SimpleNamespace(facts=facts), {fact.id for fact in facts},
        questions=[{"question": QUESTION}], requested_operations=topic_operations,
    )
    assert {row["id"] for row in payload["evidence_view"]["facts"]} == {
        fact.id for fact in facts
    }
    assert not payload.get("requested_operations")
    assert not omitted


@pytest.mark.parametrize("repair", [False, True])
def test_question_operations_stay_request_metadata_and_repair_stays_scoped(repair):
    facts = (
        original_fact(1, "Guests on Free plan can comment on documents only if invited."),
        original_fact(2, "Guests on Free plan can edit documents only after signing in."),
        original_fact(3, "Guests on Free plan can share documents with a member."),
    )
    requested = ("comment",) if repair else ()
    question = "Example Product: Can guests comment on and edit documents on Free plan?"
    payload, _ = compact_dimension_context(
        SELECTED, SimpleNamespace(facts=facts), {fact.id for fact in facts},
        questions=[{"question": question}], requested_operations=requested,
        include_non_operations=not repair,
    )
    expected = {"comment"} if repair else {"comment", "edit"}
    assert set(payload["requested_operations"]) == expected
    expected_targets = {"comment"} if repair else {"comment", "edit", "share"}
    assert {target for row in payload["evidence_view"]["facts"]
            for target in row.get("operation_targets", ())} == expected_targets
    for row in payload["evidence_view"]["facts"]:
        original = next(fact for fact in facts if fact.id == row["id"])
        assert row["quote"] == original.quote
        assert all(item["fact_id"] == original.id and item["source_id"] == original.source_id
                   for item in row["operation_observations"])


@pytest.mark.parametrize("mode", ["non_operation", "separate_questions", "compound_question"])
def test_question_facts_survive_compact_parse_and_selection(mode):
    owner = "My Items contains individually owned records."
    reading = "Members can view items."
    ownership = original_fact(2, owner + " " + reading)
    facts = [ownership]
    questions = [{"question": "Example Product: Who owns the records in My Items?"}]
    if mode != "non_operation":
        facts.insert(0, original_fact(1, "Editors can edit documents on the paid plan."))
        questions.insert(0, {"question": "Example Product: Can editors edit documents?"})
    if mode == "compound_question":
        questions = [{"question": "Example Product: Can editors edit documents, "
                                  "and who owns records in My Items?"}]
    view = SimpleNamespace(facts=facts)
    payload, omitted = compact_dimension_context(
        SELECTED, view, {fact.id for fact in facts}, questions=questions,
    )
    rows = payload["evidence_view"]["facts"]
    assert {row["id"] for row in rows} == {fact.id for fact in facts}
    expected_operations = set() if mode == "non_operation" else {"edit"}
    assert set(payload.get("requested_operations", ())) == expected_operations
    assert not omitted
    assert len(rows) <= 8 and len(compact_prompt_json(payload).encode()) <= 14000
    candidates = {item["observation_id"]: item for row in rows
                  for item in row.get("operation_observations", ())}
    drafts = [dict(
        text=reading if row["id"] == ownership.id else row["quote"],
        kind="fact", competitor=PRODUCT, dimension="feature",
        fact_ids=[row["id"]], source_ids=[row["source_id"]],
        observation_id=row["operation_observations"][0]["observation_id"],
    ) for row in rows]
    drafts.append(dict(text=owner, kind="fact", competitor=PRODUCT, dimension="feature",
                       fact_ids=[ownership.id], source_ids=[ownership.source_id]))
    sent_ids = {row["id"] for row in rows}
    claims, gaps = parse_claim_drafts(
        json.dumps({"claims": drafts}), candidates, sent_ids, "question-use",
        source_facts=facts,
    )
    assert not gaps and len(claims) == len(drafts)
    targets = {row["id"]: row.get("operation_targets", ()) for row in rows}
    selected = operation_claim_selection(
        claims, view, payload.get("requested_operations", ()), sent_ids, fact_targets=targets,
    )
    assert {claim.text for claim in selected} == {draft["text"] for draft in drafts}
    assert any(claim.operation_binding and claim.operation_binding.operation == "read"
               for claim in selected)


def test_mixed_question_repair_only_parses_and_selects_sent_operation_candidates():
    edit = original_fact(1, "Editors can edit documents on the paid plan.")
    ownership = original_fact(2, "My Items contains individually owned records. "
                              "Members can view items.")
    facts = [edit, ownership]
    view = SimpleNamespace(facts=facts)
    payload, _ = compact_dimension_context(
        SELECTED, view, {fact.id for fact in facts}, requested_operations=("edit",),
        include_non_operations=False, questions=[
            {"question": "Example Product: Can editors edit documents?"},
            {"question": "Example Product: Who owns records in My Items?"},
        ],
    )
    rows = payload["evidence_view"]["facts"]
    assert {row["id"] for row in rows} == {edit.id}
    candidates = {item["observation_id"]: item for row in rows
                  for item in row["operation_observations"]}
    draft = dict(text=edit.quote, kind="fact", competitor=PRODUCT, dimension="feature",
                 fact_ids=[edit.id], source_ids=[edit.source_id],
                 observation_id=rows[0]["operation_observations"][0]["observation_id"])
    invalid = {**draft, "observation_id": "unrequested-read-observation"}
    claims, gaps = parse_claim_drafts(
        json.dumps({"claims": [draft, invalid]}), candidates, {edit.id}, "repair-use",
        source_facts=facts,
    )
    assert len(claims) == 1 and gaps == {"claim_candidate_invalid"}
    selected = operation_claim_selection(
        claims, view, payload["requested_operations"], {edit.id},
        fact_targets={edit.id: ["edit"]},
    )
    assert selected == claims
    assert operation_claim_selection(
        claims, view, payload["requested_operations"], {edit.id}, fact_targets={edit.id: []},
    ) == []


@pytest.mark.parametrize("historical", [False, True])
def test_consumption_and_final_qa_replay_the_recorded_view_budget(historical):
    record, snapshot, ids = preservation_case()
    service = EvidenceHarness()
    if historical:
        view = select_evidence_view(
            snapshot, agent="writer", competitor=PRODUCT, dimension="feature",
            fact_ids=ids, max_bytes=16384,
        )
        use = EvidenceConsumption(
            id="historical-writer", run_id=record.detail.id,
            workspace_id=record.detail.workspace_id, project_id=record.detail.project_id,
            agent="writer", snapshot_id=snapshot.id, snapshot_version=snapshot.version,
            dependency_hash=view.dependency_hash, competitor=PRODUCT, dimension="feature",
            source_ids=view.source_ids, requested_fact_ids=ids, fact_ids=view.fact_ids,
            max_bytes=16384, estimated_bytes=view.estimated_bytes,
            estimated_tokens=view.estimated_tokens, created_at=snapshot.created_at,
        )
        record.detail.evidence_consumptions = [use]
    else:
        view, use = service._begin_evidence_use(
            record, agent="writer", competitor=PRODUCT, dimension="feature", fact_ids=ids,
        )
        assert set(ids) <= set(view.fact_ids)
    restored = EvidenceConsumption.model_validate_json(use.model_dump_json())
    service._validate_evidence_use(record, restored)
    assert record.detail.evidence_consumptions[-1].status == "validated"
    service._record_evidence_artifact(
        record, kind="writer", uses=[restored],
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    assert service._final_qa_producer_verified(record, snapshot)
    assert use.max_bytes == (16384 if historical else 32768)
