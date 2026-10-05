from __future__ import annotations

import json
from datetime import date

import pytest
from test_run_evidence_snapshot import STAMP, make_detail
from test_stage_evidence_views import FixedTime

# isort: split
from packages.config import Settings
from packages.i18n.language import report_label
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.answer_models import AnswerRequirement
from packages.research.evidence.normalization import normalized_pricing_fields_from_evidence_items
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.models import EvidenceItem
from packages.schema.api_dto import RunDetail
from packages.schema.report_artifact import (
    ClaimCard,
    ClaimCardBundle,
    ReportArtifactLegacyInfo,
    ReportArtifactRenderCache,
    ReportArtifactV2,
    ReportLayer,
)
from packages.skills.registry import SkillRegistry


def fixture_detail(*, amount=3999):
    detail = make_detail(price={"amount": amount, "currency": "CNY"})
    detail.plan.competitors = ["Product A"]
    detail.plan.dimensions = ["pricing"]
    detail.raw_sources[0].metadata["source_material_level"] = "full_source"
    detail.raw_sources[0].metadata["normalized_fields"][0]["qualifiers"] = {
        "price_type": "official_current",
        "price_basis": "device",
        "model": "Base",
        "capacity": "256 GB",
        "condition": "new",
        "billing_interval": "one_time",
        "tax_scope": "included",
        "verified_at": STAMP,
    }
    return detail


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    service = RunService(
        settings=Settings(demo_mode=True, analyst_react_enabled=False),
        skill_registry=SkillRegistry.from_default_path(),
        journal=RunJournal(tmp_path / "journal.db"),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail=fixture_detail())
    service._runs[record.detail.id] = record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    return service, record


def segment(record, **extra):
    return {
        "segment_name": "competitor_deep_dives",
        "segment_competitor": "Product A",
        "dimension": record.detail.plan.dimensions[0],
        "allowed_source_ids": [source.id for source in record.detail.raw_sources],
        **extra,
    }


async def render_segment(service, record):
    return await service._writer_segment_markdown(
        record,
        segment=segment(record),
        timeout_seconds=5,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
        retry_count=0,
    )


def stub_generator(service, monkeypatch, text, observed=None, mutation=None):
    async def generate(record, **kwargs):
        if observed is not None:
            observed.append(kwargs)
        if mutation is not None:
            mutation()
        return text

    monkeypatch.setattr(service, "_trace_llm_text", generate)


def bind_actual_segment(service, record):
    selected, use = service._writer_segment_evidence(record, segment(record))
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    return selected, use


@pytest.mark.asyncio
async def test_actual_writer_segment_receives_boundary_in_its_utf8_budget(runtime, monkeypatch):
    service, record = runtime
    observed = []
    stub_generator(service, monkeypatch, "Evidence remains limited.", observed)
    assert await render_segment(service, record) == "Evidence remains limited."
    prompt = observed[0]["user"].split("Segment Context JSON: ", 1)[1].split("\n\n", 1)[0]
    payload = json.loads(prompt)
    assert payload.get("answer_boundaries"), "Actual generation lacks the shared answer guard"
    assert payload["answer_guard_instructions"]
    boundary = record.detail.report_answer_boundaries[0]
    assert boundary.requirement.as_of == date(2026, 10, 3)
    assert boundary.requirement.intent == "current_price"
    assert boundary.status == "answer", boundary.model_dump_json()
    use = record.detail.evidence_consumptions[-1]
    assert len(prompt.encode("utf-8")) == use.estimated_bytes <= use.max_bytes
    assert boundary.view_source_ids == use.source_ids
    assert boundary.view_fact_ids == use.fact_ids


@pytest.mark.asyncio
async def test_real_writer_commit_persists_boundary_and_binds_producer(runtime, monkeypatch):
    service, record = runtime
    language = record.detail.output_language
    stub_generator(
        service,
        monkeypatch,
        f"## {report_label(language, 'executive_summary')}\n\n"
        "Known price CNY 3999. [source:source-product-a-pricing]"
        f"\n\n## {report_label(language, 'competitive_findings')}\n\n"
        "Product A has limited evidence; verify other prices.",
    )
    await service._real_writer_step(record)
    assert getattr(record.detail, "report_answer_boundaries", []), "Writer commit lost boundaries"
    stored = service._journal.load_run(record.detail.id)
    assert stored.report_answer_boundaries == record.detail.report_answer_boundaries
    payload = service._writer_evidence_artifact_payload(record.detail)
    assert payload["answer_boundaries"]
    assert service._final_qa_producer_verified(record, service._final_qa_snapshot(record))


def test_boundary_cannot_be_silently_dropped_to_fit_budget(runtime):
    service, record = runtime
    # The existing view fits, but the mandatory boundary/control contract cannot.
    from packages.orchestrator import evidence_context

    original = evidence_context._DEPTH_BYTES["quick"]
    evidence_context._DEPTH_BYTES["quick"] = 2600
    try:
        with pytest.raises(EvidenceUseRejectedError, match="budget"):
            service._writer_segment_evidence(record, segment(record))
        assert record.detail.evidence_consumptions[-1].status == "rejected"
    finally:
        evidence_context._DEPTH_BYTES["quick"] = original


@pytest.mark.asyncio
async def test_recent_fetch_of_launch_price_is_withheld_and_qa_repairs_writer(runtime):
    service, record = runtime
    row = record.detail.raw_sources[0].metadata["normalized_fields"][0]
    row["qualifiers"]["price_type"] = "launch"
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Current price CNY 3999. [source:source-product-a-pricing]"
    selected, _ = bind_actual_segment(service, record)
    assert selected.get("answer_boundaries"), "Writer lacks the launch price boundary"
    _, issues, _ = await service._final_qa_evidence(record)
    guard_issues = [issue for issue in issues if issue.metadata.get("answer_guard_reason")]
    assert guard_issues and all(issue.redo_scope.kind == "writer_only" for issue in guard_issues)


@pytest.mark.asyncio
async def test_allowed_amount_does_not_support_other_rows_or_currency(runtime):
    service, record = runtime
    record.detail.report_md = (
        "| Product | Price |\n|---|---|\n"
        "| A | CNY 3999 [source:source-product-a-pricing] |\n"
        "| B | CNY 3999 |\n| C | USD 3999 [source:source-product-a-pricing] |"
    )
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert len([issue for issue in issues if issue.metadata.get("answer_guard_reason")]) == 2


def test_legacy_models_and_payload_keep_the_old_shape(runtime):
    service, record = runtime
    restored = RunDetail.model_validate(make_detail().model_dump(mode="json"))
    assert getattr(restored.plan, "answer_requirements", None) == []
    assert getattr(restored, "report_answer_boundaries", None) == []
    assert set(service._writer_evidence_artifact_payload(record.detail)) == {
        "report_md",
        "artifact",
    }


@pytest.mark.asyncio
async def test_empty_boundaries_allow_methods_and_clarification_without_currency(runtime):
    service, record = runtime
    record.detail.raw_sources.clear()
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    selected, use = service._writer_segment_evidence(record, segment(record, allowed_source_ids=[]))
    record.detail.report_md = "Please clarify the market; verify official terms and dated records."
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    assert selected.get("answer_boundaries")
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues


def set_requirement(record, intent, context=None):
    requirement = AnswerRequirement(
        competitor="Product A",
        dimension=record.detail.plan.dimensions[0],
        intent=intent,
        market="CN",
        as_of=date(2026, 10, 3),
        context_json=canonical_json(context or {}),
    )
    record.detail.plan.answer_requirements = [requirement]
    return requirement


def attach_card(record, *, claim_type="feature_claim", source_ids=None, fact_ids=None):
    source_ids = source_ids if source_ids is not None else [record.detail.raw_sources[0].id]
    card = ClaimCard(
        id="claim-guard",
        run_id=record.detail.id,
        competitor="Product A",
        dimension=record.detail.plan.dimensions[0],
        claim_type=claim_type,
        claim="Explicit structured conclusion",
        source_ids=source_ids,
        confidence=0.8,
        evidence_strength="moderate",
        support_level="official",
        scope="CN",
        applicability="Declared use",
        producer_stage="analyst",
        metadata={"fact_ids": fact_ids} if fact_ids is not None else {},
    )
    record.detail.report_artifact = ReportArtifactV2(
        run_id=record.detail.id,
        core_report=ReportLayer(layer="core"),
        render_cache=ReportArtifactRenderCache(),
        legacy=ReportArtifactLegacyInfo(source="report_md"),
        claim_card_bundles=[
            ClaimCardBundle(
                run_id=record.detail.id,
                competitor="Product A",
                dimension=card.dimension,
                cards=[card],
            )
        ],
    )
    return card


def rebind_payload(service, record):
    dependency = next(
        item for item in record.detail.evidence_artifact_dependencies if item.kind == "writer"
    )
    uses = [
        item
        for item in record.detail.evidence_consumptions
        if item.id in dependency.consumption_ids
    ]
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=uses,
        payload=service._writer_evidence_artifact_payload(record.detail),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "## Price CNY 9999 [source:source-product-a-pricing]",
        "Price CNY -3999. [source:source-product-a-pricing]",
        "Price -3999 CNY. [source:source-product-a-pricing]",
        "Price -CNY3999. [source:source-product-a-pricing]",
        "Price -$3999. [source:source-product-a-pricing]",
        "Price SEK9999. [source:source-product-a-pricing]",
        "Price 9999 NOK. [source:source-product-a-pricing]",
        "Price cny9999. [source:source-product-a-pricing]",
        "Price usd3999. [source:source-product-a-pricing]",
    ],
)
async def test_headings_and_signed_amounts_cannot_escape_audit(runtime, text):
    service, record = runtime
    record.detail.report_md = text
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        issue.metadata.get("answer_guard_reason") == "withheld_or_unsupported_amount"
        for issue in issues
    )


def test_unrelated_dimension_facts_do_not_make_complete_price_partial(runtime):
    service, record = runtime
    other = fixture_detail().raw_sources[0].model_copy(deep=True)
    other.id = "other-feature"
    other.dimension = "feature"
    other.metadata["normalized_fields"] = [
        {
            "kind": "feature",
            "dimension": "feature",
            "competitor": "Product A",
            "slot": "integration",
            "support_level": "supported",
            "confidence": 0.8,
            "evidence_quote": "Supports integration",
            "evidence_item_ids": ["feature-item"],
        }
    ]
    record.detail.plan.dimensions.append("feature")
    record.detail.raw_sources.append(other)
    record.detail.plan.research_depth = "deep"
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    selected, _ = service._writer_segment_evidence(record, segment(record, dimension=None))
    price = next(
        item
        for item in selected["answer_boundaries"]
        if item["requirement"]["dimension"] == "pricing"
    )
    assert price["status"] == "answer"


@pytest.mark.asyncio
async def test_structured_complete_cost_requires_its_own_declared_sources(runtime):
    service, record = runtime
    set_requirement(
        record,
        "total_cost",
        {
            "currency": "CNY",
            "reporting_period": "2026-10",
            "required_components": ["subscription"],
        },
    )
    row = record.detail.raw_sources[0].metadata["normalized_fields"][0]
    row["qualifiers"] = {
        "verified_at": STAMP,
        "charge_id": "charge-subscription",
        "reporting_period": "2026-10",
        "cost_component": "subscription",
    }
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    selected, _ = bind_actual_segment(service, record)
    assert selected["answer_boundaries"][0]["status"] == "answer"
    attach_card(record, claim_type="total_cost_conclusion", source_ids=["unseen-source"])
    rebind_payload(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        issue.metadata.get("answer_guard_reason") == "incomplete_structured_conclusion"
        for issue in issues
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent,context,expected,missing",
    [
        ("price_comparison", {}, "clarify", "channels"),
        ("source_guidance", {}, "partial", "structured_facts"),
        ("compliance", {}, "clarify", "industry"),
        (
            "total_cost",
            {
                "currency": "CNY",
                "reporting_period": "2026-10",
                "required_components": ["subscription", "app_payment"],
            },
            "partial",
            "cost_component.app_payment",
        ),
    ],
)
async def test_four_offline_intents_preserve_methods_and_missing_fields(
    runtime, intent, context, expected, missing
):
    service, record = runtime
    source = record.detail.raw_sources[0]
    if intent == "source_guidance":
        source.metadata["normalized_fields"] = []
    elif intent == "compliance":
        record.detail.plan.dimensions = ["feature"]
        source.dimension = "feature"
        source.metadata["normalized_fields"] = [
            {
                "kind": "feature",
                "competitor": "Product A",
                "dimension": "feature",
                "slot": "integration",
                "support_level": "supported",
                "confidence": 0.8,
                "evidence_quote": "Integration notes exist",
                "evidence_item_ids": ["feature-notes"],
            }
        ]
    elif intent == "total_cost":
        source.metadata["normalized_fields"][0]["qualifiers"] = {
            "verified_at": STAMP,
            "charge_id": "charge-subscription",
            "reporting_period": "2026-10",
            "cost_component": "subscription",
        }
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    set_requirement(record, intent, context)
    selected, use = bind_actual_segment(service, record)
    boundary = selected["answer_boundaries"][0]
    assert boundary["status"] == expected
    if missing:
        assert missing in boundary["missing_fields"] + boundary["clarification_fields"]
    record.detail.report_md = "Check original dated records and clarify the missing scope."
    rebind_payload(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues
    assert use.snapshot_id == boundary["snapshot_id"]
    if intent == "total_cost":
        assert "cost_component.subscription" not in boundary["missing_fields"]


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 3999])
async def test_structured_official_unit_price_and_zero_are_publishable(runtime, amount):
    service, record = runtime
    record.detail = fixture_detail(amount=amount)
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = f"Recorded price CNY {amount}. [source:source-product-a-pricing]"
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues


@pytest.mark.asyncio
async def test_declared_withheld_fact_is_writer_issue(runtime):
    service, record = runtime
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["qualifiers"]["price_type"] = (
        "launch"
    )
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    fact_id = next(item.id for item in snapshot.facts if item.field == "price")
    attach_card(record, fact_ids=[fact_id])
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    issue = next(
        item
        for item in issues
        if item.metadata.get("answer_guard_reason") == "withheld_or_unseen_fact"
    )
    assert issue.redo_scope.kind == "writer_only" and issue.metadata["fact_ids"] == [fact_id]


@pytest.mark.asyncio
async def test_new_snapshot_extra_price_cannot_replace_generation_view(runtime):
    service, record = runtime
    record.detail.report_md = "Price CNY 4999. [source:source-product-a-pricing]"
    _, use = bind_actual_segment(service, record)
    other = fixture_detail(amount=4999).raw_sources[0]
    other.id = "new-source"
    record.detail.raw_sources.append(other)
    current = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    assert current.id != use.snapshot_id
    assert service._final_qa_snapshot(record).id == use.snapshot_id
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("answer_guard_reason") == "withheld_or_unsupported_amount"
        for item in issues
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["boundary", "report", "requirement"])
async def test_producer_rejects_mutated_boundary_report_or_requirement(runtime, mutation):
    service, record = runtime
    bind_actual_segment(service, record)
    if mutation == "boundary":
        boundary = record.detail.report_answer_boundaries[0]
        record.detail.report_answer_boundaries[0] = boundary.model_copy(
            update={"allowed_fact_ids": ()}
        )
    elif mutation == "report":
        record.detail.report_md = "Changed after generation"
    else:
        set_requirement(record, "price_comparison")
    assert not service._final_qa_producer_verified(record, service._final_qa_snapshot(record))
    _, issues, _ = await service._final_qa_evidence(record)
    assert issues and all(item.redo_scope.kind == "writer_only" for item in issues)


@pytest.mark.asyncio
async def test_requirement_mutation_during_generation_cannot_commit(runtime, monkeypatch):
    service, record = runtime
    previous = "Previous readable report"
    record.detail.report_md = previous
    stub_generator(
        service,
        monkeypatch,
        "New generated report",
        mutation=lambda: set_requirement(record, "compliance"),
    )
    with pytest.raises(EvidenceUseRejectedError, match="analysis artifacts changed"):
        await service._real_writer_step(record)
    assert record.detail.report_md == previous
    assert record.detail.report_answer_boundaries == []


@pytest.mark.asyncio
async def test_preserved_report_keeps_original_boundaries_and_producer(runtime, monkeypatch):
    service, record = runtime
    language = record.detail.output_language
    record.detail.report_md = (
        f"## {report_label(language, 'executive_summary')}\n\nPrevious readable report."
        f"\n\n## {report_label(language, 'competitive_findings')}\n\nLimited evidence."
    )
    bind_actual_segment(service, record)
    old = list(record.detail.report_answer_boundaries)
    producer = next(
        item for item in record.detail.evidence_artifact_dependencies if item.kind == "writer"
    )

    async def unavailable(*args, **kwargs):
        raise TimeoutError("fixed local generator failure")

    monkeypatch.setattr(service, "_trace_llm_text", unavailable)
    await service._real_writer_step(record)
    assert record.detail.report_answer_boundaries == old
    assert (
        next(item for item in record.detail.evidence_artifact_dependencies if item.kind == "writer")
        == producer
    )


@pytest.mark.asyncio
async def test_audit_quotes_are_readable_and_support_claims_still_checked(runtime):
    service, record = runtime
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["qualifiers"]["price_type"] = (
        "launch"
    )
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = (
        "<!-- report-section:key=evidence_support layer=support -->\n## Evidence support\n\n"
        "Current price CNY 3999. [source:source-product-a-pricing]\n\n"
        "<!-- report-section:key=raw_quotes layer=audit -->\n## Original quote audit\n\n"
        "Old launch quote CNY 3999. [source:source-product-a-pricing]"
    )
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert len([item for item in issues if item.metadata.get("answer_guard_reason")]) == 1


@pytest.mark.asyncio
async def test_compliance_verdict_requires_declared_conditions(runtime):
    service, record = runtime
    set_requirement(record, "compliance")
    attach_card(record, claim_type="compliance_verdict")
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("answer_guard_reason") == "incomplete_structured_conclusion"
        for item in issues
    )


def test_actual_pricing_normalization_keeps_legacy_string_price_withheld(runtime):
    service, record = runtime
    fields = normalized_pricing_fields_from_evidence_items(
        [
            EvidenceItem(
                competitor="Product A",
                dimension="pricing",
                field="price_rows",
                value=[{"tier_name": "Base", "price": "3999 CNY", "billing_cycle": "one_time"}],
                source_candidate_id="fixed-candidate",
                captured_page_id="fixed-page",
                source_url="https://product-a.example/pricing",
                quote="Base price 3999 CNY",
                confidence=0.8,
                status="accepted",
            )
        ]
    )
    assert fields[0].price == "3999 CNY"
    record.detail.raw_sources[0].metadata["normalized_fields"] = [
        item.model_dump(mode="json") for item in fields
    ]
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    selected, _ = service._writer_segment_evidence(record, segment(record))
    boundary = selected["answer_boundaries"][0]
    price_id = next(item.id for item in snapshot.facts if item.field == "price")
    assert price_id in boundary["withheld_fact_ids"]
    assert {"amount", "currency", "price_type", "price_basis"} <= set(boundary["missing_fields"])
    assert boundary["status"] != "answer"


@pytest.mark.asyncio
async def test_real_generation_failure_never_commits_initial_read_boundaries(runtime, monkeypatch):
    service, record = runtime

    async def unavailable(*args, **kwargs):
        raise TimeoutError("fixed local failure")

    monkeypatch.setattr(service, "_trace_llm_text", unavailable)
    with pytest.raises(RuntimeError, match="Writer failed"):
        await service._real_writer_step(record)
    assert record.detail.report_md == ""
    assert record.detail.report_answer_boundaries == []
    assert not any(item.kind == "writer" for item in record.detail.evidence_artifact_dependencies)
    assert service._journal.load_run(record.detail.id).report_answer_boundaries == []


def test_default_market_does_not_choose_one_of_multiple_regions(runtime):
    service, record = runtime
    other = fixture_detail().raw_sources[0].model_copy(deep=True)
    other.id = "source-us"
    other.metadata["market"] = "US"
    other.metadata["normalized_fields"][0]["market"] = "US"
    record.detail.raw_sources.append(other)
    record.detail.plan.research_depth = "deep"
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    selected, _ = service._writer_segment_evidence(record, segment(record))
    boundary = selected["answer_boundaries"][0]
    assert boundary["requirement"]["market"] is None
    assert boundary["status"] == "clarify"
    assert "market" in boundary["clarification_fields"]


@pytest.mark.asyncio
async def test_actual_source_revocation_still_uses_collector_repair(runtime):
    service, record = runtime
    record.detail.report_md = "Price CNY 3999. [source:source-product-a-pricing]"
    bind_actual_segment(service, record)
    record.detail.raw_sources.clear()
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.redo_scope.kind == "collector"
        and item.metadata.get("evidence_reason") == "source_dependency_changed"
        for item in issues
    )


@pytest.mark.asyncio
async def test_rehashed_tampered_boundary_still_fails_original_view_replay(runtime):
    service, record = runtime
    bind_actual_segment(service, record)
    boundary = record.detail.report_answer_boundaries[0]
    record.detail.report_answer_boundaries[0] = boundary.model_copy(update={"allowed_fact_ids": ()})
    rebind_payload(service, record)
    assert service._final_qa_producer_verified(record, service._final_qa_snapshot(record))
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("answer_guard_reason") == "answer_boundary_replay_mismatch"
        for item in issues
    )


@pytest.mark.asyncio
async def test_claim_only_source_revocation_still_requires_collector(runtime):
    service, record = runtime
    set_requirement(
        record,
        "total_cost",
        {
            "currency": "CNY",
            "reporting_period": "2026-10",
            "required_components": ["subscription"],
        },
    )
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["qualifiers"] = {
        "verified_at": STAMP,
        "charge_id": "charge-subscription",
        "reporting_period": "2026-10",
        "cost_component": "subscription",
    }
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    attach_card(record, claim_type="total_cost_conclusion")
    bind_actual_segment(service, record)
    record.detail.raw_sources.clear()
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    assert not record.detail.report_md
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.redo_scope.kind == "collector"
        and item.metadata.get("evidence_reason") == "source_dependency_changed"
        for item in issues
    )


@pytest.mark.asyncio
async def test_claim_text_amount_is_checked_without_fact_ids_or_markdown_money(runtime):
    service, record = runtime
    card = attach_card(record, claim_type="pricing_fact")
    card.claim = "Current price CNY 9999."
    record.detail.report_md = "Pricing requires validation."
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    issue = next(
        (
            item
            for item in issues
            if item.metadata.get("answer_guard_reason") == "withheld_or_unsupported_amount"
        ),
        None,
    )
    assert issue is not None and issue.field_path == "report.claim_cards.claim-guard.claim"
    assert issue.redo_scope.kind == "writer_only"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "There are 3 channels; verify SKU 3999, CPU 4, and RAM 16.",
        "Check all 3 sources; try 3 queries and inspect the top 3 results.",
        "- CNY3999 [source:source-product-a-pricing]",
        "- CNY 3999 [source:source-product-a-pricing]",
    ],
)
async def test_currency_audit_keeps_methods_and_positive_markdown_lists(runtime, text):
    service, record = runtime
    record.detail.report_md = text
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues


@pytest.mark.asyncio
async def test_legacy_empty_bounds_do_not_add_claim_source_audit(runtime):
    service, record = runtime
    attach_card(record, source_ids=["legacy-unavailable-source"])
    record.detail.report_md = "Legacy readable report."
    assert record.detail.report_answer_boundaries == []
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues


@pytest.mark.asyncio
async def test_negative_currency_symbol_cannot_reuse_allowed_usd(runtime):
    service, record = runtime
    row = record.detail.raw_sources[0].metadata["normalized_fields"][0]
    row["price"]["currency"] = "USD"
    row["unit"] = "USD"
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Price -$3999. [source:source-product-a-pricing]"
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("answer_guard_reason") == "withheld_or_unsupported_amount"
        for item in issues
    )


@pytest.mark.asyncio
async def test_recorded_three_letter_currency_is_audited_without_guessing_sku(runtime):
    service, record = runtime
    row = record.detail.raw_sources[0].metadata["normalized_fields"][0]
    row["price"]["currency"] = "XYZ"
    row["unit"] = "XYZ"
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Price XYZ9999. [source:source-product-a-pricing]"
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("answer_guard_reason") == "withheld_or_unsupported_amount"
        for item in issues
    )


@pytest.mark.asyncio
async def test_recorded_currency_remains_audited_when_amount_is_missing(runtime):
    service, record = runtime
    row = record.detail.raw_sources[0].metadata["normalized_fields"][0]
    row["price"] = {"currency": "XYZ"}
    row["unit"] = "XYZ"
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Price XYZ9999. [source:source-product-a-pricing]"
    bind_actual_segment(service, record)
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("answer_guard_reason") == "withheld_or_unsupported_amount"
        for item in issues
    )
