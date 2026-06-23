from __future__ import annotations

from packages.agents.writer.artifact_publication_contract import (
    validate_report_artifact_publication,
)
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


def _artifact(
    *,
    core_markdown: str,
    support_markdown: str = "",
    audit_markdown: str = "",
) -> ReportArtifactV2:
    full_markdown = "\n\n".join(
        markdown
        for markdown in (core_markdown, support_markdown, audit_markdown)
        if markdown
    )
    return ReportArtifactV2(
        artifact_version=2,
        run_id="run-contract",
        core_report=ReportLayer(layer="core", markdown=core_markdown),
        support_appendix=ReportLayer(layer="support", markdown=support_markdown),
        audit_log=ReportLayer(layer="audit", markdown=audit_markdown),
        quality=ReportQualityAccount(
            core_gate={"status": "not_run"},
            support_gate={"status": "not_run"},
            audit_gate={"status": "not_run"},
            revision_count=0,
        ),
        render_cache=ReportArtifactRenderCache(
            core_markdown=core_markdown,
            support_markdown=support_markdown,
            audit_markdown=audit_markdown,
            full_markdown=full_markdown,
        ),
        legacy=ReportArtifactLegacyInfo(
            source="report_artifact_v2",
            report_md_alias=True,
        ),
    )


def test_validate_report_artifact_publication_accepts_clean_legacy_artifact() -> None:
    artifact = legacy_report_artifact(
        run_id="run-legacy",
        report_md="## Legacy Report\n\nClean public markdown.",
    )

    result = validate_report_artifact_publication(artifact)

    assert result.passed is True
    assert result.issues == []


def test_validate_report_artifact_publication_rejects_internal_payload_leaks() -> None:
    artifact = _artifact(
        core_markdown=(
            "## Decision Summary\n\n"
            "The public report must not expose source_registry, "
            "allowed_source_ids, represented_by, Segment Evidence Pack JSON, "
            "Writer Evidence Pack, fact:raw-source:1, signal:raw-source, or kb:item."
        )
    )

    result = validate_report_artifact_publication(artifact)

    assert result.passed is False
    assert "internal_term_leak" in result.issue_codes()


def test_validate_report_artifact_publication_rejects_full_without_core() -> None:
    artifact = _artifact(core_markdown="", support_markdown="## Evidence Support\n\nNotes.")

    result = validate_report_artifact_publication(artifact)

    assert result.passed is False
    assert "full_markdown_without_core_markdown" in result.issue_codes()


def test_validate_report_artifact_publication_rejects_unknown_citation_not_in_artifact_allowlist() -> None:
    claim = ClaimCard(
        id="claim-allowed",
        run_id="run-contract",
        competitor="Cursor",
        dimension="pricing",
        claim_type="dimension_claim",
        claim="Cursor has transparent pricing.",
        source_ids=["raw-source-allowed"],
        confidence=0.86,
        evidence_strength="strong",
        support_level="official",
        scope="pricing",
        caveats=[],
        conflicts=[],
        applicability="pricing",
        producer_stage="analyst:pricing:Cursor",
        derived_from=["raw-source-allowed"],
    )
    decision = DecisionCard(
        id="decision-allowed",
        run_id="run-contract",
        decision_type="overall_recommendation",
        subject="overall",
        recommendation="Use Cursor as the baseline recommendation.",
        posture="strong",
        rationale="Cursor has supported pricing evidence.",
        claim_card_ids=[claim.id],
        source_ids=["raw-source-allowed"],
        winner="Cursor",
        alternatives=["GitHub Copilot"],
        evidence_strength="strong",
        confidence=0.84,
    )
    core_markdown = (
        "## Decision Summary\n\n"
        "This cites an unsupported source. [source:raw-source-missing]"
    )
    artifact = ReportArtifactV2(
        artifact_version=2,
        run_id="run-contract",
        core_report=ReportLayer(
            layer="core",
            markdown=core_markdown,
            sections=[
                ReportLayerSection(
                    section_key="decision_summary",
                    heading="Decision Summary",
                    start_line=1,
                    end_line=3,
                    source_ids=["raw-source-allowed"],
                    claim_card_ids=[claim.id],
                    decision_card_ids=[decision.id],
                )
            ],
        ),
        support_appendix=ReportLayer(layer="support", markdown=""),
        audit_log=ReportLayer(layer="audit", markdown=""),
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="run-contract",
                competitor="Cursor",
                dimension="pricing",
                cards=[claim],
                source_ids=["raw-source-allowed"],
            )
        ],
        decision_card_bundle=DecisionCardBundle(
            run_id="run-contract",
            cards=[decision],
            recommendation_card_id=decision.id,
        ),
        section_briefs=[
            SectionBrief(
                id="brief-decision-summary",
                section_key="decision_summary",
                layer="core",
                allowed_claim_card_ids=[claim.id],
                allowed_decision_card_ids=[decision.id],
                allowed_source_ids=["raw-source-allowed"],
            )
        ],
        quality=ReportQualityAccount(
            core_gate={"status": "not_run"},
            support_gate={"status": "not_run"},
            audit_gate={"status": "not_run"},
            revision_count=0,
        ),
        render_cache=ReportArtifactRenderCache(
            core_markdown=core_markdown,
            support_markdown="",
            audit_markdown="",
            full_markdown=core_markdown,
        ),
        legacy=ReportArtifactLegacyInfo(
            source="report_artifact_v2",
            report_md_alias=True,
        ),
        metadata={"output_language": "en-US"},
    )

    result = validate_report_artifact_publication(artifact)

    assert result.passed is False
    assert "invalid_source_id" in result.issue_codes()


def test_validate_report_artifact_publication_rejects_invented_artifact_source_not_in_registry() -> None:
    core_markdown = (
        "## Decision Summary\n\n"
        "This cites a source invented inside the artifact. [source:raw-source-invented]"
    )
    artifact = ReportArtifactV2(
        artifact_version=2,
        run_id="run-contract",
        core_report=ReportLayer(
            layer="core",
            markdown=core_markdown,
            sections=[
                ReportLayerSection(
                    section_key="decision_summary",
                    heading="Decision Summary",
                    start_line=1,
                    end_line=3,
                    source_ids=["raw-source-invented"],
                )
            ],
        ),
        support_appendix=ReportLayer(layer="support", markdown=""),
        audit_log=ReportLayer(layer="audit", markdown=""),
        section_briefs=[
            SectionBrief(
                id="brief-decision-summary",
                section_key="decision_summary",
                layer="core",
                allowed_source_ids=["raw-source-invented"],
            )
        ],
        quality=ReportQualityAccount(
            core_gate={"status": "not_run"},
            support_gate={"status": "not_run"},
            audit_gate={"status": "not_run"},
            revision_count=0,
        ),
        render_cache=ReportArtifactRenderCache(
            core_markdown=core_markdown,
            support_markdown="",
            audit_markdown="",
            full_markdown=core_markdown,
        ),
        legacy=ReportArtifactLegacyInfo(
            source="report_artifact_v2",
            report_md_alias=True,
        ),
        metadata={"output_language": "en-US"},
    )

    result = validate_report_artifact_publication(
        artifact,
        allowed_source_ids={"raw-source-authoritative"},
    )

    assert result.passed is False
    assert "invalid_source_id" in result.issue_codes()
    assert "artifact_source_outside_registry" in result.issue_codes()
