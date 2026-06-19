# Schema-First Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a schema-first writer path that generates typed report sections, validates them, renders deterministic Markdown, and keeps the existing Markdown writer as a visible fallback.

**Architecture:** Keep the existing Writer Evidence Pack and segmented Markdown path, but add a structured path beside it. The LLM fills Pydantic section payloads; deterministic code owns headings, section order, citation placement, core/support separation, and publication hygiene. The quality checks from commit `34e205a9` become validation/publication-contract rules, not more long-term Markdown cleanup in `writer/logic.py`.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, ruff, existing `RunService`/`WriterAgentMixin`, conda environment `bd-competiscope-v2`.

---

## File Structure

- Create: `backend/packages/agents/writer/structured_report.py`
  - Owns all schema models: `StructuredReport`, core/support sections, `CitedText`, battlecard, matrix, SWOT, metadata, and issue path helpers.
- Create: `backend/packages/agents/writer/structured_renderer.py`
  - Converts `StructuredReport` to `report_md`. It owns localized headings, citations, table layout, appendix layout, and core-before-support ordering.
- Create: `backend/packages/agents/writer/structured_validation.py`
  - Validates typed content before rendering: source IDs, evidence roles, competitor coverage, battlecard substance, executive summary substance, internal-term leakage, and citation token leakage.
- Create: `backend/packages/agents/writer/publication_contract.py`
  - Validates rendered Markdown plus optional structured metadata. This is where the `34e205a9` hygiene intent lives.
- Create: `backend/packages/agents/writer/structured_sections.py`
  - Maps Writer Evidence Pack segment inputs to structured section requests and schema classes. It is pure and testable.
- Create: `backend/packages/agents/writer/structured_generation.py`
  - Builds JSON-only prompts, parses model output, retries with schema errors, and returns typed section payloads.
- Modify: `backend/packages/agents/writer/logic.py`
  - Adds structured writer orchestration behind `Settings.writer_structured_report_enabled`. Existing Markdown path remains fallback.
- Modify: `backend/packages/agents/writer/repair.py`
  - Adds structured repair target mapping for publication-contract and claim consistency issues.
- Modify: `backend/packages/config/settings.py`
  - Adds `writer_structured_report_enabled`.
- Modify: `backend/packages/business_intel/report_quality.py`
  - Uses publication contract metrics once the renderer exists; keep old Markdown metrics as compatibility checks.
- Modify: `backend/packages/business_intel/release_gate.py`
  - Adds publication contract failures as report richness blockers after contract tests pass.
- Test: `backend/tests/unit/test_writer_structured_report.py`
- Test: `backend/tests/unit/test_writer_structured_renderer.py`
- Test: `backend/tests/unit/test_writer_structured_validation.py`
- Test: `backend/tests/unit/test_writer_publication_contract.py`
- Test: `backend/tests/unit/test_writer_structured_sections.py`
- Test: `backend/tests/unit/test_writer_structured_generation.py`
- Test: `backend/tests/unit/test_writer_repair.py`
- Test: `backend/tests/unit/test_run_service.py`

## Scope Check

This plan covers one subsystem: writer report generation and repair. It does not change collectors, community search, frontend tabs, database migrations, or source admission. The first live integration keeps `report_md` canonical and stores only compact structured telemetry.

## Implementation Tasks

### Task 1: Structured Report Models

**Files:**
- Create: `backend/packages/agents/writer/structured_report.py`
- Test: `backend/tests/unit/test_writer_structured_report.py`

- [ ] **Step 1: Write failing model tests**

Add `backend/tests/unit/test_writer_structured_report.py`:

```python
import pytest
from pydantic import ValidationError

from packages.agents.writer.structured_report import (
    BattlecardPlay,
    BattlecardSection,
    CitedText,
    CompetitorPosture,
    ConfidenceLevel,
    EvidenceRole,
    ExecutiveSummarySection,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    StructuredReport,
    evidence_gap,
)


def _cited(text: str, source_id: str = "raw-source-a") -> CitedText:
    return CitedText(
        text=text,
        source_ids=[source_id],
        confidence="high",
        evidence_role="official_fact",
    )


def test_cited_text_rejects_markdown_source_tokens() -> None:
    with pytest.raises(ValidationError, match="must not contain markdown source tokens"):
        CitedText(
            text="Cursor has published pricing. [source:raw-source-a]",
            source_ids=["raw-source-a"],
            confidence="high",
            evidence_role="official_fact",
        )


def test_uncited_non_gap_text_is_invalid() -> None:
    with pytest.raises(ValidationError, match="uncited text must be an evidence_gap"):
        CitedText(
            text="This claim has no source.",
            source_ids=[],
            confidence="low",
            evidence_role="inference",
        )


def test_evidence_gap_helper_builds_explicit_gap() -> None:
    gap = evidence_gap("Direct user reviews were not collected for Copilot.")
    assert gap.source_ids == []
    assert gap.confidence == "low"
    assert gap.evidence_role == "evidence_gap"


def test_structured_report_keeps_core_and_support_separate() -> None:
    report = StructuredReport(
        output_language="zh-CN",
        topic="AI coding agent comparison",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing", "feature", "persona"],
        core=ReportCore.minimal_for_tests(
            competitors=["Cursor", "GitHub Copilot"],
            cited_factory=_cited,
        ),
        support=ReportSupport.minimal_for_tests(cited_factory=_cited),
        metadata=ReportMetadata(
            writer_mode="structured",
            segment_count=3,
            source_count=2,
            warnings=[],
            structured_report_version="structured_report.v1",
        ),
    )

    assert report.core.executive_summary.recommendation.text
    assert report.support.evidence_appendix.sources == []
    assert report.metadata.writer_mode == "structured"


def test_battlecard_play_requires_substantive_fields() -> None:
    play = BattlecardPlay(
        competitor="Cursor",
        target_buyer="Engineering leader",
        use_when=_cited("Use when the buyer values fast IDE-native adoption."),
        attack_points=[_cited("Attack on price clarity.")],
        defense_points=[_cited("Defend with product integration proof.")],
        likely_objections=[_cited("Objection: procurement needs security review.")],
        rebuttal_talk_tracks=[_cited("Position proof as a POC validation item.")],
        proof_needed_before_external_use=[evidence_gap("Collect buyer quote before external use.")],
    )
    section = BattlecardSection(plays=[play], evidence_limits=[])
    assert section.plays[0].competitor == "Cursor"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_report.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_report'`.

- [ ] **Step 3: Implement schema models**

Create `backend/packages/agents/writer/structured_report.py` with these definitions:

```python
from __future__ import annotations

import re
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConfidenceLevel = Literal["high", "medium", "low"]
EvidenceRole = Literal[
    "official_fact",
    "community_signal",
    "simulated_research",
    "inference",
    "evidence_gap",
]

SOURCE_TOKEN_TEXT_RE = re.compile(r"(?:\[source:[^\]]+\]|\u3010source:[^\u3011]+\u3011)", re.I)
STRUCTURED_REPORT_VERSION = "structured_report.v1"


class CitedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = "medium"
    evidence_role: EvidenceRole = "inference"

    @model_validator(mode="after")
    def validate_citation_shape(self) -> CitedText:
        if SOURCE_TOKEN_TEXT_RE.search(self.text):
            raise ValueError("CitedText.text must not contain markdown source tokens")
        if not self.source_ids and self.evidence_role != "evidence_gap":
            raise ValueError("uncited text must be an evidence_gap")
        return self


def evidence_gap(text: str) -> CitedText:
    return CitedText(
        text=text,
        source_ids=[],
        confidence="low",
        evidence_role="evidence_gap",
    )


class CompetitorPosture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    posture: CitedText
    decision_implication: CitedText


class ExecutiveSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: CitedText
    risk_adjusted_rationale: CitedText
    competitor_postures: list[CompetitorPosture] = Field(default_factory=list)
    confidence_boundary: CitedText
    next_actions: list[CitedText] = Field(default_factory=list)


class DecisionSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buying_posture: CitedText
    shortlist_rationale: list[CitedText] = Field(default_factory=list)
    risk_boundary: CitedText
    immediate_actions: list[CitedText] = Field(default_factory=list)


class CompetitiveFindingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pricing_packaging: list[CitedText] = Field(default_factory=list)
    feature_workflow: list[CitedText] = Field(default_factory=list)
    user_persona_adoption: list[CitedText] = Field(default_factory=list)
    cross_competitor_risks: list[CitedText] = Field(default_factory=list)


class CompetitorUserTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    direct_user_signals: list[CitedText] = Field(default_factory=list)
    simulated_research_signals: list[CitedText] = Field(default_factory=list)
    adoption_blockers: list[CitedText] = Field(default_factory=list)
    switching_triggers: list[CitedText] = Field(default_factory=list)
    evidence_gaps: list[CitedText] = Field(default_factory=list)


class UserReviewThemesSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_themes: list[CompetitorUserTheme] = Field(default_factory=list)
    cross_competitor_patterns: list[CitedText] = Field(default_factory=list)
    evidence_limits: list[CitedText] = Field(default_factory=list)


class CompetitorDeepDiveSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    positioning: list[CitedText] = Field(default_factory=list)
    pricing_packaging: list[CitedText] = Field(default_factory=list)
    feature_capabilities: list[CitedText] = Field(default_factory=list)
    persona_adoption: list[CitedText] = Field(default_factory=list)
    community_feedback: list[CitedText] = Field(default_factory=list)
    competitive_plays: list[CitedText] = Field(default_factory=list)
    evidence_gaps: list[CitedText] = Field(default_factory=list)


class MatrixCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    summary: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = "medium"


class MatrixDimensionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    cells: list[MatrixCell] = Field(default_factory=list)


class DecisionMatrixSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[MatrixDimensionRow] = Field(default_factory=list)
    interpretation: list[CitedText] = Field(default_factory=list)
    confidence_notes: list[CitedText] = Field(default_factory=list)


class CompetitorSwot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    strengths: list[CitedText] = Field(default_factory=list)
    weaknesses: list[CitedText] = Field(default_factory=list)
    opportunities: list[CitedText] = Field(default_factory=list)
    threats: list[CitedText] = Field(default_factory=list)


class SwotSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[CompetitorSwot] = Field(default_factory=list)


class BattlecardPlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    target_buyer: str
    use_when: CitedText
    attack_points: list[CitedText] = Field(default_factory=list)
    defense_points: list[CitedText] = Field(default_factory=list)
    likely_objections: list[CitedText] = Field(default_factory=list)
    rebuttal_talk_tracks: list[CitedText] = Field(default_factory=list)
    proof_needed_before_external_use: list[CitedText] = Field(default_factory=list)


class BattlecardSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plays: list[BattlecardPlay] = Field(default_factory=list)
    evidence_limits: list[CitedText] = Field(default_factory=list)


class CommunityTriangulationSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    official_vs_community: list[CitedText] = Field(default_factory=list)
    repeated_signals: list[CitedText] = Field(default_factory=list)
    contested_or_low_confidence: list[CitedText] = Field(default_factory=list)


class ReportCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: ExecutiveSummarySection
    decision_summary: DecisionSummarySection
    competitive_findings: CompetitiveFindingsSection
    user_review_themes: UserReviewThemesSection
    competitor_deep_dives: list[CompetitorDeepDiveSection]
    decision_matrix: DecisionMatrixSection
    swot: SwotSection
    battlecard: BattlecardSection
    community_triangulation: CommunityTriangulationSection | None = None

    @classmethod
    def minimal_for_tests(
        cls,
        *,
        competitors: list[str],
        cited_factory: Callable[[str], CitedText],
    ) -> ReportCore:
        postures = [
            CompetitorPosture(
                competitor=name,
                posture=cited_factory(f"{name} has a distinct buying posture."),
                decision_implication=cited_factory(f"{name} requires validation."),
            )
            for name in competitors
        ]
        deep_dives = [
            CompetitorDeepDiveSection(
                competitor=name,
                positioning=[cited_factory(f"{name} positioning.")],
                pricing_packaging=[cited_factory(f"{name} pricing.")],
                feature_capabilities=[cited_factory(f"{name} features.")],
                persona_adoption=[cited_factory(f"{name} adoption.")],
                community_feedback=[evidence_gap(f"{name} direct community evidence is incomplete.")],
                competitive_plays=[cited_factory(f"{name} competitive play.")],
            )
            for name in competitors
        ]
        return cls(
            executive_summary=ExecutiveSummarySection(
                recommendation=cited_factory("Use a risk-adjusted shortlist."),
                risk_adjusted_rationale=cited_factory("The recommendation separates paper wins from evidence risk."),
                competitor_postures=postures,
                confidence_boundary=cited_factory("Do not overstate unsupported claims."),
                next_actions=[cited_factory("Collect procurement proof.")],
            ),
            decision_summary=DecisionSummarySection(
                buying_posture=cited_factory("Adopt a guarded shortlist."),
                shortlist_rationale=[cited_factory("The shortlist balances capability and risk.")],
                risk_boundary=cited_factory("Weak evidence remains bounded."),
                immediate_actions=[cited_factory("Run a buyer validation call.")],
            ),
            competitive_findings=CompetitiveFindingsSection(
                pricing_packaging=[cited_factory("Pricing differs across competitors.")],
                feature_workflow=[cited_factory("Feature fit differs by workflow.")],
                user_persona_adoption=[cited_factory("Persona fit is directional.")],
                cross_competitor_risks=[cited_factory("Evidence strength varies.")],
            ),
            user_review_themes=UserReviewThemesSection(
                competitor_themes=[
                    CompetitorUserTheme(
                        competitor=name,
                        direct_user_signals=[evidence_gap(f"{name} direct user signals are incomplete.")],
                        simulated_research_signals=[cited_factory(f"{name} simulated interview signal.")],
                        adoption_blockers=[cited_factory(f"{name} adoption blocker.")],
                        switching_triggers=[cited_factory(f"{name} switching trigger.")],
                    )
                    for name in competitors
                ],
                cross_competitor_patterns=[cited_factory("Across competitors, evidence should be qualified.")],
            ),
            competitor_deep_dives=deep_dives,
            decision_matrix=DecisionMatrixSection(
                dimensions=[
                    MatrixDimensionRow(
                        dimension="pricing",
                        cells=[
                            MatrixCell(competitor=name, summary=f"{name} pricing signal", source_ids=["raw-source-a"], confidence="medium")
                            for name in competitors
                        ],
                    )
                ],
                interpretation=[cited_factory("Matrix leadership differs from final recommendation.")],
                confidence_notes=[cited_factory("Matrix cells carry evidence limits.")],
            ),
            swot=SwotSection(
                competitors=[
                    CompetitorSwot(
                        competitor=name,
                        strengths=[cited_factory(f"{name} strength.")],
                        weaknesses=[cited_factory(f"{name} weakness.")],
                        opportunities=[cited_factory(f"{name} opportunity.")],
                        threats=[cited_factory(f"{name} threat.")],
                    )
                    for name in competitors
                ]
            ),
            battlecard=BattlecardSection(
                plays=[
                    BattlecardPlay(
                        competitor=name,
                        target_buyer="Engineering leader",
                        use_when=cited_factory(f"Use against {name} when the account asks for proof."),
                        attack_points=[cited_factory(f"{name} attack point.")],
                        defense_points=[cited_factory(f"{name} defense point.")],
                        likely_objections=[cited_factory(f"{name} objection.")],
                        rebuttal_talk_tracks=[cited_factory(f"{name} rebuttal.")],
                        proof_needed_before_external_use=[evidence_gap(f"{name} proof gap.")],
                    )
                    for name in competitors
                ]
            ),
            community_triangulation=CommunityTriangulationSection(
                official_vs_community=[cited_factory("Official and community evidence differ by role.")]
            ),
        )


class SourceAppendixItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str = ""
    source_type: str = ""
    competitor: str = ""
    dimension: str = ""
    confidence: float = 0.0


class SourceQualitySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: list[CitedText] = Field(default_factory=list)


class UserResearchEvidenceSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: list[CitedText] = Field(default_factory=list)


class RagGapFillSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_queries: list[CitedText] = Field(default_factory=list)


class ScenarioQaSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[CitedText] = Field(default_factory=list)


class ClaimRiskSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risks: list[CitedText] = Field(default_factory=list)


class NextCollectionSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[CitedText] = Field(default_factory=list)


class EvidenceAppendixSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceAppendixItem] = Field(default_factory=list)


class ReportSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_quality: SourceQualitySection
    user_research_evidence: UserResearchEvidenceSection
    rag_gap_fill: RagGapFillSection
    scenario_qa: ScenarioQaSection
    claim_risk: ClaimRiskSection
    next_collection: NextCollectionSection
    evidence_appendix: EvidenceAppendixSection

    @classmethod
    def minimal_for_tests(cls, *, cited_factory: Callable[[str], CitedText]) -> ReportSupport:
        return cls(
            source_quality=SourceQualitySection(summary=[cited_factory("Sources are mixed.")]),
            user_research_evidence=UserResearchEvidenceSection(summary=[cited_factory("User research is directional.")]),
            rag_gap_fill=RagGapFillSection(retrieval_queries=[evidence_gap("Collect direct buyer review evidence.")]),
            scenario_qa=ScenarioQaSection(checks=[cited_factory("Scenario checks passed with limits.")]),
            claim_risk=ClaimRiskSection(risks=[cited_factory("Strong claims need support.")]),
            next_collection=NextCollectionSection(tasks=[evidence_gap("Collect procurement references.")]),
            evidence_appendix=EvidenceAppendixSection(sources=[]),
        )


class ReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writer_mode: str
    segment_count: int
    source_count: int
    warnings: list[str] = Field(default_factory=list)
    structured_report_version: str = STRUCTURED_REPORT_VERSION


class StructuredReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_language: str
    topic: str
    competitors: list[str]
    dimensions: list[str]
    core: ReportCore
    support: ReportSupport
    metadata: ReportMetadata
```

- [ ] **Step 4: Run model tests**

Run:

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_report.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/structured_report.py backend/tests/unit/test_writer_structured_report.py
git commit -m "feat(writer): add structured report schema"
```

### Task 2: Deterministic Structured Renderer

**Files:**
- Create: `backend/packages/agents/writer/structured_renderer.py`
- Test: `backend/tests/unit/test_writer_structured_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Add `backend/tests/unit/test_writer_structured_renderer.py`:

```python
import re

from packages.agents.writer.structured_renderer import render_structured_report
from packages.agents.writer.structured_report import (
    CitedText,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    SourceAppendixItem,
    StructuredReport,
)


def _cited(text: str, source_id: str = "raw-source-a") -> CitedText:
    return CitedText(
        text=text,
        source_ids=[source_id],
        confidence="high",
        evidence_role="official_fact",
    )


def _report(output_language: str = "zh-CN") -> StructuredReport:
    support = ReportSupport.minimal_for_tests(cited_factory=_cited)
    support.evidence_appendix.sources.append(
        SourceAppendixItem(
            source_id="raw-source-a",
            title="Cursor pricing",
            source_type="webpage_verified",
            competitor="Cursor",
            dimension="pricing",
            confidence=0.96,
        )
    )
    return StructuredReport(
        output_language=output_language,
        topic="AI coding agent comparison",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing", "feature", "persona"],
        core=ReportCore.minimal_for_tests(
            competitors=["Cursor", "GitHub Copilot"],
            cited_factory=_cited,
        ),
        support=support,
        metadata=ReportMetadata(
            writer_mode="structured",
            segment_count=3,
            source_count=1,
            warnings=[],
            structured_report_version="structured_report.v1",
        ),
    )


def test_renderer_localizes_zh_child_headings() -> None:
    markdown = render_structured_report(_report("zh-CN"))
    assert "### Pricing and Packaging" not in markdown
    assert "#### Direct User / Community Signals" not in markdown
    assert "### 定价与包装" in markdown
    assert "#### 直接用户/社区信号" in markdown


def test_renderer_keeps_citations_out_of_headings_and_table_headers() -> None:
    markdown = render_structured_report(_report("zh-CN"))
    for line in markdown.splitlines():
        if line.lstrip().startswith("#"):
            assert "[source:" not in line
    assert not re.search(r"^\|.*\[source:", markdown, flags=re.MULTILINE)
    assert "| 维度 | Cursor | GitHub Copilot |" in markdown


def test_renderer_places_support_after_core_sections() -> None:
    markdown = render_structured_report(_report("zh-CN"))
    assert markdown.index("## 战报") < markdown.index("## 证据质量与覆盖")
    assert markdown.index("## 证据质量与覆盖") < markdown.index("## 证据附录")


def test_renderer_does_not_emit_internal_metadata_terms() -> None:
    markdown = render_structured_report(_report("zh-CN"))
    forbidden = ["source_registry", "allowed_source_ids", "Writer Evidence Pack", "Segment Evidence Pack"]
    assert all(term not in markdown for term in forbidden)


def test_renderer_evidence_appendix_rows_are_reader_facing() -> None:
    markdown = render_structured_report(_report("zh-CN"))
    appendix = markdown.split("## 证据附录", 1)[1]
    assert "`raw-source-a`" in appendix
    assert "[source:" not in appendix
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_renderer.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_renderer'`.

- [ ] **Step 3: Implement renderer**

Create `backend/packages/agents/writer/structured_renderer.py`:

```python
from __future__ import annotations

from collections.abc import Iterable, Sequence

from packages.agents.writer.structured_report import CitedText, MatrixCell, StructuredReport
from packages.i18n.language import normalize_output_language, report_label


CHILD_LABELS = {
    "zh-CN": {
        "pricing_packaging": "定价与包装",
        "feature_workflow": "功能与工作流能力",
        "user_persona_adoption": "用户画像与采用",
        "cross_competitor": "跨竞品风险与启示",
        "direct_user_community": "直接用户/社区信号",
        "simulated_research": "模拟调研/访谈信号",
        "adoption_blockers": "采用障碍",
        "switching_triggers": "切换触发",
        "evidence_gaps": "证据缺口",
        "positioning_core": "定位与核心价值",
        "feature_capabilities": "功能能力",
        "community_feedback": "社区反馈、采用障碍与切换触发",
        "competitive_plays": "竞争打法与证据缺口",
        "strengths": "优势",
        "weaknesses": "劣势",
        "opportunities": "机会",
        "threats": "威胁",
        "official_vs_community": "官方事实与社区观察",
        "repeated_signals": "重复信号",
        "contested_signals": "有争议或低置信信号",
        "dimension": "维度",
    },
    "en-US": {
        "pricing_packaging": "Pricing and Packaging",
        "feature_workflow": "Feature and Workflow Capability",
        "user_persona_adoption": "User Persona and Adoption",
        "cross_competitor": "Cross-Competitor Risks and Implications",
        "direct_user_community": "Direct User / Community Signals",
        "simulated_research": "Simulated Survey and Interview Signals",
        "adoption_blockers": "Adoption Blockers",
        "switching_triggers": "Switching Triggers",
        "evidence_gaps": "Evidence Gaps",
        "positioning_core": "Positioning and Core Value",
        "feature_capabilities": "Feature Capabilities",
        "community_feedback": "Community Feedback, Adoption Blockers, and Switching Triggers",
        "competitive_plays": "Competitive Plays and Evidence Gaps",
        "strengths": "Strengths",
        "weaknesses": "Weaknesses",
        "opportunities": "Opportunities",
        "threats": "Threats",
        "official_vs_community": "Official Facts vs Community Observations",
        "repeated_signals": "Repeated Signals",
        "contested_signals": "Contested or Low-Confidence Signals",
        "dimension": "Dimension",
    },
}


def render_structured_report(report: StructuredReport) -> str:
    language = _language(report.output_language)
    blocks: list[str] = []
    blocks.append(_render_executive_summary(report, language))
    blocks.append(_render_decision_summary(report, language))
    blocks.append(_render_competitive_findings(report, language))
    blocks.append(_render_user_review_themes(report, language))
    blocks.append(_render_competitor_deep_dives(report, language))
    blocks.append(_render_matrix(report, language))
    blocks.append(_render_swot(report, language))
    blocks.append(_render_battlecard(report, language))
    if report.core.community_triangulation is not None:
        blocks.append(_render_community_triangulation(report, language))
    blocks.append(_render_source_quality(report, language))
    blocks.append(_render_user_research_evidence(report, language))
    blocks.append(_render_rag_gap_fill(report, language))
    blocks.append(_render_scenario_qa(report, language))
    blocks.append(_render_claim_risk(report, language))
    blocks.append(_render_next_collection(report, language))
    blocks.append(_render_evidence_appendix(report, language))
    return "\n\n".join(block for block in blocks if block.strip()).strip()


def _language(output_language: str) -> str:
    normalized = normalize_output_language(output_language)
    return "zh-CN" if normalized == "zh-CN" else "en-US"


def _label(language: str, key: str) -> str:
    return CHILD_LABELS[language][key]


def _h2(report: StructuredReport, key: str) -> str:
    return f"## {report_label(report.output_language, key)}"


def _cite(source_ids: Sequence[str]) -> str:
    if not source_ids:
        return ""
    return "".join(f"[source:{source_id}]" for source_id in source_ids)


def _line(item: CitedText) -> str:
    suffix = _cite(item.source_ids)
    if suffix:
        return f"- {item.text} {suffix}"
    return f"- {item.text}"


def _lines(items: Iterable[CitedText]) -> list[str]:
    return [_line(item) for item in items]


def _render_executive_summary(report: StructuredReport, language: str) -> str:
    section = report.core.executive_summary
    lines = [_h2(report, "executive_summary")]
    lines.append(_line(section.recommendation))
    lines.append(_line(section.risk_adjusted_rationale))
    for posture in section.competitor_postures:
        lines.append(f"- {posture.competitor}: {posture.posture.text} {_cite(posture.posture.source_ids)}")
        lines.append(f"- {posture.competitor}: {posture.decision_implication.text} {_cite(posture.decision_implication.source_ids)}")
    lines.append(_line(section.confidence_boundary))
    lines.extend(_lines(section.next_actions))
    return "\n".join(line.rstrip() for line in lines)


def _render_decision_summary(report: StructuredReport, language: str) -> str:
    section = report.core.decision_summary
    lines = [_h2(report, "decision_summary"), _line(section.buying_posture)]
    lines.extend(_lines(section.shortlist_rationale))
    lines.append(_line(section.risk_boundary))
    lines.extend(_lines(section.immediate_actions))
    return "\n".join(lines)


def _render_competitive_findings(report: StructuredReport, language: str) -> str:
    section = report.core.competitive_findings
    groups = [
        ("pricing_packaging", section.pricing_packaging),
        ("feature_workflow", section.feature_workflow),
        ("user_persona_adoption", section.user_persona_adoption),
        ("cross_competitor", section.cross_competitor_risks),
    ]
    lines = [_h2(report, "competitive_findings")]
    for key, items in groups:
        lines.append(f"### {_label(language, key)}")
        lines.extend(_lines(items))
    return "\n".join(lines)


def _render_user_review_themes(report: StructuredReport, language: str) -> str:
    section = report.core.user_review_themes
    lines = [_h2(report, "review_theme_summary")]
    for theme in section.competitor_themes:
        lines.append(f"### {theme.competitor}")
        for key, items in [
            ("direct_user_community", theme.direct_user_signals),
            ("simulated_research", theme.simulated_research_signals),
            ("adoption_blockers", theme.adoption_blockers),
            ("switching_triggers", theme.switching_triggers),
            ("evidence_gaps", theme.evidence_gaps),
        ]:
            lines.append(f"#### {_label(language, key)}")
            lines.extend(_lines(items))
    if section.cross_competitor_patterns:
        lines.append(f"### {_label(language, 'cross_competitor')}")
        lines.extend(_lines(section.cross_competitor_patterns))
    if section.evidence_limits:
        lines.append(f"### {_label(language, 'evidence_gaps')}")
        lines.extend(_lines(section.evidence_limits))
    return "\n".join(lines)


def _render_competitor_deep_dives(report: StructuredReport, language: str) -> str:
    lines = [_h2(report, "competitor_deep_dives")]
    for dive in report.core.competitor_deep_dives:
        lines.append(f"### {dive.competitor}")
        for key, items in [
            ("positioning_core", dive.positioning),
            ("pricing_packaging", dive.pricing_packaging),
            ("feature_capabilities", dive.feature_capabilities),
            ("user_persona_adoption", dive.persona_adoption),
            ("community_feedback", dive.community_feedback),
            ("competitive_plays", dive.competitive_plays),
            ("evidence_gaps", dive.evidence_gaps),
        ]:
            lines.append(f"#### {_label(language, key)}")
            lines.extend(_lines(items))
    return "\n".join(lines)


def _cell_text(cell: MatrixCell) -> str:
    return f"{cell.summary} {_cite(cell.source_ids)}".rstrip()


def _render_matrix(report: StructuredReport, language: str) -> str:
    lines = [_h2(report, "side_by_side_matrix")]
    lines.append("| " + " | ".join([_label(language, "dimension"), *report.competitors]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(len(report.competitors) + 1)) + " |")
    for row in report.core.decision_matrix.dimensions:
        by_competitor = {cell.competitor: cell for cell in row.cells}
        cells = [_cell_text(by_competitor[name]) if name in by_competitor else "" for name in report.competitors]
        lines.append("| " + " | ".join([row.dimension, *cells]) + " |")
    lines.extend(_lines(report.core.decision_matrix.interpretation))
    lines.extend(_lines(report.core.decision_matrix.confidence_notes))
    return "\n".join(lines)


def _render_swot(report: StructuredReport, language: str) -> str:
    lines = [_h2(report, "swot_analysis")]
    for swot in report.core.swot.competitors:
        lines.append(f"### {swot.competitor}")
        for key, items in [
            ("strengths", swot.strengths),
            ("weaknesses", swot.weaknesses),
            ("opportunities", swot.opportunities),
            ("threats", swot.threats),
        ]:
            lines.append(f"#### {_label(language, key)}")
            lines.extend(_lines(items))
    return "\n".join(lines)


def _render_battlecard(report: StructuredReport, language: str) -> str:
    lines = [_h2(report, "battlecard")]
    target_buyer_label = "目标买家" if language == "zh-CN" else "Target buyer"
    for play in report.core.battlecard.plays:
        lines.append(f"### {play.competitor}")
        lines.append(f"- {target_buyer_label}: {play.target_buyer}")
        lines.append(_line(play.use_when))
        lines.extend(_lines(play.attack_points))
        lines.extend(_lines(play.defense_points))
        lines.extend(_lines(play.likely_objections))
        lines.extend(_lines(play.rebuttal_talk_tracks))
        lines.extend(_lines(play.proof_needed_before_external_use))
    lines.extend(_lines(report.core.battlecard.evidence_limits))
    return "\n".join(lines)


def _render_community_triangulation(report: StructuredReport, language: str) -> str:
    section = report.core.community_triangulation
    if section is None:
        return ""
    lines = [_h2(report, "community_evidence_triangulation")]
    lines.append(f"### {_label(language, 'official_vs_community')}")
    lines.extend(_lines(section.official_vs_community))
    lines.append(f"### {_label(language, 'repeated_signals')}")
    lines.extend(_lines(section.repeated_signals))
    lines.append(f"### {_label(language, 'contested_signals')}")
    lines.extend(_lines(section.contested_or_low_confidence))
    return "\n".join(lines)


def _render_source_quality(report: StructuredReport, language: str) -> str:
    return "\n".join([_h2(report, "source_quality"), *_lines(report.support.source_quality.summary)])


def _render_user_research_evidence(report: StructuredReport, language: str) -> str:
    return "\n".join([_h2(report, "user_research_evidence"), *_lines(report.support.user_research_evidence.summary)])


def _render_rag_gap_fill(report: StructuredReport, language: str) -> str:
    return "\n".join([_h2(report, "rag_gap_fill"), *_lines(report.support.rag_gap_fill.retrieval_queries)])


def _render_scenario_qa(report: StructuredReport, language: str) -> str:
    return "\n".join([_h2(report, "scenario_checklist"), *_lines(report.support.scenario_qa.checks)])


def _render_claim_risk(report: StructuredReport, language: str) -> str:
    return "\n".join([_h2(report, "claim_risk"), *_lines(report.support.claim_risk.risks)])


def _render_next_collection(report: StructuredReport, language: str) -> str:
    return "\n".join([_h2(report, "next_collection"), *_lines(report.support.next_collection.tasks)])


def _render_evidence_appendix(report: StructuredReport, language: str) -> str:
    lines = [_h2(report, "evidence_appendix")]
    for source in report.support.evidence_appendix.sources:
        lines.append(
            "- "
            f"`{source.source_id}` — {source.title or 'Untitled source'} — "
            f"{source.source_type or 'unknown'} — {source.competitor or 'unknown'} / "
            f"{source.dimension or 'unknown'} — confidence {source.confidence:.2f}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run renderer tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_renderer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/structured_renderer.py backend/tests/unit/test_writer_structured_renderer.py
git commit -m "feat(writer): render structured reports to markdown"
```

### Task 3: Structured Validator

**Files:**
- Create: `backend/packages/agents/writer/structured_validation.py`
- Test: `backend/tests/unit/test_writer_structured_validation.py`

- [ ] **Step 1: Write failing validation tests**

Add `backend/tests/unit/test_writer_structured_validation.py`:

```python
from packages.agents.writer.structured_report import (
    BattlecardSection,
    CitedText,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    StructuredReport,
)
from packages.agents.writer.structured_validation import validate_structured_report


def _cited(text: str, source_id: str = "raw-source-a") -> CitedText:
    return CitedText(
        text=text,
        source_ids=[source_id],
        confidence="high",
        evidence_role="official_fact",
    )


def _report() -> StructuredReport:
    return StructuredReport(
        output_language="zh-CN",
        topic="AI coding agent comparison",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing", "feature", "persona"],
        core=ReportCore.minimal_for_tests(
            competitors=["Cursor", "GitHub Copilot"],
            cited_factory=_cited,
        ),
        support=ReportSupport.minimal_for_tests(cited_factory=_cited),
        metadata=ReportMetadata(
            writer_mode="structured",
            segment_count=3,
            source_count=1,
            warnings=[],
            structured_report_version="structured_report.v1",
        ),
    )


def test_validation_passes_complete_report() -> None:
    result = validate_structured_report(_report(), allowed_source_ids={"raw-source-a"})
    assert result.passed is True
    assert result.issues == []


def test_validation_rejects_unknown_source_ids() -> None:
    report = _report()
    report.core.executive_summary.recommendation.source_ids = ["raw-source-missing"]
    result = validate_structured_report(report, allowed_source_ids={"raw-source-a"})
    assert result.passed is False
    assert result.has_issue("unknown_source_id")


def test_validation_rejects_template_only_battlecard() -> None:
    report = _report()
    report.core.battlecard = BattlecardSection(plays=[], evidence_limits=[])
    result = validate_structured_report(report, allowed_source_ids={"raw-source-a"})
    assert result.has_issue("battlecard_missing_competitor_play")


def test_validation_rejects_internal_terms_in_user_text() -> None:
    report = _report()
    report.core.decision_summary.buying_posture.text = "Use source_registry from Writer Evidence Pack."
    result = validate_structured_report(report, allowed_source_ids={"raw-source-a"})
    assert result.has_issue("internal_term_leak")


def test_validation_rejects_template_executive_summary() -> None:
    report = _report()
    report.core.executive_summary.recommendation.text = "This report is structured as decision analysis first."
    result = validate_structured_report(report, allowed_source_ids={"raw-source-a"})
    assert result.has_issue("executive_summary_template_only")


def test_validation_requires_per_competitor_coverage() -> None:
    report = _report()
    report.core.competitor_deep_dives = report.core.competitor_deep_dives[:1]
    result = validate_structured_report(report, allowed_source_ids={"raw-source-a"})
    assert result.has_issue("missing_competitor_deep_dive")
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_validation.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_validation'`.

- [ ] **Step 3: Implement structured validation**

Create `backend/packages/agents/writer/structured_validation.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from packages.agents.writer.structured_report import CitedText, StructuredReport

INTERNAL_TERMS = (
    "Segment Evidence Pack",
    "Writer Evidence Pack",
    "source_registry",
    "allowed_source_ids",
    "represented_by",
    "fact:",
    "signal:",
)
TEMPLATE_EXECUTIVE_SUMMARY_PHRASES = (
    "this report is structured as decision analysis first",
    "core conclusion",
    "decision posture",
    "risk boundary",
    "immediate action",
)
TEMPLATE_BATTLECARD_PHRASES = (
    "direct battlecard positioning",
    "objection handling",
    "action bias",
    "deployment check",
    "every battlecard line should",
    "直接战报定位",
    "反对意见处理",
    "行动偏向",
    "落地检查",
)


@dataclass(frozen=True)
class StructuredReportValidationIssue:
    code: str
    path: str
    message: str
    deterministic: bool = False


@dataclass(frozen=True)
class StructuredReportValidation:
    passed: bool
    issues: list[StructuredReportValidationIssue] = field(default_factory=list)

    def has_issue(self, code: str) -> bool:
        return any(issue.code == code for issue in self.issues)


def validate_structured_report(
    report: StructuredReport,
    *,
    allowed_source_ids: set[str],
) -> StructuredReportValidation:
    issues: list[StructuredReportValidationIssue] = []
    issues.extend(_source_id_issues(report, allowed_source_ids))
    issues.extend(_internal_term_issues(report))
    issues.extend(_executive_summary_issues(report))
    issues.extend(_competitor_coverage_issues(report))
    issues.extend(_battlecard_issues(report))
    return StructuredReportValidation(passed=not issues, issues=issues)


def _source_id_issues(
    report: StructuredReport,
    allowed_source_ids: set[str],
) -> list[StructuredReportValidationIssue]:
    issues: list[StructuredReportValidationIssue] = []
    for path, item in _iter_cited_text(report):
        for source_id in item.source_ids:
            if source_id not in allowed_source_ids:
                issues.append(
                    StructuredReportValidationIssue(
                        code="unknown_source_id",
                        path=f"{path}.source_ids",
                        message=f"Unknown source id: {source_id}",
                    )
                )
    for row_index, row in enumerate(report.core.decision_matrix.dimensions):
        for cell_index, cell in enumerate(row.cells):
            for source_id in cell.source_ids:
                if source_id not in allowed_source_ids:
                    issues.append(
                        StructuredReportValidationIssue(
                            code="unknown_source_id",
                            path=f"core.decision_matrix.dimensions[{row_index}].cells[{cell_index}].source_ids",
                            message=f"Unknown source id: {source_id}",
                        )
                    )
    return issues


def _internal_term_issues(report: StructuredReport) -> list[StructuredReportValidationIssue]:
    issues: list[StructuredReportValidationIssue] = []
    for path, item in _iter_cited_text(report):
        if any(term in item.text for term in INTERNAL_TERMS):
            issues.append(
                StructuredReportValidationIssue(
                    code="internal_term_leak",
                    path=f"{path}.text",
                    message="Reader-facing text contains writer-internal terms.",
                )
            )
    return issues


def _executive_summary_issues(report: StructuredReport) -> list[StructuredReportValidationIssue]:
    text = " ".join(
        [
            report.core.executive_summary.recommendation.text,
            report.core.executive_summary.risk_adjusted_rationale.text,
            report.core.executive_summary.confidence_boundary.text,
        ]
    ).casefold()
    if any(phrase in text for phrase in TEMPLATE_EXECUTIVE_SUMMARY_PHRASES):
        return [
            StructuredReportValidationIssue(
                code="executive_summary_template_only",
                path="core.executive_summary",
                message="Executive summary is a system-style template instead of a business recommendation.",
            )
        ]
    return []


def _competitor_coverage_issues(report: StructuredReport) -> list[StructuredReportValidationIssue]:
    issues: list[StructuredReportValidationIssue] = []
    competitors = set(report.competitors)
    deep_dive_competitors = {item.competitor for item in report.core.competitor_deep_dives}
    user_theme_competitors = {item.competitor for item in report.core.user_review_themes.competitor_themes}
    swot_competitors = {item.competitor for item in report.core.swot.competitors}
    battlecard_competitors = {item.competitor for item in report.core.battlecard.plays}
    for code, path, actual in [
        ("missing_competitor_deep_dive", "core.competitor_deep_dives", deep_dive_competitors),
        ("missing_competitor_user_theme", "core.user_review_themes.competitor_themes", user_theme_competitors),
        ("missing_competitor_swot", "core.swot.competitors", swot_competitors),
        ("missing_competitor_battlecard", "core.battlecard.plays", battlecard_competitors),
    ]:
        missing = sorted(competitors - actual)
        for competitor in missing:
            issues.append(
                StructuredReportValidationIssue(
                    code=code,
                    path=path,
                    message=f"Missing structured coverage for {competitor}.",
                )
            )
    return issues


def _battlecard_issues(report: StructuredReport) -> list[StructuredReportValidationIssue]:
    issues: list[StructuredReportValidationIssue] = []
    if not report.core.battlecard.plays:
        for competitor in report.competitors:
            issues.append(
                StructuredReportValidationIssue(
                    code="battlecard_missing_competitor_play",
                    path="core.battlecard.plays",
                    message=f"Missing substantive battlecard play for {competitor}.",
                )
            )
        return issues
    for index, play in enumerate(report.core.battlecard.plays):
        body = " ".join(
            [
                play.use_when.text,
                *(item.text for item in play.attack_points),
                *(item.text for item in play.defense_points),
                *(item.text for item in play.likely_objections),
                *(item.text for item in play.rebuttal_talk_tracks),
            ]
        ).casefold()
        if any(phrase in body for phrase in TEMPLATE_BATTLECARD_PHRASES):
            issues.append(
                StructuredReportValidationIssue(
                    code="battlecard_template_only",
                    path=f"core.battlecard.plays[{index}]",
                    message="Battlecard play contains generic template language.",
                )
            )
    return issues


def _iter_cited_text(report: StructuredReport) -> Iterable[tuple[str, CitedText]]:
    stack: list[tuple[str, object]] = [("report", report)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, CitedText):
            yield path, value
            continue
        if isinstance(value, list):
            for index, item in enumerate(value):
                stack.append((f"{path}[{index}]", item))
            continue
        if hasattr(value, "model_fields"):
            for field_name in value.model_fields:
                stack.append((f"{path}.{field_name}", getattr(value, field_name)))
```

- [ ] **Step 4: Run validation tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_validation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/structured_validation.py backend/tests/unit/test_writer_structured_validation.py
git commit -m "feat(writer): validate structured reports"
```

### Task 4: Publication Contract

**Files:**
- Create: `backend/packages/agents/writer/publication_contract.py`
- Test: `backend/tests/unit/test_writer_publication_contract.py`

- [ ] **Step 1: Write failing publication contract tests**

Add `backend/tests/unit/test_writer_publication_contract.py`:

```python
from packages.agents.writer.publication_contract import validate_publication_contract


def test_contract_rejects_zh_report_with_english_template_headings() -> None:
    markdown = """
## 执行摘要
- 这是中文报告。 [source:raw-source-a]

## 竞争发现
### Pricing and Packaging
- Cursor pricing is clearer. [source:raw-source-a]
""".strip()
    result = validate_publication_contract(
        markdown,
        structured_report=None,
        output_language="zh-CN",
        allowed_source_ids={"raw-source-a"},
    )
    assert result.has_issue("english_structural_heading_in_zh")


def test_contract_rejects_citations_in_heading_and_table_header() -> None:
    markdown = """
## 执行摘要 [source:raw-source-a]
- 结论。 [source:raw-source-a]

## 横向决策矩阵
| 维度 [source:raw-source-a] | Cursor |
| --- | --- |
| pricing | clear [source:raw-source-a] |
""".strip()
    result = validate_publication_contract(
        markdown,
        structured_report=None,
        output_language="zh-CN",
        allowed_source_ids={"raw-source-a"},
    )
    assert result.has_issue("citation_in_heading")
    assert result.has_issue("citation_in_table_header")


def test_contract_rejects_internal_writer_terms() -> None:
    markdown = "## 执行摘要\n- See Segment Evidence Pack JSON source_registry. [source:raw-source-a]"
    result = validate_publication_contract(
        markdown,
        structured_report=None,
        output_language="zh-CN",
        allowed_source_ids={"raw-source-a"},
    )
    assert result.has_issue("internal_term_leak")


def test_contract_rejects_template_battlecard() -> None:
    markdown = """
## 战报
- 直接战报定位：把当前赢家作为短期替代主线。 [source:raw-source-a]
- 反对意见处理：围绕定价和功能组织回答。 [source:raw-source-a]
""".strip()
    result = validate_publication_contract(
        markdown,
        structured_report=None,
        output_language="zh-CN",
        allowed_source_ids={"raw-source-a"},
    )
    assert result.has_issue("battlecard_template_only")


def test_contract_rejects_unknown_source_ids() -> None:
    markdown = "## 执行摘要\n- 结论。 [source:raw-source-missing]"
    result = validate_publication_contract(
        markdown,
        structured_report=None,
        output_language="zh-CN",
        allowed_source_ids={"raw-source-a"},
    )
    assert result.has_issue("unknown_source_id")
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_publication_contract.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.publication_contract'`.

- [ ] **Step 3: Implement publication contract**

Create `backend/packages/agents/writer/publication_contract.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

from packages.agents.writer.structured_report import StructuredReport
from packages.agents.writer.structured_validation import (
    INTERNAL_TERMS,
    TEMPLATE_BATTLECARD_PHRASES,
    StructuredReportValidationIssue,
    validate_structured_report,
)
from packages.identity.source_resolver import source_tokens

ENGLISH_TEMPLATE_HEADING_PHRASES = (
    "executive summary",
    "decision summary",
    "competitive findings",
    "pricing and packaging",
    "feature and workflow",
    "direct user / community signals",
    "simulated survey and interview signals",
    "adoption blockers",
    "switching triggers",
    "strengths",
    "weaknesses",
    "opportunities",
    "threats",
    "evidence appendix",
)


@dataclass(frozen=True)
class PublicationContractIssue:
    code: str
    path: str
    message: str
    deterministic: bool = False


@dataclass(frozen=True)
class PublicationContractResult:
    passed: bool
    issues: list[PublicationContractIssue] = field(default_factory=list)

    def has_issue(self, code: str) -> bool:
        return any(issue.code == code for issue in self.issues)


def validate_publication_contract(
    markdown: str,
    *,
    structured_report: StructuredReport | None,
    output_language: str,
    allowed_source_ids: set[str],
) -> PublicationContractResult:
    issues: list[PublicationContractIssue] = []
    issues.extend(_heading_issues(markdown, output_language))
    issues.extend(_citation_placement_issues(markdown))
    issues.extend(_internal_term_issues(markdown))
    issues.extend(_battlecard_issues(markdown))
    issues.extend(_source_id_issues(markdown, allowed_source_ids))
    if structured_report is not None:
        structured = validate_structured_report(
            structured_report,
            allowed_source_ids=allowed_source_ids,
        )
        issues.extend(_from_structured_issue(issue) for issue in structured.issues)
    return PublicationContractResult(passed=not issues, issues=issues)


def _heading_issues(markdown: str, output_language: str) -> list[PublicationContractIssue]:
    issues: list[PublicationContractIssue] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if "[source:" in stripped.casefold():
            issues.append(
                PublicationContractIssue(
                    code="citation_in_heading",
                    path=f"report_md.line[{line_number}]",
                    message="Citation appears in a Markdown heading.",
                    deterministic=True,
                )
            )
        if output_language.casefold().startswith("zh"):
            normalized = re.sub(r"\s+", " ", stripped.lstrip("#").strip()).casefold()
            if any(phrase in normalized for phrase in ENGLISH_TEMPLATE_HEADING_PHRASES):
                issues.append(
                    PublicationContractIssue(
                        code="english_structural_heading_in_zh",
                        path=f"report_md.line[{line_number}]",
                        message="Chinese report contains English structural heading.",
                        deterministic=True,
                    )
                )
    return issues


def _citation_placement_issues(markdown: str) -> list[PublicationContractIssue]:
    lines = markdown.splitlines()
    issues: list[PublicationContractIssue] = []
    for index, line in enumerate(lines):
        if _table_header_line_has_citation(lines, index):
            issues.append(
                PublicationContractIssue(
                    code="citation_in_table_header",
                    path=f"report_md.line[{index + 1}]",
                    message="Citation appears in a table header row.",
                    deterministic=True,
                )
            )
    return issues


def _table_header_line_has_citation(lines: list[str], index: int) -> bool:
    line = lines[index].strip()
    if not line.startswith("|") or "[source:" not in line.casefold():
        return False
    next_line = ""
    for candidate in lines[index + 1 :]:
        if candidate.strip():
            next_line = candidate.strip()
            break
    return bool(next_line) and re.fullmatch(r"\|?[\s|\-:]+\|?", next_line) is not None


def _internal_term_issues(markdown: str) -> list[PublicationContractIssue]:
    if not any(term in markdown for term in INTERNAL_TERMS):
        return []
    return [
        PublicationContractIssue(
            code="internal_term_leak",
            path="report_md",
            message="Reader-facing report contains writer-internal terms.",
        )
    ]


def _battlecard_issues(markdown: str) -> list[PublicationContractIssue]:
    body = markdown.casefold()
    if not any(phrase in body for phrase in TEMPLATE_BATTLECARD_PHRASES):
        return []
    return [
        PublicationContractIssue(
            code="battlecard_template_only",
            path="report_md.battlecard",
            message="Battlecard contains generic template language.",
        )
    ]


def _source_id_issues(
    markdown: str,
    allowed_source_ids: set[str],
) -> list[PublicationContractIssue]:
    issues: list[PublicationContractIssue] = []
    for source_id in source_tokens(markdown):
        if source_id not in allowed_source_ids:
            issues.append(
                PublicationContractIssue(
                    code="unknown_source_id",
                    path="report_md.source_tokens",
                    message=f"Unknown source id: {source_id}",
                )
            )
    return issues


def _from_structured_issue(issue: StructuredReportValidationIssue) -> PublicationContractIssue:
    return PublicationContractIssue(
        code=issue.code,
        path=issue.path,
        message=issue.message,
        deterministic=issue.deterministic,
    )
```

- [ ] **Step 4: Run publication tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_publication_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/publication_contract.py backend/tests/unit/test_writer_publication_contract.py
git commit -m "feat(writer): add publication contract checks"
```

### Task 5: Structured Section Planner

**Files:**
- Create: `backend/packages/agents/writer/structured_sections.py`
- Test: `backend/tests/unit/test_writer_structured_sections.py`

- [ ] **Step 1: Write failing section planner tests**

Add `backend/tests/unit/test_writer_structured_sections.py`:

```python
from packages.agents.writer.structured_report import (
    CompetitiveFindingsSection,
    CompetitorDeepDiveSection,
    DecisionMatrixSection,
    ExecutiveSummarySection,
    UserReviewThemesSection,
)
from packages.agents.writer.structured_sections import structured_section_requests


def test_section_requests_map_existing_segments_to_schema_classes() -> None:
    segments = [
        {"segment_name": "decision", "section_id": "decision_summary", "allowed_source_ids": ["raw-source-a"]},
        {"segment_name": "reviews", "section_id": "review_theme_summary", "allowed_source_ids": ["raw-source-b"]},
        {
            "segment_name": "Cursor deep dive",
            "section_id": "competitor_deep_dives",
            "segment_competitor": "Cursor",
            "allowed_source_ids": ["raw-source-c"],
        },
        {"segment_name": "matrix", "section_id": "swot_matrix", "allowed_source_ids": ["raw-source-d"]},
    ]
    requests = structured_section_requests(segments)

    schema_by_id = {request.section_id: request.schema_class for request in requests}
    assert schema_by_id["executive_summary"] is ExecutiveSummarySection
    assert schema_by_id["competitive_findings"] is CompetitiveFindingsSection
    assert schema_by_id["review_theme_summary"] is UserReviewThemesSection
    assert schema_by_id["competitor_deep_dives"] is CompetitorDeepDiveSection
    assert schema_by_id["decision_matrix"] is DecisionMatrixSection


def test_section_requests_preserve_allowed_source_ids_and_competitor() -> None:
    requests = structured_section_requests(
        [
            {
                "segment_name": "Cursor deep dive",
                "section_id": "competitor_deep_dives",
                "segment_competitor": "Cursor",
                "allowed_source_ids": ["raw-source-c", "raw-source-c"],
            }
        ]
    )

    assert requests[0].segment_competitor == "Cursor"
    assert requests[0].allowed_source_ids == {"raw-source-c"}
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_sections.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_sections'`.

- [ ] **Step 3: Implement planner**

Create `backend/packages/agents/writer/structured_sections.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from packages.agents.writer.structured_report import (
    BattlecardSection,
    ClaimRiskSection,
    CompetitiveFindingsSection,
    CompetitorDeepDiveSection,
    DecisionMatrixSection,
    DecisionSummarySection,
    ExecutiveSummarySection,
    NextCollectionSection,
    RagGapFillSection,
    ScenarioQaSection,
    SourceQualitySection,
    SwotSection,
    UserResearchEvidenceSection,
    UserReviewThemesSection,
)


@dataclass(frozen=True)
class StructuredSectionRequest:
    section_id: str
    schema_class: type[BaseModel]
    segment: dict[str, Any]
    segment_competitor: str | None
    allowed_source_ids: set[str]
    essential: bool = True


SECTION_EXPANSION: dict[str, tuple[tuple[str, type[BaseModel]], ...]] = {
    "decision_summary": (
        ("executive_summary", ExecutiveSummarySection),
        ("decision_summary", DecisionSummarySection),
        ("competitive_findings", CompetitiveFindingsSection),
    ),
    "competitive_findings": (("competitive_findings", CompetitiveFindingsSection),),
    "review_theme_summary": (("review_theme_summary", UserReviewThemesSection),),
    "competitor_deep_dives": (("competitor_deep_dives", CompetitorDeepDiveSection),),
    "swot_matrix": (
        ("decision_matrix", DecisionMatrixSection),
        ("swot", SwotSection),
        ("battlecard", BattlecardSection),
    ),
    "evidence_support": (
        ("source_quality", SourceQualitySection),
        ("user_research_evidence", UserResearchEvidenceSection),
        ("rag_gap_fill", RagGapFillSection),
        ("scenario_qa", ScenarioQaSection),
        ("claim_risk", ClaimRiskSection),
        ("next_collection", NextCollectionSection),
    ),
}


def structured_section_requests(
    segments: list[dict[str, object]],
) -> list[StructuredSectionRequest]:
    requests: list[StructuredSectionRequest] = []
    seen: set[tuple[str, str | None]] = set()
    for segment in segments:
        section_id = str(segment.get("section_id") or "")
        if section_id == "evidence_shard":
            continue
        expanded = SECTION_EXPANSION.get(section_id, ())
        segment_competitor = (
            str(segment.get("segment_competitor"))
            if isinstance(segment.get("segment_competitor"), str)
            else None
        )
        allowed_source_ids = {
            source_id
            for source_id in segment.get("allowed_source_ids", [])
            if isinstance(source_id, str)
        }
        for output_section_id, schema_class in expanded:
            dedupe_key = (
                output_section_id,
                segment_competitor if output_section_id == "competitor_deep_dives" else None,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            requests.append(
                StructuredSectionRequest(
                    section_id=output_section_id,
                    schema_class=schema_class,
                    segment=dict(segment),
                    segment_competitor=segment_competitor,
                    allowed_source_ids=allowed_source_ids,
                    essential=bool(segment.get("segment_essential", True)),
                )
            )
    return requests
```

- [ ] **Step 4: Run section planner tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_sections.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/structured_sections.py backend/tests/unit/test_writer_structured_sections.py
git commit -m "feat(writer): map evidence segments to structured sections"
```

### Task 6: JSON Section Generation Helpers

**Files:**
- Create: `backend/packages/agents/writer/structured_generation.py`
- Test: `backend/tests/unit/test_writer_structured_generation.py`

- [ ] **Step 1: Write failing generation tests**

Add `backend/tests/unit/test_writer_structured_generation.py`:

```python
import pytest

from packages.agents.writer.structured_generation import (
    StructuredSectionGenerationError,
    build_structured_section_prompt,
    parse_structured_section_payload,
)
from packages.agents.writer.structured_report import ExecutiveSummarySection


def test_parse_structured_section_payload_accepts_json_object() -> None:
    raw = """
{
  "recommendation": {"text": "Use a guarded shortlist.", "source_ids": ["raw-source-a"], "confidence": "high", "evidence_role": "official_fact"},
  "risk_adjusted_rationale": {"text": "Capability and evidence risk diverge.", "source_ids": ["raw-source-a"], "confidence": "high", "evidence_role": "official_fact"},
  "competitor_postures": [],
  "confidence_boundary": {"text": "Do not overstate weak sources.", "source_ids": ["raw-source-a"], "confidence": "medium", "evidence_role": "inference"},
  "next_actions": [{"text": "Collect buyer validation.", "source_ids": ["raw-source-a"], "confidence": "medium", "evidence_role": "inference"}]
}
"""
    payload = parse_structured_section_payload(raw, ExecutiveSummarySection)
    assert payload.recommendation.text == "Use a guarded shortlist."


def test_parse_structured_section_payload_rejects_markdown() -> None:
    with pytest.raises(StructuredSectionGenerationError, match="JSON object"):
        parse_structured_section_payload("## Executive Summary\n- Not JSON", ExecutiveSummarySection)


def test_prompt_contains_json_only_contract_and_allowed_sources() -> None:
    prompt = build_structured_section_prompt(
        topic="AI coding agent comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        section_id="executive_summary",
        schema_class=ExecutiveSummarySection,
        segment_payload={"groups": []},
        allowed_source_ids={"raw-source-a"},
        output_language="zh-CN",
    )
    assert "Return JSON only" in prompt
    assert "raw-source-a" in prompt
    assert "[source:" not in prompt.split("Schema JSON:", 1)[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_generation.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.structured_generation'`.

- [ ] **Step 3: Implement generation helpers**

Create `backend/packages/agents/writer/structured_generation.py`:

```python
from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

SectionT = TypeVar("SectionT", bound=BaseModel)


class StructuredSectionGenerationError(RuntimeError):
    pass


def parse_structured_section_payload(
    raw_text: str,
    schema_class: type[SectionT],
) -> SectionT:
    text = _strip_fenced_json(raw_text.strip())
    if not text.startswith("{"):
        raise StructuredSectionGenerationError("Structured writer output must be a JSON object.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StructuredSectionGenerationError(f"Invalid JSON: {exc.msg}") from exc
    try:
        return schema_class.model_validate(data)
    except ValidationError as exc:
        raise StructuredSectionGenerationError(str(exc)) from exc


def build_structured_section_prompt(
    *,
    topic: str,
    competitors: list[str],
    dimensions: list[str],
    section_id: str,
    schema_class: type[BaseModel],
    segment_payload: dict[str, object],
    allowed_source_ids: set[str],
    output_language: str,
) -> str:
    schema_json = json.dumps(schema_class.model_json_schema(), ensure_ascii=False)
    segment_json = json.dumps(segment_payload, ensure_ascii=False, default=str)
    return (
        "Return JSON only. Do not write Markdown headings. Do not put [source:...] "
        "tokens inside text fields. Put citations only in source_ids. Use only the "
        "allowed_source_ids listed below. Label evidence_role accurately as "
        "official_fact, community_signal, simulated_research, inference, or evidence_gap. "
        "If direct evidence is missing, write an evidence_gap item instead of inventing proof.\n\n"
        f"Output language: {output_language}\n"
        f"Topic: {topic}\n"
        f"Competitors: {', '.join(competitors)}\n"
        f"Dimensions: {', '.join(dimensions)}\n"
        f"Section ID: {section_id}\n"
        f"Allowed source IDs: {', '.join(sorted(allowed_source_ids))}\n\n"
        f"Schema JSON: {schema_json}\n\n"
        f"Evidence segment JSON: {segment_json}\n"
    )


def _strip_fenced_json(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text
```

- [ ] **Step 4: Run generation helper tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_generation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/structured_generation.py backend/tests/unit/test_writer_structured_generation.py
git commit -m "feat(writer): add structured section generation helpers"
```

### Task 7: Integrate Structured Writer Behind Feature Flag

**Files:**
- Modify: `backend/packages/config/settings.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing settings and orchestration tests**

Add these tests near the existing writer tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_writer_uses_structured_path_when_enabled(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://example.invalid",
            llm_timeout_seconds=5,
            llm_temperature=0,
            writer_structured_report_enabled=True,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Structured writer",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="zh-CN",
        )
    )
    record = service._runs[detail.id]
    record.detail.report_md = ""
    record.detail.raw_sources = _writer_repair_sources()

    async def fake_structured(record, *, evidence_pack_result, timeout_seconds):
        return "## 执行摘要\n- Structured report. [source:pricing-1]"

    monkeypatch.setattr(service, "_writer_structured_report_markdown", fake_structured)

    await service._real_writer_step(record)

    payload = record.detail.agent_messages[-1].payload
    assert payload["writer_mode"] == "real structured writer"
    assert "Structured report" in record.detail.report_md


@pytest.mark.asyncio
async def test_writer_structured_failure_falls_back_visibly(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://example.invalid",
            llm_timeout_seconds=5,
            llm_temperature=0,
            writer_structured_report_enabled=True,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Structured fallback",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="zh-CN",
        )
    )
    record = service._runs[detail.id]
    record.detail.report_md = ""
    record.detail.raw_sources = _writer_repair_sources()

    async def fake_structured(record, *, evidence_pack_result, timeout_seconds):
        raise RuntimeError("structured validation failed")

    async def fake_markdown(*args, **kwargs):
        return "## 执行摘要\n- Markdown fallback report. [source:pricing-1]"

    monkeypatch.setattr(service, "_writer_structured_report_markdown", fake_structured)
    monkeypatch.setattr(service, "_trace_llm_text", fake_markdown)

    await service._real_writer_step(record)

    assert any(event.type == "writer_markdown_fallback_used" for event in record.events)
    assert "Markdown fallback report" in record.detail.report_md
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py::test_writer_uses_structured_path_when_enabled backend/tests/unit/test_run_service.py::test_writer_structured_failure_falls_back_visibly -q
```

Expected: FAIL because `Settings` has no `writer_structured_report_enabled` field and `RunService` has no `_writer_structured_report_markdown`.

- [ ] **Step 3: Add settings flag**

Modify `backend/packages/config/settings.py` by adding this field directly after the existing `writer_timeout_seconds: float = 600.0` field:

```python
    writer_structured_report_enabled: bool = False
```

In `get_settings()`, immediately after the existing `writer_timeout_seconds=_env_float(...)` block, add:

```python
        writer_structured_report_enabled=_env_bool(
            "WRITER_STRUCTURED_REPORT_ENABLED",
            False,
        ),
```

- [ ] **Step 4: Add structured writer orchestration method**

Modify `backend/packages/agents/writer/logic.py` imports:

```python
from packages.agents.writer.publication_contract import validate_publication_contract
from packages.agents.writer.structured_generation import (
    build_structured_section_prompt,
    parse_structured_section_payload,
)
from packages.agents.writer.structured_renderer import render_structured_report
from packages.agents.writer.structured_report import (
    EvidenceAppendixSection,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    SourceAppendixItem,
    StructuredReport,
)
from packages.agents.writer.structured_sections import structured_section_requests
from packages.agents.writer.structured_validation import validate_structured_report
```

Add a method to `WriterAgentMixin`:

```python
    async def _writer_structured_report_markdown(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> str:
        detail = record.detail
        requests = structured_section_requests(evidence_pack_result.segment_inputs())
        await self.emit(
            detail.id,
            "writer_structured_report_started",
            "writer",
            None,
            "Structured writer started.",
            {"section_request_count": len(requests)},
        )

        payloads: dict[str, list[object]] = {}
        for request in requests:
            prompt = build_structured_section_prompt(
                topic=detail.topic,
                competitors=detail.plan.competitors,
                dimensions=detail.plan.dimensions,
                section_id=request.section_id,
                schema_class=request.schema_class,
                segment_payload=request.segment,
                allowed_source_ids=request.allowed_source_ids,
                output_language=detail.output_language,
            )
            raw_text = await asyncio.wait_for(
                self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=request.section_id,
                    name="structured_section_writer",
                    system=(
                        "You write one structured competitive-intelligence report section. "
                        "Return valid JSON only and obey the schema exactly."
                    ),
                    user=prompt,
                ),
                timeout=timeout_seconds,
            )
            payloads.setdefault(request.section_id, []).append(
                parse_structured_section_payload(
                    raw_text,
                    request.schema_class,
                )
            )
            await self.emit(
                detail.id,
                "writer_structured_section_generated",
                "writer",
                request.section_id,
                f"Structured section generated: {request.section_id}",
                {
                    "section_id": request.section_id,
                    "schema_name": request.schema_class.__name__,
                    "source_count": len(request.allowed_source_ids),
                    "validation_status": "parsed",
                },
            )

        def one(section_id: str) -> object:
            values = payloads.get(section_id, [])
            if not values:
                raise RuntimeError(f"structured section missing: {section_id}")
            return values[0]

        appendix_sources = [
            SourceAppendixItem(
                source_id=item.id,
                title=item.title,
                source_type=item.source_type,
                competitor=item.competitor,
                dimension=item.dimension,
                confidence=item.confidence,
            )
            for item in evidence_pack_result.pack.source_registry
        ]
        support = ReportSupport(
            source_quality=one("source_quality"),
            user_research_evidence=one("user_research_evidence"),
            rag_gap_fill=one("rag_gap_fill"),
            scenario_qa=one("scenario_qa"),
            claim_risk=one("claim_risk"),
            next_collection=one("next_collection"),
            evidence_appendix=EvidenceAppendixSection(sources=appendix_sources),
        )
        structured_report = StructuredReport(
            output_language=detail.output_language,
            topic=detail.topic,
            competitors=detail.plan.competitors,
            dimensions=detail.plan.dimensions,
            core=ReportCore(
                executive_summary=one("executive_summary"),
                decision_summary=one("decision_summary"),
                competitive_findings=one("competitive_findings"),
                user_review_themes=one("review_theme_summary"),
                competitor_deep_dives=list(payloads.get("competitor_deep_dives", [])),
                decision_matrix=one("decision_matrix"),
                swot=one("swot"),
                battlecard=one("battlecard"),
                community_triangulation=None,
            ),
            support=support,
            metadata=ReportMetadata(
                writer_mode="structured",
                segment_count=len(requests),
                source_count=len(evidence_pack_result.pack.source_registry),
                warnings=[],
                structured_report_version="structured_report.v1",
            ),
        )
        allowed_source_ids = {source.id for source in detail.raw_sources}
        validation = validate_structured_report(
            structured_report,
            allowed_source_ids=allowed_source_ids,
        )
        await self.emit(
            detail.id,
            "writer_structured_report_validated",
            "writer",
            None,
            "Structured report validated.",
            {
                "passed": validation.passed,
                "issue_count": len(validation.issues),
                "issue_codes": [issue.code for issue in validation.issues],
            },
        )
        if not validation.passed:
            raise RuntimeError(
                "structured report validation failed: "
                + ", ".join(issue.code for issue in validation.issues)
            )
        markdown = render_structured_report(structured_report)
        contract = validate_publication_contract(
            markdown,
            structured_report=structured_report,
            output_language=detail.output_language,
            allowed_source_ids=allowed_source_ids,
        )
        await self.emit(
            detail.id,
            "writer_publication_contract_validated",
            "writer",
            None,
            "Structured report publication contract validated.",
            {
                "passed": contract.passed,
                "issue_count": len(contract.issues),
                "issue_codes": [issue.code for issue in contract.issues],
            },
        )
        if not contract.passed:
            raise RuntimeError(
                "publication contract failed: "
                + ", ".join(issue.code for issue in contract.issues)
            )
        return markdown
```

- [ ] **Step 5: Route `_real_writer_step` through structured path**

Inside the existing non-repair writer path after `evidence_pack_result` passes preflight, add:

```python
                if self._settings.writer_structured_report_enabled:
                    try:
                        report_md = await self._writer_structured_report_markdown(
                            record,
                            evidence_pack_result=evidence_pack_result,
                            timeout_seconds=timeout_seconds,
                        )
                        writer_mode = "real structured writer"
                    except Exception as exc:
                        await self.emit(
                            detail.id,
                            "writer_markdown_fallback_used",
                            "writer",
                            None,
                            "Structured writer failed; using Markdown fallback.",
                            {"error": str(exc)},
                        )
                        report_md = await self._writer_markdown_report_path(
                            record,
                            evidence_pack_result=evidence_pack_result,
                            timeout_seconds=timeout_seconds,
                            language_guidance=language_guidance,
                            memory_context=memory_context,
                            layer_context=layer_context,
                            required_sections=required_sections,
                            grounding_prompt=grounding_prompt,
                            user_research_policy=user_research_policy,
                        )
                        writer_mode = "real markdown fallback after structured writer error"
```

Extract the existing Markdown generation block into `_writer_markdown_report_path(...)` in the same file so the structured failure path does not duplicate the 16,000-20,000 character prompt.

- [ ] **Step 6: Run targeted integration tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py::test_writer_uses_structured_path_when_enabled backend/tests/unit/test_run_service.py::test_writer_structured_failure_falls_back_visibly -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/packages/config/settings.py backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat(writer): route structured writer behind flag"
```

### Task 8: Repair Routing And Quality Gate Integration

**Files:**
- Modify: `backend/packages/agents/writer/repair.py`
- Modify: `backend/packages/business_intel/report_quality.py`
- Modify: `backend/packages/business_intel/release_gate.py`
- Test: `backend/tests/unit/test_writer_repair.py`
- Test: `backend/tests/unit/test_report_quality.py`

- [ ] **Step 1: Write failing repair routing tests**

Add to `backend/tests/unit/test_writer_repair.py`:

```python
def test_writer_repair_routes_publication_contract_battlecard_to_battlecard_section() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue(
        id="publication-contract-battlecard",
        severity="warn",
        detected_by="coverage",
        target_agent="writer",
        target_subagent=None,
        target_competitor=None,
        field_path="publication_contract.battlecard_template_only",
        problem="Battlecard is template-only.",
        redo_scope=RedoScope(kind="writer_only", rationale="Rewrite battlecard only."),
    )

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=False)

    assert plan.mode == "section"
    assert plan.sections == ["battlecard"]


def test_writer_repair_routes_publication_contract_heading_to_assemble() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue(
        id="publication-contract-heading",
        severity="warn",
        detected_by="coverage",
        target_agent="writer",
        target_subagent=None,
        target_competitor=None,
        field_path="publication_contract.english_structural_heading_in_zh",
        problem="Chinese report contains English template heading.",
        redo_scope=RedoScope(kind="writer_only", rationale="Renderer repair."),
    )

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=False)

    assert plan.mode == "assemble"
```

- [ ] **Step 2: Write failing report quality tests**

Add to `backend/tests/unit/test_report_quality.py`:

```python
def test_report_quality_uses_publication_contract_hygiene_signal() -> None:
    detail = _run_detail(
        run_id="publication-contract-quality",
        execution_mode="real",
        source_count=4,
        report_md="## 执行摘要\n- See Segment Evidence Pack JSON. [source:source-0]",
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[_llm_trace_span()],
    )
    detail.output_language = "zh-CN"

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["publication_contract_score"].target_value == 0.0
    assert comparison.report_quality_signal is False
```

- [ ] **Step 3: Run tests to verify they fail**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_repair.py::test_writer_repair_routes_publication_contract_battlecard_to_battlecard_section backend/tests/unit/test_writer_repair.py::test_writer_repair_routes_publication_contract_heading_to_assemble backend/tests/unit/test_report_quality.py::test_report_quality_uses_publication_contract_hygiene_signal -q
```

Expected: FAIL because repair routing and `publication_contract_score` are not connected.

- [ ] **Step 4: Add repair routing**

In `backend/packages/agents/writer/repair.py`, extend `SECTION_REPAIR_HINTS`:

```python
    "battlecard": (
        "battlecard",
        "response guidance",
        "sales response",
        "objection",
        "publication_contract.battlecard_template_only",
    ),
    "decision_summary": (
        "decision summary",
        "recommended action",
        "decision posture",
        "immediate next move",
        "publication_contract.executive_summary_template_only",
    ),
```

In `build_writer_repair_plan()`, add this deterministic publication-contract branch after the `upstream_data_changed` branch and before the `_has_release_gate_report_depth_issue(...)` branch:

```python
    if _has_publication_contract_deterministic_issue(issues):
        return WriterRepairPlan(
            mode="assemble",
            reason="publication contract failure is deterministic renderer or section-order damage",
            previous_report_protectable=True,
            anti_regression_required=False,
        )
```

Add this helper near `_has_release_gate_report_depth_issue(...)`:

```python
def _has_publication_contract_deterministic_issue(issues: list[QCIssue]) -> bool:
    deterministic_paths = {
        "publication_contract.english_structural_heading_in_zh",
        "publication_contract.citation_in_heading",
        "publication_contract.citation_in_table_header",
        "publication_contract.internal_term_leak",
    }
    return any(issue.field_path in deterministic_paths for issue in issues)
```

- [ ] **Step 5: Add publication contract metric**

In `backend/packages/business_intel/report_quality.py`, import:

```python
from packages.agents.writer.publication_contract import validate_publication_contract
```

In `_snapshot()`, add:

```python
        "publication_contract_score": _publication_contract_score(detail),
```

In normalized values, add:

```python
        "publication_contract_score": values["publication_contract_score"],
```

In `_metric_specs()`, add zero-weight hard gate metric:

```python
        ("publication_contract_score", 0.0, "higher_is_better"),
```

In `_signal_checks()`, add `"publication_contract_score"` to the hard report blockers list with minimum `1.0`.

Add helper:

```python
def _publication_contract_score(detail: RunDetail) -> float:
    allowed_source_ids = {source.id for source in detail.raw_sources}
    result = validate_publication_contract(
        detail.report_md,
        structured_report=None,
        output_language=detail.output_language,
        allowed_source_ids=allowed_source_ids,
    )
    return 1.0 if result.passed else 0.0
```

In `backend/packages/business_intel/release_gate.py`, add:

```python
    "publication_contract_score": 1.0,
```

to `REPORT_RICHNESS_MINIMUMS`.

- [ ] **Step 6: Run targeted tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_repair.py::test_writer_repair_routes_publication_contract_battlecard_to_battlecard_section backend/tests/unit/test_writer_repair.py::test_writer_repair_routes_publication_contract_heading_to_assemble backend/tests/unit/test_report_quality.py::test_report_quality_uses_publication_contract_hygiene_signal -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/packages/agents/writer/repair.py backend/packages/business_intel/report_quality.py backend/packages/business_intel/release_gate.py backend/tests/unit/test_writer_repair.py backend/tests/unit/test_report_quality.py
git commit -m "feat(writer): gate publication contract quality"
```

### Task 9: End-To-End Structured Writer Verification

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- No production file changes unless tests expose a concrete bug in Tasks 1-8.

- [ ] **Step 1: Add an end-to-end structured writer test with fake LLM JSON**

Add to `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_structured_writer_fake_llm_renders_publishable_markdown(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://example.invalid",
            llm_timeout_seconds=5,
            llm_temperature=0,
            writer_timeout_seconds=5,
            writer_structured_report_enabled=True,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Structured fake LLM",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="zh-CN",
        )
    )
    record = service._runs[detail.id]
    record.detail.report_md = ""
    record.detail.raw_sources = _writer_repair_sources()

    def cited(text: str) -> dict[str, object]:
        return {
            "text": text,
            "source_ids": ["pricing-1"],
            "confidence": "high",
            "evidence_role": "official_fact",
        }

    responses = {
        "executive_summary": {
            "recommendation": cited("Use a guarded shortlist with Cursor as the proof-led challenger."),
            "risk_adjusted_rationale": cited("The recommendation separates capability signals from evidence risk."),
            "competitor_postures": [],
            "confidence_boundary": cited("Do not overstate claims without direct procurement proof."),
            "next_actions": [cited("Run a buyer validation call before external use.")],
        },
        "decision_summary": {
            "buying_posture": cited("Adopt a guarded shortlist."),
            "shortlist_rationale": [cited("Evidence supports a comparison, not a universal winner.")],
            "risk_boundary": cited("Weak persona claims stay qualified."),
            "immediate_actions": [cited("Collect buyer validation.")],
        },
        "competitive_findings": {
            "pricing_packaging": [cited("Pricing evidence is available.")],
            "feature_workflow": [cited("Feature evidence is available.")],
            "user_persona_adoption": [cited("Persona evidence is directional.")],
            "cross_competitor_risks": [cited("Evidence quality varies across dimensions.")],
        },
        "review_theme_summary": {
            "competitor_themes": [
                {
                    "competitor": "Cursor",
                    "direct_user_signals": [cited("Direct signal is limited.")],
                    "simulated_research_signals": [cited("Simulated interview suggests fast adoption.")],
                    "adoption_blockers": [cited("Security review can block adoption.")],
                    "switching_triggers": [cited("Team workflow fit can trigger switching.")],
                    "evidence_gaps": [],
                },
                {
                    "competitor": "GitHub Copilot",
                    "direct_user_signals": [cited("Direct signal is limited.")],
                    "simulated_research_signals": [cited("Simulated interview suggests procurement comfort.")],
                    "adoption_blockers": [cited("Bundle assumptions can hide cost.")],
                    "switching_triggers": [cited("Microsoft stack fit can trigger adoption.")],
                    "evidence_gaps": [],
                },
            ],
            "cross_competitor_patterns": [cited("Both competitors need direct buyer validation.")],
            "evidence_limits": [cited("User evidence remains directional.")],
        },
        "decision_matrix": {
            "dimensions": [
                {
                    "dimension": "pricing",
                    "cells": [
                        {"competitor": "Cursor", "summary": "Pricing signal", "source_ids": ["pricing-1"], "confidence": "high"},
                        {"competitor": "GitHub Copilot", "summary": "Procurement signal", "source_ids": ["pricing-1"], "confidence": "medium"},
                    ],
                }
            ],
            "interpretation": [cited("Matrix leadership differs from final recommendation.")],
            "confidence_notes": [cited("Matrix cells need validation.")],
        },
        "swot": {
            "competitors": [
                {
                    "competitor": "Cursor",
                    "strengths": [cited("Cursor strength.")],
                    "weaknesses": [cited("Cursor weakness.")],
                    "opportunities": [cited("Cursor opportunity.")],
                    "threats": [cited("Cursor threat.")],
                },
                {
                    "competitor": "GitHub Copilot",
                    "strengths": [cited("Copilot strength.")],
                    "weaknesses": [cited("Copilot weakness.")],
                    "opportunities": [cited("Copilot opportunity.")],
                    "threats": [cited("Copilot threat.")],
                },
            ]
        },
        "battlecard": {
            "plays": [
                {
                    "competitor": "Cursor",
                    "target_buyer": "Engineering leader",
                    "use_when": cited("Use when workflow-speed proof is central."),
                    "attack_points": [cited("Ask for evidence of procurement readiness.")],
                    "defense_points": [cited("Defend with POC validation.")],
                    "likely_objections": [cited("Security evidence may be requested.")],
                    "rebuttal_talk_tracks": [cited("Turn security into a validation task.")],
                    "proof_needed_before_external_use": [cited("Collect direct customer quote.")],
                },
                {
                    "competitor": "GitHub Copilot",
                    "target_buyer": "Platform leader",
                    "use_when": cited("Use when Microsoft-stack fit dominates."),
                    "attack_points": [cited("Ask whether bundle fit hides workflow gaps.")],
                    "defense_points": [cited("Acknowledge procurement familiarity.")],
                    "likely_objections": [cited("Buyer may prefer bundled defaults.")],
                    "rebuttal_talk_tracks": [cited("Separate bundle convenience from workflow value.")],
                    "proof_needed_before_external_use": [cited("Collect direct switching proof.")],
                },
            ],
            "evidence_limits": [cited("Battlecard claims remain bounded.")],
        },
        "source_quality": {"summary": [cited("Sources are sufficient for a bounded report.")]},
        "user_research_evidence": {"summary": [cited("User research is directional.")]},
        "rag_gap_fill": {"retrieval_queries": [cited("Collect direct buyer reviews.")]},
        "scenario_qa": {"checks": [cited("Scenario checks are bounded.")]},
        "claim_risk": {"risks": [cited("Claims need evidence limits.")]},
        "next_collection": {"tasks": [cited("Collect procurement proof.")]},
    }
    deep_dive_responses = iter(
        [
            {
                "competitor": "Cursor",
                "positioning": [cited("Cursor positions around coding workflow speed.")],
                "pricing_packaging": [cited("Cursor pricing should be validated.")],
                "feature_capabilities": [cited("Cursor feature claims need workflow proof.")],
                "persona_adoption": [cited("Cursor persona fit is engineering-led.")],
                "community_feedback": [cited("Community evidence is directional.")],
                "competitive_plays": [cited("Use Cursor when buyer wants workflow speed.")],
                "evidence_gaps": [],
            },
            {
                "competitor": "GitHub Copilot",
                "positioning": [cited("Copilot positions around Microsoft workflow continuity.")],
                "pricing_packaging": [cited("Copilot pricing should be validated.")],
                "feature_capabilities": [cited("Copilot feature claims need workflow proof.")],
                "persona_adoption": [cited("Copilot persona fit is platform-led.")],
                "community_feedback": [cited("Community evidence is directional.")],
                "competitive_plays": [cited("Use Copilot when buyer wants Microsoft-stack continuity.")],
                "evidence_gaps": [],
            },
        ]
    )

    async def fake_llm(record, *, agent, subagent, name, system, user):
        if subagent == "competitor_deep_dives":
            return json.dumps(next(deep_dive_responses), ensure_ascii=False)
        return json.dumps(responses[subagent], ensure_ascii=False)

    monkeypatch.setattr(service, "_trace_llm_text", fake_llm)

    await service._real_writer_step(record)

    assert record.detail.agent_messages[-1].payload["writer_mode"] == "real structured writer"
    assert "### Pricing and Packaging" not in record.detail.report_md
    assert "## 证据附录" in record.detail.report_md
    assert "Segment Evidence Pack" not in record.detail.report_md
```

- [ ] **Step 2: Run the end-to-end test**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py::test_structured_writer_fake_llm_renders_publishable_markdown -q
```

Expected: PASS after fixing concrete bugs exposed by the test.

- [ ] **Step 3: Run focused writer suite**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_sections.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_repair.py -q
```

Expected: PASS.

- [ ] **Step 4: Run focused run-service writer tests**

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py -q -k "writer"
```

Expected: PASS, except pre-existing unrelated failures must be recorded with exact test names and current failure messages.

- [ ] **Step 5: Run ruff**

```powershell
conda run -n bd-competiscope-v2 python -m ruff check backend/packages/agents/writer backend/packages/business_intel/report_quality.py backend/packages/business_intel/release_gate.py backend/packages/config/settings.py backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_sections.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_repair.py backend/tests/unit/test_run_service.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/tests/unit/test_run_service.py
git commit -m "test(writer): cover structured writer end to end"
```

## Self-Review

**Spec coverage:** The plan implements schema models, deterministic renderer, structured validation, publication contract, JSON section generation, feature-flagged integration, structured-aware repair, telemetry events, Markdown fallback, and no database migration. It keeps existing `report_md` as canonical output and does not change frontend behavior.

**Placeholder scan:** The plan avoids undefined "TBD" work. Each task names exact files, exact tests, exact commands, expected failures, expected passes, and concrete implementation snippets.

**Type consistency:** The plan uses `StructuredReport`, `ReportCore`, `ReportSupport`, `CitedText`, `BattlecardPlay`, `PublicationContractResult`, and `StructuredSectionRequest` consistently across model, renderer, validator, generation, repair, and run-service tasks.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-19-schema-first-writer.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
