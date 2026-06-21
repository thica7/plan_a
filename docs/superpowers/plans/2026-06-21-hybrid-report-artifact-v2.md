# Hybrid Report Artifact v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the hybrid report pipeline where evidence becomes claim cards, claim cards become decision cards, cards become section briefs, natural writer prose is assembled deterministically, and Report Artifact v2 becomes the product/publication boundary.

**Architecture:** Cards and briefs are the reasoning boundary; natural segment prose is the expression layer; deterministic assembler owns final structure and core/support/audit separation. The current schema-contract segmented writer may remain during migration, but it must consume section briefs and emit into `ReportArtifactV2`; `report_md` becomes a compatibility render cache.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, pytest, Postgres SQL schema file, React 18, TypeScript, Vitest.

---

## File Structure

- Create: `backend/packages/schema/report_cards.py`
  - Defines `ClaimCard`, `DecisionCard`, `SectionBrief`.
- Create: `backend/packages/schema/report_artifact.py`
  - Defines `ReportArtifactV2`, report layers, quality account, render cache, legacy adapter.
- Modify: `backend/packages/schema/__init__.py`
  - Exports card and artifact models.
- Modify: `backend/packages/schema/api_dto.py`
  - Adds `RunDetail.report_artifact`.
- Modify: `backend/packages/schema/enterprise.py`
  - Adds artifact and rendered layer fields to `ReportVersionRecord`.
- Create: `backend/packages/business_intel/report_card_builder.py`
  - Builds deterministic first-pass claim and decision cards from current run data.
- Create: `backend/packages/business_intel/section_brief_builder.py`
  - Builds writer-facing section briefs from cards.
- Create: `backend/packages/agents/writer/artifact_assembler.py`
  - Builds `ReportArtifactV2` from cards, briefs, and writer prose.
- Modify: `backend/packages/agents/writer/logic.py`
  - Builds cards/briefs before writing, injects briefs into writer context, stores artifact, derives `report_md`.
- Modify: `backend/packages/enterprise/projection.py`
  - Projects artifact fields into enterprise report versions.
- Modify: `backend/packages/enterprise/store.py`
  - Preserves artifact fields in memory store.
- Modify: `backend/packages/enterprise/postgres.py`
  - Writes artifact fields to Postgres.
- Modify: `backend/db/postgres/001_enterprise_core.sql`
  - Adds idempotent report artifact columns.
- Modify: `backend/packages/business_intel/release_gate.py`
  - Gates against core prose plus cards, not support/audit prose.
- Modify: `backend/packages/orchestrator/service.py`
  - Writes final quality account back to artifact and blocks legacy Markdown repair on V2 artifacts.
- Modify: `backend/app/routers/enterprise.py`
  - Adds export scopes.
- Modify: `frontend/src/api/types.ts`
  - Adds card and artifact types.
- Modify: `frontend/src/api/sse_types.ts`
  - Allows report events to include artifact payload.
- Modify: `frontend/src/stores/run.ts`
  - Applies artifact updates from SSE.
- Modify: `frontend/src/api/client.ts`
  - Adds report export scope parameter.
- Modify: `frontend/src/features/run-detail/RunReportReviewStudio.tsx`
  - Adds Report/Evidence/QA/Audit tabs and card display.
- Test: `backend/tests/unit/test_report_cards.py`
- Test: `backend/tests/unit/test_report_artifact_v2.py`
- Test: `backend/tests/unit/test_writer_hybrid_artifact.py`
- Test: `backend/tests/unit/test_enterprise_projection.py`
- Test: `backend/tests/unit/test_enterprise_store.py`
- Test: `backend/tests/unit/test_enterprise_postgres_config.py`
- Test: `backend/tests/unit/test_business_intel.py`
- Test: `backend/tests/unit/test_run_service.py`
- Test: `frontend/src/features/run-detail/RunReportReviewStudio.test.tsx`

## Task 1: Card Contracts And Deterministic Builders

**Files:**
- Create: `backend/packages/schema/report_cards.py`
- Create: `backend/packages/business_intel/report_card_builder.py`
- Create: `backend/packages/business_intel/section_brief_builder.py`
- Modify: `backend/packages/schema/__init__.py`
- Test: `backend/tests/unit/test_report_cards.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_report_cards.py`:

```python
from __future__ import annotations

import pytest

from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
from packages.schema.api_dto import RawSource, RunDetail
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
        raw_sources=[
            RawSource(
                id="raw-cursor-pricing",
                url="https://cursor.com/pricing",
                title="Cursor pricing",
                source_type="web",
                competitor="Cursor",
                dimension="pricing",
                snippet="Cursor publishes pricing.",
                confidence=0.91,
            )
        ],
    )


def test_claim_card_requires_sources_unless_gap() -> None:
    with pytest.raises(ValueError, match="source_ids"):
        ClaimCard(
            id="claim-missing-source",
            competitor="Cursor",
            dimension="pricing",
            claim="Cursor publishes pricing.",
            confidence=0.9,
            evidence_role="official_fact",
            evidence_strength="strong",
        )

    gap = ClaimCard(
        id="claim-gap",
        competitor="Cursor",
        dimension="persona",
        claim="Direct buyer interview evidence is missing.",
        confidence=0.35,
        evidence_role="evidence_gap",
        evidence_strength="gap",
    )
    assert gap.source_ids == []


def test_decision_card_requires_claim_cards() -> None:
    with pytest.raises(ValueError, match="claim_card_ids"):
        DecisionCard(
            id="decision-empty",
            decision_type="primary_recommendation",
            recommendation="Use Cursor.",
            recommendation_strength="tentative",
            winner="Cursor",
            alternatives=[],
            why_not={},
            rationale="No claim cards.",
            confidence=0.5,
        )


def test_builders_create_cards_and_briefs_from_current_run_shape() -> None:
    detail = _detail()

    claim_cards = build_claim_cards_from_run_detail(detail)
    decision_cards = build_decision_cards_from_claim_cards(detail, claim_cards)
    briefs = build_section_briefs(detail, claim_cards, decision_cards)

    assert claim_cards
    assert any(card.source_ids == ["raw-cursor-pricing"] for card in claim_cards)
    assert decision_cards
    assert decision_cards[0].claim_card_ids
    assert {brief.section_key for brief in briefs} >= {
        "executive_summary",
        "decision_summary",
        "competitor_deep_dives",
    }
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_cards.py -q
```

Expected:

```text
ImportError: cannot import name 'ClaimCard'
```

- [ ] **Step 3: Implement card models**

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
RecommendationStrength = Literal[
    "strong",
    "tentative",
    "watchlist",
    "insufficient_evidence",
]


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
            raise ValueError("evidence_gap cards must use evidence_strength='gap'")
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

- [ ] **Step 4: Implement deterministic card builders**

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
            sources = [
                source
                for source in detail.raw_sources
                if source.competitor == competitor and source.dimension == dimension
            ]
            if sources:
                source_ids = [source.id for source in sources[:8]]
                avg_confidence = sum(source.confidence for source in sources) / len(sources)
                cards.append(
                    ClaimCard(
                        id=_card_id("claim", detail.id, competitor, dimension, "supported"),
                        competitor=competitor,
                        dimension=dimension,
                        claim=f"{competitor} has collected {dimension} evidence available for competitive analysis.",
                        source_ids=source_ids,
                        confidence=min(0.95, max(0.5, avg_confidence)),
                        evidence_role="inference",
                        evidence_strength="medium" if avg_confidence < 0.85 else "strong",
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
    fallback_winner = detail.plan.competitors[0] if detail.plan.competitors else ""
    winner = supported[0].competitor if supported else fallback_winner
    alternatives = [name for name in detail.plan.competitors if name != winner]
    strength = "tentative" if supported else "insufficient_evidence"
    rationale = (
        f"{winner} has the strongest available claim-card support in the current run."
        if supported
        else "No supported claim cards are available, so a strong recommendation is not allowed."
    )
    if not claim_cards:
        return []
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
            why_not={
                name: "Lower or less direct card support in the current run."
                for name in alternatives
            },
            rationale=rationale,
            claim_card_ids=[card.id for card in supported[:12]] or [claim_cards[0].id],
            confidence=0.68 if supported else 0.3,
            risk_notes=[
                "Recommendation strength must stay tentative when evidence is weak, incomplete, or conflicted."
            ],
            produced_by="comparator",
        )
    ]


def _card_id(prefix: str, *parts: str) -> str:
    return stable_prefixed_id(prefix, "|".join(parts), length=16)
```

- [ ] **Step 5: Implement section brief builder**

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
            forbidden_overclaims=[
                "Do not upgrade tentative recommendations to strong recommendations."
            ],
            required_caveats=["State evidence limits when confidence is below 0.8."],
            citation_requirements=[
                "Every material claim must cite sources from referenced claim cards."
            ],
            output_language=detail.output_language,
        ),
        SectionBrief(
            section_key="decision_summary",
            required_claim_card_ids=claim_ids,
            required_decision_card_ids=decision_ids,
            questions=["Why this recommendation, and why not the alternatives?"],
            forbidden_overclaims=["Do not invent a winner outside decision cards."],
            required_caveats=["Mention conflicts and weak evidence."],
            citation_requirements=[
                "Tie recommendation prose to decision-card claim_card_ids."
            ],
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

Add these strings to `__all__`:

```python
"ClaimCard",
"DecisionCard",
"SectionBrief",
```

- [ ] **Step 7: Run tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_cards.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 8: Commit**

```bash
git add backend/packages/schema/report_cards.py backend/packages/business_intel/report_card_builder.py backend/packages/business_intel/section_brief_builder.py backend/packages/schema/__init__.py backend/tests/unit/test_report_cards.py
git commit -m "feat: add report card reasoning contracts"
```

## Task 2: Report Artifact v2 Schema And Assembler

**Files:**
- Create: `backend/packages/schema/report_artifact.py`
- Create: `backend/packages/agents/writer/artifact_assembler.py`
- Modify: `backend/packages/schema/__init__.py`
- Test: `backend/tests/unit/test_report_artifact_v2.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_report_artifact_v2.py`:

```python
from __future__ import annotations

from packages.agents.writer.artifact_assembler import assemble_report_artifact_v2
from packages.schema.report_artifact import build_legacy_report_artifact
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief


def _claim() -> ClaimCard:
    return ClaimCard(
        id="claim-1",
        competitor="Cursor",
        dimension="pricing",
        claim="Cursor pricing is supported.",
        source_ids=["raw-1"],
        confidence=0.82,
        evidence_role="official_fact",
        evidence_strength="medium",
    )


def _decision() -> DecisionCard:
    return DecisionCard(
        id="decision-1",
        decision_type="primary_recommendation",
        recommendation="Use Cursor as the primary trial candidate.",
        recommendation_strength="tentative",
        winner="Cursor",
        alternatives=[],
        why_not={},
        rationale="Cursor has the strongest available claim-card support.",
        claim_card_ids=["claim-1"],
        confidence=0.74,
    )


def _brief() -> SectionBrief:
    return SectionBrief(
        section_key="executive_summary",
        required_claim_card_ids=["claim-1"],
        required_decision_card_ids=["decision-1"],
        questions=["What should the reader do next?"],
    )


def test_assembler_builds_artifact_with_cards_and_layers() -> None:
    artifact = assemble_report_artifact_v2(
        run_id="run-1",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="AI coding tools",
        output_language="en-US",
        competitors=["Cursor"],
        dimensions=["pricing"],
        claim_cards=[_claim()],
        decision_cards=[_decision()],
        section_briefs=[_brief()],
        core_markdown="# Report\n\nUse Cursor. [source:raw-1]",
        support_markdown="# Evidence\n\nClaim cards are listed.",
        audit_markdown="# Audit\n\nNo blockers.",
    )

    assert artifact.artifact_version == "2"
    assert artifact.claim_cards[0].id == "claim-1"
    assert artifact.decision_cards[0].claim_card_ids == ["claim-1"]
    assert artifact.render_cache.core_markdown.startswith("# Report")
    assert "# Evidence" in artifact.render_cache.full_markdown


def test_legacy_adapter_preserves_original_markdown() -> None:
    artifact = build_legacy_report_artifact(
        report_md="# Legacy\n\nBody",
        run_id="run-old",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="Old topic",
        output_language="en-US",
        competitors=["Cursor"],
        dimensions=["pricing"],
    )

    assert artifact.artifact_version == "legacy"
    assert artifact.compatibility_report_md() == "# Legacy\n\nBody"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_artifact_v2.py -q
```

Expected:

```text
ImportError: cannot import name 'assemble_report_artifact_v2'
```

- [ ] **Step 3: Implement artifact schema**

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
    claim_card_ids: list[str] = Field(default_factory=list)
    decision_card_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
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
    return "\n\n".join(part.strip() for part in [core, support, audit] if part.strip())


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
        render_cache=ReportRenderCache(full_markdown=report_md),
    )
```

- [ ] **Step 4: Implement assembler**

Create `backend/packages/agents/writer/artifact_assembler.py`:

```python
from __future__ import annotations

from packages.schema.report_artifact import (
    ReportArtifactV2,
    ReportLayer,
    ReportRenderCache,
    join_report_layers,
)
from packages.schema.report_cards import ClaimCard, DecisionCard, SectionBrief


def assemble_report_artifact_v2(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    topic: str,
    output_language: str,
    competitors: list[str],
    dimensions: list[str],
    claim_cards: list[ClaimCard],
    decision_cards: list[DecisionCard],
    section_briefs: list[SectionBrief],
    core_markdown: str,
    support_markdown: str,
    audit_markdown: str,
) -> ReportArtifactV2:
    full_markdown = join_report_layers(core_markdown, support_markdown, audit_markdown)
    return ReportArtifactV2(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=topic,
        output_language=output_language,
        competitors=list(competitors),
        dimensions=list(dimensions),
        claim_cards=list(claim_cards),
        decision_cards=list(decision_cards),
        section_briefs=list(section_briefs),
        core_report=ReportLayer(markdown=core_markdown, section_keys=_section_keys(core_markdown)),
        support_appendix=ReportLayer(markdown=support_markdown, section_keys=_section_keys(support_markdown)),
        audit_log=ReportLayer(markdown=audit_markdown, section_keys=_section_keys(audit_markdown)),
        render_cache=ReportRenderCache(
            core_markdown=core_markdown,
            support_markdown=support_markdown,
            audit_markdown=audit_markdown,
            full_markdown=full_markdown,
        ),
    )


def _section_keys(markdown: str) -> list[str]:
    return [
        line.strip("# ").strip()
        for line in markdown.splitlines()
        if line.startswith("## ")
    ]
```

- [ ] **Step 5: Export artifact models**

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

- [ ] **Step 6: Run tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_artifact_v2.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit**

```bash
git add backend/packages/schema/report_artifact.py backend/packages/agents/writer/artifact_assembler.py backend/packages/schema/__init__.py backend/tests/unit/test_report_artifact_v2.py
git commit -m "feat: add hybrid report artifact model"
```

## Task 3: API, Persistence, And Projection

**Files:**
- Modify: `backend/packages/schema/api_dto.py`
- Modify: `backend/packages/schema/enterprise.py`
- Modify: `backend/packages/enterprise/projection.py`
- Modify: `backend/packages/enterprise/store.py`
- Modify: `backend/packages/enterprise/postgres.py`
- Modify: `backend/db/postgres/001_enterprise_core.sql`
- Test: `backend/tests/unit/test_enterprise_projection.py`
- Test: `backend/tests/unit/test_enterprise_store.py`
- Test: `backend/tests/unit/test_enterprise_postgres_config.py`

- [ ] **Step 1: Write failing projection test**

Add to `backend/tests/unit/test_enterprise_projection.py`:

```python
def test_enterprise_projection_stores_hybrid_artifact_fields() -> None:
    detail = _run_detail(report_md="# Report\n\nUse Cursor. [source:pricing-1]")
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
    assert version.report_artifact["claim_cards"]
    assert version.report_artifact["decision_cards"]
    assert version.core_report_md
    assert version.full_report_md == version.report_md
```

- [ ] **Step 2: Write failing Postgres schema test**

Add to `backend/tests/unit/test_enterprise_postgres_config.py`:

```python
from pathlib import Path


def test_report_versions_schema_contains_hybrid_artifact_columns() -> None:
    sql = Path("backend/db/postgres/001_enterprise_core.sql").read_text(encoding="utf-8")

    assert "core_report_md TEXT NOT NULL DEFAULT ''" in sql
    assert "support_appendix_md TEXT NOT NULL DEFAULT ''" in sql
    assert "audit_log_md TEXT NOT NULL DEFAULT ''" in sql
    assert "full_report_md TEXT NOT NULL DEFAULT ''" in sql
    assert "report_artifact JSONB NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "ADD COLUMN IF NOT EXISTS report_artifact" in sql
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_projection.py::test_enterprise_projection_stores_hybrid_artifact_fields backend/tests/unit/test_enterprise_postgres_config.py::test_report_versions_schema_contains_hybrid_artifact_columns -q
```

Expected:

```text
At least one assertion fails because artifact fields are missing.
```

- [ ] **Step 4: Add DTO and report version fields**

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
    core_report_md: str = ""
    support_appendix_md: str = ""
    audit_log_md: str = ""
    full_report_md: str = ""
    report_artifact: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 5: Add SQL columns**

Modify `backend/db/postgres/001_enterprise_core.sql` `report_versions` table:

```sql
    report_md TEXT NOT NULL DEFAULT '',
    core_report_md TEXT NOT NULL DEFAULT '',
    support_appendix_md TEXT NOT NULL DEFAULT '',
    audit_log_md TEXT NOT NULL DEFAULT '',
    full_report_md TEXT NOT NULL DEFAULT '',
    report_artifact JSONB NOT NULL DEFAULT '{}'::jsonb,
```

Add idempotent migration lines near existing `ALTER TABLE report_versions` lines:

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

- [ ] **Step 6: Project artifact fields**

In `backend/packages/enterprise/projection.py`, import:

```python
from packages.agents.writer.artifact_assembler import assemble_report_artifact_v2
from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
```

Before constructing `ReportVersionRecord`, add:

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
    artifact = detail.report_artifact or assemble_report_artifact_v2(
        run_id=detail.id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=detail.topic,
        output_language=detail.output_language,
        competitors=list(detail.plan.competitors),
        dimensions=list(detail.plan.dimensions),
        claim_cards=claim_cards,
        decision_cards=decision_cards,
        section_briefs=section_briefs,
        core_markdown=normalized_report.report_md,
        support_markdown=_render_card_support_markdown(claim_cards, decision_cards),
        audit_markdown="## Audit\n\n- Artifact assembled from hybrid report pipeline.",
    )
    report_md = artifact.compatibility_report_md()
```

Add helper:

```python
def _render_card_support_markdown(
    claim_cards: list[ClaimCard],
    decision_cards: list[DecisionCard],
) -> str:
    lines = ["## Evidence And Decision Cards", ""]
    lines.append("### Claim Cards")
    for card in claim_cards:
        lines.append(
            f"- `{card.id}` {card.competitor or 'General'} / {card.dimension or 'general'}: "
            f"{card.claim}"
        )
    lines.append("")
    lines.append("### Decision Cards")
    for card in decision_cards:
        lines.append(f"- `{card.id}` {card.recommendation_strength}: {card.recommendation}")
    return "\n".join(lines).strip() + "\n"
```

Use these fields in `ReportVersionRecord`:

```python
        report_md=report_md,
        core_report_md=artifact.render_cache.core_markdown,
        support_appendix_md=artifact.render_cache.support_markdown,
        audit_log_md=artifact.render_cache.audit_markdown,
        full_report_md=artifact.render_cache.full_markdown,
        report_artifact=artifact.model_dump(mode="json"),
```

- [ ] **Step 7: Update Postgres upsert**

In `backend/packages/enterprise/postgres.py`, update `_upsert_report_version()` to insert and update:

```python
core_report_md, support_appendix_md, audit_log_md, full_report_md, report_artifact
```

Use values:

```python
self._text(report.core_report_md),
self._text(report.support_appendix_md),
self._text(report.audit_log_md),
self._text(report.full_report_md),
self._json(report.report_artifact),
```

- [ ] **Step 8: Run tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_enterprise_projection.py::test_enterprise_projection_stores_hybrid_artifact_fields backend/tests/unit/test_enterprise_postgres_config.py::test_report_versions_schema_contains_hybrid_artifact_columns -q
```

Expected:

```text
2 passed
```

- [ ] **Step 9: Commit**

```bash
git add backend/packages/schema/api_dto.py backend/packages/schema/enterprise.py backend/packages/enterprise/projection.py backend/packages/enterprise/store.py backend/packages/enterprise/postgres.py backend/db/postgres/001_enterprise_core.sql backend/tests/unit/test_enterprise_projection.py backend/tests/unit/test_enterprise_postgres_config.py backend/tests/unit/test_enterprise_store.py
git commit -m "feat: persist hybrid report artifacts"
```

## Task 4: Writer Consumes Briefs And Emits Artifact

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_writer_hybrid_artifact.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing writer tests**

Create `backend/tests/unit/test_writer_hybrid_artifact.py`:

```python
from __future__ import annotations

from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
from test_report_cards import _detail


def test_section_briefs_are_built_before_writer_prose() -> None:
    detail = _detail()
    claim_cards = build_claim_cards_from_run_detail(detail)
    decision_cards = build_decision_cards_from_claim_cards(detail, claim_cards)
    briefs = build_section_briefs(detail, claim_cards, decision_cards)

    assert briefs
    assert briefs[0].required_claim_card_ids or briefs[0].required_decision_card_ids
```

Add to `backend/tests/unit/test_run_service.py` near writer tests:

```python
@pytest.mark.asyncio
async def test_writer_report_updated_event_includes_hybrid_artifact(monkeypatch) -> None:
    service = RunService(settings=_settings(writer_structured_report_enabled=True))
    record = _create_run_record(service, run_id="run-hybrid-artifact")
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fake_schema_contract_report(self, record, evidence_pack_result, timeout_seconds):
        return "# Report\n\nUse Cursor cautiously. [source:cursor-pricing]"

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_schema_contract_segment_report",
        fake_schema_contract_report,
    )

    await service._run_writer(record)

    artifact = record.detail.report_artifact
    assert artifact is not None
    assert artifact.artifact_version == "2"
    assert artifact.claim_cards
    assert artifact.decision_cards
    assert artifact.section_briefs
    assert record.detail.report_md == artifact.render_cache.full_markdown
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_hybrid_artifact.py backend/tests/unit/test_run_service.py::test_writer_report_updated_event_includes_hybrid_artifact -q
```

Expected:

```text
The run service test fails because report_artifact is missing.
```

- [ ] **Step 3: Build cards and briefs in writer**

In `backend/packages/agents/writer/logic.py`, import:

```python
from packages.agents.writer.artifact_assembler import assemble_report_artifact_v2
from packages.business_intel.report_card_builder import (
    build_claim_cards_from_run_detail,
    build_decision_cards_from_claim_cards,
)
from packages.business_intel.section_brief_builder import build_section_briefs
```

Before calling the segment writer:

```python
claim_cards = build_claim_cards_from_run_detail(detail)
decision_cards = build_decision_cards_from_claim_cards(detail, claim_cards)
section_briefs = build_section_briefs(detail, claim_cards, decision_cards)
```

Pass section brief context into the writer prompt by adding this to the writer
context JSON:

```python
"section_briefs": [brief.model_dump(mode="json") for brief in section_briefs],
"decision_cards": [card.model_dump(mode="json") for card in decision_cards],
"claim_cards": [card.model_dump(mode="json") for card in claim_cards],
```

Add prompt instruction:

```text
The claim cards and decision cards are binding. Do not introduce material facts,
recommendations, winners, or recommendation strength that are not supported by
the cards. If cards are weak or incomplete, write the limitation explicitly.
```

- [ ] **Step 4: Assemble artifact after prose**

After final `detail.report_md` is selected:

```python
artifact = assemble_report_artifact_v2(
    run_id=detail.id,
    workspace_id=detail.workspace_id,
    project_id=detail.project_id or "",
    topic=detail.topic,
    output_language=detail.output_language,
    competitors=list(detail.plan.competitors),
    dimensions=list(detail.plan.dimensions),
    claim_cards=claim_cards,
    decision_cards=decision_cards,
    section_briefs=section_briefs,
    core_markdown=detail.report_md,
    support_markdown=_render_writer_card_support_markdown(claim_cards, decision_cards),
    audit_markdown="## Audit\n\n- Writer emitted hybrid Report Artifact v2.",
)
detail.report_artifact = artifact
detail.report_md = artifact.compatibility_report_md()
```

Add helper in writer logic:

```python
def _render_writer_card_support_markdown(
    claim_cards: Sequence[ClaimCard],
    decision_cards: Sequence[DecisionCard],
) -> str:
    lines = ["## Evidence And Decision Cards", "", "### Claim Cards"]
    for card in claim_cards:
        lines.append(
            f"- `{card.id}` {card.competitor or 'General'} / {card.dimension or 'general'}: {card.claim}"
        )
    lines.extend(["", "### Decision Cards"])
    for card in decision_cards:
        lines.append(f"- `{card.id}` {card.recommendation_strength}: {card.recommendation}")
    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 5: Include artifact in messages and SSE**

Change writer agent message payload schema to:

```python
payload_schema="ReportArtifactV2"
```

Include:

```python
"report_artifact": artifact.model_dump(mode="json")
```

in both the agent message and `report_updated` event payload.

- [ ] **Step 6: Run tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_hybrid_artifact.py backend/tests/unit/test_run_service.py::test_writer_report_updated_event_includes_hybrid_artifact -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit**

```bash
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_hybrid_artifact.py backend/tests/unit/test_run_service.py
git commit -m "feat: emit hybrid report artifacts from writer"
```

## Task 5: Release Gate And Quality Scope

**Files:**
- Modify: `backend/packages/business_intel/release_gate.py`
- Modify: `backend/packages/orchestrator/service.py`
- Test: `backend/tests/unit/test_business_intel.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing scope tests**

Add to `backend/tests/unit/test_business_intel.py`:

```python
def test_release_gate_ignores_support_cards_as_core_prose() -> None:
    report = _report_version(
        report_md="# Core\n\nCursor pricing is supported. [source:evidence-1]",
    ).model_copy(
        update={
            "core_report_md": "# Core\n\nCursor pricing is supported. [source:evidence-1]",
            "support_appendix_md": "## Evidence\n\n- [ ] Checklist text without claim support.",
            "full_report_md": "# Core\n\nCursor pricing is supported. [source:evidence-1]\n\n## Evidence\n\n- [ ] Checklist text without claim support.",
            "report_artifact": {
                "artifact_version": "2",
                "claim_cards": [
                    {
                        "id": "claim-1",
                        "competitor": "Cursor",
                        "dimension": "pricing",
                        "claim": "Cursor pricing is supported.",
                        "source_ids": ["evidence-1"],
                        "confidence": 0.82,
                        "evidence_role": "official_fact",
                        "evidence_strength": "medium",
                        "conflict_notes": [],
                        "applicability_scope": "pricing",
                        "caveats": [],
                        "produced_by": "analyst",
                        "created_at": "2026-06-21T00:00:00",
                    }
                ],
                "decision_cards": [],
                "section_briefs": [],
            },
        }
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[_competitor()],
        evidence=[_evidence("evidence-1")],
        claims=[_claim("claim-1", evidence_ids=["evidence-1"])],
    )

    assert all("Checklist text" not in issue.message for issue in gate.issues)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_business_intel.py::test_release_gate_ignores_support_cards_as_core_prose -q
```

Expected:

```text
The test fails if release gate still scans full report_md.
```

- [ ] **Step 3: Add V2 core text selector**

In `backend/packages/business_intel/release_gate.py`:

```python
def _is_v2_report(report_version: ReportVersionRecord) -> bool:
    return dict(report_version.report_artifact).get("artifact_version") == "2"


def _report_core_markdown(report_version: ReportVersionRecord) -> str:
    if _is_v2_report(report_version) and report_version.core_report_md.strip():
        return report_version.core_report_md
    return report_version.report_md
```

Replace report text reads in structure, depth, richness, missing citation, and
strong conclusion checks with `_report_core_markdown(report_version)`.

- [ ] **Step 4: Stop release-gate Markdown mutation for V2**

In `backend/packages/orchestrator/service.py`, where
`apply_release_gate_warning_report_repair()` is called:

```python
is_v2_report = (
    dict(projection.report_version.report_artifact).get("artifact_version") == "2"
)
if is_v2_report:
    report_repair_metadata = {"changed": False, "reason": "v2_artifact_audit_only"}
else:
    report_repair = apply_release_gate_warning_report_repair(...)
    report_repair_metadata = report_repair.metadata()
```

Use `report_repair_metadata` in `release_gate_metadata["warning_repair"]`.

- [ ] **Step 5: Run tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_business_intel.py::test_release_gate_ignores_support_cards_as_core_prose -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/packages/business_intel/release_gate.py backend/packages/orchestrator/service.py backend/tests/unit/test_business_intel.py backend/tests/unit/test_run_service.py
git commit -m "fix: scope release gate to hybrid report core"
```

## Task 6: Frontend And Export Scopes

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/sse_types.ts`
- Modify: `frontend/src/stores/run.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/run-detail/RunReportReviewStudio.tsx`
- Modify: `backend/app/routers/enterprise.py`
- Test: `frontend/src/features/run-detail/RunReportReviewStudio.test.tsx`
- Test: `backend/tests/unit/test_enterprise_store.py`

- [ ] **Step 1: Write failing frontend test**

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

describe("RunReportReviewStudio hybrid artifact", () => {
  it("opens on the core report and exposes cards in evidence", async () => {
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
          report_md: "# Core\n\nCore decision",
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
              applicability_scope: "pricing",
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
              rationale: "Cursor has card support.",
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
            support_appendix: { markdown: "# Evidence\n\nSupport text", claims: [], section_keys: [], metadata: {} },
            audit_log: { markdown: "# Audit\n\nNo blockers", claims: [], section_keys: [], metadata: {} },
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
              support_markdown: "# Evidence\n\nSupport text",
              audit_markdown: "# Audit\n\nNo blockers",
              full_markdown: "# Core\n\nCore decision\n\n# Evidence\n\nSupport text\n\n# Audit\n\nNo blockers",
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
    expect(screen.queryByText("Cursor pricing is supported.")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Evidence/i }));

    expect(screen.getByText("Cursor pricing is supported.")).toBeInTheDocument();
    expect(screen.getByText("Use Cursor as the primary trial candidate.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run frontend test to verify failure**

Run:

```bash
cd frontend
pnpm test src/features/run-detail/RunReportReviewStudio.test.tsx
cd ..
```

Expected:

```text
The test fails because artifact tabs/cards are not rendered.
```

- [ ] **Step 3: Add TypeScript types**

Modify `frontend/src/api/types.ts` with `ClaimCard`, `DecisionCard`,
`SectionBrief`, `ReportArtifactV2`, and add `report_artifact?: ReportArtifactV2
| null` to `RunDetail`.

Use the field names from the test fixture exactly.

- [ ] **Step 4: Add SSE artifact handling**

Modify `frontend/src/api/sse_types.ts` event payload:

```ts
report_artifact?: RunDetail["report_artifact"];
```

Modify `frontend/src/stores/run.ts`:

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

- [ ] **Step 5: Add report tabs and card panel**

Modify `frontend/src/features/run-detail/RunReportReviewStudio.tsx`:

```tsx
type ReportLayerTab = "report" | "evidence" | "qa" | "audit";

function artifactMarkdown(detail: RunDetailRecord, tab: ReportLayerTab) {
  const artifact = detail.report_artifact;
  if (!artifact || artifact.artifact_version !== "2") return detail.report_md ?? "";
  if (tab === "report") return artifact.render_cache.core_markdown || artifact.core_report.markdown;
  if (tab === "evidence") return artifact.render_cache.support_markdown || artifact.support_appendix.markdown;
  if (tab === "qa") return artifact.render_cache.audit_markdown || artifact.audit_log.markdown;
  return artifact.render_cache.full_markdown || detail.report_md || "";
}

function ArtifactCardsPanel({ artifact }: { artifact: NonNullable<RunDetailRecord["report_artifact"]> }) {
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

Render layer buttons and show `ArtifactCardsPanel` only on Evidence tab.

- [ ] **Step 6: Add export scope**

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

Modify `backend/app/routers/enterprise.py` export endpoint with `scope: str =
"full"` and choose Markdown from `core_report_md`, `support_appendix_md`,
`audit_log_md`, or `full_report_md`.

- [ ] **Step 7: Run frontend and export tests**

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

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/sse_types.ts frontend/src/stores/run.ts frontend/src/api/client.ts frontend/src/features/run-detail/RunReportReviewStudio.tsx backend/app/routers/enterprise.py frontend/src/features/run-detail/RunReportReviewStudio.test.tsx backend/tests/unit/test_enterprise_store.py
git commit -m "feat: show hybrid report artifact layers"
```

## Task 7: Legacy Guard And Verification

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/packages/agents/writer/repair.py`
- Modify: `backend/packages/agents/writer/quality_preflight.py`
- Test: `backend/tests/unit/test_run_service.py`
- Test: `backend/tests/unit/test_writer_hybrid_artifact.py`

- [ ] **Step 1: Add legacy guard tests**

Add to `backend/tests/unit/test_writer_hybrid_artifact.py`:

```python
def test_hybrid_artifact_repair_targets_are_not_markdown_lines() -> None:
    from packages.agents.writer.repair import structured_repair_target_for_issue
    from packages.schema.models import QCIssue

    issue = QCIssue(
        id="issue-line",
        severity="warn",
        message="Support checklist line is noisy.",
        target_agent="writer",
        field_path="report_md.line[12]",
        detected_by="release_gate",
    )

    assert structured_repair_target_for_issue(issue) != "report_md"
```

- [ ] **Step 2: Run guard test**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_hybrid_artifact.py::test_hybrid_artifact_repair_targets_are_not_markdown_lines -q
```

Expected:

```text
The test fails if repair still maps V2 work to report_md.
```

- [ ] **Step 3: Guard legacy Markdown patches**

Ensure V2 artifact paths bypass these main-path repairs:

```python
_ensure_report_required_sections
_backfill_*_section
_ensure_report_claim_citations
_repair_report_source_token
_harden_schema_contract_report_markdown
_repair_schema_contract_publication_issues
apply_release_gate_warning_report_repair
```

Use this guard:

```python
def _is_hybrid_report_artifact(detail: RunDetail) -> bool:
    return (
        detail.report_artifact is not None
        and detail.report_artifact.artifact_version == "2"
    )
```

For V2, validation failures should target cards, briefs, section prose,
assembler, or audit. They should not mutate `report_md` directly.

- [ ] **Step 4: Run focused backend tests**

Run:

```bash
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_report_cards.py backend/tests/unit/test_report_artifact_v2.py backend/tests/unit/test_writer_hybrid_artifact.py backend/tests/unit/test_enterprise_projection.py::test_enterprise_projection_stores_hybrid_artifact_fields backend/tests/unit/test_business_intel.py::test_release_gate_ignores_support_cards_as_core_prose -q
```

Expected:

```text
All selected tests pass.
```

- [ ] **Step 5: Run real-run verification**

Restart with repository scripts. First inspect available scripts:

```bash
Get-ChildItem scripts | Select-Object Name
```

Use the existing stop/start scripts, then run a real report from the UI or API.

Audit the run:

```text
detail.report_artifact.artifact_version == "2"
detail.report_artifact.claim_cards is not empty
detail.report_artifact.decision_cards is not empty
detail.report_artifact.section_briefs is not empty
detail.report_md == detail.report_artifact.render_cache.full_markdown
core recommendation traces to a decision card
support checklist lines are not release-gate business claims
frontend opens on Report tab
Evidence tab shows claim and decision cards
```

- [ ] **Step 6: Commit verification fixes if needed**

Run:

```bash
git status --short
```

If verification exposes a new code defect, write a focused failing test and a
small fix, then commit exact changed files. If verification produces no code
changes, do not create an empty commit.

## Self-Review Checklist

- Task 1 implements claim/decision/brief reasoning contracts.
- Task 2 implements artifact product boundary.
- Task 3 persists and projects artifact data.
- Task 4 makes writer consume briefs and emit artifacts.
- Task 5 scopes release gate to core/cards.
- Task 6 exposes artifact layers and cards in frontend/export.
- Task 7 prevents legacy Markdown repairs from owning V2 reports.
- No task starts by splitting Markdown as the fact source.
- `report_md` remains compatibility output only.
