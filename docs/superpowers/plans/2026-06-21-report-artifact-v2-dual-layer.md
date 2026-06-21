# Hybrid Report Artifact v2 Implementation Plan

> Superseded by
> [Card-Native Report Artifact v2 Design](../specs/2026-06-21-card-native-report-artifact-v2-design.md).
> Kept for history only. Do not implement this plan as the active plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the hybrid Report Artifact v2 pipeline: evidence becomes claim cards, claim cards become decision cards, cards become section briefs, the natural writer writes from briefs, and the final artifact stores core/support/audit layers separately instead of one overloaded `report_md` string.

**Architecture:** Claim cards and decision cards are the reasoning boundary. Section briefs are the writer contract. The current schema-contract segmented writer may remain as a transition authoring mechanism, but it consumes briefs and cannot invent facts or recommendations. `ReportArtifactV2` is the product/publication boundary: it persists cards, briefs, core report, support appendix, audit log, quality account, and render caches. Existing Markdown hardening and section repair remain only for legacy runs or legacy exports.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, in-memory enterprise store, Postgres SQL schema file, React 18, TypeScript, Vitest, pytest.

---

## File Structure

Create or modify these files only for this feature:

- Create: `backend/packages/schema/report_artifact.py`
  - Owns `ReportArtifactV2`, layer models, render cache, quality account, card references, and legacy adapter helpers.
- Create: `backend/packages/schema/report_cards.py`
  - Owns `ClaimCard`, `DecisionCard`, and `SectionBrief` contracts.
- Create: `backend/packages/business_intel/report_card_builder.py`
  - Builds initial claim cards and decision cards from existing evidence, competitor knowledge, and comparison matrix.
- Create: `backend/packages/business_intel/section_brief_builder.py`
  - Builds writer-facing section briefs from claim and decision cards.
- Modify: `backend/packages/schema/__init__.py`
  - Exports the new artifact models.
- Modify: `backend/packages/schema/api_dto.py`
  - Adds `RunDetail.report_artifact`.
- Modify: `backend/packages/schema/enterprise.py`
  - Adds dual-layer report fields to `ReportVersionRecord` and optional scoped manual revision payloads.
- Modify: `backend/packages/agents/writer/structured_renderer.py`
  - Adds split render helpers: core, support, audit, full.
- Create: `backend/packages/agents/writer/artifact_builder.py`
  - Converts cards, briefs, and authoring output into `ReportArtifactV2`; schema-contract Markdown parsing is a migration adapter, not the fact source.
- Modify: `backend/packages/agents/writer/logic.py`
  - Builds cards/briefs before writing, stores `detail.report_artifact`, derives `detail.report_md`, and avoids V2 main-path Markdown publication repair.
- Modify: `backend/packages/enterprise/projection.py`
  - Projects V2 artifact fields into `ReportVersionRecord`.
- Modify: `backend/packages/enterprise/store.py`
  - Keeps in-memory report versions normalized across legacy and V2 fields.
- Modify: `backend/packages/enterprise/postgres.py`
  - Reads and writes new report version columns.
- Modify: `backend/db/postgres/001_enterprise_core.sql`
  - Adds nullable V2 columns and idempotent `ALTER TABLE` migration lines.
- Modify: `backend/packages/business_intel/release_gate.py`
  - Evaluates report structure, depth, richness, citation policy, and strong-conclusion rules against core report text for V2 versions.
- Modify: `backend/packages/orchestrator/service.py`
  - Uses a single final quality account, writes it back to the artifact, and avoids release-gate Markdown warning repair for V2 reports.
- Modify: `backend/packages/orchestrator/audit.py`
  - Keeps revision counts sourced from final quality result for V2.
- Modify: `backend/app/routers/enterprise.py`
  - Adds export `scope` and uses V2 fields for export bodies.
- Modify: `frontend/src/api/types.ts`
  - Adds `ReportArtifactV2` types and dual-layer report version fields.
- Modify: `frontend/src/api/sse_types.ts`
  - Allows report events to carry `report_artifact`.
- Modify: `frontend/src/stores/run.ts`
  - Applies `report_artifact` updates from SSE.
- Modify: `frontend/src/api/client.ts`
  - Adds report export scope parameter.
- Modify: `frontend/src/features/run-detail/RunReportReviewStudio.tsx`
  - Adds Report, Evidence, QA, and Audit tabs, preferring artifact fields.
- Modify: `frontend/src/features/run-detail/ReportReaderWorkspace.tsx`
  - Renders selected artifact layer Markdown.
- Modify: `frontend/src/features/run-detail/ReportOutline.tsx`
  - Builds outline for the active layer only.
- Add or modify focused tests in:
  - `backend/tests/unit/test_report_artifact_v2.py`
  - `backend/tests/unit/test_report_cards.py`
  - `backend/tests/unit/test_writer_report_artifact_v2.py`
  - `backend/tests/unit/test_enterprise_projection.py`
  - `backend/tests/unit/test_enterprise_store.py`
  - `backend/tests/unit/test_enterprise_postgres_config.py`
  - `backend/tests/unit/test_business_intel.py`
  - `backend/tests/unit/test_run_service.py`
  - `frontend/src/features/run-detail/RunReportReviewStudio.test.tsx`

## Cleanup Decisions Locked In

These current mechanisms must not be used as V2 main-path correctness:

- `writer/publication_contract.py`: legacy Markdown export validation only.
- `writer/repair.py::replace_markdown_section()`: legacy Markdown repair only.
- `writer/repair.py::_restore_canonical_section_order()`: legacy Markdown repair only.
- `writer/quality_preflight.py`: legacy Markdown preflight only.
- `logic.py::_ensure_report_required_sections()`: not called for V2 artifacts.
- `logic.py::_backfill_*_section()`: not called for V2 artifacts.
- `logic.py::_ensure_report_claim_citations()`: not called for V2 artifacts.
- `logic.py::_repair_report_source_token()`: not called for V2 artifacts.
- `logic.py::_harden_schema_contract_report_markdown()`: legacy export hardening only.
- `logic.py::_repair_schema_contract_publication_issues()`: not called for V2 artifacts.
- `apply_release_gate_warning_report_repair()`: not allowed to mutate V2 rendered Markdown. It may only produce audit follow-up metadata for V2.

## Task 0: Claim Cards, Decision Cards, And Section Brief Contracts

**Files:**
- Create: `backend/packages/schema/report_cards.py`
- Create: `backend/packages/business_intel/report_card_builder.py`
- Create: `backend/packages/business_intel/section_brief_builder.py`
- Modify: `backend/packages/schema/__init__.py`
- Test: `backend/tests/unit/test_report_cards.py`

- [ ] **Step 1: Write failing card contract tests**

Create `backend/tests/unit/test_report_cards.py`:

```python
from __future__ import annotations

import pytest

from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan
from packages.schema.report_cards import ClaimCard, DecisionCard


def _detail() -> RunDetail:
    return RunDetail(
        id="run-cards",
        idempotency_key="run-cards",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="AI coding tools",
        status="completed",
        execution_mode="real",
        output_language="en-US",
        created_at="2026-06-21T00:00:00",
        updated_at="2026-06-21T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding tools",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing", "feature", "persona"],
        ),
    )


def test_claim_card_requires_source_ids_unless_gap() -> None:
    with pytest.raises(ValueError, match="source_ids"):
        ClaimCard(
            id="claim-1",
            competitor="Cursor",
            dimension="pricing",
            claim="Cursor publishes paid pricing.",
            confidence=0.82,
            evidence_role="official_fact",
            evidence_strength="medium",
        )

    gap = ClaimCard(
        id="claim-gap",
        competitor="Cursor",
        dimension="persona",
        claim="Direct buyer interviews are missing.",
        confidence=0.4,
        evidence_role="evidence_gap",
        evidence_strength="gap",
    )
    assert gap.source_ids == []


def test_decision_card_references_claim_cards() -> None:
    card = DecisionCard(
        id="decision-primary",
        decision_type="primary_recommendation",
        recommendation="Use Cursor as the primary trial candidate.",
        recommendation_strength="tentative",
        winner="Cursor",
        alternatives=["GitHub Copilot"],
        why_not={"GitHub Copilot": "Feature evidence is weaker for the target workflow."},
        rationale="Cursor has stronger workflow evidence, but buyer evidence remains incomplete.",
        claim_card_ids=["claim-cursor-feature"],
        confidence=0.72,
        risk_notes=["Validate enterprise controls before procurement."],
    )

    assert card.claim_card_ids == ["claim-cursor-feature"]
    assert card.recommendation_strength == "tentative"


def test_builders_create_cards_and_section_briefs_from_current_run_shape() -> None:
    detail = _detail()

    claim_cards = build_claim_cards_from_run_detail(detail)
    decision_cards = build_decision_cards_from_claim_cards(detail, claim_cards)
    briefs = build_section_briefs(detail, claim_cards, decision_cards)

    assert claim_cards
    assert decision_cards
    assert briefs
    assert {brief.section_key for brief in briefs} >= {
        "executive_summary",
        "decision_summary",
        "competitor_deep_dives",
    }
    assert briefs[0].required_claim_card_ids or briefs[0].required_decision_card_ids
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_cards.py -q
```

Expected:

```text
ImportError: cannot import name 'ClaimCard'
```

- [ ] **Step 3: Add card schema models**

Create `backend/packages/schema/report_cards.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EvidenceRole = Literal[
    "official_fact",
    "community_signal",
    "simulated_research",
    "inference",
    "evidence_gap",
]
EvidenceStrength = Literal["strong", "medium", "weak", "gap"]
RecommendationStrength = Literal["strong", "tentative", "watchlist", "insufficient_evidence"]


class ClaimCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    competitor: str = ""
    dimension: str = ""
    claim: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_role: EvidenceRole
    evidence_strength: EvidenceStrength
    conflict_notes: list[str] = Field(default_factory=list)
    applicability_scope: str = ""
    caveats: list[str] = Field(default_factory=list)
    produced_by: str = "analyst"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("source_ids")
    @classmethod
    def _clean_source_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("source_ids must not contain duplicates")
        return cleaned

    @model_validator(mode="after")
    def _source_ids_required_except_gap(self) -> "ClaimCard":
        if self.evidence_role != "evidence_gap" and not self.source_ids:
            raise ValueError("source_ids are required unless evidence_role is evidence_gap")
        if self.evidence_role == "evidence_gap" and self.evidence_strength != "gap":
            raise ValueError("evidence_gap claim cards must use evidence_strength='gap'")
        return self


class DecisionCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    decision_type: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    recommendation_strength: RecommendationStrength
    winner: str = ""
    alternatives: list[str] = Field(default_factory=list)
    why_not: dict[str, str] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    claim_card_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_notes: list[str] = Field(default_factory=list)
    produced_by: str = "comparator"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SectionBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str = Field(min_length=1)
    required_claim_card_ids: list[str] = Field(default_factory=list)
    required_decision_card_ids: list[str] = Field(default_factory=list)
    questions: list[str] = Field(min_length=1)
    forbidden_overclaims: list[str] = Field(default_factory=list)
    required_caveats: list[str] = Field(default_factory=list)
    citation_requirements: list[str] = Field(default_factory=list)
    output_language: str = "en-US"
    tone: str = "professional competitive intelligence"

    @model_validator(mode="after")
    def _requires_some_card(self) -> "SectionBrief":
        if not self.required_claim_card_ids and not self.required_decision_card_ids:
            raise ValueError("section brief must reference at least one claim or decision card")
        return self
```

- [ ] **Step 4: Add deterministic first-pass card builders**

Create `backend/packages/business_intel/report_card_builder.py`:

```python
from __future__ import annotations

from packages.identity import stable_prefixed_id
from packages.schema.api_dto import RunDetail
from packages.schema.report_cards import ClaimCard, DecisionCard


def build_claim_cards_from_run_detail(detail: RunDetail) -> list[ClaimCard]:
    cards: list[ClaimCard] = []
    for competitor in detail.plan.competitors:
        for dimension in detail.plan.dimensions:
            source_ids = [
                source.id
                for source in detail.raw_sources
                if source.competitor == competitor and source.dimension == dimension
            ]
            if source_ids:
                cards.append(
                    ClaimCard(
                        id=_card_id("claim", detail.id, competitor, dimension, "evidence"),
                        competitor=competitor,
                        dimension=dimension,
                        claim=f"{competitor} has collected {dimension} evidence available for report analysis.",
                        source_ids=source_ids[:8],
                        confidence=0.72,
                        evidence_role="inference",
                        evidence_strength="medium",
                        applicability_scope=f"{dimension} comparison for {detail.topic}",
                        produced_by="analyst",
                    )
                )
            else:
                cards.append(
                    ClaimCard(
                        id=_card_id("claim", detail.id, competitor, dimension, "gap"),
                        competitor=competitor,
                        dimension=dimension,
                        claim=f"{competitor} lacks collected {dimension} evidence for a strong conclusion.",
                        confidence=0.35,
                        evidence_role="evidence_gap",
                        evidence_strength="gap",
                        caveats=["Treat related conclusions as tentative until evidence is collected."],
                        applicability_scope=f"{dimension} comparison for {detail.topic}",
                        produced_by="analyst",
                    )
                )
    return cards


def build_decision_cards_from_claim_cards(
    detail: RunDetail,
    claim_cards: list[ClaimCard],
) -> list[DecisionCard]:
    supported = [card for card in claim_cards if card.source_ids]
    winner = supported[0].competitor if supported else (detail.plan.competitors[0] if detail.plan.competitors else "")
    alternatives = [item for item in detail.plan.competitors if item != winner]
    strength = "tentative" if supported else "insufficient_evidence"
    rationale = (
        f"{winner} has the earliest available supported claim cards, but the recommendation remains evidence-weighted."
        if supported
        else "No supported claim cards are available, so no strong recommendation is allowed."
    )
    return [
        DecisionCard(
            id=_card_id("decision", detail.id, "primary", winner or "none"),
            decision_type="primary_recommendation",
            recommendation=(
                f"Prioritize {winner} for the current evaluation."
                if winner
                else "Do not issue a primary recommendation."
            ),
            recommendation_strength=strength,
            winner=winner,
            alternatives=alternatives,
            why_not={name: "Lower or less direct card support in the current run." for name in alternatives},
            rationale=rationale,
            claim_card_ids=[card.id for card in supported[:12]] or [claim_cards[0].id],
            confidence=0.68 if supported else 0.3,
            risk_notes=["Recommendation strength must be downgraded if card support is weak or conflicted."],
            produced_by="comparator",
        )
    ] if claim_cards else []


def _card_id(prefix: str, *parts: str) -> str:
    return stable_prefixed_id(prefix, "|".join(parts), length=16)
```

- [ ] **Step 5: Add section brief builder**

Create `backend/packages/business_intel/section_brief_builder.py`:

```python
from __future__ import annotations

from packages.schema.api_dto import RunDetail
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief


def build_section_briefs(
    detail: RunDetail,
    claim_cards: list[ClaimCard],
    decision_cards: list[DecisionCard],
) -> list[SectionBrief]:
    claim_ids = [card.id for card in claim_cards]
    decision_ids = [card.id for card in decision_cards]
    return [
        SectionBrief(
            section_key="executive_summary",
            required_claim_card_ids=claim_ids[:6],
            required_decision_card_ids=decision_ids,
            questions=[
                "What should the reader do next?",
                "How strong is the recommendation?",
                "Which evidence gaps limit the decision?",
            ],
            forbidden_overclaims=["Do not upgrade tentative recommendations to strong recommendations."],
            required_caveats=["State evidence limits when confidence is below 0.8."],
            citation_requirements=["Every material claim must cite the underlying claim card sources."],
            output_language=detail.output_language,
        ),
        SectionBrief(
            section_key="decision_summary",
            required_claim_card_ids=claim_ids,
            required_decision_card_ids=decision_ids,
            questions=["Why this recommendation, and why not the alternatives?"],
            forbidden_overclaims=["Do not invent a winner outside decision cards."],
            required_caveats=["Mention conflicts and weak evidence."],
            citation_requirements=["Tie recommendation prose to decision card claim_card_ids."],
            output_language=detail.output_language,
        ),
        SectionBrief(
            section_key="competitor_deep_dives",
            required_claim_card_ids=claim_ids,
            required_decision_card_ids=[],
            questions=["What does each competitor prove, imply, and still lack?"],
            forbidden_overclaims=["Do not convert evidence gaps into product weaknesses."],
            required_caveats=["Separate direct evidence from inference."],
            citation_requirements=["Each competitor subsection must cite its claim cards."],
            output_language=detail.output_language,
        ),
    ]
```

- [ ] **Step 6: Export card models**

Modify `backend/packages/schema/__init__.py`:

```python
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief
```

Add `ClaimCard`, `DecisionCard`, and `SectionBrief` to `__all__`.

- [ ] **Step 7: Run card tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_cards.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 8: Commit Task 0**

Run:

```bash
git add backend/packages/schema/report_cards.py backend/packages/business_intel/report_card_builder.py backend/packages/business_intel/section_brief_builder.py backend/packages/schema/__init__.py backend/tests/unit/test_report_cards.py
git commit -m "feat: add report claim and decision cards"
```

## Task 1: Artifact Schema, Split Renderer, And Legacy Adapter

**Files:**
- Create: `backend/packages/schema/report_artifact.py`
- Modify: `backend/packages/schema/__init__.py`
- Modify: `backend/packages/agents/writer/structured_renderer.py`
- Test: `backend/tests/unit/test_report_artifact_v2.py`

- [ ] **Step 1: Write failing artifact model and renderer tests**

Add `backend/tests/unit/test_report_artifact_v2.py`:

```python
from __future__ import annotations

from packages.agents.writer.structured_renderer import (
    render_structured_report_core,
    render_structured_report_full,
    render_structured_report_support,
)
from packages.schema.report_artifact import (
    ReportArtifactV2,
    ReportLayer,
    build_legacy_report_artifact,
)
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief
from test_writer_structured_renderer import _report


def test_structured_renderer_splits_core_and_support_layers() -> None:
    report = _report("en-US")

    core = render_structured_report_core(report)
    support = render_structured_report_support(report)
    full = render_structured_report_full(report)

    assert "## Executive Summary" in core
    assert "## Evidence Appendix" not in core
    assert "## Evidence Appendix" in support
    assert core in full
    assert support in full


def test_report_artifact_v2_derives_compatibility_markdown() -> None:
    claim = ClaimCard(
        id="claim-cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        claim="Cursor has pricing evidence.",
        source_ids=["raw-1"],
        confidence=0.82,
        evidence_role="official_fact",
        evidence_strength="medium",
    )
    decision = DecisionCard(
        id="decision-primary",
        decision_type="primary_recommendation",
        recommendation="Use Cursor as the primary trial candidate.",
        recommendation_strength="tentative",
        winner="Cursor",
        alternatives=[],
        why_not={},
        rationale="Cursor has the strongest available claim card support.",
        claim_card_ids=[claim.id],
        confidence=0.74,
    )
    brief = SectionBrief(
        section_key="executive_summary",
        required_claim_card_ids=[claim.id],
        required_decision_card_ids=[decision.id],
        questions=["What should the reader do next?"],
    )
    artifact = ReportArtifactV2(
        run_id="run-1",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="AI coding tools",
        output_language="en-US",
        competitors=["Cursor"],
        dimensions=["pricing"],
        claim_cards=[claim],
        decision_cards=[decision],
        section_briefs=[brief],
        core_report=ReportLayer(markdown="# Core\n\nDecision."),
        support_appendix=ReportLayer(markdown="# Evidence\n\nSource table."),
        audit_log=ReportLayer(markdown="# QA\n\nNo blockers."),
    )

    assert artifact.artifact_version == "2"
    assert artifact.render_cache.core_markdown == "# Core\n\nDecision."
    assert artifact.render_cache.support_markdown == "# Evidence\n\nSource table."
    assert artifact.render_cache.audit_markdown == "# QA\n\nNo blockers."
    assert artifact.render_cache.full_markdown.count("# Core") == 1
    assert artifact.render_cache.full_markdown.count("# Evidence") == 1
    assert artifact.claim_cards[0].id == "claim-cursor-pricing"
    assert artifact.decision_cards[0].claim_card_ids == ["claim-cursor-pricing"]
    assert artifact.section_briefs[0].section_key == "executive_summary"
    assert artifact.compatibility_report_md() == artifact.render_cache.full_markdown


def test_legacy_report_artifact_preserves_original_markdown() -> None:
    legacy = build_legacy_report_artifact(
        report_md="# Legacy\n\nBody [source:raw-1]",
        run_id="run-legacy",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="Legacy topic",
        output_language="en-US",
        competitors=["Cursor"],
        dimensions=["pricing"],
    )

    assert legacy.artifact_version == "legacy"
    assert legacy.render_cache.full_markdown == "# Legacy\n\nBody [source:raw-1]"
    assert legacy.core_report.markdown == "# Legacy\n\nBody [source:raw-1]"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_artifact_v2.py -q
```

Expected:

```text
ImportError: cannot import name 'ReportArtifactV2'
```

- [ ] **Step 3: Add the artifact models**

Create `backend/packages/schema/report_artifact.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief


ArtifactVersion = Literal["2", "legacy"]
LayerScope = Literal["core", "support", "audit", "full"]


class ReportClaimRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    source_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    evidence_role: str = "inference"
    claim_kind: str = "business_claim"
    risk_note: str = ""


class ReportLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: str = ""
    claims: list[ReportClaimRef] = Field(default_factory=list)
    section_keys: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportQualityAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_status: str = "unknown"
    publication_status: str = "unknown"
    release_status: str = "unknown"
    blocker_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    issue_count: int = Field(default=0, ge=0)
    readiness_score: int | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    quality_source: str = "not_recorded"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReportRenderCache(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_markdown: str = ""
    support_markdown: str = ""
    audit_markdown: str = ""
    full_markdown: str = ""


class ReportArtifactV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_version: ArtifactVersion = "2"
    run_id: str = ""
    workspace_id: str = ""
    project_id: str = ""
    topic: str = ""
    output_language: str = "en-US"
    competitors: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    claim_cards: list[ClaimCard] = Field(default_factory=list)
    decision_cards: list[DecisionCard] = Field(default_factory=list)
    section_briefs: list[SectionBrief] = Field(default_factory=list)
    core_report: ReportLayer = Field(default_factory=ReportLayer)
    support_appendix: ReportLayer = Field(default_factory=ReportLayer)
    audit_log: ReportLayer = Field(default_factory=ReportLayer)
    structured_report: dict[str, Any] = Field(default_factory=dict)
    quality_result: ReportQualityAccount = Field(default_factory=ReportQualityAccount)
    render_cache: ReportRenderCache = Field(default_factory=ReportRenderCache)

    @model_validator(mode="after")
    def _fill_render_cache(self) -> "ReportArtifactV2":
        core = self.render_cache.core_markdown or self.core_report.markdown
        support = self.render_cache.support_markdown or self.support_appendix.markdown
        audit = self.render_cache.audit_markdown or self.audit_log.markdown
        full = self.render_cache.full_markdown or join_report_layers(core, support, audit)
        self.render_cache = ReportRenderCache(
            core_markdown=core,
            support_markdown=support,
            audit_markdown=audit,
            full_markdown=full,
        )
        return self

    def compatibility_report_md(self) -> str:
        return self.render_cache.full_markdown or self.core_report.markdown

    def markdown_for_scope(self, scope: LayerScope) -> str:
        if scope == "core":
            return self.render_cache.core_markdown
        if scope == "support":
            return self.render_cache.support_markdown
        if scope == "audit":
            return self.render_cache.audit_markdown
        return self.compatibility_report_md()


def join_report_layers(core: str, support: str, audit: str) -> str:
    parts = [part.strip() for part in [core, support, audit] if part.strip()]
    return "\n\n".join(parts)


def build_legacy_report_artifact(
    *,
    report_md: str,
    run_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
    topic: str = "",
    output_language: str = "en-US",
    competitors: list[str] | None = None,
    dimensions: list[str] | None = None,
) -> ReportArtifactV2:
    return ReportArtifactV2(
        artifact_version="legacy",
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=topic,
        output_language=output_language,
        competitors=list(competitors or []),
        dimensions=list(dimensions or []),
        core_report=ReportLayer(markdown=report_md),
        support_appendix=ReportLayer(markdown=""),
        audit_log=ReportLayer(markdown=""),
        render_cache=ReportRenderCache(full_markdown=report_md),
    )
```

- [ ] **Step 4: Export the models**

Modify `backend/packages/schema/__init__.py`:

```python
from packages.schema.report_artifact import (
    ReportArtifactV2,
    ReportClaimRef,
    ReportLayer,
    ReportQualityAccount,
    ReportRenderCache,
    build_legacy_report_artifact,
)
```

Add these names to `__all__`.

- [ ] **Step 5: Split structured renderer outputs**

Modify `backend/packages/agents/writer/structured_renderer.py` by keeping `render_structured_report()` as the legacy full renderer and adding:

```python
def render_structured_report_core(report: StructuredReport) -> str:
    is_zh = _is_zh(report.output_language)
    labels = _labels_for(is_zh)
    lines: list[str] = [f"# {_inline_text(report.topic, 'topic')}", ""]
    _render_executive_summary(lines, report, labels)
    _section_heading(lines, "decision_summary", "core", labels["decision_summary"])
    _bullet_list(lines, report.core.decision_summary)
    _section_heading(lines, "competitive_findings", "core", labels["competitive_findings"])
    _bullet_list(lines, report.core.competitive_findings)
    _render_user_review_themes(lines, report, labels)
    _render_deep_dives(lines, report, labels)
    _render_decision_matrix(lines, report, labels, is_zh)
    _render_swot(lines, report, labels)
    _render_battlecard(lines, report, labels)
    _section_heading(lines, "community_evidence_triangulation", "core", labels["community_triangulation"])
    _bullet_list(lines, report.core.community_triangulation)
    return "\n".join(lines).strip() + "\n"


def render_structured_report_support(report: StructuredReport) -> str:
    is_zh = _is_zh(report.output_language)
    labels = _labels_for(is_zh)
    lines: list[str] = []
    _render_support(lines, report, labels, is_zh)
    return "\n".join(lines).strip() + "\n"


def render_structured_report_audit(report: StructuredReport) -> str:
    heading = "## QA And Audit" if not _is_zh(report.output_language) else "## QA 与审计"
    return f"{heading}\n\n- Writer mode: {report.metadata.writer_mode}\n- Source count: {report.metadata.source_count}\n"


def render_structured_report_full(report: StructuredReport) -> str:
    return "\n\n".join(
        part.strip()
        for part in [
            render_structured_report_core(report),
            render_structured_report_support(report),
            render_structured_report_audit(report),
        ]
        if part.strip()
    ) + "\n"
```

Then change existing `render_structured_report()` to call `render_structured_report_full(report)`.

- [ ] **Step 6: Run artifact tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_artifact_v2.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add backend/packages/schema/report_artifact.py backend/packages/schema/__init__.py backend/packages/agents/writer/structured_renderer.py backend/tests/unit/test_report_artifact_v2.py
git commit -m "feat: add report artifact v2 schema"
```

## Task 2: API DTOs And TypeScript Contract

**Files:**
- Modify: `backend/packages/schema/api_dto.py`
- Modify: `backend/packages/schema/enterprise.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/sse_types.ts`
- Modify: `frontend/src/stores/run.ts`
- Test: `backend/tests/unit/test_enterprise_schema.py`

- [ ] **Step 1: Write failing schema contract tests**

Append to `backend/tests/unit/test_enterprise_schema.py`:

```python
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import ReportVersionRecord
from packages.schema.models import AnalysisPlan
from packages.schema.report_artifact import ReportArtifactV2, ReportLayer


def test_run_detail_accepts_report_artifact_v2() -> None:
    detail = RunDetail(
        id="run-artifact",
        idempotency_key="run-artifact",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="AI coding tools",
        status="completed",
        execution_mode="real",
        output_language="en-US",
        created_at="2026-06-21T00:00:00",
        updated_at="2026-06-21T00:00:00",
        plan=AnalysisPlan(topic="AI coding tools", competitors=["Cursor"], dimensions=["pricing"]),
        report_artifact=ReportArtifactV2(
            run_id="run-artifact",
            workspace_id="workspace-1",
            project_id="project-1",
            topic="AI coding tools",
            core_report=ReportLayer(markdown="# Core"),
        ),
    )

    assert detail.report_artifact is not None
    assert detail.report_artifact.render_cache.core_markdown == "# Core"


def test_report_version_record_carries_dual_layer_fields() -> None:
    version = ReportVersionRecord(
        id="report-v1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="ai-coding-tools",
        competitor_set_hash="hash",
        core_report_md="# Core",
        support_appendix_md="# Evidence",
        audit_log_md="# QA",
        full_report_md="# Core\n\n# Evidence\n\n# QA",
        report_artifact={"artifact_version": "2"},
    )

    assert version.report_md == ""
    assert version.core_report_md == "# Core"
    assert version.report_artifact["artifact_version"] == "2"
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_schema.py::test_run_detail_accepts_report_artifact_v2 backend/tests/unit/test_enterprise_schema.py::test_report_version_record_carries_dual_layer_fields -q
```

Expected:

```text
pydantic_core._pydantic_core.ValidationError
```

- [ ] **Step 3: Add backend DTO fields**

Modify `backend/packages/schema/api_dto.py`:

```python
from packages.schema.report_artifact import ReportArtifactV2
```

Add to `RunDetail`:

```python
    report_artifact: ReportArtifactV2 | None = None
```

Modify `backend/packages/schema/enterprise.py`:

```python
from packages.schema.report_artifact import ReportArtifactV2
```

Add to `ReportVersionRecord`:

```python
    core_report_md: str = ""
    support_appendix_md: str = ""
    audit_log_md: str = ""
    full_report_md: str = ""
    report_artifact: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Add frontend types**

Modify `frontend/src/api/types.ts`:

```ts
export type ReportArtifactVersion = "2" | "legacy";
export type ReportLayerScope = "core" | "support" | "audit" | "full";

export interface ReportClaimRef {
  text: string;
  source_ids: string[];
  confidence: string;
  evidence_role: string;
  claim_kind: string;
  risk_note: string;
}

export interface ClaimCard {
  id: string;
  competitor: string;
  dimension: string;
  claim: string;
  source_ids: string[];
  confidence: number;
  evidence_role: string;
  evidence_strength: string;
  conflict_notes: string[];
  applicability_scope: string;
  caveats: string[];
  produced_by: string;
  created_at: string;
}

export interface DecisionCard {
  id: string;
  decision_type: string;
  recommendation: string;
  recommendation_strength: string;
  winner: string;
  alternatives: string[];
  why_not: Record<string, string>;
  rationale: string;
  claim_card_ids: string[];
  confidence: number;
  risk_notes: string[];
  produced_by: string;
  created_at: string;
}

export interface SectionBrief {
  section_key: string;
  required_claim_card_ids: string[];
  required_decision_card_ids: string[];
  questions: string[];
  forbidden_overclaims: string[];
  required_caveats: string[];
  citation_requirements: string[];
  output_language: OutputLanguage;
  tone: string;
}

export interface ReportLayer {
  markdown: string;
  claims: ReportClaimRef[];
  section_keys: string[];
  metadata: Record<string, unknown>;
}

export interface ReportQualityAccount {
  execution_status: string;
  publication_status: string;
  release_status: string;
  blocker_count: number;
  warn_count: number;
  issue_count: number;
  readiness_score?: number | null;
  issues: Record<string, unknown>[];
  quality_source: string;
  created_at: string;
}

export interface ReportRenderCache {
  core_markdown: string;
  support_markdown: string;
  audit_markdown: string;
  full_markdown: string;
}

export interface ReportArtifactV2 {
  artifact_version: ReportArtifactVersion;
  run_id: string;
  workspace_id: string;
  project_id: string;
  topic: string;
  output_language: OutputLanguage;
  competitors: string[];
  dimensions: string[];
  claim_cards: ClaimCard[];
  decision_cards: DecisionCard[];
  section_briefs: SectionBrief[];
  core_report: ReportLayer;
  support_appendix: ReportLayer;
  audit_log: ReportLayer;
  structured_report: Record<string, unknown>;
  quality_result: ReportQualityAccount;
  render_cache: ReportRenderCache;
}
```

Add to `RunDetail`:

```ts
  report_artifact?: ReportArtifactV2 | null;
```

Add to `ReportVersionRecord`:

```ts
  core_report_md: string;
  support_appendix_md: string;
  audit_log_md: string;
  full_report_md: string;
  report_artifact: Record<string, unknown>;
```

Modify `frontend/src/api/sse_types.ts` payload:

```ts
    report_artifact?: RunDetail["report_artifact"];
```

Modify `frontend/src/stores/run.ts` report update branch:

```ts
: event.type === "report_updated" && state.detail
? {
    ...state.detail,
    report_md: String(event.payload.report_md || ""),
    report_artifact:
      event.payload.report_artifact === undefined
        ? state.detail.report_artifact
        : (event.payload.report_artifact as RunDetail["report_artifact"]),
  }
```

- [ ] **Step 5: Run backend and frontend type checks**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_schema.py::test_run_detail_accepts_report_artifact_v2 backend/tests/unit/test_enterprise_schema.py::test_report_version_record_carries_dual_layer_fields -q
cd frontend
pnpm build
```

Expected:

```text
2 passed
vite build completes
```

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add backend/packages/schema/api_dto.py backend/packages/schema/enterprise.py frontend/src/api/types.ts frontend/src/api/sse_types.ts frontend/src/stores/run.ts backend/tests/unit/test_enterprise_schema.py
git commit -m "feat: expose report artifact v2 contracts"
```

## Task 3: Persistence Fields And Migration

**Files:**
- Modify: `backend/db/postgres/001_enterprise_core.sql`
- Modify: `backend/packages/enterprise/postgres.py`
- Modify: `backend/packages/enterprise/store.py`
- Test: `backend/tests/unit/test_enterprise_postgres_config.py`
- Test: `backend/tests/unit/test_enterprise_store.py`

- [ ] **Step 1: Write failing persistence tests**

Add to `backend/tests/unit/test_enterprise_postgres_config.py`:

```python
from pathlib import Path


def test_report_versions_schema_contains_report_artifact_v2_columns() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "core_report_md TEXT NOT NULL DEFAULT ''" in sql
    assert "support_appendix_md TEXT NOT NULL DEFAULT ''" in sql
    assert "audit_log_md TEXT NOT NULL DEFAULT ''" in sql
    assert "full_report_md TEXT NOT NULL DEFAULT ''" in sql
    assert "report_artifact JSONB NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "ALTER TABLE report_versions" in sql
    assert "ADD COLUMN IF NOT EXISTS core_report_md" in sql
```

Add to `backend/tests/unit/test_enterprise_store.py`:

```python
def test_in_memory_store_preserves_report_artifact_v2_fields() -> None:
    store = EnterpriseStore()
    version = ReportVersionRecord(
        id="report-artifact-v2",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="topic",
        competitor_set_hash="hash",
        report_md="# Full",
        core_report_md="# Core",
        support_appendix_md="# Evidence",
        audit_log_md="# QA",
        full_report_md="# Full",
        report_artifact={"artifact_version": "2"},
    )

    saved = store.upsert_report_version(version)
    loaded = store.get_report_version(saved.id)

    assert loaded is not None
    assert loaded.core_report_md == "# Core"
    assert loaded.support_appendix_md == "# Evidence"
    assert loaded.audit_log_md == "# QA"
    assert loaded.full_report_md == "# Full"
    assert loaded.report_artifact == {"artifact_version": "2"}
```

- [ ] **Step 2: Run persistence tests and verify the SQL test fails**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_postgres_config.py::test_report_versions_schema_contains_report_artifact_v2_columns backend/tests/unit/test_enterprise_store.py::test_in_memory_store_preserves_report_artifact_v2_fields -q
```

Expected:

```text
1 failed, 1 passed
```

- [ ] **Step 3: Add SQL columns and idempotent migration lines**

Modify `backend/db/postgres/001_enterprise_core.sql` report_versions table:

```sql
    report_md TEXT NOT NULL DEFAULT '',
    core_report_md TEXT NOT NULL DEFAULT '',
    support_appendix_md TEXT NOT NULL DEFAULT '',
    audit_log_md TEXT NOT NULL DEFAULT '',
    full_report_md TEXT NOT NULL DEFAULT '',
    report_artifact JSONB NOT NULL DEFAULT '{}'::jsonb,
    claim_ids TEXT[] NOT NULL DEFAULT '{}',
```

Add near existing `ALTER TABLE report_versions` lines:

```sql
ALTER TABLE report_versions
    ADD COLUMN IF NOT EXISTS core_report_md TEXT NOT NULL DEFAULT '';
ALTER TABLE report_versions
    ADD COLUMN IF NOT EXISTS support_appendix_md TEXT NOT NULL DEFAULT '';
ALTER TABLE report_versions
    ADD COLUMN IF NOT EXISTS audit_log_md TEXT NOT NULL DEFAULT '';
ALTER TABLE report_versions
    ADD COLUMN IF NOT EXISTS full_report_md TEXT NOT NULL DEFAULT '';
ALTER TABLE report_versions
    ADD COLUMN IF NOT EXISTS report_artifact JSONB NOT NULL DEFAULT '{}'::jsonb;
UPDATE report_versions
SET full_report_md = report_md
WHERE full_report_md = '' AND report_md <> '';
```

- [ ] **Step 4: Update Postgres upsert columns**

Modify `_upsert_report_version()` in `backend/packages/enterprise/postgres.py`:

```python
            INSERT INTO report_versions (
                id, workspace_id, project_id, run_id, parent_version_id, version_number,
                topic_normalized, competitor_layer, competitor_set_hash, status,
                report_md, core_report_md, support_appendix_md, audit_log_md,
                full_report_md, report_artifact,
                claim_ids, evidence_ids, quality_metadata, created_at, published_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                report_md = EXCLUDED.report_md,
                core_report_md = EXCLUDED.core_report_md,
                support_appendix_md = EXCLUDED.support_appendix_md,
                audit_log_md = EXCLUDED.audit_log_md,
                full_report_md = EXCLUDED.full_report_md,
                report_artifact = EXCLUDED.report_artifact,
                claim_ids = EXCLUDED.claim_ids,
                evidence_ids = EXCLUDED.evidence_ids,
                quality_metadata = EXCLUDED.quality_metadata,
                published_at = EXCLUDED.published_at
```

Add the matching values:

```python
                self._text(report.report_md),
                self._text(report.core_report_md),
                self._text(report.support_appendix_md),
                self._text(report.audit_log_md),
                self._text(report.full_report_md),
                self._json(report.report_artifact),
                report.claim_ids,
```

- [ ] **Step 5: Run persistence tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_postgres_config.py::test_report_versions_schema_contains_report_artifact_v2_columns backend/tests/unit/test_enterprise_store.py::test_in_memory_store_preserves_report_artifact_v2_fields -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add backend/db/postgres/001_enterprise_core.sql backend/packages/enterprise/postgres.py backend/packages/enterprise/store.py backend/tests/unit/test_enterprise_postgres_config.py backend/tests/unit/test_enterprise_store.py
git commit -m "feat: persist dual layer report artifacts"
```

## Task 4: Artifact Builder And Enterprise Projection

**Files:**
- Create: `backend/packages/agents/writer/artifact_builder.py`
- Modify: `backend/packages/enterprise/projection.py`
- Test: `backend/tests/unit/test_writer_report_artifact_v2.py`
- Test: `backend/tests/unit/test_enterprise_projection.py`

- [ ] **Step 1: Write failing builder and projection tests**

Create `backend/tests/unit/test_writer_report_artifact_v2.py`:

```python
from __future__ import annotations

from packages.agents.writer.artifact_builder import build_report_artifact_v2_from_markdown
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief


def test_markdown_builder_splits_core_support_and_audit_by_markers() -> None:
    claim = ClaimCard(
        id="claim-1",
        competitor="Cursor",
        dimension="pricing",
        claim="Cursor pricing is supported.",
        source_ids=["raw-1"],
        confidence=0.82,
        evidence_role="official_fact",
        evidence_strength="medium",
    )
    decision = DecisionCard(
        id="decision-1",
        decision_type="primary_recommendation",
        recommendation="Use Cursor as the primary trial candidate.",
        recommendation_strength="tentative",
        winner="Cursor",
        alternatives=[],
        why_not={},
        rationale="Cursor has the strongest available claim card support.",
        claim_card_ids=[claim.id],
        confidence=0.74,
    )
    brief = SectionBrief(
        section_key="executive_summary",
        required_claim_card_ids=[claim.id],
        required_decision_card_ids=[decision.id],
        questions=["What should the reader do next?"],
    )
    markdown = "\n".join(
        [
            "# Topic",
            "<!-- report-section:core:executive_summary -->",
            "## Executive Summary",
            "Core claim. [source:raw-1]",
            "<!-- report-section:support:evidence_support -->",
            "## Evidence Support",
            "Evidence row. [source:raw-1]",
            "<!-- report-section:audit:quality_audit -->",
            "## QA",
            "Audit row.",
        ]
    )

    artifact = build_report_artifact_v2_from_markdown(
        report_md=markdown,
        run_id="run-1",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="Topic",
        output_language="en-US",
        competitors=["Cursor"],
        dimensions=["pricing"],
        claim_cards=[claim],
        decision_cards=[decision],
        section_briefs=[brief],
    )

    assert artifact.artifact_version == "2"
    assert "Core claim" in artifact.core_report.markdown
    assert "Evidence row" not in artifact.core_report.markdown
    assert "Evidence row" in artifact.support_appendix.markdown
    assert "Audit row" in artifact.audit_log.markdown
    assert "Core claim" in artifact.render_cache.full_markdown
    assert "Evidence row" in artifact.render_cache.full_markdown
    assert artifact.claim_cards == [claim]
    assert artifact.decision_cards == [decision]
    assert artifact.section_briefs == [brief]
```

Add to `backend/tests/unit/test_enterprise_projection.py`:

```python
def test_enterprise_projection_writes_report_artifact_v2_fields() -> None:
    detail = _run_detail(
        report_md=(
            "# Topic\n"
            "<!-- report-section:core:executive_summary -->\n"
            "## Executive Summary\n"
            "Core claim. [source:pricing-1]\n"
            "<!-- report-section:support:evidence_support -->\n"
            "## Evidence Support\n"
            "Support row. [source:pricing-1]\n"
        )
    )

    projection = build_enterprise_projection(
        detail,
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        competitor_layer="unknown",
        competitor_id_map=None,
    )

    version = projection.report_version
    assert version.report_artifact["artifact_version"] == "2"
    assert "Core claim" in version.core_report_md
    assert "Support row" not in version.core_report_md
    assert "Support row" in version.support_appendix_md
    assert version.full_report_md == version.report_md
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_artifact_v2.py backend/tests/unit/test_enterprise_projection.py::test_enterprise_projection_writes_report_artifact_v2_fields -q
```

Expected:

```text
ImportError: cannot import name 'build_report_artifact_v2_from_markdown'
```

- [ ] **Step 3: Implement the artifact builder**

Create `backend/packages/agents/writer/artifact_builder.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from packages.agents.writer.structured_renderer import (
    render_structured_report_audit,
    render_structured_report_core,
    render_structured_report_full,
    render_structured_report_support,
)
from packages.agents.writer.structured_report import StructuredReport
from packages.business_intel.report_sections import build_report_section_index
from packages.schema.report_artifact import (
    ReportArtifactV2,
    ReportLayer,
    ReportRenderCache,
)
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief


def build_report_artifact_v2_from_structured_report(
    report: StructuredReport,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    claim_cards: list[ClaimCard],
    decision_cards: list[DecisionCard],
    section_briefs: list[SectionBrief],
) -> ReportArtifactV2:
    core = render_structured_report_core(report)
    support = render_structured_report_support(report)
    audit = render_structured_report_audit(report)
    full = render_structured_report_full(report)
    return ReportArtifactV2(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=report.topic,
        output_language=report.output_language,
        competitors=list(report.competitors),
        dimensions=list(report.dimensions),
        claim_cards=claim_cards,
        decision_cards=decision_cards,
        section_briefs=section_briefs,
        core_report=ReportLayer(markdown=core, section_keys=_section_keys(core)),
        support_appendix=ReportLayer(markdown=support, section_keys=_section_keys(support)),
        audit_log=ReportLayer(markdown=audit, section_keys=["quality_audit"]),
        structured_report=report.model_dump(mode="json"),
        render_cache=ReportRenderCache(
            core_markdown=core,
            support_markdown=support,
            audit_markdown=audit,
            full_markdown=full,
        ),
    )


def build_report_artifact_v2_from_markdown(
    *,
    report_md: str,
    run_id: str,
    workspace_id: str,
    project_id: str,
    topic: str,
    output_language: str,
    competitors: Iterable[str],
    dimensions: Iterable[str],
    claim_cards: list[ClaimCard],
    decision_cards: list[DecisionCard],
    section_briefs: list[SectionBrief],
) -> ReportArtifactV2:
    layers = _split_markdown_layers(report_md)
    core = layers["core"].strip()
    support = layers["support"].strip()
    audit = layers["audit"].strip()
    if not core:
        core = report_md.strip()
        support = ""
        audit = ""
    return ReportArtifactV2(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=topic,
        output_language=output_language,
        competitors=list(competitors),
        dimensions=list(dimensions),
        claim_cards=claim_cards,
        decision_cards=decision_cards,
        section_briefs=section_briefs,
        core_report=ReportLayer(markdown=core, section_keys=_section_keys(core)),
        support_appendix=ReportLayer(markdown=support, section_keys=_section_keys(support)),
        audit_log=ReportLayer(markdown=audit, section_keys=_section_keys(audit)),
        render_cache=ReportRenderCache(
            core_markdown=core,
            support_markdown=support,
            audit_markdown=audit,
            full_markdown="\n\n".join(part for part in [core, support, audit] if part),
        ),
    )


def _split_markdown_layers(markdown: str) -> dict[str, str]:
    index = build_report_section_index(markdown)
    layers = {"core": [], "support": [], "audit": []}
    for section in index.sections:
        layer = section.layer.value if hasattr(section.layer, "value") else str(section.layer)
        if layer not in layers:
            layer = "support"
        layers[layer].append(section.text.strip())
    return {key: "\n\n".join(value) for key, value in layers.items()}


def _section_keys(markdown: str) -> list[str]:
    return [
        line.strip("# ").strip()
        for line in markdown.splitlines()
        if line.startswith("## ")
    ]
```

- [ ] **Step 4: Project artifact fields**

Modify `_build_report_version()` in `backend/packages/enterprise/projection.py` before `ReportVersionRecord(...)`:

```python
    claim_cards = (
        list(detail.report_artifact.claim_cards)
        if detail.report_artifact is not None
        else build_claim_cards_from_run_detail(detail)
    )
    decision_cards = (
        list(detail.report_artifact.decision_cards)
        if detail.report_artifact is not None
        else build_decision_cards_from_claim_cards(detail, claim_cards)
    )
    section_briefs = (
        list(detail.report_artifact.section_briefs)
        if detail.report_artifact is not None
        else build_section_briefs(detail, claim_cards, decision_cards)
    )
    artifact = detail.report_artifact or build_report_artifact_v2_from_markdown(
        report_md=normalized_report.report_md,
        run_id=detail.id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=detail.topic,
        output_language=detail.output_language,
        competitors=detail.plan.competitors,
        dimensions=detail.plan.dimensions,
        claim_cards=claim_cards,
        decision_cards=decision_cards,
        section_briefs=section_briefs,
    )
    report_md = artifact.compatibility_report_md()
```

Add imports:

```python
from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
```

Then set these fields on `ReportVersionRecord`:

```python
        report_md=report_md,
        core_report_md=artifact.render_cache.core_markdown,
        support_appendix_md=artifact.render_cache.support_markdown,
        audit_log_md=artifact.render_cache.audit_markdown,
        full_report_md=artifact.render_cache.full_markdown,
        report_artifact=artifact.model_dump(mode="json"),
```

Keep `evidence_ids=normalized_report.evidence_ids` for now so existing scope rules remain stable.

- [ ] **Step 5: Run builder and projection tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_artifact_v2.py backend/tests/unit/test_enterprise_projection.py::test_enterprise_projection_writes_report_artifact_v2_fields -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add backend/packages/agents/writer/artifact_builder.py backend/packages/enterprise/projection.py backend/tests/unit/test_writer_report_artifact_v2.py backend/tests/unit/test_enterprise_projection.py
git commit -m "feat: project writer output as report artifact v2"
```

## Task 5: Writer Stores Artifact And Stops V2 Markdown Publication Repair

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing writer service tests**

Add focused tests near existing structured writer tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_writer_report_updated_event_includes_report_artifact_v2(monkeypatch) -> None:
    service = RunService(settings=_settings(writer_structured_report_enabled=True))
    record = _create_run_record(service, run_id="run-artifact-writer")
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fake_schema_contract_report(self, record, evidence_pack_result, timeout_seconds):
        return (
            "# Topic\n"
            "<!-- report-section:core:executive_summary -->\n"
            "## Executive Summary\n"
            "Core claim. [source:cursor-pricing]\n"
            "<!-- report-section:support:evidence_support -->\n"
            "## Evidence Support\n"
            "Support row. [source:cursor-pricing]\n"
        )

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_schema_contract_segment_report",
        fake_schema_contract_report,
    )

    await service._run_writer(record)

    assert record.detail.report_artifact is not None
    assert record.detail.report_artifact.artifact_version == "2"
    assert record.detail.report_artifact.claim_cards
    assert record.detail.report_artifact.decision_cards
    assert record.detail.report_artifact.section_briefs
    assert "Core claim" in record.detail.report_artifact.core_report.markdown
    report_events = [event for event in record.events if event.type == "report_updated"]
    assert report_events
    assert report_events[-1].payload["report_artifact"]["artifact_version"] == "2"


@pytest.mark.asyncio
async def test_v2_writer_does_not_call_publication_markdown_repair(monkeypatch) -> None:
    service = RunService(settings=_settings(writer_structured_report_enabled=True))
    record = _create_run_record(service, run_id="run-v2-no-publication-repair")
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fail_publication_repair(*args, **kwargs):
        raise AssertionError("V2 writer must not repair Markdown publication issues")

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._repair_schema_contract_publication_issues",
        fail_publication_repair,
    )

    await service._run_writer(record)

    assert record.detail.report_artifact is not None
```

- [ ] **Step 2: Run writer tests and verify they fail**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_writer_report_updated_event_includes_report_artifact_v2 backend/tests/unit/test_run_service.py::test_v2_writer_does_not_call_publication_markdown_repair -q
```

Expected:

```text
AssertionError: assert None is not None
```

- [ ] **Step 3: Store artifact after writer authoring**

In `backend/packages/agents/writer/logic.py`, import:

```python
from packages.agents.writer.artifact_builder import build_report_artifact_v2_from_markdown
from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
```

Before the natural/schema-contract segment writer is called, build cards and
briefs:

```python
        claim_cards = build_claim_cards_from_run_detail(detail)
        decision_cards = build_decision_cards_from_claim_cards(detail, claim_cards)
        section_briefs = build_section_briefs(detail, claim_cards, decision_cards)
```

Pass `section_briefs` into the segment writer prompt context. At minimum, add
their JSON to the writer context and instruct the writer that recommendations
and material claims must not exceed card content.

After `hardened_report` is selected and before agent message append:

```python
        artifact = build_report_artifact_v2_from_markdown(
            report_md=detail.report_md,
            run_id=detail.id,
            workspace_id=detail.workspace_id,
            project_id=detail.project_id or "",
            topic=detail.topic,
            output_language=detail.output_language,
            competitors=detail.plan.competitors,
            dimensions=detail.plan.dimensions,
            claim_cards=claim_cards,
            decision_cards=decision_cards,
            section_briefs=section_briefs,
        )
        detail.report_artifact = artifact
        detail.report_md = artifact.compatibility_report_md()
```

Change the agent message payload:

```python
            payload_schema="ReportArtifactV2",
            payload={
                "report_md": detail.report_md,
                "report_artifact": artifact.model_dump(mode="json"),
                "writer_mode": writer_mode,
                "error": writer_error,
                **repair_metadata,
            },
```

Change the `report_updated` event payload:

```python
            {
                "report_md": detail.report_md,
                "report_artifact": artifact.model_dump(mode="json"),
                "writer_mode": writer_mode,
                "error": writer_error,
                **repair_metadata,
                **self._enterprise_projection_payload(projection),
            },
```

- [ ] **Step 4: Guard Markdown publication repair behind legacy mode**

In the structured writer path, remove the call to `_repair_schema_contract_publication_issues()` from the V2 branch. Keep validation telemetry, then let artifact validation and release gate handle quality. The V2 branch should look like:

```python
                        publication_validation = validate_publication_contract(
                            report_md,
                            structured_report=None,
                            allowed_source_ids={source.id for source in detail.raw_sources},
                            output_language=detail.output_language,
                        )
                        await self.emit(...publication_payload...)
                        if not publication_validation.passed:
                            self._trace_local_tool(
                                record,
                                agent="writer",
                                subagent=None,
                                name="writer_publication_contract_legacy_diagnostic",
                                input_text="schema_contract_segment_report",
                                output_text=json.dumps(publication_payload, ensure_ascii=False, default=str),
                                metadata={"passed": False, "v2_diagnostic_only": True},
                            )
```

Do not raise solely because legacy publication contract failed when a V2 artifact can be built. Invalid source IDs still fail through artifact/source validation in Task 6.

- [ ] **Step 5: Run writer tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_writer_report_updated_event_includes_report_artifact_v2 backend/tests/unit/test_run_service.py::test_v2_writer_does_not_call_publication_markdown_repair -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: store writer output as report artifact"
```

## Task 6: Release Gate Uses Core Layer And Stops Mutating V2 Markdown

**Files:**
- Modify: `backend/packages/business_intel/release_gate.py`
- Modify: `backend/packages/orchestrator/service.py`
- Modify: `backend/packages/quality/final_result.py`
- Test: `backend/tests/unit/test_business_intel.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing release gate scope tests**

Add to `backend/tests/unit/test_business_intel.py`:

```python
def test_release_gate_ignores_support_checklist_when_core_is_clean() -> None:
    report = _report_version(
        report_md="# Core\n\nCursor pricing is supported. [source:evidence-1]\n\n## QA\n\n- [ ] Unsupported checklist wording.",
    )
    report = report.model_copy(
        update={
            "core_report_md": "# Core\n\nCursor pricing is supported. [source:evidence-1]",
            "support_appendix_md": "## QA\n\n- [ ] Unsupported checklist wording.",
            "full_report_md": report.report_md,
            "report_artifact": {"artifact_version": "2"},
        }
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[_competitor()],
        evidence=[_evidence("evidence-1")],
        claims=[_claim("claim-1", evidence_ids=["evidence-1"])],
    )

    assert all(
        issue.rule_id != "strong_conclusion_uses_weak_source"
        for issue in gate.issues
    )
```

Add to `backend/tests/unit/test_run_service.py`:

```python
def test_release_gate_metadata_does_not_mutate_v2_report_markdown(monkeypatch) -> None:
    service = RunService(settings=_settings())
    record = _create_completed_record_with_projection(service, run_id="run-v2-release")
    original = record.detail.enterprise_projection.report_version.report_md
    record.detail.enterprise_projection.report_version = (
        record.detail.enterprise_projection.report_version.model_copy(
            update={
                "report_artifact": {"artifact_version": "2"},
                "core_report_md": original,
                "full_report_md": original,
            }
        )
    )

    changed = service._attach_release_gate_quality_metadata(
        record.detail.enterprise_projection,
        service._evaluate_report_release_gate(record.detail.enterprise_projection),
    )

    assert changed in {True, False}
    assert record.detail.enterprise_projection.report_version.report_md == original
```

- [ ] **Step 2: Run tests and verify the support checklist test fails**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_business_intel.py::test_release_gate_ignores_support_checklist_when_core_is_clean backend/tests/unit/test_run_service.py::test_release_gate_metadata_does_not_mutate_v2_report_markdown -q
```

Expected:

```text
At least one test fails because release gate still reads report_md or mutates report_md.
```

- [ ] **Step 3: Add core markdown selector**

In `backend/packages/business_intel/release_gate.py`, add:

```python
def _report_core_markdown(report_version: ReportVersionRecord) -> str:
    if _is_v2_report(report_version) and report_version.core_report_md.strip():
        return report_version.core_report_md
    return report_version.report_md


def _is_v2_report(report_version: ReportVersionRecord) -> bool:
    return dict(report_version.report_artifact).get("artifact_version") == "2"
```

Replace every direct report text read in `_report_structure_issues`, `_report_depth_issues`, `_report_richness_issues`, `_missing_report_citation_issues`, and `_report_citation_quality_issues` with `_report_core_markdown(report_version)`.

- [ ] **Step 4: Stop V2 release-gate Markdown warning repair**

In `_attach_release_gate_quality_metadata()` in `backend/packages/orchestrator/service.py`, split V2 from legacy:

```python
        is_v2_report = (
            dict(projection.report_version.report_artifact).get("artifact_version") == "2"
        )
        report_repair = apply_release_gate_warning_report_repair(
            projection.report_version.report_md,
            gate=gate,
            tasks=initial_tasks,
        ) if not is_v2_report else ReleaseGateReportRepair(
            report_md=projection.report_version.report_md,
            changed=False,
            repairs=[],
        )
```

Import the repair result class if needed from `packages.business_intel.release_repair`. If that class is not exported, add a small local branch that sets `report_repair_changed = False` and writes `warning_repair` metadata manually:

```python
        warning_repair_metadata = (
            report_repair.metadata()
            if not is_v2_report
            else {"changed": False, "reason": "v2_artifact_audit_only"}
        )
```

Use `warning_repair_metadata` in `release_gate_metadata`.

- [ ] **Step 5: Store final quality account into artifact**

Extend `FinalQualityResult.telemetry_payload()` or add a method:

```python
    def artifact_quality_payload(self) -> dict[str, object]:
        return {
            "execution_status": self.quality_status,
            "publication_status": "validated",
            "release_status": self.quality_status,
            "blocker_count": self.blocker_count,
            "warn_count": self.warn_count,
            "issue_count": self.issue_count,
            "readiness_score": self.readiness_score,
            "issues": [finding.model_dump(mode="json") for finding in self.findings],
            "quality_source": "final_quality_result",
        }
```

In `_record_unified_quality_result_event()` or immediately before it is emitted, update `record.detail.report_artifact.quality_result` from this payload and refresh `record.detail.report_md`.

- [ ] **Step 6: Run release gate tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_business_intel.py::test_release_gate_ignores_support_checklist_when_core_is_clean backend/tests/unit/test_run_service.py::test_release_gate_metadata_does_not_mutate_v2_report_markdown -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit Task 6**

Run:

```bash
git add backend/packages/business_intel/release_gate.py backend/packages/orchestrator/service.py backend/packages/quality/final_result.py backend/tests/unit/test_business_intel.py backend/tests/unit/test_run_service.py
git commit -m "fix: gate report quality on artifact core layer"
```

## Task 7: Frontend Dual-Layer Reader And Export Scopes

**Files:**
- Modify: `frontend/src/features/run-detail/RunReportReviewStudio.tsx`
- Modify: `frontend/src/features/run-detail/ReportReaderWorkspace.tsx`
- Modify: `frontend/src/features/run-detail/ReportOutline.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `backend/app/routers/enterprise.py`
- Test: `frontend/src/features/run-detail/RunReportReviewStudio.test.tsx`
- Test: `backend/tests/unit/test_enterprise_store.py`

- [ ] **Step 1: Write failing frontend reader test**

Create `frontend/src/features/run-detail/RunReportReviewStudio.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RunReportReviewStudio } from "./RunReportReviewStudio";

vi.mock("../../api/client", () => ({
  exportReportVersion: vi.fn(),
  startReportApprovalWorkflow: vi.fn(),
}));

describe("RunReportReviewStudio artifact tabs", () => {
  it("opens on core report and separates evidence and qa layers", async () => {
    render(
      <RunReportReviewStudio
        detail={{
          id: "run-1",
          idempotency_key: "run-1",
          workspace_id: "workspace-1",
          project_id: "project-1",
          topic: "Topic",
          status: "completed",
          execution_mode: "real",
          output_language: "en-US",
          created_at: "2026-06-21T00:00:00",
          updated_at: "2026-06-21T00:00:00",
          plan: { topic: "Topic", competitors: ["Cursor"], dimensions: ["pricing"], tasks: [] },
          max_iterations: 2,
          auto_redo_warn_enabled: false,
          hitl_enabled: false,
          report_md: "# Full\n\nEvidence text",
          report_artifact: {
            artifact_version: "2",
            run_id: "run-1",
            workspace_id: "workspace-1",
            project_id: "project-1",
            topic: "Topic",
            output_language: "en-US",
            competitors: ["Cursor"],
            dimensions: ["pricing"],
            claim_cards: [{
              id: "claim-1",
              competitor: "Cursor",
              dimension: "pricing",
              claim: "Cursor pricing is supported.",
              source_ids: ["raw-1"],
              confidence: 0.82,
              evidence_role: "official_fact",
              evidence_strength: "medium",
              conflict_notes: [],
              applicability_scope: "pricing comparison",
              caveats: [],
              produced_by: "analyst",
              created_at: "2026-06-21T00:00:00",
            }],
            decision_cards: [{
              id: "decision-1",
              decision_type: "primary_recommendation",
              recommendation: "Use Cursor as the primary trial candidate.",
              recommendation_strength: "tentative",
              winner: "Cursor",
              alternatives: [],
              why_not: {},
              rationale: "Cursor has the strongest available claim card support.",
              claim_card_ids: ["claim-1"],
              confidence: 0.74,
              risk_notes: [],
              produced_by: "comparator",
              created_at: "2026-06-21T00:00:00",
            }],
            section_briefs: [{
              section_key: "executive_summary",
              required_claim_card_ids: ["claim-1"],
              required_decision_card_ids: ["decision-1"],
              questions: ["What should the reader do next?"],
              forbidden_overclaims: [],
              required_caveats: [],
              citation_requirements: [],
              output_language: "en-US",
              tone: "professional competitive intelligence",
            }],
            core_report: { markdown: "# Core\n\nCore decision", claims: [], section_keys: [], metadata: {} },
            support_appendix: { markdown: "# Evidence\n\nEvidence text", claims: [], section_keys: [], metadata: {} },
            audit_log: { markdown: "# QA\n\nWarn count: 0", claims: [], section_keys: [], metadata: {} },
            structured_report: {},
            quality_result: {
              execution_status: "clean_pass",
              publication_status: "validated",
              release_status: "clean_pass",
              blocker_count: 0,
              warn_count: 0,
              issue_count: 0,
              readiness_score: 91,
              issues: [],
              quality_source: "test",
              created_at: "2026-06-21T00:00:00",
            },
            render_cache: {
              core_markdown: "# Core\n\nCore decision",
              support_markdown: "# Evidence\n\nEvidence text",
              audit_markdown: "# QA\n\nWarn count: 0",
              full_markdown: "# Core\n\nCore decision\n\n# Evidence\n\nEvidence text\n\n# QA\n\nWarn count: 0",
            },
          },
          raw_sources: [],
          competitor_kbs: {},
          competitor_knowledge: {},
          qa_findings: [],
          reflections: [],
          revisions: [],
          agent_messages: [],
          tool_call_messages: [],
          trace_spans: [],
          metrics: { llm_calls: 0, source_coverage_rate: 0, claim_citation_rate: 0, qa_pass_rate: 0, total_tokens: 0, total_spans: 0 },
        }}
        reportSources={{ sources: [], aliases: new Map() }}
      />,
    );

    expect(screen.getByText("Core decision")).toBeInTheDocument();
    expect(screen.queryByText("Evidence text")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Evidence/i }));

    expect(screen.getByText("Evidence text")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Write failing export scope backend test**

Add to `backend/tests/unit/test_enterprise_store.py`:

```python
def test_report_export_payload_uses_requested_v2_scope() -> None:
    from app.routers.enterprise import _report_export_payload

    version = ReportVersionRecord(
        id="report-export-v2",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="topic",
        competitor_set_hash="hash",
        report_md="# Full",
        core_report_md="# Core",
        support_appendix_md="# Evidence",
        audit_log_md="# QA",
        full_report_md="# Full",
        report_artifact={"artifact_version": "2"},
    )

    body, filename, media_type = _report_export_payload(version, "markdown", scope="core")

    assert body == "# Core"
    assert filename.endswith("-core.md")
    assert media_type == "text/markdown"
```

- [ ] **Step 3: Run frontend and backend tests and verify they fail**

Run:

```bash
cd frontend
pnpm test src/features/run-detail/RunReportReviewStudio.test.tsx
cd ..
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_store.py::test_report_export_payload_uses_requested_v2_scope -q
```

Expected:

```text
Frontend cannot find Evidence tab.
Backend _report_export_payload does not accept scope.
```

- [ ] **Step 4: Add export scope parameter**

Modify `backend/app/routers/enterprise.py` endpoint:

```python
def export_report_version(
    version_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    artifact_storage: ArtifactStorageDep,
    format: str = "markdown",
    scope: str = "full",
) -> ArtifactCreateResult:
```

Change payload call:

```python
    body, filename, media_type = _report_export_payload(version, format, scope=scope)
```

Add:

```python
def _normalize_report_export_scope(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"core", "report"}:
        return "core"
    if normalized in {"support", "evidence"}:
        return "support"
    if normalized in {"audit", "qa"}:
        return "audit"
    if normalized in {"full", "complete"}:
        return "full"
    raise HTTPException(
        status_code=400,
        detail="Unsupported report export scope. Use core, support, audit, or full.",
    )
```

Change `_report_export_payload` signature and body:

```python
def _report_export_payload(
    version: ReportVersionRecord,
    format: str,
    *,
    scope: str = "full",
) -> tuple[str, str, str]:
    normalized = _normalize_report_export_format(format)
    export_scope = _normalize_report_export_scope(scope)
    markdown = _report_markdown_for_export_scope(version, export_scope)
    filename_base = f"report-v{version.version_number}-{version.id}-{export_scope}"
    if normalized == "markdown":
        return markdown, f"{filename_base}.md", "text/markdown"
```

Add helper:

```python
def _report_markdown_for_export_scope(version: ReportVersionRecord, scope: str) -> str:
    if scope == "core":
        return version.core_report_md or version.report_md
    if scope == "support":
        return version.support_appendix_md
    if scope == "audit":
        return version.audit_log_md
    return version.full_report_md or version.report_md
```

- [ ] **Step 5: Add frontend tabs**

Modify `frontend/src/features/run-detail/RunReportReviewStudio.tsx`:

```tsx
type ReportLayerTab = "report" | "evidence" | "qa" | "audit";

function artifactMarkdown(detail: RunDetailRecord, tab: ReportLayerTab) {
  const artifact = detail.report_artifact;
  if (!artifact || artifact.artifact_version !== "2") {
    return detail.report_md ?? "";
  }
  if (tab === "report") return artifact.render_cache.core_markdown || artifact.core_report.markdown;
  if (tab === "evidence") return artifact.render_cache.support_markdown || artifact.support_appendix.markdown;
  if (tab === "qa") return artifact.render_cache.audit_markdown || artifact.audit_log.markdown;
  return artifact.render_cache.full_markdown || detail.report_md || "";
}
```

For the Evidence tab, render support markdown and a compact cards panel:

```tsx
function ArtifactCardsPanel({ artifact }: { artifact: ReportArtifactV2 }) {
  return (
    <aside className="artifact-cards-panel">
      <h3>Claim cards</h3>
      {artifact.claim_cards.map((card) => (
        <article key={card.id}>
          <strong>{card.competitor || "General"} / {card.dimension || "general"}</strong>
          <p>{card.claim}</p>
          <span>{card.evidence_strength} / {Math.round(card.confidence * 100)}%</span>
        </article>
      ))}
      <h3>Decision cards</h3>
      {artifact.decision_cards.map((card) => (
        <article key={card.id}>
          <strong>{card.recommendation_strength}</strong>
          <p>{card.recommendation}</p>
        </article>
      ))}
    </aside>
  );
}
```

Add state:

```tsx
  const [activeLayer, setActiveLayer] = useState<ReportLayerTab>("report");
  const markdown = artifactMarkdown(detail, activeLayer);
```

Render tabs above the reader:

```tsx
        {detail.report_artifact?.artifact_version === "2" ? (
          <div className="report-layer-tabs" aria-label="Report layers">
            {[
              ["report", "Report"],
              ["evidence", "Evidence"],
              ["qa", "QA"],
              ["audit", "Audit"],
            ].map(([id, label]) => (
              <button
                className={activeLayer === id ? "active" : ""}
                key={id}
                onClick={() => setActiveLayer(id as ReportLayerTab)}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
```

Modify export call to pass scope:

```tsx
      const scope = activeLayer === "report" ? "core" : activeLayer === "evidence" ? "support" : activeLayer;
      const response = await exportReportVersion(reportVersion.id, format, scope);
```

Modify `frontend/src/api/client.ts`:

```ts
export function exportReportVersion(
  versionId: string,
  format: "markdown" | "html" | "csv",
  scope: "core" | "support" | "audit" | "full" = "full",
) {
  return request<ArtifactCreateResult>(
    `/enterprise/report-versions/${versionId}/export?format=${encodeURIComponent(format)}&scope=${encodeURIComponent(scope)}`,
    { method: "POST" },
  );
}
```

- [ ] **Step 6: Run frontend and export tests**

Run:

```bash
cd frontend
pnpm test src/features/run-detail/RunReportReviewStudio.test.tsx
pnpm build
cd ..
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_store.py::test_report_export_payload_uses_requested_v2_scope -q
```

Expected:

```text
Frontend test passes, frontend build passes, backend export test passes.
```

- [ ] **Step 7: Commit Task 7**

Run:

```bash
git add frontend/src/features/run-detail/RunReportReviewStudio.tsx frontend/src/features/run-detail/ReportReaderWorkspace.tsx frontend/src/features/run-detail/ReportOutline.tsx frontend/src/api/client.ts backend/app/routers/enterprise.py frontend/src/features/run-detail/RunReportReviewStudio.test.tsx backend/tests/unit/test_enterprise_store.py
git commit -m "feat: add dual layer report reader and exports"
```

## Task 8: Legacy Guards And Patch Retirement

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/packages/agents/writer/repair.py`
- Modify: `backend/packages/agents/writer/quality_preflight.py`
- Test: `backend/tests/unit/test_writer_report_artifact_v2.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing tests that old patches are not used for V2**

Append to `backend/tests/unit/test_writer_report_artifact_v2.py`:

```python
def test_v2_artifact_is_not_repaired_by_markdown_line_target() -> None:
    from packages.agents.writer.repair import structured_repair_target_for_issue
    from packages.schema.models import QCIssue

    issue = QCIssue(
        id="issue-line",
        severity="warn",
        message="Line noise in support checklist",
        target_agent="writer",
        field_path="report_md.line[12]",
        detected_by="release_gate",
    )

    assert structured_repair_target_for_issue(issue) != "report_md"
```

Append to `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_v2_writer_skips_required_section_backfill(monkeypatch) -> None:
    service = RunService(settings=_settings(writer_structured_report_enabled=True))
    record = _create_run_record(service, run_id="run-v2-no-backfill")
    record.detail.raw_sources = _structured_writer_raw_sources()

    def fail_backfill(*args, **kwargs):
        raise AssertionError("V2 writer must not backfill Markdown sections")

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._ensure_report_required_sections",
        fail_backfill,
    )

    await service._run_writer(record)

    assert record.detail.report_artifact is not None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_artifact_v2.py::test_v2_artifact_is_not_repaired_by_markdown_line_target backend/tests/unit/test_run_service.py::test_v2_writer_skips_required_section_backfill -q
```

Expected:

```text
The backfill test fails if V2 still uses Markdown backfill.
```

- [ ] **Step 3: Add explicit legacy guards**

In `backend/packages/agents/writer/logic.py`, add:

```python
def _is_report_artifact_v2(detail: RunDetail) -> bool:
    return (
        detail.report_artifact is not None
        and detail.report_artifact.artifact_version == "2"
    )
```

Before each old Markdown patch call, keep it only for legacy:

```python
if _is_report_artifact_v2(detail):
    hardened_report = detail.report_artifact.compatibility_report_md()
else:
    hardened_report = self._harden_report_markdown(detail, report_md)
```

Do the same for calls to:

- `_ensure_report_required_sections`
- `_ensure_report_claim_citations`
- `_repair_report_source_token`
- `_harden_schema_contract_report_markdown`
- `_repair_schema_contract_publication_issues`

In `backend/packages/agents/writer/repair.py`, make V2 line targets fail closed to artifact repair:

```python
if detail.report_artifact is not None and detail.report_artifact.artifact_version == "2":
    return WriterRepairPlan(
        mode="structured_section",
        sections=[],
        reason="v2 artifact repairs target artifact paths, not report_md lines",
        previous_report_protectable=True,
    )
```

- [ ] **Step 4: Run legacy guard tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_report_artifact_v2.py::test_v2_artifact_is_not_repaired_by_markdown_line_target backend/tests/unit/test_run_service.py::test_v2_writer_skips_required_section_backfill -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit Task 8**

Run:

```bash
git add backend/packages/agents/writer/logic.py backend/packages/agents/writer/repair.py backend/packages/agents/writer/quality_preflight.py backend/tests/unit/test_writer_report_artifact_v2.py backend/tests/unit/test_run_service.py
git commit -m "refactor: guard legacy markdown report repairs"
```

## Task 9: End-To-End Verification And Regression Audit

**Files:**
- Modify only files required by failing tests from earlier tasks.
- No new architecture files unless a test exposes a missed V2 boundary.

- [ ] **Step 1: Run focused backend test set**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_artifact_v2.py backend/tests/unit/test_writer_report_artifact_v2.py backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_enterprise_postgres_config.py backend/tests/unit/test_business_intel.py::test_release_gate_ignores_support_checklist_when_core_is_clean -q
```

Expected:

```text
All selected tests pass.
```

- [ ] **Step 2: Run focused run service tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py -q
```

Expected:

```text
All test_run_service tests pass or only known unrelated failures are listed with exact test names.
```

- [ ] **Step 3: Run frontend tests and build**

Run:

```bash
cd frontend
pnpm test src/features/run-detail/RunReportReviewStudio.test.tsx
pnpm build
cd ..
```

Expected:

```text
Vitest passes and Vite build completes.
```

- [ ] **Step 4: Run one real report with local scripts**

Use the repository stop/start scripts instead of ad-hoc process management. Run the documented backend/frontend restart commands from `scripts/` after inspecting their names with:

```bash
Get-ChildItem scripts | Select-Object Name
```

Start a real run through the existing UI or API. Record the run id in the implementation notes.

- [ ] **Step 5: Audit the real run**

Inspect the generated run detail JSON and confirm:

```text
detail.report_artifact.artifact_version == "2"
detail.report_artifact.claim_cards is not empty
detail.report_artifact.decision_cards is not empty
detail.report_artifact.section_briefs is not empty
detail.report_md == detail.report_artifact.render_cache.full_markdown
detail.enterprise_projection.report_version.core_report_md is not empty
detail.enterprise_projection.report_version.support_appendix_md is not empty
detail.enterprise_projection.report_version.report_artifact.artifact_version == "2"
the core recommendation can be traced to a decision card
release_gate issue scan does not flag support checklist lines as core claims
report_updated SSE payload includes report_artifact
frontend report tab opens on core report
```

- [ ] **Step 6: Record verification result**

Run:

```bash
git status --short
```

Expected when verification required no code changes:

```text
Only pre-existing untracked artifacts are listed.
```

If Step 5 exposes a code defect, stop execution and write a new focused task
with the exact failing test, exact files, exact patch shape, and exact commit
command before changing code. Do not make an unplanned verification commit.

## Self-Review Checklist

- Spec coverage:
  - Claim cards, decision cards, and section briefs: Task 0.
  - V2 schema: Task 1.
  - RunDetail and ReportVersionRecord fields: Task 2.
  - Postgres migration and store support: Task 3.
  - Enterprise projection: Task 4.
  - Writer artifact emission: Task 5.
  - Core-only release gate and single quality account: Task 6.
  - Frontend tabs and export scopes: Task 7.
  - Old Markdown patch retirement: Task 8.
  - End-to-end verification: Task 9.
- Patch retirement:
  - Old Markdown publication repair is not allowed to mutate V2 reports.
  - Support checklist text is not scanned as a core business claim.
  - Markdown line targets are not V2 repair targets.
- Boundary check:
  - Raw collection and source identity semantics are not redesigned.
  - Claim cards are analyst-owned reasoning artifacts.
  - Decision cards are comparator-owned recommendation artifacts.
  - Section briefs are writer-facing contracts.
  - Current schema-contract segmented writer can remain an authoring detail.
  - `report_md` remains only as a compatibility/render cache field.
