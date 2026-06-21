from __future__ import annotations

from packages.agents.writer.section_briefs import (
    build_section_briefs,
    segment_payloads_from_briefs,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource
from packages.schema.report_artifact import (
    ClaimCard,
    ClaimCardBundle,
    DecisionCard,
    DecisionCardBundle,
)


def _source(
    source_id: str,
    *,
    competitor: str = "Cursor",
    dimension: str = "pricing",
) -> RawSource:
    return RawSource(
        id=source_id,
        competitor=competitor,
        dimension=dimension,
        source_type="interview_record" if dimension == "persona" else "webpage_verified",
        title=f"{source_id} source",
        snippet=f"{dimension} evidence for {competitor}.",
        content_hash=f"{source_id}-hash",
        confidence=0.9,
    )


def _claim(
    competitor: str,
    dimension: str,
    source_id: str,
    *,
    claim_id: str | None = None,
) -> ClaimCard:
    return ClaimCard(
        id=claim_id or f"claim-{competitor.casefold().replace(' ', '-')}-{dimension}",
        run_id="run-briefs",
        competitor=competitor,
        dimension=dimension,
        claim_type=f"{dimension}_claim",
        claim=f"{competitor} has supported {dimension} evidence.",
        source_ids=[source_id],
        confidence=0.86,
        evidence_strength="moderate",
        support_level="official",
        scope=dimension,
        caveats=[],
        conflicts=[],
        applicability=dimension,
        producer_stage=f"analyst:{dimension}:{competitor}",
        derived_from=[source_id],
    )


def _detail_with_cards() -> RunDetail:
    claim = ClaimCard(
        id="claim-cursor-pricing",
        run_id="run-briefs",
        competitor="Cursor",
        dimension="pricing",
        claim_type="dimension_claim",
        claim="Cursor has transparent pricing for individual developers.",
        source_ids=["raw-source-cursor-pricing"],
        confidence=0.86,
        evidence_strength="strong",
        support_level="official",
        scope="pricing",
        caveats=[],
        conflicts=[],
        applicability="pricing",
        producer_stage="analyst:pricing:Cursor",
        derived_from=["raw-source-cursor-pricing"],
    )
    decision = DecisionCard(
        id="decision-overall",
        run_id="run-briefs",
        decision_type="overall_recommendation",
        subject="overall",
        recommendation="Use Cursor as the baseline recommendation.",
        posture="strong",
        rationale="Cursor has stronger pricing evidence for the target buyer.",
        claim_card_ids=[claim.id],
        source_ids=["raw-source-cursor-pricing"],
        winner="Cursor",
        alternatives=["GitHub Copilot"],
        evidence_strength="strong",
        confidence=0.84,
    )
    return RunDetail(
        id="run-briefs",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        output_language="en-US",
        created_at="2026-06-21T00:00:00",
        updated_at="2026-06-21T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            competitor_layer="L1",
        ),
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="run-briefs",
                competitor="Cursor",
                dimension="pricing",
                cards=[claim],
                source_ids=["raw-source-cursor-pricing"],
            )
        ],
        decision_card_bundle=DecisionCardBundle(
            run_id="run-briefs",
            cards=[decision],
            recommendation_card_id=decision.id,
        ),
        raw_sources=[_source("raw-source-cursor-pricing")],
    )


def test_build_section_briefs_scopes_core_summary_to_cards_and_sources() -> None:
    detail = _detail_with_cards()

    briefs = build_section_briefs(detail)

    by_key = {brief.section_key: brief for brief in briefs}
    executive = by_key["decision_summary"]
    assert executive.layer == "core"
    assert executive.allowed_decision_card_ids == ["decision-overall"]
    assert executive.allowed_claim_card_ids == ["claim-cursor-pricing"]
    assert executive.allowed_source_ids == ["raw-source-cursor-pricing"]

    support = by_key["evidence_support"]
    assert support.layer == "support"
    assert support.allowed_decision_card_ids == ["decision-overall"]
    assert support.allowed_claim_card_ids == ["claim-cursor-pricing"]
    assert support.allowed_source_ids == ["raw-source-cursor-pricing"]
    assert any("business recommendations" in rule for rule in support.must_not_claim)


def test_segment_payloads_from_briefs_preserve_schema_contract_fields() -> None:
    detail = _detail_with_cards()
    briefs = build_section_briefs(detail)

    payloads = segment_payloads_from_briefs(detail, briefs)

    by_name = {str(payload["segment_name"]): payload for payload in payloads}
    summary = by_name["decision_summary"]
    assert summary["segment_kind"] == "section_fragment"
    assert summary["section_id"] == "decision_summary"
    assert summary["section_key"] == "decision_summary"
    assert summary["layer"] == "core"
    assert summary["output_language"] == "en-US"
    assert summary["allowed_source_ids"] == ["raw-source-cursor-pricing"]
    assert summary["allowed_claim_card_ids"] == ["claim-cursor-pricing"]
    assert summary["allowed_decision_card_ids"] == ["decision-overall"]
    assert summary["schema_contract_source"] == "section_brief"
    assert summary["section_brief"] == briefs[0].model_dump(mode="json")
    assert summary["require_executive_summary"] is True


def test_core_brief_without_relevant_cards_keeps_scope_empty_with_gap_note() -> None:
    detail = _detail_with_cards()
    detail.decision_card_bundle = DecisionCardBundle(run_id="run-briefs")

    briefs = build_section_briefs(detail)

    review = {brief.section_key: brief for brief in briefs}["review_theme_summary"]
    assert review.allowed_decision_card_ids == []
    assert review.allowed_claim_card_ids == []
    assert review.allowed_source_ids == []
    assert any("No section-relevant card scope" in note for note in review.must_include)


def test_review_theme_brief_selects_user_research_claims_without_all_claim_fallback() -> None:
    pricing_claim = _detail_with_cards().claim_card_bundles[0].cards[0]
    persona_claim = ClaimCard(
        id="claim-cursor-persona",
        run_id="run-briefs",
        competitor="Cursor",
        dimension="persona",
        claim_type="user_research_signal",
        claim="Developers say Cursor reduces review friction.",
        source_ids=["raw-source-cursor-persona"],
        confidence=0.72,
        evidence_strength="moderate",
        support_level="single_source",
        scope="persona",
        caveats=[],
        conflicts=[],
        applicability="developer workflow",
        producer_stage="analyst:persona:Cursor",
        derived_from=["raw-source-cursor-persona"],
    )
    detail = _detail_with_cards()
    detail.decision_card_bundle = DecisionCardBundle(run_id="run-briefs")
    detail.claim_card_bundles = [
        ClaimCardBundle(
            run_id="run-briefs",
            competitor="Cursor",
            dimension="pricing",
            cards=[pricing_claim],
            source_ids=pricing_claim.source_ids,
        ),
        ClaimCardBundle(
            run_id="run-briefs",
            competitor="Cursor",
            dimension="persona",
            cards=[persona_claim],
            source_ids=persona_claim.source_ids,
        ),
    ]
    detail.raw_sources = [
        _source("raw-source-cursor-pricing"),
        _source("raw-source-cursor-persona", dimension="persona"),
    ]

    briefs = build_section_briefs(detail)

    review = {brief.section_key: brief for brief in briefs}["review_theme_summary"]
    assert review.allowed_claim_card_ids == ["claim-cursor-persona"]
    assert review.allowed_source_ids == ["raw-source-cursor-persona"]


def test_competitor_deep_dive_brief_uses_all_competitor_claims_not_only_winner_decision() -> None:
    cursor_pricing = _claim("Cursor", "pricing", "raw-source-cursor-pricing")
    cursor_persona = _claim("Cursor", "persona", "raw-source-cursor-persona")
    copilot_feature = _claim(
        "GitHub Copilot",
        "feature",
        "raw-source-copilot-feature",
    )
    windsurf_feature = _claim(
        "Windsurf",
        "feature",
        "raw-source-windsurf-feature",
    )
    windsurf_decision = DecisionCard(
        id="decision-windsurf-feature",
        run_id="run-briefs",
        decision_type="dimension_winner",
        subject="feature",
        recommendation="Prefer Windsurf for feature.",
        posture="strong",
        rationale="Windsurf has supported feature evidence.",
        claim_card_ids=[windsurf_feature.id],
        source_ids=windsurf_feature.source_ids,
        winner="Windsurf",
        alternatives=["Cursor", "GitHub Copilot"],
        evidence_strength="moderate",
        confidence=0.82,
    )
    detail = RunDetail(
        id="run-briefs",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        output_language="en-US",
        created_at="2026-06-21T00:00:00",
        updated_at="2026-06-21T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Cursor", "GitHub Copilot", "Windsurf"],
            dimensions=["pricing", "feature", "persona"],
            competitor_layer="L1",
        ),
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="run-briefs",
                competitor=claim.competitor,
                dimension=claim.dimension,
                cards=[claim],
                source_ids=claim.source_ids,
            )
            for claim in (
                cursor_pricing,
                cursor_persona,
                copilot_feature,
                windsurf_feature,
            )
        ],
        decision_card_bundle=DecisionCardBundle(
            run_id="run-briefs",
            cards=[windsurf_decision],
            recommendation_card_id=windsurf_decision.id,
        ),
        raw_sources=[
            _source("raw-source-cursor-pricing", competitor="Cursor", dimension="pricing"),
            _source("raw-source-cursor-persona", competitor="Cursor", dimension="persona"),
            _source(
                "raw-source-copilot-feature",
                competitor="GitHub Copilot",
                dimension="feature",
            ),
            _source(
                "raw-source-windsurf-feature",
                competitor="Windsurf",
                dimension="feature",
            ),
        ],
    )

    briefs = build_section_briefs(detail)

    deep_dive = {brief.section_key: brief for brief in briefs}["competitor_deep_dives"]
    assert set(deep_dive.allowed_claim_card_ids) == {
        cursor_pricing.id,
        cursor_persona.id,
        copilot_feature.id,
        windsurf_feature.id,
    }
    assert set(deep_dive.allowed_source_ids) == {
        "raw-source-cursor-pricing",
        "raw-source-cursor-persona",
        "raw-source-copilot-feature",
        "raw-source-windsurf-feature",
    }
    assert deep_dive.allowed_decision_card_ids == [windsurf_decision.id]


def test_competitor_deep_dive_segments_are_split_by_competitor_with_raw_user_sources() -> None:
    cursor_pricing = _claim("Cursor", "pricing", "raw-source-cursor-pricing")
    windsurf_feature = _claim(
        "Windsurf",
        "feature",
        "raw-source-windsurf-feature",
    )
    detail = RunDetail(
        id="run-briefs",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        output_language="en-US",
        created_at="2026-06-21T00:00:00",
        updated_at="2026-06-21T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Cursor", "Windsurf", "No Evidence Tool"],
            dimensions=["pricing", "feature", "persona"],
            competitor_layer="L1",
        ),
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="run-briefs",
                competitor=cursor_pricing.competitor,
                dimension=cursor_pricing.dimension,
                cards=[cursor_pricing],
                source_ids=cursor_pricing.source_ids,
            ),
            ClaimCardBundle(
                run_id="run-briefs",
                competitor=windsurf_feature.competitor,
                dimension=windsurf_feature.dimension,
                cards=[windsurf_feature],
                source_ids=windsurf_feature.source_ids,
            ),
        ],
        raw_sources=[
            _source("raw-source-cursor-pricing", competitor="Cursor", dimension="pricing"),
            RawSource(
                id="raw-source-cursor-community",
                competitor="Cursor",
                dimension="persona",
                source_type="community_forum",
                title="Cursor community adoption blocker",
                snippet="Cursor users discuss adoption blockers.",
                content_hash="raw-source-cursor-community-hash",
                confidence=0.72,
            ),
            _source(
                "raw-source-windsurf-feature",
                competitor="Windsurf",
                dimension="feature",
            ),
        ],
    )

    payloads = segment_payloads_from_briefs(detail, build_section_briefs(detail))

    deep_dive_payloads = [
        payload for payload in payloads if payload["section_id"] == "competitor_deep_dives"
    ]
    assert [payload["segment_competitor"] for payload in deep_dive_payloads] == [
        "Cursor",
        "Windsurf",
        "No Evidence Tool",
    ]
    cursor_payload = deep_dive_payloads[0]
    assert cursor_payload["allowed_claim_card_ids"] == [cursor_pricing.id]
    assert set(cursor_payload["allowed_source_ids"]) == {
        "raw-source-cursor-pricing",
        "raw-source-cursor-community",
    }
    assert {source["id"] for source in cursor_payload["source_registry"]} == {
        "raw-source-cursor-pricing",
        "raw-source-cursor-community",
    }
    empty_payload = deep_dive_payloads[2]
    assert empty_payload["allowed_claim_card_ids"] == []
    assert empty_payload["allowed_source_ids"] == []
    assert empty_payload["claim_cards"] == []
    assert empty_payload["source_registry"] == []


def test_segment_payloads_filter_allowed_sources_to_raw_source_registry() -> None:
    detail = _detail_with_cards()
    claim = detail.claim_card_bundles[0].cards[0]
    claim.source_ids.append("raw-source-missing")
    assert detail.decision_card_bundle is not None
    detail.decision_card_bundle.cards[0].source_ids.append("raw-source-missing")

    payloads = segment_payloads_from_briefs(detail, build_section_briefs(detail))

    by_name = {str(payload["segment_name"]): payload for payload in payloads}
    assert by_name["decision_summary"]["allowed_source_ids"] == ["raw-source-cursor-pricing"]
    assert by_name["evidence_support"]["allowed_source_ids"] == ["raw-source-cursor-pricing"]


def test_section_briefs_do_not_emit_audit_layer_until_artifact_assembler() -> None:
    briefs = build_section_briefs(_detail_with_cards())
    payloads = segment_payloads_from_briefs(_detail_with_cards(), briefs)

    assert all(brief.layer != "audit" for brief in briefs)
    assert "generation_notes" not in {brief.section_key for brief in briefs}
    assert all(payload["layer"] != "audit" for payload in payloads)
