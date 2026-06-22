from __future__ import annotations

import pytest

from packages.agents.writer.artifact_assembler import assemble_report_artifact_v2
from packages.agents.writer.logic import WriterAgentMixin
from packages.business_intel.report_sections import report_section_marker
from packages.i18n.language import report_label
from packages.observability.tracing import build_run_event
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource, RevisionRecord
from packages.schema.report_artifact import (
    ClaimCard,
    ClaimCardBundle,
    DecisionCard,
    DecisionCardBundle,
    SectionBrief,
)


def _source(source_id: str) -> RawSource:
    return RawSource(
        id=source_id,
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title=f"{source_id} source",
        snippet="Pricing evidence for Cursor.",
        content_hash=f"{source_id}-hash",
        confidence=0.9,
    )


def _detail_with_cards_and_briefs() -> RunDetail:
    claim = ClaimCard(
        id="claim-cursor-pricing",
        run_id="run-artifact",
        competitor="Cursor",
        dimension="pricing",
        claim_type="dimension_claim",
        claim="Cursor has transparent pricing.",
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
        run_id="run-artifact",
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
    detail = RunDetail(
        id="run-artifact",
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
        raw_sources=[_source("raw-source-cursor-pricing")],
        revisions=[
            RevisionRecord(
                id="revision-1",
                iteration=1,
                stage="writer",
                before_md="before",
                after_md="after",
                issue_ids=["tighten-recommendation"],
            )
        ],
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="run-artifact",
                competitor="Cursor",
                dimension="pricing",
                cards=[claim],
                source_ids=["raw-source-cursor-pricing"],
            )
        ],
        decision_card_bundle=DecisionCardBundle(
            run_id="run-artifact",
            cards=[decision],
            recommendation_card_id=decision.id,
        ),
    )
    detail.section_briefs = [
        SectionBrief(
            id="brief-decision-summary",
            section_key="decision_summary",
            layer="core",
            allowed_claim_card_ids=[claim.id],
            allowed_decision_card_ids=[decision.id],
            allowed_source_ids=["raw-source-cursor-pricing"],
        ),
        SectionBrief(
            id="brief-evidence-support",
            section_key="evidence_support",
            layer="support",
            allowed_claim_card_ids=[claim.id],
            allowed_decision_card_ids=[decision.id],
            allowed_source_ids=["raw-source-cursor-pricing"],
        ),
    ]
    return detail


def _schema_contract_report_markdown(detail: RunDetail) -> str:
    section_keys = [
        "executive_summary",
        "decision_summary",
        "competitive_findings",
        "review_theme_summary",
        "community_evidence_triangulation",
        "side_by_side_matrix",
        "competitor_deep_dives",
        "swot_analysis",
        "battlecard",
        "evidence_support",
    ]
    blocks: list[str] = []
    for section_key in section_keys:
        layer = "support" if section_key == "evidence_support" else "core"
        heading = report_label(detail.output_language, section_key)
        blocks.append(
            "\n".join(
                [
                    report_section_marker(section_key, layer),
                    f"## {heading}",
                    (
                        f"{heading} keeps the schema marker paired with its heading and "
                        "cites the registered pricing source. "
                        "[source:raw-source-cursor-pricing]"
                    ),
                ]
            )
        )
    return "\n\n".join(blocks)


def _marker_heading_pairs(markdown: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    marker: str | None = None
    for line in markdown.splitlines():
        if line.startswith("<!-- report-section:"):
            marker = line
        elif line.startswith("## ") and marker:
            pairs.append((marker, line))
            marker = None
    return pairs


def _expected_marker_heading_pairs(detail: RunDetail) -> list[tuple[str, str]]:
    return [
        (
            report_section_marker(
                section_key,
                "support" if section_key == "evidence_support" else "core",
            ),
            f"## {report_label(detail.output_language, section_key)}",
        )
        for section_key in [
            "executive_summary",
            "decision_summary",
            "competitive_findings",
            "review_theme_summary",
            "community_evidence_triangulation",
            "side_by_side_matrix",
            "competitor_deep_dives",
            "swot_analysis",
            "battlecard",
            "evidence_support",
        ]
    ]


def _assert_marker_heading_contract(markdown: str, detail: RunDetail) -> None:
    actual = _marker_heading_pairs(markdown)
    expected = _expected_marker_heading_pairs(detail)
    assert dict(actual) == dict(expected)
    assert len(actual) == len(expected)


class _WriterHarness(WriterAgentMixin):
    def __init__(self) -> None:
        self.emitted_events = []
        self.traces: list[dict[str, object]] = []

    async def emit(
        self,
        run_id: str,
        event_type: str,
        node: str | None,
        subagent: str | None,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.emitted_events.append(
            build_run_event(
                event_id=len(self.emitted_events) + 1,
                run_id=run_id,
                event_type=event_type,
                agent=node,
                subagent=subagent,
                message=message,
                payload=payload or {},
            )
        )

    def _trace_local_tool(self, record, **kwargs: object) -> None:
        self.traces.append(kwargs)


class _Record:
    def __init__(self, detail: RunDetail) -> None:
        self.detail = detail


def test_assemble_report_artifact_v2_splits_layers_and_render_cache() -> None:
    detail = _detail_with_cards_and_briefs()
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Cursor is the recommended baseline. [source:raw-source-cursor-pricing]"
    )
    support_markdown = (
        f"{report_section_marker('evidence_support', 'support')}\n"
        "## Evidence Support\n"
        "Pricing evidence is official. [source:raw-source-cursor-pricing]"
    )

    artifact = assemble_report_artifact_v2(
        detail,
        {
            "decision_summary": core_markdown,
            "evidence_support": support_markdown,
        },
    )

    assert artifact.run_id == detail.id
    assert artifact.core_report.markdown == core_markdown
    assert artifact.support_appendix.markdown.startswith(support_markdown)
    assert "Claim card coverage" in artifact.support_appendix.markdown
    assert artifact.audit_log.markdown == ""
    assert artifact.render_cache.core_markdown == artifact.core_report.markdown
    assert artifact.render_cache.support_markdown == artifact.support_appendix.markdown
    assert artifact.render_cache.audit_markdown == artifact.audit_log.markdown
    assert artifact.render_cache.full_markdown == (
        f"{core_markdown}\n\n{artifact.support_appendix.markdown}"
    )
    assert artifact.legacy.source == "report_artifact_v2"
    assert artifact.legacy.report_md_alias is True
    assert artifact.quality.core_gate["status"] == "not_run"
    assert artifact.quality.revision_count == 1


def test_assemble_report_artifact_v2_carries_cards_briefs_and_section_metadata() -> None:
    detail = _detail_with_cards_and_briefs()
    artifact = assemble_report_artifact_v2(
        detail,
        {
            "decision_summary": (
                f"{report_section_marker('decision_summary', 'core')}\n"
                "## Decision Summary\n"
                "Cursor is recommended.\n"
                "The reasoning is concise. [source:raw-source-cursor-pricing]"
            ),
            "evidence_support": (
                f"{report_section_marker('evidence_support', 'support')}\n"
                "## Evidence Support\n"
                "Official pricing page support. [source:raw-source-cursor-pricing]"
            ),
        },
    )

    assert artifact.claim_card_bundles == detail.claim_card_bundles
    assert artifact.decision_card_bundle == detail.decision_card_bundle
    assert artifact.section_briefs == detail.section_briefs
    core_section = artifact.core_report.sections[0]
    support_section = artifact.support_appendix.sections[0]
    assert core_section.section_key == "decision_summary"
    assert core_section.heading == "Decision Summary"
    assert core_section.start_line == 1
    assert core_section.end_line == 4
    assert core_section.claim_card_ids == ["claim-cursor-pricing"]
    assert core_section.decision_card_ids == ["decision-overall"]
    assert core_section.source_ids == ["raw-source-cursor-pricing"]
    assert support_section.section_key == "evidence_support"
    assert support_section.claim_card_ids == ["claim-cursor-pricing"]


def test_assemble_report_artifact_v2_appends_deterministic_support_index() -> None:
    detail = _detail_with_cards_and_briefs()
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Cursor is recommended. [source:raw-source-cursor-pricing]"
    )
    placeholder_support = (
        f"{report_section_marker('evidence_support', 'support')}\n"
        "## Evidence Support\n"
        "Evidence support will be audited from registered cards and sources."
    )

    artifact = assemble_report_artifact_v2(
        detail,
        {
            "decision_summary": core_markdown,
            "evidence_support": placeholder_support,
        },
    )

    support = artifact.support_appendix.markdown
    assert "claim-cursor-pricing" in support
    assert "decision-overall" in support
    assert "raw-source-cursor-pricing" in support
    assert "Claim card coverage" in support


def test_assemble_report_artifact_v2_localizes_deterministic_support_index() -> None:
    detail = _detail_with_cards_and_briefs()
    detail.output_language = "zh-CN"
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## \u51b3\u7b56\u6458\u8981\n"
        "Cursor is recommended. [source:raw-source-cursor-pricing]"
    )

    artifact = assemble_report_artifact_v2(
        detail,
        {
            "decision_summary": core_markdown,
        },
    )

    support = artifact.support_appendix.markdown
    assert "### \u58f0\u660e\u5361\u8986\u76d6" in support
    assert "### Claim card coverage" not in support


def test_assemble_report_artifact_v2_can_split_final_markdown_by_existing_markers() -> None:
    detail = _detail_with_cards_and_briefs()
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Cursor is recommended. [source:raw-source-cursor-pricing]"
    )
    support_markdown = (
        f"{report_section_marker('evidence_support', 'support')}\n"
        "## Evidence Support\n"
        "Official pricing page support. [source:raw-source-cursor-pricing]"
    )
    final_markdown = f"{core_markdown}\n\n{support_markdown}"

    artifact = assemble_report_artifact_v2(
        detail,
        {"final_report": final_markdown},
    )

    assert artifact.core_report.markdown == core_markdown
    assert artifact.support_appendix.markdown.startswith(support_markdown)
    assert artifact.render_cache.full_markdown == (
        f"{core_markdown}\n\n{artifact.support_appendix.markdown}"
    )


def test_assemble_report_artifact_v2_honors_explicit_audit_marker_layer() -> None:
    detail = _detail_with_cards_and_briefs()
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Cursor is recommended. [source:raw-source-cursor-pricing]"
    )
    audit_markdown = (
        f"{report_section_marker('generation_notes', 'audit')}\n"
        "## Generation Notes\n"
        "Deterministic validation metadata only."
    )

    artifact = assemble_report_artifact_v2(
        detail,
        {"final_report": f"{core_markdown}\n\n{audit_markdown}"},
    )

    assert artifact.core_report.markdown == core_markdown
    assert "Claim card coverage" in artifact.support_appendix.markdown
    assert artifact.audit_log.markdown == audit_markdown
    assert artifact.audit_log.sections[0].section_key == "generation_notes"


def test_assemble_report_artifact_v2_metadata_section_keys_are_input_order_independent() -> None:
    detail = _detail_with_cards_and_briefs()
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Cursor is recommended. [source:raw-source-cursor-pricing]"
    )
    support_markdown = (
        f"{report_section_marker('evidence_support', 'support')}\n"
        "## Evidence Support\n"
        "Official pricing page support. [source:raw-source-cursor-pricing]"
    )

    first = assemble_report_artifact_v2(
        detail,
        {
            "decision_summary": core_markdown,
            "evidence_support": support_markdown,
        },
    )
    second = assemble_report_artifact_v2(
        detail,
        {
            "evidence_support": support_markdown,
            "decision_summary": core_markdown,
        },
    )

    assert first.metadata["section_keys"] == second.metadata["section_keys"]
    assert first.render_cache.full_markdown == second.render_cache.full_markdown


def test_legacy_report_hardener_preserves_schema_contract_marker_heading_pairs() -> None:
    detail = _detail_with_cards_and_briefs()
    markdown = _schema_contract_report_markdown(detail)
    harness = _WriterHarness()

    hardened = harness._harden_report_markdown(detail, markdown)

    _assert_marker_heading_contract(hardened, detail)


def test_preserving_schema_contract_report_rebuilds_artifact_without_marker_drift() -> None:
    detail = _detail_with_cards_and_briefs()
    previous_report = _schema_contract_report_markdown(detail)
    detail.report_md = previous_report
    detail.report_artifact = assemble_report_artifact_v2(
        detail,
        {"final_report": previous_report},
    )
    harness = _WriterHarness()

    preserved = harness._preserve_hardened_previous_report(detail, previous_report)

    _assert_marker_heading_contract(preserved, detail)
    assert detail.report_md == preserved
    assert detail.report_artifact is not None
    assert detail.report_artifact.render_cache.full_markdown == preserved
    assert detail.report_artifact.legacy.source == "report_artifact_v2"


@pytest.mark.asyncio
async def test_writer_schema_contract_publication_sets_report_artifact_alias() -> None:
    detail = _detail_with_cards_and_briefs()
    core_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Cursor is recommended. [source:raw-source-cursor-pricing]"
    )
    support_markdown = (
        f"{report_section_marker('evidence_support', 'support')}\n"
        "## Evidence Support\n"
        "Official pricing page support. [source:raw-source-cursor-pricing]"
    )
    detail.report_md = f"{core_markdown}\n\n{support_markdown}"
    harness = _WriterHarness()

    await harness._publish_schema_contract_report_artifact_if_current(
        _Record(detail),
        schema_contract_final_report_md=detail.report_md,
    )

    assert detail.report_artifact is not None
    assert detail.report_artifact.render_cache.full_markdown == detail.report_md
    assert detail.report_artifact.legacy.source == "report_artifact_v2"
    assert harness.emitted_events[0].type == ("writer_report_artifact_v2_publication_validated")
    assert harness.emitted_events[0].payload["passed"] is True


@pytest.mark.asyncio
async def test_writer_schema_contract_publication_skips_preserved_previous_output() -> None:
    detail = _detail_with_cards_and_briefs()
    generated_markdown = (
        f"{report_section_marker('decision_summary', 'core')}\n"
        "## Decision Summary\n"
        "Generated schema output. [source:raw-source-cursor-pricing]"
    )
    detail.report_md = "## Previous Report\n\nPreserved older report."
    detail.report_artifact = assemble_report_artifact_v2(
        detail,
        {"final_report": generated_markdown},
    )
    harness = _WriterHarness()

    published = await harness._publish_schema_contract_report_artifact_if_current(
        _Record(detail),
        schema_contract_final_report_md=generated_markdown,
    )

    assert published is False
    assert detail.report_artifact is None
    assert harness.emitted_events == []
