from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.agents.writer.structured_report import (
    BattlecardPlay,
    BattlecardSection,
    CitedText,
    CompetitorDeepDiveSection,
    CompetitorPosture,
    CompetitorSwot,
    CompetitorUserTheme,
    DecisionMatrixSection,
    ExecutiveSummarySection,
    MatrixCell,
    MatrixDimensionRow,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    SourceAppendixRow,
    StructuredReport,
    SwotSection,
    UserReviewThemesSection,
)


def _claim(
    text: str = "Cursor is the risk-adjusted recommendation for teams that value workflow maturity.",
    source_ids: list[str] | None = None,
    confidence: str = "high",
    evidence_role: str = "official_fact",
) -> CitedText:
    return CitedText(
        text=text,
        source_ids=source_ids or ["raw-source-cursor-pricing"],
        confidence=confidence,
        evidence_role=evidence_role,
    )


def _gap(text: str = "No direct user review source was collected for this narrow claim.") -> CitedText:
    return CitedText(
        text=text,
        source_ids=[],
        confidence="low",
        evidence_role="evidence_gap",
    )


def _support() -> ReportSupport:
    row = SourceAppendixRow(
        source_id="raw-source-cursor-pricing",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        competitor="Cursor",
        dimension="pricing",
        evidence_role="official_fact",
        confidence="high",
    )
    return ReportSupport(
        source_quality=[_claim("Official pricing and product documentation dominate pricing support.")],
        user_research_evidence=[_gap()],
        rag_gap_fill=[_gap("Collect direct buyer interview evidence before external publication.")],
        scenario_qa=[_claim("The recommendation is valid for engineering teams evaluating AI coding tools.")],
        claim_risk=[_claim("Pricing claims should be refreshed before procurement use.")],
        next_collection=[_gap("Collect two direct customer references for Cursor and Claude Code.")],
        evidence_appendix=[row],
    )


def _core() -> ReportCore:
    summary = ExecutiveSummarySection(
        recommendation=_claim(),
        risk_adjusted_rationale=_claim(
            "Windsurf has broad paper feature coverage, but Cursor remains the safer primary choice because reliability and ecosystem maturity reduce adoption risk."
        ),
        competitor_postures=[
            CompetitorPosture(
                competitor="Cursor",
                posture=_claim("Primary shortlist option for teams prioritizing mature IDE workflows."),
            ),
            CompetitorPosture(
                competitor="Windsurf",
                posture=_claim("Feature-rich challenger that requires reliability diligence."),
            ),
        ],
        confidence_boundary=_claim("The recommendation is strongest for team adoption, not individual hobby use."),
        next_actions=[
            _claim("Run a two-week pilot with Cursor as baseline and Windsurf as challenger."),
            _claim("Refresh pricing pages before final procurement."),
        ],
    )
    user_theme = CompetitorUserTheme(
        competitor="Cursor",
        direct_user_signals=[_claim("Community signals emphasize workflow speed.")],
        simulated_research_signals=[
            _claim(
                "Simulated interview respondents prefer low-friction IDE integration.",
                confidence="medium",
                evidence_role="simulated_research",
            )
        ],
        adoption_blockers=[_claim("Pricing clarity remains a buyer diligence item.")],
        switching_triggers=[_claim("Switching is most plausible when teams need consistent repository context.")],
        evidence_gaps=[_gap()],
    )
    deep_dive = CompetitorDeepDiveSection(
        competitor="Cursor",
        positioning=[_claim("Cursor positions around AI-native coding workflows.")],
        pricing_packaging=[_claim("Cursor publishes team pricing.")],
        feature_capabilities=[_claim("Cursor emphasizes editor-native coding assistance.")],
        persona_adoption=[_claim("Engineering teams are the primary adoption persona.")],
        community_feedback=[_claim("Community feedback is strongest around productivity gains.")],
        competitive_plays=[_claim("Lead with adoption maturity against less proven challengers.")],
        evidence_gaps=[_gap()],
    )
    matrix = DecisionMatrixSection(
        dimensions=[
            MatrixDimensionRow(
                dimension="pricing",
                cells=[
                    MatrixCell(
                        competitor="Cursor",
                        summary="Public team pricing is visible.",
                        source_ids=["raw-source-cursor-pricing"],
                        confidence="high",
                    ),
                    MatrixCell(
                        competitor="Windsurf",
                        summary="Pricing requires refresh before final comparison.",
                        source_ids=["raw-source-windsurf-pricing"],
                        confidence="medium",
                    ),
                ],
            )
        ],
        interpretation=[_claim("Cursor is easier to diligence on pricing.")],
        confidence_notes=[_claim("Matrix confidence varies by dimension and competitor.")],
    )
    swot = SwotSection(
        competitors=[
            CompetitorSwot(
                competitor="Cursor",
                strengths=[_claim("Strong workflow fit.")],
                weaknesses=[_claim("Pricing must be checked before final procurement.")],
                opportunities=[_claim("Can expand from individual developer adoption to teams.")],
                threats=[_claim("Feature-rich challengers can pressure roadmap expectations.")],
            )
        ]
    )
    battlecard = BattlecardSection(
        plays=[
            BattlecardPlay(
                competitor="Cursor",
                target_buyer="Engineering leadership",
                use_when=_claim("Use when the buyer values reliable team rollout over speculative feature breadth."),
                attack_points=[_claim("Ask whether challenger workflows are proven in team-scale repositories.")],
                defense_points=[_claim("Defend with mature IDE workflow and visible pricing diligence.")],
                likely_objections=[_claim("Buyer may object that a challenger has broader paper features.")],
                rebuttal_talk_tracks=[_claim("Separate feature breadth from risk-adjusted adoption readiness.")],
                proof_needed_before_external_use=[_claim("Refresh public pricing and security evidence.")],
            )
        ],
        evidence_limits=[_gap()],
    )
    return ReportCore(
        executive_summary=summary,
        decision_summary=[_claim("Choose Cursor as the baseline and test Windsurf as a challenger.")],
        competitive_findings=[_claim("The market splits between mature workflow adoption and feature breadth.")],
        user_review_themes=UserReviewThemesSection(
            competitor_themes=[user_theme],
            cross_competitor_patterns=[_claim("Teams value repository context and low workflow disruption.")],
            evidence_limits=[_gap()],
        ),
        competitor_deep_dives=[deep_dive],
        decision_matrix=matrix,
        swot=swot,
        battlecard=battlecard,
        community_triangulation=[_claim("Community and official evidence must be kept distinct.")],
    )


def test_structured_report_accepts_valid_core_and_support() -> None:
    report = StructuredReport(
        output_language="zh-CN",
        topic="AI coding agent competitive analysis",
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
        core=_core(),
        support=_support(),
        metadata=ReportMetadata(
            writer_mode="structured",
            segment_count=5,
            source_count=2,
            warnings=[],
            structured_report_version="1",
        ),
    )

    summary = report.compact_summary()

    assert summary["writer_mode"] == "structured"
    assert summary["core_section_count"] == 9
    assert summary["support_section_count"] == 7
    assert summary["competitors"] == ["Cursor", "Windsurf"]


def test_cited_text_rejects_markdown_source_tokens() -> None:
    with pytest.raises(ValidationError, match="must not contain Markdown source tokens"):
        CitedText(
            text="Cursor publishes pricing. [source:raw-source-cursor-pricing]",
            source_ids=["raw-source-cursor-pricing"],
            confidence="high",
            evidence_role="official_fact",
        )


def test_evidence_gap_is_the_only_empty_source_role() -> None:
    with pytest.raises(ValidationError, match="source_ids are required"):
        CitedText(
            text="Cursor has visible pricing.",
            source_ids=[],
            confidence="high",
            evidence_role="official_fact",
        )

    gap = _gap()
    assert gap.source_ids == []
