import pytest
from pydantic import ValidationError

from packages.report_artifact.legacy_adapter import legacy_report_artifact
from packages.schema.report_artifact import (
    ClaimCard,
    ClaimCardBundle,
    DecisionCard,
    DecisionCardBundle,
    ReportArtifactLegacyInfo,
    ReportArtifactRenderCache,
    ReportArtifactV2,
    ReportLayer,
    ReportLayerSection,
    ReportQualityAccount,
    SectionBrief,
)


def _claim_card_kwargs(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "claim-1",
        "run_id": "run-1",
        "competitor": "Cursor",
        "dimension": "pricing",
        "claim_type": "pricing_fact",
        "claim": "Cursor has a Pro plan.",
        "source_ids": ["source-1"],
        "confidence": 0.8,
        "evidence_strength": "moderate",
        "support_level": "official",
        "scope": "current public pricing",
        "caveats": [],
        "conflicts": [],
        "applicability": "developer teams",
        "produced_by": "analyst",
        "producer_stage": "analyst:pricing:Cursor",
        "derived_from": [],
        "metadata": {},
    }
    data.update(overrides)
    return data


def _decision_card_kwargs(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "decision-1",
        "run_id": "run-1",
        "decision_type": "dimension_winner",
        "subject": "overall",
        "recommendation": "Prefer Cursor for prototype-heavy engineering teams.",
        "posture": "tentative",
        "rationale": "Evidence is incomplete.",
        "claim_card_ids": ["claim-1"],
        "source_ids": ["source-1"],
        "winner": "Cursor",
        "alternatives": ["GitHub Copilot"],
        "why_not": {"GitHub Copilot": "Less IDE-native for this workflow."},
        "risk_factors": ["Persona evidence is weak."],
        "evidence_strength": "moderate",
        "confidence": 0.55,
        "produced_by": "comparator",
        "producer_stage": "comparator",
        "metadata": {},
    }
    data.update(overrides)
    return data


def _artifact_kwargs(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "artifact_version": 2,
        "run_id": "run-1",
        "core_report": ReportLayer(layer="core", markdown="## Core"),
        "support_appendix": ReportLayer(layer="support", markdown="## Support"),
        "audit_log": ReportLayer(layer="audit", markdown="## Audit"),
        "claim_card_bundles": [],
        "decision_card_bundle": None,
        "section_briefs": [],
        "quality": ReportQualityAccount(
            core_gate={"status": "not_run"},
            support_gate={"status": "not_run"},
            audit_gate={"status": "not_run"},
            warnings=[],
            blockers=[],
            revision_count=0,
        ),
        "render_cache": ReportArtifactRenderCache(
            core_markdown="## Core",
            support_markdown="## Support",
            audit_markdown="## Audit",
            full_markdown="## Core\n\n## Support\n\n## Audit",
        ),
        "legacy": ReportArtifactLegacyInfo(
            source="report_artifact_v2", report_md_alias=True
        ),
    }
    data.update(overrides)
    return data


def test_claim_card_requires_sources_for_supported_fact() -> None:
    with pytest.raises(
        ValidationError, match="claims without source_ids require support_level='gap'"
    ):
        ClaimCard(
            **_claim_card_kwargs(
                source_ids=[],
                support_level="single_source",
                evidence_strength="insufficient",
            )
        )


def test_claim_card_gap_requires_insufficient_evidence_strength() -> None:
    with pytest.raises(
        ValidationError,
        match="claim cards with support_level='gap' require evidence_strength='insufficient'",
    ):
        ClaimCard(
            **_claim_card_kwargs(
                source_ids=["source-1"],
                support_level="gap",
                evidence_strength="weak",
            )
        )


def test_claim_card_non_insufficient_evidence_requires_sources_even_for_gap() -> None:
    with pytest.raises(
        ValidationError,
        match="claim cards with evidence_strength other than 'insufficient' require source_ids",
    ):
        ClaimCard(
            **_claim_card_kwargs(
                claim_type="evidence_gap",
                source_ids=[],
                support_level="gap",
                evidence_strength="weak",
            )
        )


def test_gap_claim_may_have_no_sources() -> None:
    card = ClaimCard(
        id="claim-gap-1",
        run_id="run-1",
        competitor="Cursor",
        dimension="persona",
        claim_type="evidence_gap",
        claim="No direct enterprise buyer interview was collected.",
        source_ids=[],
        confidence=0.3,
        evidence_strength="insufficient",
        support_level="gap",
        scope="buyer interviews",
        caveats=["Missing direct user research."],
        conflicts=[],
        applicability="persona analysis",
        produced_by="analyst",
        producer_stage="analyst:persona:Cursor",
        derived_from=[],
        metadata={},
    )
    assert card.support_level == "gap"


def test_claim_card_accepts_official_support_level() -> None:
    card = ClaimCard(**_claim_card_kwargs(support_level="official"))
    assert card.support_level == "official"


def test_claim_card_accepts_simulated_support_level() -> None:
    card = ClaimCard(**_claim_card_kwargs(support_level="simulated"))
    assert card.support_level == "simulated"


def test_claim_card_accepts_open_claim_type() -> None:
    card = ClaimCard(**_claim_card_kwargs(claim_type="dimension_claim"))
    assert card.claim_type == "dimension_claim"


def test_claim_card_rejects_wrong_producer_owner() -> None:
    with pytest.raises(ValidationError):
        ClaimCard(**_claim_card_kwargs(produced_by="writer"))


def test_decision_card_requires_claim_card_ids() -> None:
    with pytest.raises(ValidationError, match="decision cards require claim_card_ids"):
        DecisionCard(**_decision_card_kwargs(claim_card_ids=[], source_ids=[]))


def test_decision_card_strong_posture_requires_moderate_or_strong_evidence() -> None:
    with pytest.raises(
        ValidationError,
        match="decision cards with posture='strong' require moderate or strong evidence_strength",
    ):
        DecisionCard(**_decision_card_kwargs(posture="strong", evidence_strength="weak"))


def test_decision_card_accepts_dimension_winner_type() -> None:
    card = DecisionCard(**_decision_card_kwargs(decision_type="dimension_winner"))
    assert card.decision_type == "dimension_winner"


def test_decision_card_accepts_watch_and_avoid_postures() -> None:
    watch = DecisionCard(**_decision_card_kwargs(posture="watch"))
    avoid = DecisionCard(**_decision_card_kwargs(posture="avoid"))
    assert watch.posture == "watch"
    assert avoid.posture == "avoid"


def test_decision_card_rejects_wrong_producer_owner() -> None:
    with pytest.raises(ValidationError):
        DecisionCard(**_decision_card_kwargs(produced_by="analyst"))


def test_decision_card_rejects_wrong_producer_stage() -> None:
    with pytest.raises(ValidationError):
        DecisionCard(**_decision_card_kwargs(producer_stage="writer"))


def test_report_layer_uses_typed_sections() -> None:
    layer = ReportLayer(
        layer="core",
        markdown="## Core\n\nDecision.",
        sections=[
            ReportLayerSection(
                section_key="executive_summary",
                heading="Executive Summary",
                start_line=1,
                end_line=4,
                source_ids=["source-1"],
                claim_card_ids=["claim-1"],
                decision_card_ids=["decision-1"],
            )
        ],
    )
    assert layer.sections[0].section_key == "executive_summary"


def test_report_quality_account_accepts_structured_warnings_and_blockers() -> None:
    quality = ReportQualityAccount(
        core_gate={"status": "warn"},
        support_gate={"status": "block"},
        audit_gate={"status": "not_run"},
        warnings=[{"code": "thin_support", "message": "Support appendix is thin."}],
        blockers=[{"code": "missing_core", "message": "Core layer missing."}],
        revision_count=1,
    )
    assert quality.warnings[0]["code"] == "thin_support"
    assert quality.blockers[0]["code"] == "missing_core"


def test_report_artifact_v2_sets_legacy_full_markdown() -> None:
    artifact = ReportArtifactV2(
        artifact_version=2,
        run_id="run-1",
        core_report=ReportLayer(layer="core", markdown="## Core\n\nDecision.", sections=[]),
        support_appendix=ReportLayer(
            layer="support", markdown="## Evidence\n\nSources.", sections=[]
        ),
        audit_log=ReportLayer(layer="audit", markdown="## Audit\n\nTrace.", sections=[]),
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="run-1",
                competitor="Cursor",
                dimension="pricing",
                cards=[],
                source_ids=[],
                coverage={"source_count": 0},
                gap_count=0,
                generated_at="2026-06-21T00:00:00Z",
                producer_context={"branch": "analyst:pricing:Cursor"},
            )
        ],
        decision_card_bundle=DecisionCardBundle(
            run_id="run-1",
            cards=[],
            matrix_snapshot={},
            coverage_by_dimension={},
            recommendation_card_id=None,
            generated_at="2026-06-21T00:00:00Z",
            producer_context={"stage": "comparator"},
        ),
        section_briefs=[
            SectionBrief(
                id="brief-core-summary",
                section_key="executive_summary",
                layer="core",
                required_questions=["What should the buyer do?"],
                allowed_claim_card_ids=[],
                allowed_decision_card_ids=[],
                allowed_source_ids=[],
                must_include=["Clear recommendation posture."],
                must_not_claim=[
                    "Do not claim direct interviews if only simulated evidence exists."
                ],
                tone="executive",
                minimum_depth={"paragraphs": 3},
                citation_policy={"mode": "claim_scoped"},
                repair_targets={
                    "section_key": "executive_summary",
                    "artifact_layer": "core",
                },
            )
        ],
        quality=ReportQualityAccount(
            core_gate={"status": "not_run"},
            support_gate={"status": "not_run"},
            audit_gate={"status": "not_run"},
            warnings=[],
            blockers=[],
            revision_count=0,
        ),
        render_cache=ReportArtifactRenderCache(
            core_markdown="## Core\n\nDecision.",
            support_markdown="## Evidence\n\nSources.",
            audit_markdown="## Audit\n\nTrace.",
            full_markdown="## Core\n\nDecision.\n\n## Evidence\n\nSources.\n\n## Audit\n\nTrace.",
        ),
        legacy=ReportArtifactLegacyInfo(
            source="report_artifact_v2", report_md_alias=True
        ),
    )
    assert artifact.render_cache.full_markdown.endswith("Trace.")


def test_report_artifact_rejects_swapped_layers() -> None:
    with pytest.raises(ValidationError, match="core_report.layer must be 'core'"):
        ReportArtifactV2(
            artifact_version=2,
            run_id="run-1",
            core_report=ReportLayer(layer="support", markdown="## Core"),
            support_appendix=ReportLayer(layer="support", markdown="## Support"),
            audit_log=ReportLayer(layer="audit", markdown="## Audit"),
            claim_card_bundles=[],
            decision_card_bundle=None,
            section_briefs=[],
            quality=ReportQualityAccount(
                core_gate={"status": "not_run"},
                support_gate={"status": "not_run"},
                audit_gate={"status": "not_run"},
                warnings=[],
                blockers=[],
                revision_count=0,
            ),
            render_cache=ReportArtifactRenderCache(
                core_markdown="## Core",
                support_markdown="## Support",
                audit_markdown="## Audit",
                full_markdown="## Core\n\n## Support\n\n## Audit",
            ),
            legacy=ReportArtifactLegacyInfo(
                source="report_artifact_v2", report_md_alias=True
            ),
        )


def test_report_artifact_rejects_full_markdown_cache_mismatch() -> None:
    with pytest.raises(
        ValidationError,
        match="render_cache.full_markdown must match joined layer markdown",
    ):
        ReportArtifactV2(
            artifact_version=2,
            run_id="run-1",
            core_report=ReportLayer(layer="core", markdown="## Core"),
            support_appendix=ReportLayer(layer="support", markdown="## Support"),
            audit_log=ReportLayer(layer="audit", markdown=""),
            claim_card_bundles=[],
            decision_card_bundle=None,
            section_briefs=[],
            quality=ReportQualityAccount(
                core_gate={"status": "not_run"},
                support_gate={"status": "not_run"},
                audit_gate={"status": "not_run"},
                warnings=[],
                blockers=[],
                revision_count=0,
            ),
            render_cache=ReportArtifactRenderCache(
                core_markdown="## Core",
                support_markdown="## Support",
                audit_markdown="",
                full_markdown="## Core\n\nwrong",
            ),
            legacy=ReportArtifactLegacyInfo(
                source="report_artifact_v2", report_md_alias=True
            ),
        )


def test_report_artifact_rejects_empty_full_markdown_when_layers_have_markdown() -> None:
    with pytest.raises(
        ValidationError,
        match="render_cache.full_markdown must match joined layer markdown",
    ):
        ReportArtifactV2(
            **_artifact_kwargs(
                render_cache=ReportArtifactRenderCache(
                    core_markdown="## Core",
                    support_markdown="## Support",
                    audit_markdown="## Audit",
                    full_markdown="",
                )
            )
        )


def test_report_artifact_rejects_mismatched_layer_render_cache() -> None:
    with pytest.raises(
        ValidationError,
        match="render_cache.core_markdown must equal core_report.markdown",
    ):
        ReportArtifactV2(
            **_artifact_kwargs(
                render_cache=ReportArtifactRenderCache(
                    core_markdown="wrong",
                    support_markdown="## Support",
                    audit_markdown="## Audit",
                    full_markdown="## Core\n\n## Support\n\n## Audit",
                )
            )
        )


def test_legacy_adapter_wraps_report_md_without_mutation() -> None:
    artifact = legacy_report_artifact(run_id="run-old", report_md="## Legacy Report\n\nBody")
    assert artifact.artifact_version == 2
    assert artifact.core_report.markdown == "## Legacy Report\n\nBody"
    assert artifact.support_appendix.markdown == ""
    assert artifact.audit_log.markdown == ""
    assert artifact.decision_card_bundle is None
    assert artifact.render_cache.full_markdown == "## Legacy Report\n\nBody"
    assert artifact.legacy.source == "report_md"
