# Schema-First Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a schema-first writer pipeline that generates structured report objects first, validates them, renders deterministic Markdown into the existing `report_md`, and prevents the recurring report-quality failures seen in recent completed runs.

**Architecture:** Keep the current source-rich Writer Evidence Pack and existing Markdown writer as explicit fallback, but add a new structured path behind a feature flag. LLM calls fill typed section payloads; deterministic Python code owns headings, section order, table layout, citation placement, core/support separation, validation, and targeted repair routing.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing backend writer modules under `backend/packages/agents/writer`, existing `RunDetail`/`RunRecord` DTOs, existing conda Python environment.

---

## Scope Check

This plan implements only the user-approved schema-first writer backend spec:

- No frontend report view changes.
- No database migration.
- No generated reports, DB packages, output artifacts, or local document exports.
- No collector, analyst, comparator, community search, or source collection redesign.
- No weakening of source ID validation.
- No removal of the Markdown writer path.

The implementation must keep `report_md` as the canonical stored and frontend-visible output. Structured payloads are used in memory, compact trace events, and compact quality metadata when an enterprise projection already exists.

## File Structure

Create focused structured-writer modules:

- `backend/packages/agents/writer/structured_report.py`
  - Pydantic models for cited text, core sections, support sections, metadata, and complete `StructuredReport`.
  - Small helper methods for walking cited text fields and deriving compact summaries.

- `backend/packages/agents/writer/structured_renderer.py`
  - Deterministic Markdown renderer from `StructuredReport`.
  - Owns all H2/H3/H4 headings, localized labels, citation placement, table rendering, and core/support ordering.

- `backend/packages/agents/writer/structured_validation.py`
  - Semantic validator for source IDs, evidence roles, competitor coverage, internal term leakage, executive summary quality, battlecard substance, and citation tokens inside text fields.

- `backend/packages/agents/writer/publication_contract.py`
  - Final Markdown publishability checks after rendering.
  - Produces repair targets for renderer fixes or structured section rewrites.

- `backend/packages/agents/writer/structured_adapter.py`
  - Test and diagnostic adapter for minimal Markdown failure fixtures.
  - Detects current failure shapes without storing full real reports in tests.

Modify existing writer modules:

- `backend/packages/agents/writer/assembler.py`
  - Add `StructuredReportAssembler` for merging structured section payloads.
  - Leave existing Markdown assembly behavior untouched.

- `backend/packages/agents/writer/logic.py`
  - Add structured section JSON generation.
  - Route normal writer generation through structured path when the flag is enabled.
  - Keep Markdown fallback visible in trace.

- `backend/packages/agents/writer/repair.py`
  - Add structured repair target selection for structured-publication issues.
  - Keep existing Markdown repair plan for fallback reports.

- `backend/packages/config/settings.py`
  - Add `writer_structured_report_enabled`.

Add tests:

- `backend/tests/unit/test_writer_structured_report.py`
- `backend/tests/unit/test_writer_structured_renderer.py`
- `backend/tests/unit/test_writer_structured_validation.py`
- `backend/tests/unit/test_writer_publication_contract.py`
- `backend/tests/unit/test_writer_structured_adapter.py`
- `backend/tests/unit/test_writer_structured_generation.py`
- `backend/tests/unit/test_writer_structured_repair.py`

Every task below must be done with TDD: write the failing test, run it and see the expected failure, implement the smallest passing code, run the focused tests, then commit.

---

### Task 1: Structured Report Models

**Files:**
- Create: `backend/packages/agents/writer/structured_report.py`
- Test: `backend/tests/unit/test_writer_structured_report.py`

- [ ] **Step 1: Write the failing model tests**

Add this file:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run from the activated conda environment:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_report'`.

- [ ] **Step 3: Implement the structured report models**

Create `backend/packages/agents/writer/structured_report.py` with these public models and helpers:

```python
from __future__ import annotations

import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Confidence = Literal["high", "medium", "low"]
EvidenceRole = Literal[
    "official_fact",
    "community_signal",
    "simulated_research",
    "inference",
    "evidence_gap",
]

_SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]")


class CitedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    evidence_role: EvidenceRole

    @field_validator("text")
    @classmethod
    def _text_has_no_markdown_source_tokens(cls, value: str) -> str:
        if _SOURCE_TOKEN_RE.search(value):
            raise ValueError("text must not contain Markdown source tokens")
        return value.strip()

    @field_validator("source_ids")
    @classmethod
    def _source_ids_are_clean(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("source_ids must not contain duplicates")
        return cleaned

    @model_validator(mode="after")
    def _source_ids_required_except_gap(self) -> CitedText:
        if self.evidence_role != "evidence_gap" and not self.source_ids:
            raise ValueError("source_ids are required unless evidence_role is evidence_gap")
        if self.evidence_role == "evidence_gap" and self.confidence == "high":
            raise ValueError("evidence gaps cannot be high confidence")
        return self


class CompetitorPosture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    posture: CitedText


class ExecutiveSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: CitedText
    risk_adjusted_rationale: CitedText
    competitor_postures: list[CompetitorPosture] = Field(min_length=1)
    confidence_boundary: CitedText
    next_actions: list[CitedText] = Field(min_length=1)


class CompetitorUserTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    direct_user_signals: list[CitedText] = Field(default_factory=list)
    simulated_research_signals: list[CitedText] = Field(default_factory=list)
    adoption_blockers: list[CitedText] = Field(default_factory=list)
    switching_triggers: list[CitedText] = Field(default_factory=list)
    evidence_gaps: list[CitedText] = Field(default_factory=list)


class UserReviewThemesSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_themes: list[CompetitorUserTheme] = Field(min_length=1)
    cross_competitor_patterns: list[CitedText] = Field(default_factory=list)
    evidence_limits: list[CitedText] = Field(default_factory=list)


class CompetitorDeepDiveSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    positioning: list[CitedText] = Field(default_factory=list)
    pricing_packaging: list[CitedText] = Field(default_factory=list)
    feature_capabilities: list[CitedText] = Field(default_factory=list)
    persona_adoption: list[CitedText] = Field(default_factory=list)
    community_feedback: list[CitedText] = Field(default_factory=list)
    competitive_plays: list[CitedText] = Field(default_factory=list)
    evidence_gaps: list[CitedText] = Field(default_factory=list)


class MatrixCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Confidence

    @field_validator("summary")
    @classmethod
    def _summary_has_no_source_tokens(cls, value: str) -> str:
        if _SOURCE_TOKEN_RE.search(value):
            raise ValueError("matrix summary must not contain Markdown source tokens")
        return value.strip()


class MatrixDimensionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(min_length=1)
    cells: list[MatrixCell] = Field(min_length=1)


class DecisionMatrixSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[MatrixDimensionRow] = Field(min_length=1)
    interpretation: list[CitedText] = Field(default_factory=list)
    confidence_notes: list[CitedText] = Field(default_factory=list)


class CompetitorSwot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    strengths: list[CitedText] = Field(default_factory=list)
    weaknesses: list[CitedText] = Field(default_factory=list)
    opportunities: list[CitedText] = Field(default_factory=list)
    threats: list[CitedText] = Field(default_factory=list)


class SwotSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[CompetitorSwot] = Field(min_length=1)


class BattlecardPlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    target_buyer: str = Field(min_length=1)
    use_when: CitedText
    attack_points: list[CitedText] = Field(min_length=1)
    defense_points: list[CitedText] = Field(min_length=1)
    likely_objections: list[CitedText] = Field(min_length=1)
    rebuttal_talk_tracks: list[CitedText] = Field(min_length=1)
    proof_needed_before_external_use: list[CitedText] = Field(min_length=1)


class BattlecardSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plays: list[BattlecardPlay] = Field(default_factory=list)
    evidence_limits: list[CitedText] = Field(default_factory=list)


class SourceAppendixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = ""
    competitor: str = ""
    dimension: str = ""
    evidence_role: EvidenceRole
    confidence: Confidence


class ReportCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: ExecutiveSummarySection
    decision_summary: list[CitedText] = Field(min_length=1)
    competitive_findings: list[CitedText] = Field(min_length=1)
    user_review_themes: UserReviewThemesSection
    competitor_deep_dives: list[CompetitorDeepDiveSection] = Field(min_length=1)
    decision_matrix: DecisionMatrixSection
    swot: SwotSection
    battlecard: BattlecardSection
    community_triangulation: list[CitedText] = Field(default_factory=list)


class ReportSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_quality: list[CitedText] = Field(default_factory=list)
    user_research_evidence: list[CitedText] = Field(default_factory=list)
    rag_gap_fill: list[CitedText] = Field(default_factory=list)
    scenario_qa: list[CitedText] = Field(default_factory=list)
    claim_risk: list[CitedText] = Field(default_factory=list)
    next_collection: list[CitedText] = Field(default_factory=list)
    evidence_appendix: list[SourceAppendixRow] = Field(default_factory=list)


class ReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writer_mode: str = Field(min_length=1)
    segment_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    structured_report_version: str = Field(min_length=1)


class StructuredReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_language: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    competitors: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    core: ReportCore
    support: ReportSupport
    metadata: ReportMetadata

    def iter_cited_text(self) -> Iterable[tuple[str, CitedText]]:
        yield from _walk_cited_text("core", self.core)
        yield from _walk_cited_text("support", self.support)

    def compact_summary(self) -> dict[str, Any]:
        return {
            "writer_mode": self.metadata.writer_mode,
            "structured_report_version": self.metadata.structured_report_version,
            "competitors": list(self.competitors),
            "dimensions": list(self.dimensions),
            "core_section_count": 9,
            "support_section_count": 7,
            "source_count": self.metadata.source_count,
            "segment_count": self.metadata.segment_count,
            "warning_count": len(self.metadata.warnings),
        }


def _walk_cited_text(prefix: str, value: Any) -> Iterable[tuple[str, CitedText]]:
    if isinstance(value, CitedText):
        yield prefix, value
        return
    if isinstance(value, BaseModel):
        for field_name in value.model_fields:
            child = getattr(value, field_name)
            child_prefix = f"{prefix}.{field_name}"
            yield from _walk_cited_text(child_prefix, child)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_cited_text(f"{prefix}[{index}]", child)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/agents/writer/structured_report.py backend/tests/unit/test_writer_structured_report.py
git commit -m "feat: add structured writer report models"
```

---

### Task 2: Deterministic Structured Markdown Renderer

**Files:**
- Create: `backend/packages/agents/writer/structured_renderer.py`
- Test: `backend/tests/unit/test_writer_structured_renderer.py`

- [ ] **Step 1: Write renderer tests**

Add `backend/tests/unit/test_writer_structured_renderer.py`:

```python
from __future__ import annotations

from packages.agents.writer.structured_renderer import render_structured_report
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


def _claim(text: str, source_ids: list[str] | None = None) -> CitedText:
    return CitedText(
        text=text,
        source_ids=source_ids or ["raw-source-a"],
        confidence="high",
        evidence_role="official_fact",
    )


def _report(output_language: str = "zh-CN") -> StructuredReport:
    return StructuredReport(
        output_language=output_language,
        topic="AI coding agent competitive analysis",
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature"],
        core=ReportCore(
            executive_summary=ExecutiveSummarySection(
                recommendation=_claim("优先以 Cursor 作为团队采购基线。"),
                risk_adjusted_rationale=_claim("Windsurf 功能覆盖更宽，但可靠性风险使其更适合作为挑战者。"),
                competitor_postures=[
                    CompetitorPosture(competitor="Cursor", posture=_claim("主力候选。")),
                    CompetitorPosture(competitor="Windsurf", posture=_claim("挑战者候选。")),
                ],
                confidence_boundary=_claim("结论适用于团队采购，不覆盖个人轻量使用。"),
                next_actions=[_claim("先做两周试点，再刷新价格证据。")],
            ),
            decision_summary=[_claim("采购建议是 Cursor baseline 加 Windsurf challenger。")],
            competitive_findings=[_claim("竞争焦点是成熟工作流与功能广度的取舍。")],
            user_review_themes=UserReviewThemesSection(
                competitor_themes=[
                    CompetitorUserTheme(
                        competitor="Cursor",
                        direct_user_signals=[_claim("社区信号强调开发工作流速度。")],
                        simulated_research_signals=[
                            CitedText(
                                text="模拟访谈显示团队更看重 IDE 内低摩擦协作。",
                                source_ids=["raw-source-survey"],
                                confidence="medium",
                                evidence_role="simulated_research",
                            )
                        ],
                        adoption_blockers=[_claim("采购前仍需确认价格口径。")],
                        switching_triggers=[_claim("团队需要统一上下文时更容易切换。")],
                        evidence_gaps=[
                            CitedText(
                                text="缺少直接买家访谈。",
                                source_ids=[],
                                confidence="low",
                                evidence_role="evidence_gap",
                            )
                        ],
                    )
                ],
                cross_competitor_patterns=[_claim("团队共同关注上下文和落地风险。")],
                evidence_limits=[
                    CitedText(
                        text="直接评论证据不足。",
                        source_ids=[],
                        confidence="low",
                        evidence_role="evidence_gap",
                    )
                ],
            ),
            competitor_deep_dives=[
                CompetitorDeepDiveSection(
                    competitor="Cursor",
                    positioning=[_claim("Cursor 以 AI 原生编码工作流定位。")],
                    pricing_packaging=[_claim("Cursor 有公开价格页。")],
                    feature_capabilities=[_claim("Cursor 强调编辑器内能力。")],
                    persona_adoption=[_claim("主要采用者是工程团队。")],
                    community_feedback=[_claim("社区反馈集中在效率提升。")],
                    competitive_plays=[_claim("用成熟落地对抗功能广度。")],
                    evidence_gaps=[],
                )
            ],
            decision_matrix=DecisionMatrixSection(
                dimensions=[
                    MatrixDimensionRow(
                        dimension="pricing",
                        cells=[
                            MatrixCell(
                                competitor="Cursor",
                                summary="公开价格更易核验",
                                source_ids=["raw-source-a"],
                                confidence="high",
                            ),
                            MatrixCell(
                                competitor="Windsurf",
                                summary="采购前需要刷新价格",
                                source_ids=["raw-source-b"],
                                confidence="medium",
                            ),
                        ],
                    )
                ],
                interpretation=[_claim("价格维度 Cursor 更易完成采购核验。")],
                confidence_notes=[_claim("矩阵置信度按维度变化。")],
            ),
            swot=SwotSection(
                competitors=[
                    CompetitorSwot(
                        competitor="Cursor",
                        strengths=[_claim("工作流成熟。")],
                        weaknesses=[_claim("价格需采购前刷新。")],
                        opportunities=[_claim("可从个人扩展到团队。")],
                        threats=[_claim("挑战者会施压功能路线图。")],
                    )
                ]
            ),
            battlecard=BattlecardSection(
                plays=[
                    BattlecardPlay(
                        competitor="Windsurf",
                        target_buyer="工程负责人",
                        use_when=_claim("当客户被功能广度吸引但担心落地风险时使用。"),
                        attack_points=[_claim("追问挑战者是否有团队规模落地证据。")],
                        defense_points=[_claim("强调成熟工作流和采购可核验性。")],
                        likely_objections=[_claim("客户可能认为 Windsurf 功能更多。")],
                        rebuttal_talk_tracks=[_claim("把纸面功能和风险调整后的采用成功率分开。")],
                        proof_needed_before_external_use=[_claim("对外使用前刷新价格和安全材料。")],
                    )
                ],
                evidence_limits=[],
            ),
            community_triangulation=[_claim("社区信号只作为辅助，不替代官方事实。")],
        ),
        support=ReportSupport(
            source_quality=[_claim("价格证据主要来自官方来源。")],
            user_research_evidence=[_claim("用户证据包含社区和模拟研究，二者需分层。")],
            rag_gap_fill=[_claim("缺口集中在直接买家访谈。")],
            scenario_qa=[_claim("场景检查覆盖团队采购。")],
            claim_risk=[_claim("高风险声明需采购前刷新。")],
            next_collection=[_claim("下一步补直接访谈。")],
            evidence_appendix=[
                SourceAppendixRow(
                    source_id="raw-source-a",
                    title="Cursor pricing",
                    url="https://cursor.com/pricing",
                    competitor="Cursor",
                    dimension="pricing",
                    evidence_role="official_fact",
                    confidence="high",
                )
            ],
        ),
        metadata=ReportMetadata(
            writer_mode="structured",
            segment_count=5,
            source_count=3,
            warnings=[],
            structured_report_version="1",
        ),
    )


def test_renderer_localizes_zh_structural_headings_and_keeps_support_after_core() -> None:
    markdown = render_structured_report(_report("zh-CN"))

    assert "## 执行摘要" in markdown
    assert "## 战报" in markdown
    assert "### Pricing and Packaging" not in markdown
    assert markdown.index("## 战报") < markdown.index("## 支撑材料")
    assert "Segment Evidence Pack JSON" not in markdown


def test_renderer_puts_citations_in_body_cells_not_table_headers() -> None:
    markdown = render_structured_report(_report("zh-CN"))
    lines = markdown.splitlines()

    header_lines = [line for line in lines if line.startswith("| 维度 |")]

    assert header_lines
    assert all("[source:" not in line for line in header_lines)
    assert "| pricing | 公开价格更易核验 [source:raw-source-a] |" in markdown


def test_renderer_keeps_text_fields_free_of_raw_source_tokens_until_render_time() -> None:
    markdown = render_structured_report(_report("zh-CN"))

    assert "优先以 Cursor 作为团队采购基线。 [source:raw-source-a]" in markdown
    assert "[source: raw-source-a]" not in markdown
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_renderer.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_renderer'`.

- [ ] **Step 3: Implement renderer**

Create `backend/packages/agents/writer/structured_renderer.py`:

```python
from __future__ import annotations

from collections.abc import Iterable

from packages.agents.writer.structured_report import (
    BattlecardPlay,
    CitedText,
    CompetitorDeepDiveSection,
    CompetitorSwot,
    CompetitorUserTheme,
    MatrixCell,
    StructuredReport,
)


_ZH_LABELS: dict[str, str] = {
    "executive_summary": "执行摘要",
    "decision_summary": "决策摘要",
    "competitive_findings": "竞争发现",
    "user_review_themes": "用户评价整理",
    "direct_user_signals": "直接用户与社区信号",
    "simulated_research_signals": "模拟调研信号",
    "adoption_blockers": "采用障碍",
    "switching_triggers": "切换触发器",
    "evidence_gaps": "证据缺口",
    "competitor_deep_dives": "竞品深挖",
    "positioning": "定位与核心价值",
    "pricing_packaging": "定价与包装",
    "feature_capabilities": "功能与工作流能力",
    "persona_adoption": "用户画像与采用路径",
    "community_feedback": "社区与用户反馈",
    "competitive_plays": "竞争打法",
    "decision_matrix": "决策矩阵",
    "matrix_interpretation": "矩阵解读",
    "confidence_notes": "置信度说明",
    "swot": "SWOT 分析",
    "battlecard": "战报",
    "community_triangulation": "社区三角验证",
    "support": "支撑材料",
    "source_quality": "来源质量",
    "user_research_evidence": "用户研究证据",
    "rag_gap_fill": "RAG 补缺",
    "scenario_qa": "场景 QA",
    "claim_risk": "声明风险",
    "next_collection": "后续采集",
    "evidence_appendix": "证据附录",
}

_EN_LABELS: dict[str, str] = {
    "executive_summary": "Executive Summary",
    "decision_summary": "Decision Summary",
    "competitive_findings": "Competitive Findings",
    "user_review_themes": "User Review Themes",
    "direct_user_signals": "Direct User and Community Signals",
    "simulated_research_signals": "Simulated Research Signals",
    "adoption_blockers": "Adoption Blockers",
    "switching_triggers": "Switching Triggers",
    "evidence_gaps": "Evidence Gaps",
    "competitor_deep_dives": "Competitor Deep Dives",
    "positioning": "Positioning and Core Value",
    "pricing_packaging": "Pricing and Packaging",
    "feature_capabilities": "Feature and Workflow Capability",
    "persona_adoption": "Persona and Adoption Path",
    "community_feedback": "Community and User Feedback",
    "competitive_plays": "Competitive Plays",
    "decision_matrix": "Decision Matrix",
    "matrix_interpretation": "Matrix Interpretation",
    "confidence_notes": "Confidence Notes",
    "swot": "SWOT Analysis",
    "battlecard": "Battlecard",
    "community_triangulation": "Community Triangulation",
    "support": "Support Materials",
    "source_quality": "Source Quality",
    "user_research_evidence": "User Research Evidence",
    "rag_gap_fill": "RAG Gap Fill",
    "scenario_qa": "Scenario QA",
    "claim_risk": "Claim Risk",
    "next_collection": "Next Collection",
    "evidence_appendix": "Evidence Appendix",
}


def render_structured_report(report: StructuredReport) -> str:
    labels = _ZH_LABELS if report.output_language.lower().startswith("zh") else _EN_LABELS
    lines: list[str] = []
    lines.extend(_heading(1, report.topic))
    lines.extend(_executive_summary(report, labels))
    lines.extend(_cited_list_section(2, labels["decision_summary"], report.core.decision_summary))
    lines.extend(_cited_list_section(2, labels["competitive_findings"], report.core.competitive_findings))
    lines.extend(_user_review_themes(report, labels))
    lines.extend(_deep_dives(report.core.competitor_deep_dives, labels))
    lines.extend(_decision_matrix(report, labels))
    lines.extend(_swot(report.core.swot.competitors, labels))
    lines.extend(_battlecard(report.core.battlecard.plays, report.core.battlecard.evidence_limits, labels))
    if report.core.community_triangulation:
        lines.extend(_cited_list_section(2, labels["community_triangulation"], report.core.community_triangulation))
    lines.extend(_support_sections(report, labels))
    return _clean_markdown(lines)


def _heading(level: int, text: str) -> list[str]:
    return [f"{'#' * level} {text.strip()}", ""]


def _executive_summary(report: StructuredReport, labels: dict[str, str]) -> list[str]:
    section = report.core.executive_summary
    lines = _heading(2, labels["executive_summary"])
    lines.extend(
        [
            f"- **推荐：** {_render_claim(section.recommendation)}",
            f"- **风险调整理由：** {_render_claim(section.risk_adjusted_rationale)}",
            "- **竞品姿态：**",
        ]
    )
    for item in section.competitor_postures:
        lines.append(f"  - **{item.competitor}：** {_render_claim(item.posture)}")
    lines.extend(
        [
            f"- **置信边界：** {_render_claim(section.confidence_boundary)}",
            "- **下一步行动：**",
        ]
    )
    for action in section.next_actions:
        lines.append(f"  - {_render_claim(action)}")
    lines.append("")
    return lines


def _user_review_themes(report: StructuredReport, labels: dict[str, str]) -> list[str]:
    lines = _heading(2, labels["user_review_themes"])
    for theme in report.core.user_review_themes.competitor_themes:
        lines.extend(_theme_block(theme, labels))
    lines.extend(_cited_list_section(3, "跨竞品模式", report.core.user_review_themes.cross_competitor_patterns))
    lines.extend(_cited_list_section(3, "证据边界", report.core.user_review_themes.evidence_limits))
    return lines


def _theme_block(theme: CompetitorUserTheme, labels: dict[str, str]) -> list[str]:
    lines = _heading(3, theme.competitor)
    groups = [
        (labels["direct_user_signals"], theme.direct_user_signals),
        (labels["simulated_research_signals"], theme.simulated_research_signals),
        (labels["adoption_blockers"], theme.adoption_blockers),
        (labels["switching_triggers"], theme.switching_triggers),
        (labels["evidence_gaps"], theme.evidence_gaps),
    ]
    for title, claims in groups:
        if claims:
            lines.extend(_cited_list_section(4, title, claims))
    return lines


def _deep_dives(sections: list[CompetitorDeepDiveSection], labels: dict[str, str]) -> list[str]:
    lines = _heading(2, labels["competitor_deep_dives"])
    for section in sections:
        lines.extend(_heading(3, section.competitor))
        groups = [
            (labels["positioning"], section.positioning),
            (labels["pricing_packaging"], section.pricing_packaging),
            (labels["feature_capabilities"], section.feature_capabilities),
            (labels["persona_adoption"], section.persona_adoption),
            (labels["community_feedback"], section.community_feedback),
            (labels["competitive_plays"], section.competitive_plays),
            (labels["evidence_gaps"], section.evidence_gaps),
        ]
        for title, claims in groups:
            if claims:
                lines.extend(_cited_list_section(4, title, claims))
    return lines


def _decision_matrix(report: StructuredReport, labels: dict[str, str]) -> list[str]:
    lines = _heading(2, labels["decision_matrix"])
    competitors = list(report.competitors)
    header = "| 维度 | " + " | ".join(competitors) + " |"
    divider = "|---|" + "|".join("---" for _ in competitors) + "|"
    lines.extend([header, divider])
    for row in report.core.decision_matrix.dimensions:
        by_competitor = {cell.competitor: cell for cell in row.cells}
        rendered = [_render_matrix_cell(by_competitor.get(competitor)) for competitor in competitors]
        lines.append("| " + row.dimension + " | " + " | ".join(rendered) + " |")
    lines.append("")
    lines.extend(_cited_list_section(3, labels["matrix_interpretation"], report.core.decision_matrix.interpretation))
    lines.extend(_cited_list_section(3, labels["confidence_notes"], report.core.decision_matrix.confidence_notes))
    return lines


def _swot(items: list[CompetitorSwot], labels: dict[str, str]) -> list[str]:
    lines = _heading(2, labels["swot"])
    quadrant_labels = [
        ("优势", "strengths"),
        ("劣势", "weaknesses"),
        ("机会", "opportunities"),
        ("威胁", "threats"),
    ]
    for item in items:
        lines.extend(_heading(3, item.competitor))
        for label, field_name in quadrant_labels:
            claims = getattr(item, field_name)
            lines.extend(_cited_list_section(4, label, claims))
    return lines


def _battlecard(plays: list[BattlecardPlay], evidence_limits: list[CitedText], labels: dict[str, str]) -> list[str]:
    lines = _heading(2, labels["battlecard"])
    for play in plays:
        lines.extend(_heading(3, play.competitor))
        lines.append(f"- **目标买家：** {play.target_buyer}")
        lines.append(f"- **使用场景：** {_render_claim(play.use_when)}")
        lines.extend(_cited_list_section(4, "攻击点", play.attack_points))
        lines.extend(_cited_list_section(4, "防守点", play.defense_points))
        lines.extend(_cited_list_section(4, "常见异议", play.likely_objections))
        lines.extend(_cited_list_section(4, "反驳话术", play.rebuttal_talk_tracks))
        lines.extend(_cited_list_section(4, "对外使用前需补证", play.proof_needed_before_external_use))
    if evidence_limits:
        lines.extend(_cited_list_section(3, "证据边界", evidence_limits))
    return lines


def _support_sections(report: StructuredReport, labels: dict[str, str]) -> list[str]:
    lines = _heading(2, labels["support"])
    support = report.support
    lines.extend(_cited_list_section(3, labels["source_quality"], support.source_quality))
    lines.extend(_cited_list_section(3, labels["user_research_evidence"], support.user_research_evidence))
    lines.extend(_cited_list_section(3, labels["rag_gap_fill"], support.rag_gap_fill))
    lines.extend(_cited_list_section(3, labels["scenario_qa"], support.scenario_qa))
    lines.extend(_cited_list_section(3, labels["claim_risk"], support.claim_risk))
    lines.extend(_cited_list_section(3, labels["next_collection"], support.next_collection))
    lines.extend(_heading(3, labels["evidence_appendix"]))
    lines.extend(["| Source ID | Title | Competitor | Dimension | Role | Confidence |", "|---|---|---|---|---|---|"])
    for row in support.evidence_appendix:
        lines.append(
            f"| {row.source_id} | {row.title} | {row.competitor} | {row.dimension} | {row.evidence_role} | {row.confidence} |"
        )
    lines.append("")
    return lines


def _cited_list_section(level: int, title: str, claims: Iterable[CitedText]) -> list[str]:
    items = list(claims)
    if not items:
        return []
    lines = _heading(level, title)
    for claim in items:
        lines.append(f"- {_render_claim(claim)}")
    lines.append("")
    return lines


def _render_matrix_cell(cell: MatrixCell | None) -> str:
    if cell is None:
        return "证据缺口"
    return cell.summary + _render_source_ids(cell.source_ids)


def _render_claim(claim: CitedText) -> str:
    return claim.text + _render_source_ids(claim.source_ids)


def _render_source_ids(source_ids: list[str]) -> str:
    if not source_ids:
        return ""
    return " " + "".join(f"[source:{source_id}]" for source_id in source_ids)


def _clean_markdown(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text + "\n"
```

- [ ] **Step 4: Run renderer and model tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/agents/writer/structured_renderer.py backend/tests/unit/test_writer_structured_renderer.py
git commit -m "feat: render structured writer reports"
```

---

### Task 3: Structured Report Semantic Validation

**Files:**
- Create: `backend/packages/agents/writer/structured_validation.py`
- Modify: `backend/tests/unit/test_writer_structured_renderer.py`
- Test: `backend/tests/unit/test_writer_structured_validation.py`

- [ ] **Step 1: Reuse the renderer test fixture**

Keep `_report()` in `backend/tests/unit/test_writer_structured_renderer.py` and import it in this validation test with `from test_writer_structured_renderer import _report`. This keeps the plan minimal and matches the current test layout, where `backend/tests` is not a Python package.

- [ ] **Step 2: Write semantic validation tests**

Add `backend/tests/unit/test_writer_structured_validation.py`:

```python
from __future__ import annotations

from packages.agents.writer.structured_validation import validate_structured_report
from packages.agents.writer.structured_renderer import render_structured_report
from packages.agents.writer.structured_report import CitedText
from test_writer_structured_renderer import _report


def test_validation_rejects_unknown_source_ids() -> None:
    report = _report()

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-b", "raw-source-survey"},
        strong_source_ids={"raw-source-b"},
    )

    assert not result.passed
    assert "invalid_source_id" in result.issue_codes()
    assert any(issue.path.endswith("recommendation") for issue in result.issues)


def test_validation_rejects_template_only_battlecard() -> None:
    report = _report()
    play = report.core.battlecard.plays[0]
    report.core.battlecard.plays[0] = play.model_copy(
        update={
            "attack_points": [
                CitedText(
                    text="直接战报定位",
                    source_ids=["raw-source-a"],
                    confidence="high",
                    evidence_role="official_fact",
                )
            ],
            "defense_points": [
                CitedText(
                    text="反对意见处理",
                    source_ids=["raw-source-a"],
                    confidence="high",
                    evidence_role="official_fact",
                )
            ],
        }
    )

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
        strong_source_ids={"raw-source-a", "raw-source-b"},
    )

    assert not result.passed
    assert "battlecard_template_only" in result.issue_codes()


def test_validation_rejects_template_like_executive_summary() -> None:
    report = _report()
    report.core.executive_summary.recommendation = CitedText(
        text="This report is structured as decision analysis first, with evidence and QA support after the core competitive readout.",
        source_ids=["raw-source-a"],
        confidence="high",
        evidence_role="official_fact",
    )

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
        strong_source_ids={"raw-source-a", "raw-source-b"},
    )

    assert not result.passed
    assert "executive_summary_template_only" in result.issue_codes()


def test_validation_rejects_internal_terms_after_rendering_text_is_clean() -> None:
    report = _report()
    report.core.competitive_findings[0] = CitedText(
        text="Segment Evidence Pack JSON contains source_registry rows.",
        source_ids=["raw-source-a"],
        confidence="high",
        evidence_role="official_fact",
    )

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
        strong_source_ids={"raw-source-a", "raw-source-b"},
    )

    assert not result.passed
    assert "internal_term_leak" in result.issue_codes()
    assert "Segment Evidence Pack JSON" in render_structured_report(report)


def test_validation_rejects_missing_competitor_coverage() -> None:
    report = _report()

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
        strong_source_ids={"raw-source-a", "raw-source-b"},
    )

    assert not result.passed
    assert "competitor_coverage_missing" in result.issue_codes()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_validation.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_validation'`.

- [ ] **Step 4: Implement semantic validation**

Create `backend/packages/agents/writer/structured_validation.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from packages.agents.writer.structured_report import (
    BattlecardPlay,
    CitedText,
    CompetitorSwot,
    StructuredReport,
)


_INTERNAL_TERMS = (
    "source_registry",
    "allowed_source_ids",
    "represented_by",
    "Segment Evidence Pack JSON",
    "Writer Evidence Pack",
    "fact:",
    "signal:",
)
_SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]")
_TEMPLATE_BATTLECARD_TERMS = {
    "直接战报定位",
    "反对意见处理",
    "行动偏向",
    "落地检查",
    "direct battlecard positioning",
    "objection handling",
    "deployment check",
}
_TEMPLATE_EXECUTIVE_TERMS = (
    "This report is structured as decision analysis first",
    "core conclusion",
    "decision posture",
    "risk boundary",
    "immediate action",
    "核心结论",
    "决策姿态",
    "风险边界",
    "立即行动",
)


@dataclass(frozen=True)
class StructuredValidationIssue:
    code: str
    path: str
    message: str
    repair_target: str


@dataclass(frozen=True)
class StructuredReportValidation:
    passed: bool
    issues: list[StructuredValidationIssue] = field(default_factory=list)

    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issue_count": len(self.issues),
            "issue_codes": self.issue_codes(),
            "repair_targets": [issue.repair_target for issue in self.issues],
        }


def validate_structured_report(
    report: StructuredReport,
    *,
    allowed_source_ids: set[str],
    strong_source_ids: set[str],
) -> StructuredReportValidation:
    issues: list[StructuredValidationIssue] = []
    issues.extend(_source_id_issues(report, allowed_source_ids))
    issues.extend(_strong_recommendation_issues(report, strong_source_ids))
    issues.extend(_competitor_coverage_issues(report))
    issues.extend(_internal_term_issues(report))
    issues.extend(_markdown_token_issues(report))
    issues.extend(_battlecard_issues(report))
    issues.extend(_executive_summary_issues(report))
    return StructuredReportValidation(passed=not issues, issues=issues)


def _source_id_issues(
    report: StructuredReport,
    allowed_source_ids: set[str],
) -> Iterable[StructuredValidationIssue]:
    for path, claim in report.iter_cited_text():
        for source_id in claim.source_ids:
            if source_id not in allowed_source_ids:
                yield StructuredValidationIssue(
                    code="invalid_source_id",
                    path=path,
                    message=f"Unknown source id {source_id}",
                    repair_target=path,
                )


def _strong_recommendation_issues(
    report: StructuredReport,
    strong_source_ids: set[str],
) -> Iterable[StructuredValidationIssue]:
    required = {
        "core.executive_summary.recommendation": report.core.executive_summary.recommendation,
        "core.executive_summary.risk_adjusted_rationale": report.core.executive_summary.risk_adjusted_rationale,
    }
    for path, claim in required.items():
        if claim.evidence_role in {"simulated_research", "evidence_gap"}:
            yield StructuredValidationIssue(
                code="weak_recommendation_evidence",
                path=path,
                message="Recommendation cannot rely on simulated research or evidence gaps",
                repair_target="core.executive_summary",
            )
            continue
        if not set(claim.source_ids) & strong_source_ids:
            yield StructuredValidationIssue(
                code="weak_recommendation_evidence",
                path=path,
                message="Recommendation lacks a strong official or verified source",
                repair_target="core.executive_summary",
            )


def _competitor_coverage_issues(report: StructuredReport) -> Iterable[StructuredValidationIssue]:
    expected = set(report.competitors)
    deep_dive = {item.competitor for item in report.core.competitor_deep_dives}
    themes = {item.competitor for item in report.core.user_review_themes.competitor_themes}
    swot = {item.competitor for item in report.core.swot.competitors}
    battlecard = {item.competitor for item in report.core.battlecard.plays}
    coverage = {
        "core.competitor_deep_dives": deep_dive,
        "core.user_review_themes": themes,
        "core.swot": swot,
        "core.battlecard": battlecard,
    }
    for path, actual in coverage.items():
        missing = sorted(expected - actual)
        if missing:
            yield StructuredValidationIssue(
                code="competitor_coverage_missing",
                path=path,
                message=f"Missing competitors: {', '.join(missing)}",
                repair_target=path,
            )
    for item in report.core.swot.competitors:
        yield from _swot_quadrant_issues(item)


def _swot_quadrant_issues(item: CompetitorSwot) -> Iterable[StructuredValidationIssue]:
    quadrants = {
        "strengths": item.strengths,
        "weaknesses": item.weaknesses,
        "opportunities": item.opportunities,
        "threats": item.threats,
    }
    for name, claims in quadrants.items():
        if not claims:
            yield StructuredValidationIssue(
                code="swot_quadrant_missing",
                path=f"core.swot.{item.competitor}.{name}",
                message=f"Missing SWOT quadrant {name} for {item.competitor}",
                repair_target="core.swot",
            )


def _internal_term_issues(report: StructuredReport) -> Iterable[StructuredValidationIssue]:
    for path, claim in report.iter_cited_text():
        for term in _INTERNAL_TERMS:
            if term in claim.text:
                yield StructuredValidationIssue(
                    code="internal_term_leak",
                    path=path,
                    message=f"Internal term leaked: {term}",
                    repair_target=path,
                )


def _markdown_token_issues(report: StructuredReport) -> Iterable[StructuredValidationIssue]:
    for path, claim in report.iter_cited_text():
        if _SOURCE_TOKEN_RE.search(claim.text):
            yield StructuredValidationIssue(
                code="markdown_source_token_in_text",
                path=path,
                message="CitedText.text contains a Markdown source token",
                repair_target=path,
            )


def _battlecard_issues(report: StructuredReport) -> Iterable[StructuredValidationIssue]:
    for index, play in enumerate(report.core.battlecard.plays):
        texts = _play_texts(play)
        lower_text = " ".join(texts).casefold()
        template_hits = [term for term in _TEMPLATE_BATTLECARD_TERMS if term.casefold() in lower_text]
        substantive_count = sum(1 for text in texts if len(text) >= 28)
        if template_hits or substantive_count < 5:
            yield StructuredValidationIssue(
                code="battlecard_template_only",
                path=f"core.battlecard.plays[{index}]",
                message="Battlecard play is too generic to use as competitive guidance",
                repair_target="core.battlecard",
            )


def _play_texts(play: BattlecardPlay) -> list[str]:
    claims = [
        play.use_when,
        *play.attack_points,
        *play.defense_points,
        *play.likely_objections,
        *play.rebuttal_talk_tracks,
        *play.proof_needed_before_external_use,
    ]
    return [claim.text for claim in claims]


def _executive_summary_issues(report: StructuredReport) -> Iterable[StructuredValidationIssue]:
    section = report.core.executive_summary
    texts = [
        section.recommendation.text,
        section.risk_adjusted_rationale.text,
        section.confidence_boundary.text,
    ]
    joined = " ".join(texts)
    if any(term in joined for term in _TEMPLATE_EXECUTIVE_TERMS):
        yield StructuredValidationIssue(
            code="executive_summary_template_only",
            path="core.executive_summary",
            message="Executive summary contains system-style template language",
            repair_target="core.executive_summary",
        )
    if len(section.risk_adjusted_rationale.text) < 40:
        yield StructuredValidationIssue(
            code="executive_summary_missing_risk_adjusted_rationale",
            path="core.executive_summary.risk_adjusted_rationale",
            message="Risk-adjusted rationale is too short to explain the recommendation",
            repair_target="core.executive_summary",
        )
```

- [ ] **Step 5: Run validation tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_validation.py -v
```

Expected: PASS.

- [ ] **Step 6: Run renderer and model tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/agents/writer/structured_validation.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_structured_renderer.py
git commit -m "feat: validate structured writer reports"
```

---

### Task 4: Publication Contract Over Rendered Markdown

**Files:**
- Create: `backend/packages/agents/writer/publication_contract.py`
- Test: `backend/tests/unit/test_writer_publication_contract.py`

- [ ] **Step 1: Write publication contract tests**

Add `backend/tests/unit/test_writer_publication_contract.py`:

```python
from __future__ import annotations

from packages.agents.writer.publication_contract import validate_publication_contract
from packages.agents.writer.structured_renderer import render_structured_report
from test_writer_structured_renderer import _report


def test_publication_contract_rejects_english_structural_heading_in_zh_report() -> None:
    markdown = "## 用户评价整理\n\n### Direct User / Community Signals\n\n- Text [source:raw-source-a]\n"

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "english_structural_heading_in_zh" in result.issue_codes()
    assert result.issues[0].repair_target == "renderer"


def test_publication_contract_rejects_citations_in_headings_and_table_headers() -> None:
    markdown = (
        "## 决策矩阵 [source:raw-source-a]\n\n"
        "| 维度 [source:raw-source-a] | Cursor |\n"
        "|---|---|\n"
        "| pricing | visible [source:raw-source-a] |\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "citation_in_heading" in result.issue_codes()
    assert "citation_in_table_header" in result.issue_codes()


def test_publication_contract_accepts_renderer_output() -> None:
    report = _report("zh-CN")
    markdown = render_structured_report(report)

    result = validate_publication_contract(
        markdown,
        structured_report=report,
        allowed_source_ids={"raw-source-a", "raw-source-b", "raw-source-survey"},
    )

    assert result.passed
    assert result.issues == []


def test_publication_contract_rejects_internal_terms_and_unknown_sources() -> None:
    markdown = (
        "## 执行摘要\n\n"
        "- Segment Evidence Pack JSON leaked here. [source:raw-source-a]\n"
        "- Unknown citation. [source:raw-source-missing]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=_report("zh-CN"),
        allowed_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "internal_term_leak" in result.issue_codes()
    assert "invalid_source_id" in result.issue_codes()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_publication_contract.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.publication_contract'`.

- [ ] **Step 3: Implement publication contract**

Create `backend/packages/agents/writer/publication_contract.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

from packages.agents.writer.structured_report import StructuredReport


_SOURCE_TOKEN_RE = re.compile(r"\[source:([^\]]+)\]")
_ENGLISH_STRUCTURAL_HEADINGS = (
    "Pricing and Packaging",
    "Feature and Workflow Capability",
    "Direct User / Community Signals",
    "Simulated Survey and Interview Signals",
    "Simulated Research Signals",
    "Positioning and Core Value",
    "Strengths",
    "Weaknesses",
    "Opportunities",
    "Threats",
)
_INTERNAL_TERMS = (
    "source_registry",
    "allowed_source_ids",
    "represented_by",
    "Segment Evidence Pack JSON",
    "Writer Evidence Pack",
    "fact:",
    "signal:",
)


@dataclass(frozen=True)
class PublicationContractIssue:
    code: str
    line_number: int
    message: str
    repair_target: str


@dataclass(frozen=True)
class PublicationContractResult:
    passed: bool
    issues: list[PublicationContractIssue] = field(default_factory=list)

    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issue_count": len(self.issues),
            "issue_codes": self.issue_codes(),
            "repair_targets": [issue.repair_target for issue in self.issues],
        }


def validate_publication_contract(
    markdown: str,
    *,
    structured_report: StructuredReport | None,
    allowed_source_ids: set[str],
) -> PublicationContractResult:
    issues: list[PublicationContractIssue] = []
    output_language = structured_report.output_language if structured_report is not None else ""
    lines = markdown.splitlines()
    for index, line in enumerate(lines, start=1):
        issues.extend(_line_issues(line, index, output_language, allowed_source_ids))
    issues.extend(_ordering_issues(markdown, structured_report))
    return PublicationContractResult(passed=not issues, issues=issues)


def _line_issues(
    line: str,
    line_number: int,
    output_language: str,
    allowed_source_ids: set[str],
) -> list[PublicationContractIssue]:
    issues: list[PublicationContractIssue] = []
    stripped = line.strip()
    if stripped.startswith("#") and "[source:" in stripped:
        issues.append(
            PublicationContractIssue(
                code="citation_in_heading",
                line_number=line_number,
                message="Headings must not contain citations",
                repair_target="renderer",
            )
        )
    if _is_table_header(stripped) and "[source:" in stripped:
        issues.append(
            PublicationContractIssue(
                code="citation_in_table_header",
                line_number=line_number,
                message="Table headers must not contain citations",
                repair_target="renderer",
            )
        )
    if output_language.lower().startswith("zh") and stripped.startswith("###"):
        for heading in _ENGLISH_STRUCTURAL_HEADINGS:
            if heading in stripped:
                issues.append(
                    PublicationContractIssue(
                        code="english_structural_heading_in_zh",
                        line_number=line_number,
                        message=f"English structural heading in zh-CN report: {heading}",
                        repair_target="renderer",
                    )
                )
    for term in _INTERNAL_TERMS:
        if term in line:
            issues.append(
                PublicationContractIssue(
                    code="internal_term_leak",
                    line_number=line_number,
                    message=f"Internal term leaked: {term}",
                    repair_target="structured_section",
                )
            )
    for source_id in _SOURCE_TOKEN_RE.findall(line):
        if source_id.strip() not in allowed_source_ids:
            issues.append(
                PublicationContractIssue(
                    code="invalid_source_id",
                    line_number=line_number,
                    message=f"Unknown source id {source_id}",
                    repair_target="structured_section",
                )
            )
    return issues


def _is_table_header(line: str) -> bool:
    if not line.startswith("|"):
        return False
    lowered = line.lower()
    return "维度" in line or "dimension" in lowered or "source id" in lowered


def _ordering_issues(
    markdown: str,
    structured_report: StructuredReport | None,
) -> list[PublicationContractIssue]:
    if structured_report is None:
        return []
    if structured_report.output_language.lower().startswith("zh"):
        support_heading = "## 支撑材料"
        battlecard_heading = "## 战报"
    else:
        support_heading = "## Support Materials"
        battlecard_heading = "## Battlecard"
    if support_heading in markdown and battlecard_heading in markdown:
        if markdown.index(support_heading) < markdown.index(battlecard_heading):
            return [
                PublicationContractIssue(
                    code="support_before_core",
                    line_number=1,
                    message="Support material appears before core battlecard content",
                    repair_target="renderer",
                )
            ]
    return []
```

- [ ] **Step 4: Run publication contract tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_publication_contract.py -v
```

Expected: PASS.

- [ ] **Step 5: Run structured writer unit suite**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/packages/agents/writer/publication_contract.py backend/tests/unit/test_writer_publication_contract.py
git commit -m "feat: enforce structured report publication contract"
```

---

### Task 5: Markdown Failure Adapter For Regression Fixtures

**Files:**
- Create: `backend/packages/agents/writer/structured_adapter.py`
- Test: `backend/tests/unit/test_writer_structured_adapter.py`

- [ ] **Step 1: Write adapter tests for the known failure shapes**

Add `backend/tests/unit/test_writer_structured_adapter.py`:

```python
from __future__ import annotations

from packages.agents.writer.structured_adapter import detect_markdown_failure_shapes


def test_adapter_detects_recent_real_run_failure_shapes_without_full_report_fixture() -> None:
    markdown = """
## 执行摘要

- **核心结论：** This report is structured as decision analysis first, with evidence and QA support after the core competitive readout. [source:raw-source-a]

## 用户评价整理

### Direct User / Community Signals

- Cursor users mention speed. [source:raw-source-a]

## 战报

- 直接战报定位
- 反对意见处理
- 行动偏向
- 落地检查

## 决策矩阵

| 维度 [source:raw-source-a] | Cursor |
|---|---|
| pricing | visible [source:raw-source-a] |

## 支撑材料

Segment Evidence Pack JSON includes source_registry.
"""

    result = detect_markdown_failure_shapes(markdown, output_language="zh-CN")

    assert result.issue_codes() == [
        "executive_summary_template_only",
        "english_structural_heading_in_zh",
        "battlecard_template_only",
        "citation_in_table_header",
        "internal_term_leak",
    ]


def test_adapter_does_not_flag_clean_structured_markdown() -> None:
    markdown = """
## 执行摘要

- **推荐：** 优先选择 Cursor 作为团队采购基线。 [source:raw-source-a]

## 战报

### Cursor

- **目标买家：** 工程负责人
- **使用场景：** 当买家重视低风险团队落地时使用。 [source:raw-source-a]

## 支撑材料

### 证据附录

| Source ID | Title | Competitor | Dimension | Role | Confidence |
|---|---|---|---|---|---|
| raw-source-a | Cursor pricing | Cursor | pricing | official_fact | high |
"""

    result = detect_markdown_failure_shapes(markdown, output_language="zh-CN")

    assert result.passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_adapter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_adapter'`.

- [ ] **Step 3: Implement adapter detection**

Create `backend/packages/agents/writer/structured_adapter.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field


_ENGLISH_ZH_HEADINGS = (
    "Direct User / Community Signals",
    "Simulated Survey and Interview Signals",
    "Pricing and Packaging",
    "Feature and Workflow Capability",
    "Positioning and Core Value",
)
_BATTLECARD_TEMPLATE_TERMS = ("直接战报定位", "反对意见处理", "行动偏向", "落地检查")
_EXECUTIVE_TEMPLATE_TERMS = (
    "This report is structured as decision analysis first",
    "核心结论",
    "决策姿态",
    "风险边界",
    "立即行动",
)
_INTERNAL_TERMS = ("Segment Evidence Pack JSON", "source_registry", "Writer Evidence Pack")


@dataclass(frozen=True)
class MarkdownFailureShape:
    code: str
    section: str
    line_number: int


@dataclass(frozen=True)
class MarkdownFailureShapeResult:
    passed: bool
    issues: list[MarkdownFailureShape] = field(default_factory=list)

    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


def detect_markdown_failure_shapes(
    markdown: str,
    *,
    output_language: str,
) -> MarkdownFailureShapeResult:
    issues: list[MarkdownFailureShape] = []
    lines = markdown.splitlines()
    current_section = ""
    battlecard_terms_seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped.removeprefix("## ").strip()
        if output_language.lower().startswith("zh") and stripped.startswith("### "):
            if any(heading in stripped for heading in _ENGLISH_ZH_HEADINGS):
                issues.append(
                    MarkdownFailureShape(
                        code="english_structural_heading_in_zh",
                        section=current_section,
                        line_number=line_number,
                    )
                )
        if current_section == "执行摘要" and any(term in stripped for term in _EXECUTIVE_TEMPLATE_TERMS):
            _append_once(issues, "executive_summary_template_only", current_section, line_number)
        if current_section == "战报":
            for term in _BATTLECARD_TEMPLATE_TERMS:
                if term in stripped:
                    battlecard_terms_seen.add(term)
        if _looks_like_table_header(stripped) and "[source:" in stripped:
            issues.append(
                MarkdownFailureShape(
                    code="citation_in_table_header",
                    section=current_section,
                    line_number=line_number,
                )
            )
        if any(term in stripped for term in _INTERNAL_TERMS):
            issues.append(
                MarkdownFailureShape(
                    code="internal_term_leak",
                    section=current_section,
                    line_number=line_number,
                )
            )
    if len(battlecard_terms_seen) >= 3:
        issues.append(
            MarkdownFailureShape(
                code="battlecard_template_only",
                section="战报",
                line_number=_section_line(lines, "## 战报"),
            )
        )
    ordered = _dedupe_ordered(issues)
    return MarkdownFailureShapeResult(passed=not ordered, issues=ordered)


def _looks_like_table_header(line: str) -> bool:
    if not line.startswith("|"):
        return False
    return "维度" in line or "Dimension" in line or "Source ID" in line


def _append_once(
    issues: list[MarkdownFailureShape],
    code: str,
    section: str,
    line_number: int,
) -> None:
    if not any(issue.code == code for issue in issues):
        issues.append(MarkdownFailureShape(code=code, section=section, line_number=line_number))


def _section_line(lines: list[str], heading: str) -> int:
    for index, line in enumerate(lines, start=1):
        if line.strip() == heading:
            return index
    return 1


def _dedupe_ordered(issues: list[MarkdownFailureShape]) -> list[MarkdownFailureShape]:
    seen: set[str] = set()
    ordered: list[MarkdownFailureShape] = []
    for issue in issues:
        if issue.code in seen:
            continue
        seen.add(issue.code)
        ordered.append(issue)
    return ordered
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_adapter.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/agents/writer/structured_adapter.py backend/tests/unit/test_writer_structured_adapter.py
git commit -m "test: detect structured writer regression shapes"
```

---

### Task 6: Structured Report Assembler

**Files:**
- Modify: `backend/packages/agents/writer/assembler.py`
- Test: `backend/tests/unit/test_writer_structured_generation.py`

- [ ] **Step 1: Write assembler tests**

Add this section to `backend/tests/unit/test_writer_structured_generation.py`:

```python
from __future__ import annotations

from packages.agents.writer.assembler import StructuredReportAssembler
from test_writer_structured_renderer import _report


def test_structured_assembler_accepts_complete_report_and_emits_coverage_telemetry() -> None:
    report = _report("zh-CN")
    result = StructuredReportAssembler().assemble(
        report=report,
        expected_competitors=["Cursor", "Windsurf"],
    )

    assert result.report is report
    assert result.telemetry["missing_deep_dive_competitors"] == ["Windsurf"]
    assert result.telemetry["duplicate_deep_dive_competitors"] == []
    assert result.telemetry["missing_battlecard_competitors"] == ["Cursor"]


def test_structured_assembler_reports_duplicate_deep_dives() -> None:
    report = _report("zh-CN")
    first = report.core.competitor_deep_dives[0]
    report.core.competitor_deep_dives.append(first.model_copy())

    result = StructuredReportAssembler().assemble(
        report=report,
        expected_competitors=["Cursor", "Windsurf"],
    )

    assert result.telemetry["duplicate_deep_dive_competitors"] == ["Cursor"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_generation.py::test_structured_assembler_accepts_complete_report_and_emits_coverage_telemetry backend/tests/unit/test_writer_structured_generation.py::test_structured_assembler_reports_duplicate_deep_dives -v
```

Expected: FAIL with `ImportError: cannot import name 'StructuredReportAssembler'`.

- [ ] **Step 3: Implement assembler without changing Markdown assembly**

Append to `backend/packages/agents/writer/assembler.py`:

```python
from dataclasses import dataclass

from packages.agents.writer.structured_report import StructuredReport


@dataclass(frozen=True)
class StructuredReportAssemblyResult:
    report: StructuredReport
    telemetry: dict[str, object]


class StructuredReportAssembler:
    def assemble(
        self,
        *,
        report: StructuredReport,
        expected_competitors: list[str],
    ) -> StructuredReportAssemblyResult:
        expected = list(dict.fromkeys(expected_competitors))
        deep_dive_names = [item.competitor for item in report.core.competitor_deep_dives]
        user_theme_names = [item.competitor for item in report.core.user_review_themes.competitor_themes]
        swot_names = [item.competitor for item in report.core.swot.competitors]
        battlecard_names = [item.competitor for item in report.core.battlecard.plays]
        telemetry = {
            "expected_competitors": expected,
            "missing_deep_dive_competitors": _missing(expected, deep_dive_names),
            "duplicate_deep_dive_competitors": _duplicates(deep_dive_names),
            "missing_user_theme_competitors": _missing(expected, user_theme_names),
            "duplicate_user_theme_competitors": _duplicates(user_theme_names),
            "missing_swot_competitors": _missing(expected, swot_names),
            "duplicate_swot_competitors": _duplicates(swot_names),
            "missing_battlecard_competitors": _missing(expected, battlecard_names),
            "duplicate_battlecard_competitors": _duplicates(battlecard_names),
        }
        return StructuredReportAssemblyResult(report=report, telemetry=telemetry)


def _missing(expected: list[str], actual: list[str]) -> list[str]:
    actual_set = set(actual)
    return [item for item in expected if item not in actual_set]


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates
```

Move the two new imports to the existing import block at the top of `assembler.py`; never leave imports mid-file.

- [ ] **Step 4: Run assembler tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_generation.py -v
```

Expected: PASS for the two assembler tests.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/agents/writer/assembler.py backend/tests/unit/test_writer_structured_generation.py
git commit -m "feat: assemble structured writer reports"
```

---

### Task 7: Structured JSON Section Generation

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/packages/config/settings.py`
- Modify: `backend/tests/unit/test_writer_structured_generation.py`

- [ ] **Step 1: Add settings test**

Add to the existing settings test file `backend/tests/unit/test_enterprise_postgres_config.py`:

```python
def test_writer_structured_report_enabled_defaults_to_false_until_integration_gate() -> None:
    from packages.config.settings import Settings

    settings = Settings()

    assert settings.writer_structured_report_enabled is False
```

- [ ] **Step 2: Add structured section JSON generation tests**

Append to `backend/tests/unit/test_writer_structured_generation.py`:

```python
import json

import pytest

from packages.agents.writer.logic import WriterAgentMixin
from packages.agents.writer.structured_report import ExecutiveSummarySection


class _WriterHarness(WriterAgentMixin):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def _trace_llm_text(self, record, *, agent, subagent, name, system, user) -> str:
        self.prompts.append(system + "\n" + user)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_structured_section_json_accepts_valid_json_and_rejects_markdown_citations() -> None:
    payload = {
        "recommendation": {
            "text": "优先以 Cursor 作为团队采购基线。",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "risk_adjusted_rationale": {
            "text": "Windsurf 功能覆盖更宽，但 Cursor 在团队落地风险上更稳。",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "competitor_postures": [
            {
                "competitor": "Cursor",
                "posture": {
                    "text": "主力候选。",
                    "source_ids": ["raw-source-a"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
            }
        ],
        "confidence_boundary": {
            "text": "结论适用于团队采购。",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "next_actions": [
            {
                "text": "先做两周试点。",
                "source_ids": ["raw-source-a"],
                "confidence": "high",
                "evidence_role": "official_fact",
            }
        ],
    }
    harness = _WriterHarness([json.dumps(payload)])

    section = await harness._writer_structured_section_json(
        record=object(),
        segment={"section_id": "executive_summary", "content": "Evidence"},
        section_schema=ExecutiveSummarySection,
        allowed_source_ids={"raw-source-a"},
        timeout_seconds=5.0,
    )

    assert section.recommendation.text == "优先以 Cursor 作为团队采购基线。"
    assert "[source:" not in harness.prompts[0]


@pytest.mark.asyncio
async def test_structured_section_json_retries_invalid_json_once() -> None:
    valid_payload = {
        "recommendation": {
            "text": "Choose Cursor.",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "risk_adjusted_rationale": {
            "text": "Cursor is lower risk for team rollout than Windsurf.",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "competitor_postures": [
            {
                "competitor": "Cursor",
                "posture": {
                    "text": "Primary option.",
                    "source_ids": ["raw-source-a"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
            }
        ],
        "confidence_boundary": {
            "text": "Team procurement only.",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "next_actions": [
            {
                "text": "Run a pilot.",
                "source_ids": ["raw-source-a"],
                "confidence": "high",
                "evidence_role": "official_fact",
            }
        ],
    }
    harness = _WriterHarness(["## Markdown response", json.dumps(valid_payload)])

    section = await harness._writer_structured_section_json(
        record=object(),
        segment={"section_id": "executive_summary", "content": "Evidence"},
        section_schema=ExecutiveSummarySection,
        allowed_source_ids={"raw-source-a"},
        timeout_seconds=5.0,
    )

    assert section.recommendation.text == "Choose Cursor."
    assert len(harness.prompts) == 2
    assert "Return JSON only" in harness.prompts[1]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_enterprise_postgres_config.py::test_writer_structured_report_enabled_defaults_to_false_until_integration_gate backend/tests/unit/test_writer_structured_generation.py::test_structured_section_json_accepts_valid_json_and_rejects_markdown_citations backend/tests/unit/test_writer_structured_generation.py::test_structured_section_json_retries_invalid_json_once -v
```

Expected: FAIL because `Settings.writer_structured_report_enabled` and `_writer_structured_section_json` do not exist.

- [ ] **Step 4: Add feature flag**

In `backend/packages/config/settings.py`, add the setting near the other writer settings:

```python
    writer_structured_report_enabled: bool = False
```

Keep the initial default `False` until Task 9 proves the integrated structured path passes focused run-service tests. This preserves stable real runs while the structured path is built.

- [ ] **Step 5: Implement structured JSON helper**

In `backend/packages/agents/writer/logic.py`, add imports:

```python
import json
from pydantic import BaseModel, ValidationError
```

Add this method to `WriterAgentMixin`:

```python
    async def _writer_structured_section_json(
        self,
        record: RunRecord,
        *,
        segment: dict[str, object],
        section_schema: type[BaseModel],
        allowed_source_ids: set[str],
        timeout_seconds: float,
    ) -> BaseModel:
        prompt = self._structured_section_prompt(
            segment=segment,
            section_schema=section_schema,
            allowed_source_ids=allowed_source_ids,
            previous_error=None,
        )
        first = await asyncio.wait_for(
            self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="structured_report_section",
                system="You are a senior competitive-intelligence writer. Return valid JSON only.",
                user=prompt,
            ),
            timeout=timeout_seconds,
        )
        try:
            return _parse_structured_section_response(first, section_schema, allowed_source_ids)
        except ValueError as exc:
            retry_prompt = self._structured_section_prompt(
                segment=segment,
                section_schema=section_schema,
                allowed_source_ids=allowed_source_ids,
                previous_error=str(exc),
            )
            second = await asyncio.wait_for(
                self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=None,
                    name="structured_report_section_retry",
                    system="You are fixing a structured writer JSON response. Return valid JSON only.",
                    user=retry_prompt,
                ),
                timeout=timeout_seconds,
            )
            return _parse_structured_section_response(second, section_schema, allowed_source_ids)

    def _structured_section_prompt(
        self,
        *,
        segment: dict[str, object],
        section_schema: type[BaseModel],
        allowed_source_ids: set[str],
        previous_error: str | None,
    ) -> str:
        schema_json = json.dumps(section_schema.model_json_schema(), ensure_ascii=False)
        allowed_json = json.dumps(sorted(allowed_source_ids), ensure_ascii=False)
        segment_json = json.dumps(segment, ensure_ascii=False, default=str)
        error_text = f"\nPrevious validation error: {previous_error}\n" if previous_error else ""
        return (
            "Return JSON only. Do not write Markdown headings. "
            "Do not include tokens such as [source:raw-source-example] inside text fields. "
            "Put citations only in source_ids. "
            "Use only allowed_source_ids. "
            "Separate official_fact, community_signal, simulated_research, inference, and evidence_gap roles.\n"
            f"{error_text}"
            f"Schema:\n{schema_json}\n"
            f"allowed_source_ids:\n{allowed_json}\n"
            f"segment:\n{segment_json}\n"
        )
```

Add module-level helpers in the same file:

```python
def _parse_structured_section_response(
    response: str,
    section_schema: type[BaseModel],
    allowed_source_ids: set[str],
) -> BaseModel:
    text = response.strip()
    if not text.startswith("{"):
        raise ValueError("Structured writer returned non-JSON content")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Structured writer returned invalid JSON: {exc}") from exc
    try:
        section = section_schema.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Structured writer schema validation failed: {exc}") from exc
    invalid = sorted(_source_ids_from_section(section) - allowed_source_ids)
    if invalid:
        raise ValueError(f"Structured writer used unknown source ids: {', '.join(invalid)}")
    return section


def _source_ids_from_section(section: BaseModel) -> set[str]:
    found: set[str] = set()
    data = section.model_dump()
    stack: list[object] = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "source_ids" and isinstance(value, list):
                    found.update(str(source_id) for source_id in value)
                else:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return found
```

The current writer LLM path uses `_trace_llm_text`; keep structured section generation on that helper so trace events remain consistent with the existing writer.

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest backend/tests/unit/test_enterprise_postgres_config.py::test_writer_structured_report_enabled_defaults_to_false_until_integration_gate backend/tests/unit/test_writer_structured_generation.py::test_structured_section_json_accepts_valid_json_and_rejects_markdown_citations backend/tests/unit/test_writer_structured_generation.py::test_structured_section_json_retries_invalid_json_once -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/config/settings.py backend/packages/agents/writer/logic.py backend/tests/unit/test_enterprise_postgres_config.py backend/tests/unit/test_writer_structured_generation.py
git commit -m "feat: add structured writer JSON section generation"
```

---

### Task 8: Structured Writer Integration Behind Feature Flag

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write run-service structured success test**

Add a focused test near existing writer segmented tests in `backend/tests/unit/test_run_service.py`:

```python
def test_real_writer_uses_structured_path_when_enabled(monkeypatch) -> None:
    service = _segmented_writer_service()
    service._settings = service._settings.model_copy(
        update={"writer_structured_report_enabled": True, "writer_timeout_seconds": 10}
    )
    record = _segmented_writer_record(service, competitors=["Cursor", "Windsurf"])
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()

    structured_report = _structured_writer_fixture_report(record.detail)

    async def fake_structured_report(self, record, evidence_pack_result, timeout_seconds):
        return structured_report

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fake_structured_report,
    )

    service._run_writer_node(record)

    assert "## 执行摘要" in record.detail.report_md
    assert "## 支撑材料" in record.detail.report_md
    assert "Segment Evidence Pack JSON" not in record.detail.report_md
    assert any(span.name == "writer_structured_report_validated" for span in record.detail.trace_spans)
```

Add the fixture helper in the same test file:

```python
def _structured_writer_fixture_report(detail: RunDetail) -> StructuredReport:
    from test_writer_structured_renderer import _report

    report = _report(detail.output_language or "zh-CN")
    return report.model_copy(
        update={
            "topic": detail.topic,
            "competitors": list(detail.plan.competitors),
            "dimensions": list(detail.plan.dimensions),
        }
    )


def _structured_writer_raw_sources() -> list[RawSource]:
    return [
        RawSource(
            id="raw-source-a",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor pricing is visible.",
            content_hash="raw-source-a-hash",
            confidence=0.96,
        ),
        RawSource(
            id="raw-source-b",
            competitor="Windsurf",
            dimension="pricing",
            source_type="webpage_verified",
            title="Windsurf pricing",
            snippet="Windsurf pricing needs refresh.",
            content_hash="raw-source-b-hash",
            confidence=0.84,
        ),
        RawSource(
            id="raw-source-survey",
            competitor="Cursor",
            dimension="persona",
            source_type="simulated_interview",
            title="Simulated interview",
            snippet="Simulated teams prefer low-friction IDE integration.",
            content_hash="raw-source-survey-hash",
            confidence=0.76,
        ),
    ]
```

- [ ] **Step 2: Write fallback visibility test**

Add:

```python
def test_real_writer_traces_markdown_fallback_when_structured_path_fails(monkeypatch) -> None:
    service = _segmented_writer_service()
    service._settings = service._settings.model_copy(
        update={"writer_structured_report_enabled": True, "writer_timeout_seconds": 10}
    )
    record = _segmented_writer_record(service, competitors=["Cursor", "Windsurf"])
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fake_structured_report(self, record, evidence_pack_result, timeout_seconds):
        raise ValueError("structured section failed")

    async def fake_markdown_writer(self, record, evidence_pack_result, timeout_seconds):
        return "## 执行摘要\n\nFallback report. [source:raw-source-a]\n"

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fake_structured_report,
    )
    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_markdown_report_from_evidence_pack",
        fake_markdown_writer,
    )

    service._run_writer_node(record)

    assert "Fallback report" in record.detail.report_md
    assert any(span.name == "writer_markdown_fallback_used" for span in record.detail.trace_spans)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_run_service.py::test_real_writer_uses_structured_path_when_enabled backend/tests/unit/test_run_service.py::test_real_writer_traces_markdown_fallback_when_structured_path_fails -v
```

Expected: FAIL because `_writer_structured_report` and `_writer_markdown_report_from_evidence_pack` are not integrated.

- [ ] **Step 4: Add structured integration helpers**

In `backend/packages/agents/writer/logic.py`, add imports:

```python
from packages.agents.writer.assembler import StructuredReportAssembler
from packages.agents.writer.publication_contract import validate_publication_contract
from packages.agents.writer.structured_renderer import render_structured_report
from packages.agents.writer.structured_report import StructuredReport
from packages.agents.writer.structured_validation import validate_structured_report
```

Add a structured integration helper:

```python
    async def _writer_structured_report(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> StructuredReport:
        raise ValueError("structured writer section planner is not connected")
```

Add a Markdown fallback helper that wraps the existing Markdown generation branch. Move the current non-structured Markdown report generation code into:

```python
    async def _writer_markdown_report_from_evidence_pack(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> str:
        detail = record.detail
        if evidence_pack_result.metrics.segmented_writer_required:
            return await self._writer_segmented_report_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                timeout_seconds=timeout_seconds,
            )
        prompt = evidence_pack_result.to_prompt_json()
        return await asyncio.wait_for(
            self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="report_writer",
                system="You are a senior enterprise competitive-intelligence analyst.",
                user=json.dumps(prompt, ensure_ascii=False, default=str),
            ),
            timeout=timeout_seconds,
        )
```

Use the existing LLM call method name from the current Markdown branch. Keep the body identical to current behavior except for moving it behind the helper.

- [ ] **Step 5: Route normal generation through structured path**

In `_real_writer_step`, after `evidence_pack_result = build_writer_evidence_pack(detail)`, branch like this:

```python
            if self._settings.writer_structured_report_enabled:
                try:
                    structured_report = await self._writer_structured_report(
                        record,
                        evidence_pack_result,
                        timeout_seconds,
                    )
                    assembly = StructuredReportAssembler().assemble(
                        report=structured_report,
                        expected_competitors=list(detail.plan.competitors),
                    )
                    validation = validate_structured_report(
                        structured_report,
                        allowed_source_ids={source.id for source in detail.raw_sources},
                        strong_source_ids=_strong_writer_source_ids(detail),
                    )
                    await self.emit(
                        detail.id,
                        "writer_structured_report_validated",
                        "writer",
                        None,
                        "Structured writer report validated",
                        {
                            **validation.telemetry_payload(),
                            "assembly": assembly.telemetry,
                        },
                    )
                    if not validation.passed:
                        raise ValueError(f"structured validation failed: {validation.issue_codes()}")
                    rendered = render_structured_report(structured_report)
                    publication = validate_publication_contract(
                        rendered,
                        structured_report=structured_report,
                        allowed_source_ids={source.id for source in detail.raw_sources},
                    )
                    await self.emit(
                        detail.id,
                        "writer_publication_contract_validated",
                        "writer",
                        None,
                        "Structured writer publication contract validated",
                        publication.telemetry_payload(),
                    )
                    if not publication.passed:
                        raise ValueError(f"publication contract failed: {publication.issue_codes()}")
                    report_md = rendered
                except Exception as exc:
                    await self.emit(
                        detail.id,
                        "writer_markdown_fallback_used",
                        "writer",
                        None,
                        "Structured writer failed; using Markdown fallback",
                        {"reason": str(exc)[:500]},
                    )
                    report_md = await self._writer_markdown_report_from_evidence_pack(
                        record,
                        evidence_pack_result,
                        timeout_seconds,
                    )
            else:
                report_md = await self._writer_markdown_report_from_evidence_pack(
                    record,
                    evidence_pack_result,
                    timeout_seconds,
                )
```

Add helper:

```python
def _strong_writer_source_ids(detail: RunDetail) -> set[str]:
    strong: set[str] = set()
    for source in detail.raw_sources:
        confidence = getattr(source, "confidence", None)
        source_type = str(getattr(source, "source_type", "") or "").casefold()
        metadata = getattr(source, "metadata", {}) or {}
        if confidence is not None and float(confidence) >= 0.75:
            strong.add(source.id)
        if source_type in {"official", "documentation", "pricing"}:
            strong.add(source.id)
        if metadata.get("official_source") is True or metadata.get("trusted_source") is True:
            strong.add(source.id)
    return strong
```

- [ ] **Step 6: Run focused integration tests**

Run:

```bash
python -m pytest backend/tests/unit/test_run_service.py::test_real_writer_uses_structured_path_when_enabled backend/tests/unit/test_run_service.py::test_real_writer_traces_markdown_fallback_when_structured_path_fails -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: integrate structured writer behind feature flag"
```

---

### Task 9: Structured Section Planner And Full Structured Report Generation

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_writer_structured_generation.py`

- [ ] **Step 1: Write section planner tests**

Add to `backend/tests/unit/test_writer_structured_generation.py`:

```python
from packages.agents.writer.logic import build_structured_writer_section_plan


def test_structured_section_plan_has_core_before_support_and_no_markdown_layout_ownership() -> None:
    plan = build_structured_writer_section_plan(
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    assert [item["section_id"] for item in plan][:4] == [
        "executive_summary",
        "decision_summary",
        "competitive_findings",
        "user_review_themes",
    ]
    assert plan[-1]["section_id"] == "support"
    assert all(item["owns_markdown_layout"] is False for item in plan)
```

- [ ] **Step 2: Write structured report generation test with monkeypatched sections**

Add:

```python
@pytest.mark.asyncio
async def test_writer_structured_report_builds_full_report_from_section_payloads(monkeypatch) -> None:
    from test_writer_structured_renderer import _report

    record = _writer_record_with_sources(["raw-source-a", "raw-source-b", "raw-source-survey"])
    fixture = _report("zh-CN")
    harness = _WriterHarness([])

    async def fake_section_json(record, *, segment, section_schema, allowed_source_ids, timeout_seconds):
        mapping = {
            "ExecutiveSummarySection": fixture.core.executive_summary,
            "UserReviewThemesSection": fixture.core.user_review_themes,
            "DecisionMatrixSection": fixture.core.decision_matrix,
            "SwotSection": fixture.core.swot,
            "BattlecardSection": fixture.core.battlecard,
            "ReportSupport": fixture.support,
        }
        if section_schema.__name__ in mapping:
            return mapping[section_schema.__name__]
        return fixture.core.competitor_deep_dives[0]

    monkeypatch.setattr(harness, "_writer_structured_section_json", fake_section_json)

    report = await harness._writer_structured_report(
        record,
        evidence_pack_result=_minimal_evidence_pack_result(),
        timeout_seconds=10,
    )

    assert report.core.executive_summary.recommendation.text
    assert report.support.evidence_appendix[0].source_id == "raw-source-a"
```

Add small local helpers:

```python
def _writer_record_with_sources(source_ids: list[str]):
    detail = _run_detail_for_structured_writer()
    detail.raw_sources = [_raw_source(source_id) for source_id in source_ids]
    return RunRecord(detail=detail)


def _minimal_evidence_pack_result():
    return type(
        "EvidencePackResultStub",
        (),
        {
            "metrics": type("MetricsStub", (), {"segment_count": 1})(),
            "to_prompt_json": lambda self: {"evidence": "compact"},
            "segment_inputs": [
                {"section_id": "executive_summary", "content": "summary evidence"},
                {"section_id": "user_review_themes", "content": "user evidence"},
                {"section_id": "competitor_deep_dive", "competitor": "Cursor", "content": "deep dive evidence"},
                {"section_id": "decision_matrix", "content": "matrix evidence"},
                {"section_id": "swot", "content": "swot evidence"},
                {"section_id": "battlecard", "content": "battlecard evidence"},
                {"section_id": "support", "content": "support evidence"},
            ],
        },
    )()
```

Use existing test helpers for `RunRecord`, `RunDetail`, and `RawSource` if they already exist in `test_run_service.py`; do not create duplicate DTO factories if a nearby helper already returns the same object shape.

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_generation.py::test_structured_section_plan_has_core_before_support_and_no_markdown_layout_ownership backend/tests/unit/test_writer_structured_generation.py::test_writer_structured_report_builds_full_report_from_section_payloads -v
```

Expected: FAIL because `build_structured_writer_section_plan` and `_writer_structured_report` are not complete.

- [ ] **Step 4: Implement section plan**

Add module-level function in `backend/packages/agents/writer/logic.py`:

```python
def build_structured_writer_section_plan(
    *,
    competitors: list[str],
    dimensions: list[str],
) -> list[dict[str, object]]:
    return [
        {"section_id": "executive_summary", "schema": "ExecutiveSummarySection", "owns_markdown_layout": False},
        {"section_id": "decision_summary", "schema": "list[CitedText]", "owns_markdown_layout": False},
        {"section_id": "competitive_findings", "schema": "list[CitedText]", "owns_markdown_layout": False},
        {"section_id": "user_review_themes", "schema": "UserReviewThemesSection", "owns_markdown_layout": False},
        *[
            {
                "section_id": "competitor_deep_dive",
                "competitor": competitor,
                "schema": "CompetitorDeepDiveSection",
                "owns_markdown_layout": False,
            }
            for competitor in competitors
        ],
        {"section_id": "decision_matrix", "dimensions": list(dimensions), "schema": "DecisionMatrixSection", "owns_markdown_layout": False},
        {"section_id": "swot", "schema": "SwotSection", "owns_markdown_layout": False},
        {"section_id": "battlecard", "schema": "BattlecardSection", "owns_markdown_layout": False},
        {"section_id": "community_triangulation", "schema": "list[CitedText]", "owns_markdown_layout": False},
        {"section_id": "support", "schema": "ReportSupport", "owns_markdown_layout": False},
    ]
```

- [ ] **Step 5: Implement `_writer_structured_report`**

Replace the temporary method from Task 8 with a real implementation:

```python
    async def _writer_structured_report(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> StructuredReport:
        detail = record.detail
        allowed_source_ids = {source.id for source in detail.raw_sources}
        section_inputs = _structured_section_inputs(
            evidence_pack_result=evidence_pack_result,
            competitors=list(detail.plan.competitors),
            dimensions=list(detail.plan.dimensions),
        )
        executive_summary = await self._writer_structured_section_json(
            record,
            segment=section_inputs["executive_summary"],
            section_schema=ExecutiveSummarySection,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        user_review_themes = await self._writer_structured_section_json(
            record,
            segment=section_inputs["user_review_themes"],
            section_schema=UserReviewThemesSection,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        deep_dives: list[CompetitorDeepDiveSection] = []
        for competitor in detail.plan.competitors:
            deep_dives.append(
                await self._writer_structured_section_json(
                    record,
                    segment=section_inputs[f"competitor_deep_dive::{competitor}"],
                    section_schema=CompetitorDeepDiveSection,
                    allowed_source_ids=allowed_source_ids,
                    timeout_seconds=timeout_seconds,
                )
            )
        decision_matrix = await self._writer_structured_section_json(
            record,
            segment=section_inputs["decision_matrix"],
            section_schema=DecisionMatrixSection,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        swot = await self._writer_structured_section_json(
            record,
            segment=section_inputs["swot"],
            section_schema=SwotSection,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        battlecard = await self._writer_structured_section_json(
            record,
            segment=section_inputs["battlecard"],
            section_schema=BattlecardSection,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        support = await self._writer_structured_section_json(
            record,
            segment=section_inputs["support"],
            section_schema=ReportSupport,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        core = ReportCore(
            executive_summary=executive_summary,
            decision_summary=_default_decision_summary(executive_summary),
            competitive_findings=_default_competitive_findings(deep_dives),
            user_review_themes=user_review_themes,
            competitor_deep_dives=deep_dives,
            decision_matrix=decision_matrix,
            swot=swot,
            battlecard=battlecard,
            community_triangulation=[],
        )
        return StructuredReport(
            output_language=detail.output_language,
            topic=detail.topic,
            competitors=list(detail.plan.competitors),
            dimensions=list(detail.plan.dimensions),
            core=core,
            support=support,
            metadata=ReportMetadata(
                writer_mode="structured",
                segment_count=int(getattr(evidence_pack_result.metrics, "segment_count", 0)),
                source_count=len(detail.raw_sources),
                warnings=[],
                structured_report_version="1",
            ),
        )
```

Add these helpers:

```python
def _structured_section_inputs(
    *,
    evidence_pack_result,
    competitors: list[str],
    dimensions: list[str],
) -> dict[str, dict[str, object]]:
    base = evidence_pack_result.to_prompt_json()
    inputs: dict[str, dict[str, object]] = {}
    for item in build_structured_writer_section_plan(competitors=competitors, dimensions=dimensions):
        section_id = str(item["section_id"])
        key = section_id
        if section_id == "competitor_deep_dive":
            key = f"competitor_deep_dive::{item['competitor']}"
        inputs[key] = {
            "section_id": section_id,
            "competitor": item.get("competitor"),
            "dimensions": item.get("dimensions", dimensions),
            "evidence_pack": base,
        }
    return inputs


def _default_decision_summary(executive_summary: ExecutiveSummarySection) -> list[CitedText]:
    return [executive_summary.recommendation, executive_summary.risk_adjusted_rationale]


def _default_competitive_findings(
    deep_dives: list[CompetitorDeepDiveSection],
) -> list[CitedText]:
    findings: list[CitedText] = []
    for deep_dive in deep_dives:
        findings.extend(deep_dive.positioning[:1])
        findings.extend(deep_dive.pricing_packaging[:1])
        findings.extend(deep_dive.feature_capabilities[:1])
    return findings[:8] or [
        CitedText(
            text="核心竞争发现需要更多结构化证据支撑。",
            source_ids=[],
            confidence="low",
            evidence_role="evidence_gap",
        )
    ]
```

Add the corresponding imports for all structured section model classes.

- [ ] **Step 6: Run structured generation tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_generation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_structured_generation.py
git commit -m "feat: generate full structured writer reports"
```

---

### Task 10: Structured Repair Routing

**Files:**
- Modify: `backend/packages/agents/writer/repair.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_writer_structured_repair.py`

- [ ] **Step 1: Write repair target tests**

Add `backend/tests/unit/test_writer_structured_repair.py`:

```python
from __future__ import annotations

from packages.agents.writer.repair import structured_repair_target_for_issue
from packages.schema.models import QCIssue


def _issue(code: str, field_path: str = "report_md") -> QCIssue:
    return QCIssue(
        id=f"issue-{code}",
        severity="warn",
        code=code,
        message=code,
        field_path=field_path,
        suggested_fix="repair",
    )


def test_structured_repair_maps_localized_issue_codes_to_schema_paths() -> None:
    assert structured_repair_target_for_issue(_issue("battlecard_template_only")) == "core.battlecard"
    assert structured_repair_target_for_issue(_issue("executive_summary_template_only")) == "core.executive_summary"
    assert structured_repair_target_for_issue(_issue("citation_in_table_header")) == "renderer"
    assert structured_repair_target_for_issue(_issue("english_structural_heading_in_zh")) == "renderer"
    assert structured_repair_target_for_issue(_issue("internal_term_leak", "core.competitive_findings[0]")) == "core.competitive_findings"


def test_structured_repair_maps_persona_claim_warns_to_user_review_themes() -> None:
    issue = _issue("release_gate.claim_self_consistency_required", "report_md.section[user_review_themes]")

    assert structured_repair_target_for_issue(issue) == "core.user_review_themes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_repair.py -v
```

Expected: FAIL with `ImportError: cannot import name 'structured_repair_target_for_issue'`.

- [ ] **Step 3: Implement repair target mapping**

In `backend/packages/agents/writer/repair.py`, add:

```python
def structured_repair_target_for_issue(issue: QCIssue) -> str | None:
    code = issue.code
    path = issue.field_path or ""
    if code == "battlecard_template_only":
        return "core.battlecard"
    if code == "executive_summary_template_only":
        return "core.executive_summary"
    if code in {"citation_in_table_header", "citation_in_heading", "english_structural_heading_in_zh"}:
        return "renderer"
    if code == "internal_term_leak":
        return _structured_path_prefix(path)
    if code == "release_gate.claim_self_consistency_required":
        lowered = path.casefold()
        if "user_review" in lowered or "persona" in lowered:
            return "core.user_review_themes"
        if "pricing" in lowered:
            return "core.decision_matrix"
        if "feature" in lowered:
            return "core.competitor_deep_dives"
    return None


def _structured_path_prefix(path: str) -> str:
    if path.startswith("core."):
        parts = path.split(".")
        if len(parts) >= 2:
            return ".".join(parts[:2])
    return "structured_section"
```

- [ ] **Step 4: Connect structured repair telemetry without full rewrite**

In `backend/packages/agents/writer/logic.py`, after `redo_issues` are collected and before falling into Markdown repair, add:

```python
        structured_targets = [
            target
            for issue in redo_issues
            if (target := structured_repair_target_for_issue(issue)) is not None
        ]
        if self._settings.writer_structured_report_enabled and structured_targets:
            await self.emit(
                detail.id,
                "writer_structured_repair_selected",
                "writer",
                None,
                "Structured repair targets selected",
                {
                    "targets": list(dict.fromkeys(structured_targets)),
                    "llm_required": any(target != "renderer" for target in structured_targets),
                },
            )
```

Add import:

```python
from packages.agents.writer.repair import structured_repair_target_for_issue
```

Do not bypass existing repair planning in this task. This task makes structured repair target selection observable and prevents these issue codes from silently becoming generic full rewrite reasons in later tasks.

- [ ] **Step 5: Run repair tests**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_repair.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/packages/agents/writer/repair.py backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_structured_repair.py
git commit -m "feat: route structured writer repair targets"
```

---

### Task 11: Enable Structured Writer After Focused Gates Pass

**Files:**
- Modify: `backend/packages/config/settings.py`
- Modify: `backend/tests/unit/test_enterprise_postgres_config.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write default-enabled test**

Replace the Task 7 settings test with:

```python
def test_writer_structured_report_enabled_defaults_to_true_after_integration_gate() -> None:
    from packages.config.settings import Settings

    settings = Settings()

    assert settings.writer_structured_report_enabled is True
```

- [ ] **Step 2: Run the settings test to verify it fails**

Run:

```bash
python -m pytest backend/tests/unit/test_enterprise_postgres_config.py::test_writer_structured_report_enabled_defaults_to_true_after_integration_gate -v
```

Expected: FAIL because the flag is still `False`.

- [ ] **Step 3: Enable the structured writer flag**

In `backend/packages/config/settings.py`, change:

```python
    writer_structured_report_enabled: bool = False
```

to:

```python
    writer_structured_report_enabled: bool = True
```

- [ ] **Step 4: Run focused writer suites**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_adapter.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_structured_repair.py -v
```

Expected: PASS.

- [ ] **Step 5: Run run-service writer tests that cover fallback and existing Markdown repair**

Run:

```bash
python -m pytest backend/tests/unit/test_run_service.py -k writer -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/packages/config/settings.py backend/tests/unit/test_enterprise_postgres_config.py backend/tests/unit/test_run_service.py
git commit -m "feat: enable schema-first writer by default"
```

---

### Task 12: End-to-End Verification And Guardrails

**Files:**
- Modify: `STATE.md`

- [ ] **Step 1: Run full focused regression suite**

Run:

```bash
python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_adapter.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_structured_repair.py backend/tests/unit/test_enterprise_postgres_config.py -v
```

Expected: PASS.

- [ ] **Step 2: Run a broader backend smoke test**

Run:

```bash
python -m pytest backend/tests/unit/test_run_service.py -k "writer" -v
```

Expected: PASS.

- [ ] **Step 3: Verify plan-specific source hygiene**

Run:

```bash
rg -n "Segment Evidence Pack JSON|source_registry|allowed_source_ids|represented_by|fact:|signal:" backend/packages/agents/writer backend/tests/unit/test_writer_structured_*.py
```

Expected: Matches are allowed only in validation tests, adapter tests, and internal deny-list constants. No renderer output fixture should contain those terms as accepted report text.

- [ ] **Step 4: Update STATE.md with implementation summary**

Append a concise entry to `STATE.md`:

```markdown
## 2026-06-19 Schema-First Writer

- Added structured writer models, renderer, validator, publication contract, regression-shape adapter, structured section generation, and structured repair target telemetry.
- `report_md` remains the frontend-visible output; no database migration or frontend change was added.
- Markdown writer remains a trace-visible fallback.
- Focused verification commands:
  - `python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_adapter.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_structured_repair.py backend/tests/unit/test_enterprise_postgres_config.py -v`
  - `python -m pytest backend/tests/unit/test_run_service.py -k "writer" -v`
```

- [ ] **Step 5: Check git status before final commit**

Run:

```bash
git status --short
```

Expected: only tracked source, test, and `STATE.md` changes related to this plan. Do not stage untracked generated reports, database packages, output artifacts, or local document exports.

- [ ] **Step 6: Commit verification notes**

```bash
git add STATE.md
git commit -m "docs: record schema-first writer implementation state"
```

---

## Self-Review Against Spec

- Models: Task 1 creates the typed `StructuredReport`, `CitedText`, core sections, support sections, and metadata.
- Renderer: Task 2 makes Python own headings, citation placement, table layout, core/support ordering, appendix shape, and localization.
- Validator: Task 3 checks source IDs, recommendation evidence strength, competitor coverage, battlecard substance, executive summary quality, internal terms, and Markdown citation tokens in text fields.
- Publication contract: Task 4 checks the final Markdown for English structural headings in Chinese reports, citation placement, internal leaks, source ID validity, and core/support order.
- Regression fixture adapter: Task 5 represents the two recent run failure shapes without committing full generated reports.
- Existing evidence richness: Tasks 8 and 9 keep `build_writer_evidence_pack(detail)` as the structured writer input and do not reduce source collection breadth.
- Fallback: Tasks 8 and 11 keep Markdown fallback available and trace-visible.
- Repair routing: Task 10 maps localized warnings to schema paths or renderer fixes instead of generic full rewrite.
- Compatibility: Tasks 8 through 12 preserve `report_md` as canonical output and avoid database migration.
- Feature flag: Tasks 7 and 11 build the path behind a flag, then enable it only after focused gates pass.

## Execution Notes

- Use the activated conda environment for every `python -m pytest` command.
- Keep commits small and task-aligned.
- Do not stage untracked generated artifacts currently present in the workspace.
- Keep structured and fallback writer calls on the existing `_trace_llm_text` helper; do not introduce a second LLM client.
