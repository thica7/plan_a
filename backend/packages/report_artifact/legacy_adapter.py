from packages.schema.report_artifact import (
    ReportArtifactLegacyInfo,
    ReportArtifactRenderCache,
    ReportArtifactV2,
    ReportLayer,
    ReportQualityAccount,
)


def legacy_report_artifact(run_id: str, report_md: str) -> ReportArtifactV2:
    return ReportArtifactV2(
        artifact_version=2,
        run_id=run_id,
        core_report=ReportLayer(layer="core", markdown=report_md, sections=[]),
        support_appendix=ReportLayer(layer="support", markdown="", sections=[]),
        audit_log=ReportLayer(layer="audit", markdown="", sections=[]),
        claim_card_bundles=[],
        decision_card_bundle=None,
        section_briefs=[],
        quality=ReportQualityAccount(
            core_gate={"status": "legacy"},
            support_gate={"status": "legacy"},
            audit_gate={"status": "legacy"},
            warnings=[],
            blockers=[],
            revision_count=0,
        ),
        render_cache=ReportArtifactRenderCache(
            core_markdown=report_md,
            support_markdown="",
            audit_markdown="",
            full_markdown=report_md,
        ),
        legacy=ReportArtifactLegacyInfo(source="report_md", report_md_alias=True),
    )
