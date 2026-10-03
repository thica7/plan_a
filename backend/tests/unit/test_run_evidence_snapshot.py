from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.knowledge.models import KnowledgeDocument
from packages.memory.run_journal import RunJournal
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource

STAMP = "2026-10-03T00:00:00+00:00"


def make_detail(*, price: object = "3999 CNY") -> RunDetail:
    return RunDetail(
        id="run-shared-evidence",
        workspace_id="workspace-a",
        project_id="project-a",
        topic="Product research",
        status="running",
        execution_mode="real",
        created_at=STAMP,
        updated_at=STAMP,
        plan=AnalysisPlan(
            topic="Product research",
            competitors=["Product A", "Product B"],
            dimensions=["pricing", "feature"],
            research_depth="quick",
        ),
        raw_sources=[
            RawSource(
                id="source-product-a-pricing",
                competitor="Product A",
                dimension="pricing",
                source_type="webpage_verified",
                title="Product A pricing",
                url="https://product-a.example/pricing",
                snippet="Original price evidence",
                content_hash="fixed-original-page-hash",
                confidence=0.8,
                extracted_at=STAMP,
                metadata={
                    "last_verified_at": STAMP,
                    "market": "CN",
                    "normalized_fields": [
                        {
                            "kind": "pricing",
                            "dimension": "pricing",
                            "competitor": "Product A",
                            "tier_name": "Base",
                            "price": price,
                            "unit": "CNY",
                            "market": "CN",
                            "billing_cycle": "one_time",
                            "source_quote": f"Base price: {price}",
                            "confidence": 0.8,
                            "source_url": "https://product-a.example/pricing",
                            "evidence_item_ids": ["item-product-a-price"],
                        }
                    ],
                },
            )
        ],
    )


def make_document(**overrides: object) -> KnowledgeDocument:
    values = dict(
        id="document-a",
        workspace_id="workspace-a",
        project_id="project-a",
        competitor="Product A",
        dimension="pricing",
        market="CN",
        source_role="source",
        title="Canonical pricing",
        url="https://product-a.example/pricing",
        source_type="webpage_verified",
        content_hash="canonical-document-hash",
        version=2,
        text="Full body stays in knowledge storage",
        fetched_at=STAMP,
        source_published_at="2025-01-02T00:00:00+00:00",
        last_verified_at=STAMP,
    )
    values.update(overrides)
    return KnowledgeDocument(**values)


def with_document(detail: RunDetail) -> RunDetail:
    detail.raw_sources[0].metadata.update(
        {
            "kb_document_id": "document-a",
            "kb_document_version": 2,
            "kb_document_content_hash": "canonical-document-hash",
            "kb_chunk_id": "chunk-a",
        }
    )
    return detail


def snapshot_api():
    from packages.research.evidence.snapshot import (
        changed_evidence,
        current_snapshot,
        seal_snapshot,
    )

    return seal_snapshot, current_snapshot, changed_evidence


def test_arrival_order_and_retrieval_rank_do_not_change_snapshot() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    other = make_detail().raw_sources[0].model_copy(deep=True)
    other.id = "source-product-b-pricing"
    other.competitor = "Product B"
    other.metadata["normalized_fields"][0]["competitor"] = "Product B"
    detail.raw_sources.append(other)
    first = seal(detail, phase="analysis", canonical_documents={})
    detail.raw_sources.reverse()
    for source in detail.raw_sources:
        source.candidate_rank = 91
        source.metadata.update(kb_hit_score=0.2, kb_rerank_score=0.1)
        source.metadata["normalized_fields"].reverse()
    second = seal(detail, phase="analysis", canonical_documents={})
    assert first.id == second.id
    assert len(detail.evidence_snapshots) == 1


def test_fact_change_with_same_body_creates_new_snapshot() -> None:
    seal, _, changes = snapshot_api()
    detail = make_detail()
    first = seal(detail, phase="analysis", canonical_documents={})
    detail.raw_sources = make_detail(price="4299 CNY").raw_sources
    second = seal(detail, phase="analysis", canonical_documents={})
    assert second.version == first.version + 1
    assert second.parent_id == first.id
    assert second.id != first.id
    assert "3999 CNY" in first.model_dump_json()
    assert "4299 CNY" not in first.model_dump_json()
    previous_price = next(fact for fact in first.facts if fact.field == "price")
    current_price = next(fact for fact in second.facts if fact.field == "price")
    assert previous_price.semantic_id == current_price.semantic_id
    assert previous_price.semantic_id in changes(first, second).changed_facts


def test_nested_values_and_projection_cannot_mutate_history() -> None:
    seal, _, _ = snapshot_api()
    price = {"amount": 3999, "options": ["base", {"capacity": 256}]}
    detail = make_detail(price=price)
    first = seal(detail, phase="analysis", canonical_documents={})
    before = first.model_dump_json()
    fact = next(fact for fact in first.facts if fact.field == "price")
    fact.value["options"][1]["capacity"] = 512
    first.sources[0].to_raw_source().metadata["normalized_fields"][0]["price"] = "changed"
    price["amount"] = 1
    assert first.model_dump_json() == before
    assert fact.value["amount"] == 3999
    with pytest.raises(ValidationError):
        fact.quote = "changed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "workspace-b"),
        ("project_id", "project-b"),
    ],
)
def test_same_body_in_another_scope_cannot_reuse_snapshot(field, value) -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    first = seal(detail, phase="analysis", canonical_documents={})
    setattr(detail, field, value)
    second = seal(detail, phase="analysis", canonical_documents={})
    assert first.id != second.id
    assert second.version == first.version + 1


def test_old_run_json_defaults_and_journal_reopen(tmp_path) -> None:
    seal, current, _ = snapshot_api()
    old_payload = make_detail().model_dump(mode="json")
    for key in ("evidence_snapshots", "evidence_snapshot_id", "evidence_consumptions"):
        old_payload.pop(key, None)
    detail = RunDetail.model_validate(old_payload)
    assert detail.evidence_snapshots == []
    assert current(detail) is None
    first = seal(detail, phase="analysis", canonical_documents={})
    path = tmp_path / "journal.db"
    RunJournal(path).save_run(detail)
    loaded = RunJournal(path).load_run(detail.id)
    assert loaded is not None
    assert current(loaded).model_dump() == first.model_dump()
    assert seal(loaded, phase="analysis", canonical_documents={}).id == first.id


def test_phase_transition_explicitly_increases_version() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    collect = seal(detail, phase="collect", canonical_documents={})
    analysis = seal(detail, phase="analysis", canonical_documents={})
    assert analysis.version == collect.version + 1
    assert analysis.parent_id == collect.id
    assert analysis.phase == "analysis"


def test_broken_pointer_and_hash_are_explicit_errors() -> None:
    seal, current, _ = snapshot_api()
    detail = make_detail()
    first = seal(detail, phase="analysis", canonical_documents={})
    detail.evidence_snapshot_id = "missing"
    with pytest.raises(ValueError, match="pointer"):
        current(detail)
    detail.evidence_snapshot_id = first.id
    detail.evidence_snapshots[0] = first.model_copy(update={"content_hash": "tampered"})
    with pytest.raises(ValueError, match="hash"):
        current(detail)


def test_tampered_id_is_rejected() -> None:
    seal, current, _ = snapshot_api()
    detail = make_detail()
    first = seal(detail, phase="analysis", canonical_documents={})
    detail.evidence_snapshots[0] = first.model_copy(update={"id": "tampered"})
    detail.evidence_snapshot_id = "tampered"
    with pytest.raises(ValueError, match="identity"):
        current(detail)


def test_canonical_kb_ownership_dates_and_public_library_are_preserved() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    detail.raw_sources[0].metadata.update(
        {
            "kb_document_workspace_id": "spoofed",
            "kb_document_project_id": "spoofed",
            "source_published_at": "2099-01-01",
            "last_verified_at": "2099-01-01",
        }
    )
    doc = make_document(project_id=None, last_verified_at=None)
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    source = snapshot.sources[0]
    assert source.document_id == doc.id
    assert source.document_workspace_id == "workspace-a"
    assert source.document_project_id is None
    assert source.source_published_at == doc.source_published_at
    assert source.last_verified_at is None
    assert source.source_fetched_at == doc.fetched_at
    assert "spoofed" not in source.payload_json
    assert "2099" not in source.payload_json


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"workspace_id": "workspace-b"}, "scope_mismatch"),
        ({"workspace_id": None}, "scope_mismatch"),
        ({"project_id": "project-b"}, "scope_mismatch"),
        ({"version": 3}, "version_mismatch"),
        ({"content_hash": "changed"}, "hash_mismatch"),
        ({"competitor": "Product A Pro"}, "identity_mismatch"),
        ({"status": "deleted", "is_active": False}, "document_inactive"),
    ],
)
def test_invalid_canonical_references_are_rejected_as_gaps(override, reason) -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    doc = make_document(**override)
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert snapshot.sources == ()
    assert snapshot.facts == ()
    assert reason in {gap.reason for gap in snapshot.gaps}


def test_missing_or_untyped_canonical_document_is_not_trusted() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    missing = seal(detail, phase="analysis", canonical_documents={})
    assert missing.sources == ()
    assert missing.gaps[0].reason == "canonical_document_missing"
    with pytest.raises(TypeError, match="KnowledgeDocument"):
        seal(
            detail,
            phase="analysis",
            canonical_documents={"document-a": make_document().model_dump()},
        )


def test_snapshot_projection_uses_metadata_whitelist() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata.update(
        {
            "full_text": "PRIVATE_FULL_TEXT",
            "html": "PRIVATE_HTML",
            "credentials": "PRIVATE_CREDENTIALS",
            "instructions": "PRIVATE_INSTRUCTIONS",
            "random_nested": {"password": "PRIVATE_PASSWORD"},
        }
    )
    detail.raw_sources[0].metadata["normalized_fields"][0]["raw_text"] = "PRIVATE_RAW_TEXT"
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert "PRIVATE_" not in snapshot.model_dump_json()
    projection = snapshot.sources[0].to_raw_source()
    assert "normalized_fields" in projection.metadata
    assert not set(projection.metadata) & {"full_text", "html", "credentials", "instructions"}


def test_summary_and_historical_report_only_produce_signals() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata["normalized_fields"][0]["evidence_item_ids"] = []
    summary = seal(detail, phase="analysis", canonical_documents={})
    assert all(fact.status == "signal" for fact in summary.facts)
    historical = with_document(make_detail())
    doc = make_document(source_role="historical_report", source_type="report")
    snapshot = seal(historical, phase="analysis", canonical_documents={doc.id: doc})
    assert snapshot.sources[0].role == "historical_report"
    assert all(fact.status == "signal" for fact in snapshot.facts)


def test_conflicting_prices_keep_both_values_and_distinct_tiers_do_not_conflict() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    other = make_detail(price="4299 CNY").raw_sources[0]
    other.id = "source-price-correction"
    detail.raw_sources.append(other)
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert len(snapshot.conflicts) == 1
    assert snapshot.conflicts[0].status == "unresolved"
    prices = {fact.value for fact in snapshot.facts if fact.field == "price"}
    assert prices == {"3999 CNY", "4299 CNY"}
    other.metadata["normalized_fields"][0]["tier_name"] = "Pro"
    next_snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert next_snapshot.conflicts == ()


def test_date_confidence_and_status_changes_affect_version_but_not_created_at() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    previous = seal(detail, phase="analysis", canonical_documents={})
    detail.raw_sources[0].metadata["last_verified_at"] = "2026-10-02T00:00:00+00:00"
    changed = seal(detail, phase="analysis", canonical_documents={})
    assert changed.version == previous.version + 1
    detail.raw_sources[0].confidence = 0.7
    changed_again = seal(detail, phase="analysis", canonical_documents={})
    assert changed_again.version == changed.version + 1
    detail.evidence_snapshots[-1] = changed_again.model_copy(
        update={"created_at": datetime(2026, 1, 1, tzinfo=UTC)}
    )
    same = seal(detail, phase="analysis", canonical_documents={})
    assert same.id == changed_again.id
    assert json.loads(same.model_dump_json())["created_at"].startswith("2026-01-01")


def test_changed_evidence_reports_additions_deletions_and_changes() -> None:
    seal, _, changes = snapshot_api()
    detail = make_detail()
    first = seal(detail, phase="analysis", canonical_documents={})
    original = detail.raw_sources[0]
    replacement = make_detail().raw_sources[0]
    replacement.id = "replacement"
    detail.raw_sources = [replacement]
    second = seal(detail, phase="analysis", canonical_documents={})
    delta = changes(first, second)
    assert first.sources[0].semantic_id in delta.removed_sources
    assert second.sources[0].semantic_id in delta.added_sources
    assert not delta.changed_sources
    assert delta.removed_facts and delta.added_facts
    detail.raw_sources = [original]


def test_snapshot_models_forbid_unexpected_fields() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        type(snapshot).model_validate({**snapshot.model_dump(), "metadata": {}})


def test_full_model_and_explicit_covered_competitors_control_admission() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].competitor = "Product A Pro"
    rejected = seal(detail, phase="analysis", canonical_documents={})
    assert rejected.sources == ()
    assert rejected.gaps[0].reason == "identity_mismatch"
    detail.raw_sources[0].competitor = "Comparison page"
    detail.raw_sources[0].covered_competitors = ["Product A", "Product B"]
    accepted = seal(detail, phase="analysis", canonical_documents={})
    assert len(accepted.sources) == 1
    assert all(fact.competitor == "Product A" for fact in accepted.facts)
    detail.raw_sources[0].covered_competitors.append("Product A Pro")
    rejected_again = seal(detail, phase="analysis", canonical_documents={})
    assert rejected_again.sources == ()


def test_invalid_normalized_fields_never_enter_projection() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata["normalized_fields"].extend(
        [
            {"kind": "arbitrary", "workflow": "PRIVATE_WORKFLOW"},
            {"kind": "pricing", "competitor": "Product A Pro", "price": "PRIVATE_MODEL"},
            {"kind": "pricing", "dimension": "other", "price": "PRIVATE_DIMENSION"},
            {"kind": "pricing", "price": "PRIVATE_CONFIDENCE", "confidence": 99},
        ]
    )
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert "PRIVATE_" not in snapshot.model_dump_json()


def test_recalled_kb_extraction_time_and_rank_do_not_refresh_original_dates() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    doc = make_document()
    first = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    detail.raw_sources[0].extracted_at = datetime(2027, 1, 1, tzinfo=UTC)
    detail.raw_sources[0].candidate_rank = 100
    second = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert second.id == first.id
    assert second.sources[0].source_fetched_at == doc.fetched_at


@pytest.mark.parametrize(
    "reference",
    [
        {"document_id": "missing-document"},
        {"kb_retrieved": True},
        {"source_material_level": "kb_retrieval_chunk"},
    ],
)
def test_kb_reference_aliases_and_missing_ids_cannot_bypass_canonical_check(reference) -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata.update(reference)
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert snapshot.sources == ()
    assert snapshot.gaps[0].reason in {
        "canonical_document_missing",
        "canonical_reference_missing",
    }


def test_snapshot_models_import_directly_in_a_fresh_interpreter() -> None:
    import os
    import subprocess
    import sys

    environment = os.environ.copy()
    environment["COMPETISCOPE_LOAD_ENV_FILES"] = "0"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from packages.research.evidence.snapshot_models import RunEvidenceSnapshot",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_summary_material_cannot_be_promoted_by_quote_and_ids() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata["source_material_level"] = "summary"
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert snapshot.facts
    assert all(fact.status == "signal" for fact in snapshot.facts)


def test_normalized_market_is_preserved_without_overriding_canonical_market() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata.pop("market")
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert next(fact for fact in snapshot.facts if fact.field == "price").market == "CN"
    detail = with_document(make_detail())
    detail.raw_sources[0].metadata["normalized_fields"][0]["market"] = "spoofed-market"
    doc = make_document()
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert "spoofed-market" not in snapshot.model_dump_json()
    assert next(fact for fact in snapshot.facts if fact.field == "price").market == doc.market


def test_different_capacities_units_markets_and_unknown_basis_are_not_merged() -> None:
    seal, _, _ = snapshot_api()
    for changed_field in ("capacity", "unit", "market"):
        detail = make_detail()
        other = make_detail(price="4299 CNY").raw_sources[0]
        other.id = "other-price"
        detail.raw_sources[0].metadata["normalized_fields"][0][changed_field] = "one"
        other.metadata["normalized_fields"][0][changed_field] = "two"
        detail.raw_sources.append(other)
        snapshot = seal(detail, phase="analysis", canonical_documents={})
        assert not snapshot.conflicts, changed_field
    detail = make_detail()
    other = make_detail(price="4299 CNY").raw_sources[0]
    other.id = "other-price"
    detail.raw_sources.append(other)
    for raw in detail.raw_sources:
        raw.metadata["normalized_fields"][0].pop("unit")
    unknown = seal(detail, phase="analysis", canonical_documents={})
    assert unknown.conflicts[0].status == "unknown"


def test_duplicate_fact_positions_have_unambiguous_ids_and_stable_semantic_identity() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    row = dict(detail.raw_sources[0].metadata["normalized_fields"][0])
    row.update(price="4299 CNY", evidence_item_ids=["another-observation"])
    detail.raw_sources[0].metadata["normalized_fields"].append(row)
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    prices = [fact for fact in snapshot.facts if fact.field == "price"]
    assert len({fact.id for fact in prices}) == 2
    assert len({fact.semantic_id for fact in prices}) == 1
    assert len(snapshot.conflicts) == 1


def test_invalid_kb_version_type_is_rejected() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    detail.raw_sources[0].metadata["kb_document_version"] = 2.0
    doc = make_document()
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert not snapshot.sources
    assert snapshot.gaps[0].reason == "version_mismatch"


@pytest.mark.parametrize("level", ["summary", "search_summary", "historical_report"])
@pytest.mark.parametrize("basis", ["canonical", "raw", "canonical_with_raw_upgrade"])
def test_canonical_reference_keeps_low_quality_material_as_signal(level, basis) -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    doc = make_document()
    if basis in {"canonical", "canonical_with_raw_upgrade"}:
        doc.metadata["source_material_level"] = level
    if basis == "raw":
        detail.raw_sources[0].metadata["source_material_level"] = level
    elif basis == "canonical_with_raw_upgrade":
        detail.raw_sources[0].metadata["source_material_level"] = "full_source"
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert snapshot.sources[0].material_level == level
    assert snapshot.facts and all(fact.status == "signal" for fact in snapshot.facts)


def test_explicit_qualifiers_preserve_tax_basis_and_do_not_merge_positions() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    other = make_detail(price="4299 CNY").raw_sources[0]
    other.id = "tax-exclusive-price"
    detail.raw_sources[0].metadata["normalized_fields"][0]["qualifiers"] = {
        "tax_included": True,
        "capacity": {"amount": 256, "unit": "GB"},
    }
    other.metadata["normalized_fields"][0]["qualifiers"] = {
        "capacity": {"unit": "GB", "amount": 256},
        "tax_included": False,
    }
    detail.raw_sources.append(other)
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert not snapshot.conflicts
    prices = [fact for fact in snapshot.facts if fact.field == "price"]
    assert {fact.qualifiers["tax_included"] for fact in prices} == {True, False}
    assert all(fact.qualifiers["capacity"] == {"amount": 256, "unit": "GB"} for fact in prices)
    projection = snapshot.sources[0].to_raw_source()
    assert "qualifiers" in projection.metadata["normalized_fields"][0]


def test_explicit_qualifier_change_creates_new_semantic_identity_and_version() -> None:
    seal, _, changes = snapshot_api()
    detail = make_detail()
    row = detail.raw_sources[0].metadata["normalized_fields"][0]
    row["qualifiers"] = {"tax_included": True}
    first = seal(detail, phase="analysis", canonical_documents={})
    row["qualifiers"]["tax_included"] = False
    second = seal(detail, phase="analysis", canonical_documents={})
    assert second.version == first.version + 1
    assert second.content_hash != first.content_hash
    assert changes(first, second).added_facts
    assert changes(first, second).removed_facts
    assert all(fact.qualifiers["tax_included"] is True for fact in first.facts)


def test_explicit_qualifiers_drop_injection_fields_at_every_level() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    forbidden = (
        "credentials",
        "api_key",
        "instructions",
        "system_prompt",
        "workflow",
        "full_text",
        "metadata",
        "html",
        "password",
        "token",
        "raw_text",
    )
    row = detail.raw_sources[0].metadata["normalized_fields"][0]
    row["qualifiers"] = {
        "tax_included": True,
        **{key: f"PRIVATE_{key}" for key in forbidden},
        "capacity": {
            "amount": 256,
            "unit": "GB",
            **{key: f"PRIVATE_NESTED_{key}" for key in forbidden},
        },
    }
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert "PRIVATE_" not in snapshot.model_dump_json()
    price = next(fact for fact in snapshot.facts if fact.field == "price")
    assert price.qualifiers["tax_included"] is True
    assert price.qualifiers["capacity"] == {"amount": 256, "unit": "GB"}


@pytest.mark.parametrize(
    "marker",
    [
        "kb_document_version",
        "kb_document_content_hash",
        "kb_content_hash",
        "kb_chunk_id",
        "kb_chunk_ids",
        "kb_document_workspace_id",
        "kb_document_project_id",
        "kb_source_role",
        "kb_document_status",
        "kb_parent_document_id",
        "kb_document_source_type",
        "kb_document_url",
        "kb_canonical_url",
        "kb_competitor",
        "kb_competitor_name",
        "kb_dimension",
        "kb_market",
        "kb_source_type",
        "kb_fetched_at",
        "kb_last_verified_at",
        "kb_source_published_at",
        "kb_source_updated_at",
        "document_version",
        "chunk_id",
    ],
)
def test_kb_identity_marker_without_document_id_is_rejected(marker) -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    detail.raw_sources[0].metadata[marker] = None if marker.endswith("project_id") else "declared"
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    assert snapshot.sources == ()
    assert snapshot.facts == ()
    assert snapshot.gaps[0].reason == "canonical_reference_missing"


def test_kb_retrieval_diagnostics_are_not_identity_markers_or_content() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    first = seal(detail, phase="analysis", canonical_documents={})
    detail.raw_sources[0].metadata.update(
        {
            "kb_hit_score": 0.2,
            "kb_rerank_score": 0.3,
            "kb_retrieval_rank": 42,
            "kb_retrieval_query": "Product A pricing",
            "kb_rerank_model": "test-model",
        }
    )
    second = seal(detail, phase="analysis", canonical_documents={})
    assert second.id == first.id
    assert second.sources and not second.gaps


def test_distinct_observations_keep_original_ids_and_unique_record_ids() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    original = detail.raw_sources[0].metadata["normalized_fields"][0]
    correction = dict(original, price="4299 CNY", source_quote="Base price changed to 4299 CNY")
    detail.raw_sources[0].metadata["normalized_fields"] = [original, correction, dict(original)]
    first = seal(detail, phase="analysis", canonical_documents={})
    prices = [fact for fact in first.facts if fact.field == "price"]
    assert len(prices) == 2
    assert len({fact.id for fact in prices}) == 2
    assert len({fact.semantic_id for fact in prices}) == 1
    assert all(fact.evidence_item_ids == ("item-product-a-price",) for fact in prices)
    conflict = first.conflicts[0]
    by_id = {fact.id: fact for fact in first.facts}
    assert {by_id[fact_id].value for fact_id in conflict.fact_ids} == {"3999 CNY", "4299 CNY"}
    detail.raw_sources[0].metadata["normalized_fields"].reverse()
    reordered = seal(detail, phase="analysis", canonical_documents={})
    assert reordered.id == first.id


def test_equal_values_with_different_quotes_have_distinct_observation_ids() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    original = detail.raw_sources[0].metadata["normalized_fields"][0]
    same_value = dict(original, source_quote="Another quote supports Base price 3999 CNY")
    detail.raw_sources[0].metadata["normalized_fields"].append(same_value)
    snapshot = seal(detail, phase="analysis", canonical_documents={})
    prices = [fact for fact in snapshot.facts if fact.field == "price"]
    assert len({fact.id for fact in prices}) == 2
    assert len({fact.semantic_id for fact in prices}) == 1


@pytest.mark.parametrize("kind", ["fact", "conflict"])
@pytest.mark.parametrize("qualifiers_json", ["[]", "null", "1", "true", '"scope"', "not json"])
def test_fact_and_conflict_qualifiers_require_json_objects(kind, qualifiers_json) -> None:
    from packages.research.evidence.snapshot_models import EvidenceConflict, EvidenceFact

    if kind == "fact":
        fields = dict(
            id="fact",
            semantic_id="semantic",
            source_id="source",
            competitor="Product A",
            dimension="pricing",
            field="price",
            value_json="3999",
            confidence=0.8,
        )
        model = EvidenceFact
    else:
        fields = dict(
            id="conflict",
            competitor="Product A",
            dimension="pricing",
            field="price",
            fact_ids=("fact-a", "fact-b"),
            source_ids=("source",),
        )
        model = EvidenceConflict
    with pytest.raises(ValidationError):
        model(**fields, qualifiers_json=qualifiers_json)


@pytest.mark.parametrize("kind", ["fact", "conflict"])
def test_qualifier_objects_are_canonical_and_decode_to_fresh_nested_values(kind) -> None:
    from packages.research.evidence.snapshot_models import EvidenceConflict, EvidenceFact

    qualifiers = ' { "tax_included" : true, "capacity" : [{"amount": 256}] } '
    if kind == "fact":
        record = EvidenceFact(
            id="fact",
            semantic_id="semantic",
            source_id="source",
            competitor="Product A",
            dimension="pricing",
            field="price",
            value_json=' [3999, {"tax": true}] ',
            confidence=0.8,
            qualifiers_json=qualifiers,
        )
        assert record.value == [3999, {"tax": True}]
    else:
        record = EvidenceConflict(
            id="conflict",
            competitor="Product A",
            dimension="pricing",
            field="price",
            fact_ids=("fact-a", "fact-b"),
            source_ids=("source",),
            qualifiers_json=qualifiers,
        )
    assert record.qualifiers_json == '{"capacity":[{"amount":256}],"tax_included":true}'
    record.qualifiers["capacity"][0]["amount"] = 512
    assert record.qualifiers["capacity"][0]["amount"] == 256


def test_original_capture_fetched_at_alias_is_preserved_and_changes_version() -> None:
    seal, _, _ = snapshot_api()
    detail = make_detail()
    source = detail.raw_sources[0]
    source.metadata["fetched_at"] = "2026-10-01T00:00:00+00:00"
    first = seal(detail, phase="analysis", canonical_documents={})
    assert first.sources[0].source_fetched_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert (
        first.sources[0].to_raw_source().metadata["source_fetched_at"]
        == source.metadata["fetched_at"]
    )
    source.metadata["fetched_at"] = "2026-10-02T00:00:00+00:00"
    second = seal(detail, phase="analysis", canonical_documents={})
    assert second.version == first.version + 1
    assert first.sources[0].source_fetched_at == datetime(2026, 10, 1, tzinfo=UTC)


def test_raw_capture_alias_never_overrides_canonical_fetched_at() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    detail.raw_sources[0].metadata["fetched_at"] = "2099-01-01T00:00:00+00:00"
    doc = make_document()
    first = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert first.sources[0].source_fetched_at == doc.fetched_at
    detail.raw_sources[0].metadata["fetched_at"] = "2098-01-01T00:00:00+00:00"
    second = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert second.id == first.id


@pytest.mark.parametrize(
    "kind,quote_key,field",
    [
        ("pricing", "source_quote", "price"),
        ("feature", "evidence_quote", "support_level"),
    ],
)
def test_complete_original_quote_is_saved_and_tail_correction_increases_version(
    kind, quote_key, field
):
    seal, _, changes = snapshot_api()
    detail = make_detail()
    row = detail.raw_sources[0].metadata["normalized_fields"][0]
    if kind == "feature":
        detail.raw_sources[0].dimension = "feature"
        row = dict(
            kind="feature",
            competitor="Product A",
            dimension="feature",
            slot="support",
            support_level="supported",
            evidence_item_ids=["feature-evidence"],
            confidence=0.8,
        )
        detail.raw_sources[0].metadata["normalized_fields"] = [row]
    original_quote = (
        "  Original evidence line\n" + "Product support price evidence. " * 20 + "Tax included  "
    )
    row[quote_key] = original_quote
    first = seal(detail, phase="analysis", canonical_documents={})
    original_fact = next(fact for fact in first.facts if fact.field == field)
    assert original_fact.quote == original_quote
    assert (
        first.sources[0].to_raw_source().metadata["normalized_fields"][0][quote_key]
        == original_quote
    )
    row[quote_key] = original_quote.replace("Tax included", "Tax excluded")
    second = seal(detail, phase="analysis", canonical_documents={})
    assert second.version == first.version + 1
    assert original_fact.semantic_id in changes(first, second).changed_facts
    assert original_fact.quote == original_quote


def test_raw_covered_competitor_cannot_extend_canonical_document_identity() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    detail.raw_sources[0].covered_competitors = ["Product B"]
    detail.raw_sources[0].metadata["normalized_fields"][0]["competitor"] = "Product B"
    doc = make_document()
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert not snapshot.sources
    assert not snapshot.facts
    assert snapshot.gaps[0].reason == "identity_mismatch"
    assert detail.raw_sources[0].covered_competitors == ["Product B"]


def test_canonical_product_can_be_explicitly_covered_without_losing_its_facts() -> None:
    seal, _, _ = snapshot_api()
    detail = with_document(make_detail())
    detail.raw_sources[0].covered_competitors = [" product a "]
    doc = make_document()
    snapshot = seal(detail, phase="analysis", canonical_documents={doc.id: doc})
    assert snapshot.facts
    assert all(fact.competitor == "Product A" for fact in snapshot.facts)
