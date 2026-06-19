# Writer Evidence Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the writer's full raw-source prompt payload with a structured, full-coverage evidence pack plus segmented writer routing so rich reports stop timing out on large evidence sets.

**Architecture:** Add a focused `backend/packages/agents/writer/evidence_pack.py` module that builds a serializable `WriterEvidencePackResult` from `RunDetail` without calling the LLM or emitting events. Integrate the pack into initial writer and section repair prompts, emit preflight telemetry in writer orchestration, and route oversized packs through section-scoped writer calls with citation validation. Keep complete raw sources in persisted run data; the writer receives full-coverage projections, not full repeated source text.

**Tech Stack:** Python 3.11, Pydantic v2 models already used by `packages.schema`, pytest async tests under `backend/tests/unit`, existing `RunService` writer mixin, conda Python at `D:\Anaconda\envs\bd-competiscope-v2\python.exe`.

---

## Scope And Boundaries

This plan implements the approved spec at `docs/superpowers/specs/2026-06-16-writer-evidence-pack-design.md`.

Do not stage or commit generated DB/output artifacts. The workspace currently has unrelated untracked artifacts such as `outputs/`, `data/artifacts/`, and `.docx` files. Leave them alone.

The plan intentionally does not change collector breadth, release gate rules, or report target length. It also does not restore writer fallback reports.

## File Structure

- Create `backend/packages/agents/writer/evidence_pack.py`
  - Owns Pydantic models, deterministic evidence-pack construction, compaction metrics, segment selection, appendix rows, and citation validation helpers.
  - Must not call the LLM.
  - Must not emit run events directly.

- Modify `backend/packages/agents/writer/logic.py`
  - Imports the evidence-pack builder and helper functions.
  - Replaces initial writer's old full source digest context with evidence pack context.
  - Emits writer preflight telemetry.
  - Uses evidence pack context in section repair.
  - Adds segmented writer routing for oversized packs.
  - Generates source appendix from registry metadata instead of full raw snippets.

- Create `backend/tests/unit/test_writer_evidence_pack.py`
  - Unit tests for the new module, independent from `RunService` where possible.

- Modify `backend/tests/unit/test_run_service.py`
  - Integration-style tests for writer prompt context, preflight events, section repair context, segmented routing, and anti-regression preservation.

---

### Task 1: Evidence Pack Models And Source Registry

**Files:**
- Create: `backend/packages/agents/writer/evidence_pack.py`
- Create: `backend/tests/unit/test_writer_evidence_pack.py`

- [ ] **Step 1: Write failing tests for source registry coverage and noisy source handling**

Add this new test file:

```python
from __future__ import annotations

import json

from packages.agents.writer.evidence_pack import build_writer_evidence_pack
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource


def _detail_with_sources(sources: list[RawSource]) -> RunDetail:
    return RunDetail(
        id="run-evidence-pack",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at="2026-06-16T00:00:00",
        updated_at="2026-06-16T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Cursor"],
            dimensions=["pricing", "persona"],
        ),
        raw_sources=sources,
    )


def test_evidence_pack_source_registry_represents_every_accepted_source() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.com/pricing",
            snippet="Cursor Pro costs $20 per month for individual developers.",
            content_hash="cursor-pricing-hash",
            confidence=0.96,
        ),
        RawSource(
            id="cursor-persona",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona interview",
            snippet=(
                "Enterprise engineering managers evaluate Cursor for repository-aware "
                "agentic coding, security review, onboarding friction, and budget control."
            ),
            content_hash="cursor-persona-hash",
            confidence=0.82,
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))

    assert result.pack.schema_version == "writer_evidence_pack.v1"
    assert result.metrics.raw_source_count == 2
    assert result.metrics.represented_source_count == 2
    assert result.metrics.dropped_source_count == 0
    registry_by_id = {item.id: item for item in result.pack.source_registry}
    assert set(registry_by_id) == {"cursor-pricing", "cursor-persona"}
    assert registry_by_id["cursor-pricing"].represented_by
    assert registry_by_id["cursor-persona"].represented_by
    assert registry_by_id["cursor-pricing"].no_signal_reason is None


def test_evidence_pack_marks_noisy_source_without_inventing_signal() -> None:
    source = RawSource(
        id="cursor-noisy",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing navigation",
        snippet="Skip to content Navigation Menu Sign in Cookie Privacy policy",
        content_hash="cursor-noisy-hash",
        confidence=0.9,
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))

    registry_item = result.pack.source_registry[0]
    assert registry_item.id == "cursor-noisy"
    assert registry_item.represented_by == []
    assert registry_item.no_signal_reason == "no_clean_business_signal"
    assert result.metrics.no_signal_source_count == 1
    assert result.metrics.dropped_source_count == 0
    assert json.loads(result.to_prompt_json())["coverage"]["raw_source_count"] == 1
```

- [ ] **Step 2: Run tests and verify they fail because the module does not exist**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.agents.writer.evidence_pack'`.

- [ ] **Step 3: Implement minimal evidence pack models and source registry builder**

Create `backend/packages/agents/writer/evidence_pack.py` with this starting implementation:

```python
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource


SCHEMA_VERSION = "writer_evidence_pack.v1"
QUOTE_EXCERPT_LIMIT = 500
UNSTRUCTURED_SIGNAL_LIMIT = 420
SOURCE_NOTE_LIMIT = 180
GROUP_TARGET_CHARS = 12_000
SINGLE_SOURCE_TARGET_CHARS = 8_000
SINGLE_CALL_CONTEXT_TARGET_CHARS = 160_000
SEGMENT_INPUT_TARGET_CHARS = 90_000


class WriterSourceRegistryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    competitor: str
    covered_competitors: list[str] = Field(default_factory=list)
    dimension: str
    source_type: str
    title: str
    url: str | None = None
    confidence: float
    candidate_origin: str = "unknown"
    quality_score: float = 0.0
    short_source_note: str = ""
    has_normalized_fields: bool = False
    has_community_clusters: bool = False
    represented_by: list[str] = Field(default_factory=list)
    no_signal_reason: str | None = None


class WriterQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    excerpt: str
    full_text_source_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    used_by_fact_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_quote_chars: int = 0


class WriterFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    competitor: str
    dimension: str
    values: dict[str, object] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    quote_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class WriterUnstructuredSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    competitor: str
    dimension: str
    source_type: str
    signal_summary: str
    salient_terms: list[str] = Field(default_factory=list)
    confidence: float
    quote_ids: list[str] = Field(default_factory=list)


class WriterKBSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    competitor: str
    dimension: str
    text: str
    source_ids: list[str] = Field(default_factory=list)
    merged_into: str | None = None


class WriterConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    claim_area: str
    positions: dict[str, str] = Field(default_factory=dict)
    source_ids_by_position: dict[str, list[str]] = Field(default_factory=dict)
    confidence_by_position: dict[str, float] = Field(default_factory=dict)
    resolution_status: Literal["unresolved", "resolved"] = "unresolved"


class WriterEvidenceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    dimension: str
    source_ids: list[str] = Field(default_factory=list)
    official_source_ids: list[str] = Field(default_factory=list)
    community_source_ids: list[str] = Field(default_factory=list)
    user_research_source_ids: list[str] = Field(default_factory=list)
    facts: list[WriterFact] = Field(default_factory=list)
    unstructured_signals: list[WriterUnstructuredSignal] = Field(default_factory=list)
    kb_signals: list[WriterKBSignal] = Field(default_factory=list)
    quotes: list[WriterQuote] = Field(default_factory=list)
    conflicts: list[WriterConflict] = Field(default_factory=list)
    confidence_summary: dict[str, float] = Field(default_factory=dict)
    coverage_notes: list[str] = Field(default_factory=list)


class WriterEvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    source_registry: list[WriterSourceRegistryItem] = Field(default_factory=list)
    groups: list[WriterEvidenceGroup] = Field(default_factory=list)
    quotes: list[WriterQuote] = Field(default_factory=list)
    matrix: dict[str, object] = Field(default_factory=dict)
    coverage: dict[str, object] = Field(default_factory=dict)


class WriterEvidencePackMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writer_evidence_pack_chars: int = 0
    source_registry_count: int = 0
    represented_source_count: int = 0
    raw_source_count: int = 0
    dropped_source_count: int = 0
    no_signal_source_count: int = 0
    kb_slice_count: int = 0
    represented_kb_slice_count: int = 0
    dropped_kb_slice_count: int = 0
    largest_source_projection_chars: int = 0
    largest_group_chars: int = 0
    largest_quote_projection_chars: int = 0
    deduped_quote_count: int = 0
    deduped_fact_count: int = 0
    segmented_writer_required: bool = False


class WriterEvidencePackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack: WriterEvidencePack
    metrics: WriterEvidencePackMetrics
    warnings: list[str] = Field(default_factory=list)

    def to_prompt_json(self) -> str:
        return json.dumps(self.pack.model_dump(mode="json"), ensure_ascii=False)

    def telemetry_payload(self) -> dict[str, object]:
        payload = self.metrics.model_dump(mode="json")
        payload["preflight_warnings"] = list(self.warnings)
        return payload


USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_user_note",
    "manual_note",
    "manual",
}
OFFICIAL_SOURCE_TYPES = {"webpage_verified", "official_docs", "official_webpage"}
COMMUNITY_SOURCE_TYPES = {
    "community_forum",
    "github_discussion",
    "reddit_thread",
    "snippet_only",
}


def build_writer_evidence_pack(detail: RunDetail) -> WriterEvidencePackResult:
    builder = _WriterEvidencePackBuilder(detail)
    return builder.build()


class _WriterEvidencePackBuilder:
    def __init__(self, detail: RunDetail) -> None:
        self.detail = detail
        self.registry_by_id: dict[str, WriterSourceRegistryItem] = {}
        self.groups: dict[tuple[str, str], WriterEvidenceGroup] = {}
        self.quotes_by_key: dict[str, WriterQuote] = {}
        self.warnings: list[str] = []
        self.deduped_quote_count = 0
        self.deduped_fact_count = 0

    def build(self) -> WriterEvidencePackResult:
        for source in self.detail.raw_sources:
            self._register_source(source)
            self._project_source(source)
        pack = WriterEvidencePack(
            source_registry=list(self.registry_by_id.values()),
            groups=list(self.groups.values()),
            quotes=list(self.quotes_by_key.values()),
            matrix=self._matrix_digest(),
        )
        metrics = self._metrics(pack)
        pack.coverage = metrics.model_dump(mode="json")
        metrics = self._metrics(pack)
        return WriterEvidencePackResult(pack=pack, metrics=metrics, warnings=self.warnings)

    def _register_source(self, source: RawSource) -> None:
        fields = normalized_fields_from_source(source)
        item = WriterSourceRegistryItem(
            id=source.id,
            competitor=source.competitor,
            covered_competitors=list(source.covered_competitors),
            dimension=source.dimension,
            source_type=source.source_type,
            title=source.title,
            url=str(source.url) if source.url else None,
            confidence=round(source.confidence, 3),
            candidate_origin=source.candidate_origin,
            quality_score=round(source.quality_score, 3),
            short_source_note=_trim(_clean(source.title), SOURCE_NOTE_LIMIT),
            has_normalized_fields=bool(fields),
            has_community_clusters=bool(source.metadata.get("community_claim_clusters")),
        )
        self.registry_by_id[source.id] = item
        group = self._group(source.competitor, source.dimension)
        group.source_ids = _unique([*group.source_ids, source.id])
        if source.source_type.casefold() in OFFICIAL_SOURCE_TYPES:
            group.official_source_ids = _unique([*group.official_source_ids, source.id])
        if source.source_type.casefold() in COMMUNITY_SOURCE_TYPES or source.metadata.get("community_evidence"):
            group.community_source_ids = _unique([*group.community_source_ids, source.id])
        if source.source_type.casefold() in USER_RESEARCH_SOURCE_TYPES:
            group.user_research_source_ids = _unique([*group.user_research_source_ids, source.id])

    def _project_source(self, source: RawSource) -> None:
        clean_snippet = source_business_snippet(
            source,
            dimension=source.dimension,
            limit=UNSTRUCTURED_SIGNAL_LIMIT,
        )
        if clean_snippet:
            signal = WriterUnstructuredSignal(
                id=f"signal:{source.id}",
                source_id=source.id,
                competitor=source.competitor,
                dimension=source.dimension,
                source_type=source.source_type,
                signal_summary=clean_snippet,
                salient_terms=_salient_terms(clean_snippet),
                confidence=round(source.confidence, 3),
            )
            self._group(source.competitor, source.dimension).unstructured_signals.append(signal)
            self._mark_source_represented(source.id, signal.id)
        else:
            self.registry_by_id[source.id].no_signal_reason = "no_clean_business_signal"

    def _group(self, competitor: str, dimension: str) -> WriterEvidenceGroup:
        key = (competitor, dimension)
        if key not in self.groups:
            self.groups[key] = WriterEvidenceGroup(
                competitor=competitor,
                dimension=dimension,
            )
        return self.groups[key]

    def _mark_source_represented(self, source_id: str, item_id: str) -> None:
        item = self.registry_by_id[source_id]
        item.represented_by = _unique([*item.represented_by, item_id])
        item.no_signal_reason = None

    def _matrix_digest(self) -> dict[str, object]:
        matrix = self.detail.comparison_matrix
        if matrix is None:
            return {"winner_by_dimension": {}, "summary": [], "cells": []}
        return {
            "winner_by_dimension": dict(matrix.winner_by_dimension),
            "summary": list(matrix.summary),
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "value": _trim(str(cell.value), 1200),
                    "source_ids": list(cell.source_ids),
                    "confidence": round(cell.confidence, 3),
                }
                for cell in matrix.cells
            ],
        }

    def _metrics(self, pack: WriterEvidencePack) -> WriterEvidencePackMetrics:
        prompt_json = json.dumps(pack.model_dump(mode="json"), ensure_ascii=False)
        group_sizes = [
            len(json.dumps(group.model_dump(mode="json"), ensure_ascii=False))
            for group in pack.groups
        ]
        quote_sizes = [
            len(json.dumps(quote.model_dump(mode="json"), ensure_ascii=False))
            for quote in pack.quotes
        ]
        represented_count = sum(1 for item in pack.source_registry if item.represented_by)
        no_signal_count = sum(1 for item in pack.source_registry if item.no_signal_reason)
        return WriterEvidencePackMetrics(
            writer_evidence_pack_chars=len(prompt_json),
            source_registry_count=len(pack.source_registry),
            represented_source_count=represented_count,
            raw_source_count=len(self.detail.raw_sources),
            dropped_source_count=0,
            no_signal_source_count=no_signal_count,
            largest_source_projection_chars=max(
                (
                    len(json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
                    for item in pack.source_registry
                ),
                default=0,
            ),
            largest_group_chars=max(group_sizes, default=0),
            largest_quote_projection_chars=max(quote_sizes, default=0),
            deduped_quote_count=self.deduped_quote_count,
            deduped_fact_count=self.deduped_fact_count,
            segmented_writer_required=len(prompt_json) > SINGLE_CALL_CONTEXT_TARGET_CHARS,
        )


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _trim(value: str, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _salient_terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{2,}", text.casefold())
    stop_words = {"and", "the", "for", "with", "that", "this", "from", "into"}
    terms: list[str] = []
    for word in words:
        if word in stop_words or word in terms:
            continue
        terms.append(word)
        if len(terms) >= 8:
            break
    return terms
```

- [ ] **Step 4: Run tests and verify Task 1 passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py -q
```

Expected: PASS for 2 tests.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\tests\unit\test_writer_evidence_pack.py
git commit -m "feat: add writer evidence pack registry"
```

Expected: commit succeeds with only these two files.

---

### Task 2: Normalized Fields, Quote Registry, Residual Signals, And Conflicts

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`

- [ ] **Step 1: Add failing tests for repeated normalized fields, bounded quotes, mixed residual signals, and conflicts**

Append these tests to `backend/tests/unit/test_writer_evidence_pack.py`:

```python
def test_pricing_normalized_fields_become_deduped_facts_and_bounded_quote() -> None:
    repeated_quote = "OpenAI pricing table lists model input cached input and output rates. " * 80
    fields = [
        {
            "kind": "pricing",
            "dimension": "pricing",
            "competitor": "OpenAI Codex",
            "model_type": "api_usage_based",
            "tier_name": f"gpt-5.{index}",
            "price": "$5.00",
            "billing_cycle": "per 1m tokens",
            "usage_limit": "short context",
            "enterprise_condition": "enterprise_available",
            "source_quote": repeated_quote,
        }
        for index in range(65)
    ]
    source = RawSource(
        id="openai-pricing",
        competitor="OpenAI Codex",
        dimension="pricing",
        source_type="webpage_verified",
        title="Pricing | OpenAI API",
        url="https://openai.com/api/pricing",
        snippet="Pricing table for OpenAI API models.",
        content_hash="openai-pricing-hash",
        confidence=0.96,
        metadata={"normalized_fields": fields},
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    group = result.pack.groups[0]

    assert len(group.facts) == 65
    assert len(result.pack.quotes) == 1
    assert result.pack.quotes[0].raw_quote_chars == len(repeated_quote)
    assert len(result.pack.quotes[0].excerpt) <= 500
    assert group.facts[0].quote_ids == [result.pack.quotes[0].id]
    assert result.metrics.deduped_quote_count == 64
    assert result.metrics.largest_quote_projection_chars < 900
    assert result.metrics.writer_evidence_pack_chars < 80_000


def test_mixed_structured_source_keeps_residual_snippet_signal() -> None:
    source = RawSource(
        id="cursor-pricing-mixed",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        snippet=(
            "Cursor Pro costs $20 per month. Enterprise procurement requires sales "
            "contact and security review before rollout."
        ),
        content_hash="cursor-pricing-mixed-hash",
        confidence=0.95,
        metadata={
            "normalized_fields": [
                {
                    "kind": "pricing",
                    "model_type": "subscription_saas",
                    "tier_name": "Pro",
                    "price": "$20/month",
                    "billing_cycle": "monthly",
                    "source_quote": "Cursor Pro costs $20 per month.",
                }
            ]
        },
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    group = result.pack.groups[0]

    assert len(group.facts) == 1
    assert group.unstructured_signals
    assert "Enterprise procurement requires sales contact" in group.unstructured_signals[0].signal_summary
    assert result.pack.source_registry[0].represented_by


def test_conflicting_normalized_pricing_facts_create_conflict() -> None:
    sources = [
        RawSource(
            id="cursor-official",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-official-hash",
            confidence=0.96,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20/month",
                        "billing_cycle": "monthly",
                        "source_quote": "Cursor Pro costs $20 per month.",
                    }
                ]
            },
        ),
        RawSource(
            id="cursor-community",
            competitor="Cursor",
            dimension="pricing",
            source_type="community_forum",
            title="Cursor community pricing",
            snippet="A community post says Cursor Pro is $25 per month in one billing view.",
            content_hash="cursor-community-hash",
            confidence=0.74,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$25/month",
                        "billing_cycle": "monthly",
                        "source_quote": "Cursor Pro is $25 per month in one billing view.",
                    }
                ],
                "community_evidence": True,
            },
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    group = result.pack.groups[0]

    assert group.conflicts
    assert group.conflicts[0].claim_area == "pricing:pro:monthly"
    assert "cursor-official" in group.conflicts[0].source_ids_by_position["$20/month"]
    assert "cursor-community" in group.conflicts[0].source_ids_by_position["$25/month"]
```

- [ ] **Step 2: Run tests and verify new cases fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py -q
```

Expected: FAIL because facts, quote dedupe, residual signal extraction, and conflicts are not implemented.

- [ ] **Step 3: Add normalized field projection helpers**

In `backend/packages/agents/writer/evidence_pack.py`, add these helpers near `_project_source()` and update `_project_source()` to call them before residual snippet handling:

```python
    def _project_source(self, source: RawSource) -> None:
        fact_ids = self._project_normalized_fields(source)
        cluster_ids = self._project_community_clusters(source)
        residual_signal_id = self._project_residual_signal(source, fact_ids or cluster_ids)
        if not fact_ids and not cluster_ids and residual_signal_id is None:
            self.registry_by_id[source.id].no_signal_reason = "no_clean_business_signal"

    def _project_normalized_fields(self, source: RawSource) -> list[str]:
        fact_ids: list[str] = []
        for field in normalized_fields_from_source(source):
            if not isinstance(field, Mapping):
                continue
            fact = self._fact_from_field(source, field)
            if fact is None:
                continue
            group = self._group(fact.competitor, fact.dimension)
            existing = next((item for item in group.facts if item.id == fact.id), None)
            if existing is None:
                group.facts.append(fact)
            else:
                existing.source_ids = _unique([*existing.source_ids, *fact.source_ids])
                existing.quote_ids = _unique([*existing.quote_ids, *fact.quote_ids])
                existing.confidence = max(existing.confidence, fact.confidence)
                self.deduped_fact_count += 1
            self._mark_source_represented(source.id, fact.id)
            fact_ids.append(fact.id)
        self._detect_pricing_conflicts(source.competitor, source.dimension)
        return _unique(fact_ids)

    def _fact_from_field(self, source: RawSource, field: Mapping[str, object]) -> WriterFact | None:
        kind = _string(field.get("kind")) or source.dimension
        values: dict[str, object] = {}
        for key in (
            "model_type",
            "tier_name",
            "price",
            "billing_cycle",
            "usage_limit",
            "enterprise_condition",
            "feature_name",
            "capability",
            "limitation",
            "integration",
            "workflow",
            "segment",
            "role",
            "use_case",
            "pain_point",
            "adoption_blocker",
            "switching_trigger",
            "sentiment",
        ):
            value = _string(field.get(key))
            if value:
                values[key] = _trim(value, 240)
        if not values:
            return None
        quote_ids = []
        quote = _string(field.get("source_quote"))
        if quote:
            quote_ids.append(self._quote_id_for_text(quote, source_id=source.id, confidence=source.confidence))
        fact_id = f"fact:{source.competitor}:{source.dimension}:{kind}:{_fact_key(kind, source, values)}"
        return WriterFact(
            id=fact_id,
            kind=kind,
            competitor=source.competitor,
            dimension=source.dimension,
            values=values,
            source_ids=[source.id],
            quote_ids=quote_ids,
            confidence=round(source.confidence, 3),
        )

    def _quote_id_for_text(self, text: str, *, source_id: str, confidence: float) -> str:
        raw = _clean(text)
        key = hashlib.sha256(raw.casefold().encode("utf-8")).hexdigest()[:16]
        quote_id = f"quote:{key}"
        if quote_id in self.quotes_by_key:
            quote = self.quotes_by_key[quote_id]
            quote.source_ids = _unique([*quote.source_ids, source_id])
            quote.full_text_source_ids = _unique([*quote.full_text_source_ids, source_id])
            quote.confidence = max(quote.confidence, round(confidence, 3))
            self.deduped_quote_count += 1
            return quote_id
        self.quotes_by_key[quote_id] = WriterQuote(
            id=quote_id,
            excerpt=_trim(raw, QUOTE_EXCERPT_LIMIT),
            full_text_source_ids=[source_id],
            source_ids=[source_id],
            confidence=round(confidence, 3),
            raw_quote_chars=len(raw),
        )
        return quote_id

    def _project_residual_signal(self, source: RawSource, already_represented: bool) -> str | None:
        clean_snippet = source_business_snippet(
            source,
            dimension=source.dimension,
            limit=UNSTRUCTURED_SIGNAL_LIMIT,
        )
        if not clean_snippet:
            return None
        if already_represented and self._snippet_is_covered_by_facts(source, clean_snippet):
            return None
        signal = WriterUnstructuredSignal(
            id=f"signal:{source.id}",
            source_id=source.id,
            competitor=source.competitor,
            dimension=source.dimension,
            source_type=source.source_type,
            signal_summary=clean_snippet,
            salient_terms=_salient_terms(clean_snippet),
            confidence=round(source.confidence, 3),
        )
        self._group(source.competitor, source.dimension).unstructured_signals.append(signal)
        self._mark_source_represented(source.id, signal.id)
        return signal.id

    def _snippet_is_covered_by_facts(self, source: RawSource, snippet: str) -> bool:
        group = self._group(source.competitor, source.dimension)
        fact_text = " ".join(
            _clean(str(value)).casefold()
            for fact in group.facts
            for value in fact.values.values()
        )
        snippet_text = snippet.casefold()
        if not fact_text:
            return False
        covered_terms = sum(1 for term in _salient_terms(snippet_text) if term in fact_text)
        return covered_terms >= 3 and len(snippet_text) < 260

    def _detect_pricing_conflicts(self, competitor: str, dimension: str) -> None:
        if dimension != "pricing":
            return
        group = self._group(competitor, dimension)
        by_area: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        confidence_by_area: dict[str, dict[str, float]] = defaultdict(dict)
        for fact in group.facts:
            tier = _string(fact.values.get("tier_name")).casefold() or "unknown"
            billing = _string(fact.values.get("billing_cycle")).casefold() or "unknown"
            price = _string(fact.values.get("price"))
            if not price:
                continue
            area = f"pricing:{tier}:{billing}"
            by_area[area][price].extend(fact.source_ids)
            confidence_by_area[area][price] = max(
                confidence_by_area[area].get(price, 0.0),
                fact.confidence,
            )
        group.conflicts = [
            conflict
            for conflict in group.conflicts
            if not conflict.id.startswith("conflict:pricing:")
        ]
        for area, positions in by_area.items():
            if len(positions) < 2:
                continue
            group.conflicts.append(
                WriterConflict(
                    id=f"conflict:{area}",
                    claim_area=area,
                    positions={price: price for price in positions},
                    source_ids_by_position={
                        price: _unique(ids) for price, ids in positions.items()
                    },
                    confidence_by_position=confidence_by_area[area],
                )
            )
```

Add these module-level helpers:

```python
def _string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _clean(value)


def _fact_key(kind: str, source: RawSource, values: Mapping[str, object]) -> str:
    if source.dimension == "pricing" or kind == "pricing":
        parts = [
            source.competitor,
            _string(values.get("model_type")),
            _string(values.get("tier_name")),
            _string(values.get("price")),
            _string(values.get("billing_cycle")),
            _string(values.get("usage_limit")),
        ]
    elif source.dimension == "feature":
        parts = [
            source.competitor,
            _string(values.get("feature_name")),
            _string(values.get("capability")),
            _string(values.get("limitation")),
            _string(values.get("workflow")),
        ]
    else:
        parts = [
            source.competitor,
            _string(values.get("segment")),
            _string(values.get("role")),
            _string(values.get("use_case")),
            _string(values.get("pain_point")),
            _string(values.get("switching_trigger")),
        ]
    raw_key = "|".join(part.casefold() for part in parts if part)
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
    return digest
```

- [ ] **Step 4: Add community cluster projection**

In `evidence_pack.py`, implement `_project_community_clusters()`:

```python
    def _project_community_clusters(self, source: RawSource) -> list[str]:
        clusters = source.metadata.get("community_claim_clusters")
        if not isinstance(clusters, list):
            return []
        ids: list[str] = []
        for index, cluster in enumerate(clusters):
            if not isinstance(cluster, Mapping):
                continue
            claim = _string(cluster.get("claim"))
            if not claim:
                continue
            fact_id = f"community:{source.id}:{index}"
            fact = WriterFact(
                id=fact_id,
                kind=_string(cluster.get("kind")) or "community",
                competitor=source.competitor,
                dimension=source.dimension,
                values={
                    "claim": _trim(claim, 260),
                    "normalized_value": _trim(_string(cluster.get("normalized_value")), 160),
                    "label": _trim(_string(cluster.get("label")), 120),
                    "authority_signal": _trim(
                        _string(source.metadata.get("community_authority_signal")),
                        160,
                    ),
                    "official_commitment": bool(source.metadata.get("official_commitment", False)),
                },
                source_ids=_unique([source.id, *_string_list(cluster.get("source_ids"))]),
                confidence=_float(cluster.get("confidence"), fallback=source.confidence),
            )
            self._group(source.competitor, source.dimension).facts.append(fact)
            self._mark_source_represented(source.id, fact.id)
            ids.append(fact.id)
        return ids
```

Add helpers:

```python
def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_string(item) for item in value) if item]


def _float(value: object, *, fallback: float = 0.0) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return round(fallback, 3)
```

- [ ] **Step 5: Run evidence pack tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py -q
```

Expected: PASS for all evidence pack tests.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\tests\unit\test_writer_evidence_pack.py
git commit -m "feat: project writer evidence facts"
```

Expected: commit succeeds.

---

### Task 3: KB Slices, Structured Knowledge, Matrix Projection, And Pack Metrics

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`

- [ ] **Step 1: Add failing tests for KB slice preservation and comparison matrix projection**

Append:

```python
from packages.schema.models import CompetitorKB, ComparisonCell, ComparisonMatrix


def test_evidence_pack_preserves_every_kb_slice_with_provenance() -> None:
    detail = _detail_with_sources([])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["persona"]
    detail.competitor_kbs = {
        "Cursor": CompetitorKB(
            competitor="Cursor",
            slices={
                "persona": [
                    "Enterprise buyers evaluate Cursor for security review.",
                    "Developer teams use Cursor for repository-aware coding.",
                ]
            },
        )
    }

    result = build_writer_evidence_pack(detail)
    group = result.pack.groups[0]

    assert result.metrics.kb_slice_count == 2
    assert result.metrics.represented_kb_slice_count == 2
    assert result.metrics.dropped_kb_slice_count == 0
    assert [signal.id for signal in group.kb_signals] == [
        "kb:Cursor:persona:0",
        "kb:Cursor:persona:1",
    ]
    assert "security review" in group.kb_signals[0].text


def test_evidence_pack_preserves_comparison_matrix_digest() -> None:
    detail = _detail_with_sources([])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["pricing"]
    detail.comparison_matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Cursor Pro is priced at $20/month for individual developers.",
                source_ids=["cursor-pricing"],
                confidence=0.94,
            )
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=["Cursor has clear individual pricing."],
    )

    result = build_writer_evidence_pack(detail)

    assert result.pack.matrix["winner_by_dimension"]["pricing"] == "Cursor"
    assert result.pack.matrix["cells"][0]["source_ids"] == ["cursor-pricing"]
```

- [ ] **Step 2: Run tests and verify failures**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py -q
```

Expected: FAIL because KB slice projection is not implemented.

- [ ] **Step 3: Implement KB slice projection**

In `build()`, after projecting raw sources, add:

```python
        self._project_kb_slices()
```

Add methods:

```python
    def _project_kb_slices(self) -> None:
        for competitor, kb in self.detail.competitor_kbs.items():
            for dimension, findings in kb.slices.items():
                if dimension not in self.detail.plan.dimensions:
                    continue
                group = self._group(competitor, dimension)
                for index, finding in enumerate(findings):
                    text = _trim(_string(finding), 700)
                    if not text:
                        continue
                    signal = WriterKBSignal(
                        id=f"kb:{competitor}:{dimension}:{index}",
                        competitor=competitor,
                        dimension=dimension,
                        text=text,
                        source_ids=[],
                    )
                    group.kb_signals.append(signal)
```

Update `_metrics()`:

```python
        kb_slice_count = sum(
            len(findings)
            for kb in self.detail.competitor_kbs.values()
            for dimension, findings in kb.slices.items()
            if dimension in self.detail.plan.dimensions
        )
        represented_kb_slice_count = sum(len(group.kb_signals) for group in pack.groups)
```

Set these fields in `WriterEvidencePackMetrics(...)`:

```python
            kb_slice_count=kb_slice_count,
            represented_kb_slice_count=represented_kb_slice_count,
            dropped_kb_slice_count=max(0, kb_slice_count - represented_kb_slice_count),
```

- [ ] **Step 4: Add structured knowledge projection test**

Append:

```python
def test_evidence_pack_structured_knowledge_stays_visible() -> None:
    detail = _detail_with_sources([])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["pricing"]
    detail.competitor_knowledge = {}

    result = build_writer_evidence_pack(detail)

    assert "structured_knowledge" in result.pack.model_dump(mode="json")
```

Expected initially: FAIL because `WriterEvidencePack` has no `structured_knowledge`.

- [ ] **Step 5: Add compact structured knowledge field**

Add to `WriterEvidencePack`:

```python
    structured_knowledge: dict[str, object] = Field(default_factory=dict)
```

Set it in `build()`:

```python
            structured_knowledge=self._structured_knowledge_digest(),
```

Add method:

```python
    def _structured_knowledge_digest(self) -> dict[str, object]:
        digest: dict[str, object] = {}
        for competitor, knowledge in self.detail.competitor_knowledge.items():
            item: dict[str, object] = {"confidence": round(knowledge.confidence, 3)}
            if getattr(knowledge, "review_summary", None) is not None:
                item["review_summary"] = knowledge.review_summary.model_dump(mode="json")
            if getattr(knowledge, "pricing_model", None) is not None:
                item["pricing_model"] = knowledge.pricing_model.model_dump(mode="json")
            if getattr(knowledge, "feature_tree", None) is not None:
                item["feature_tree"] = knowledge.feature_tree.model_dump(mode="json")
            if getattr(knowledge, "user_personas", None) is not None:
                item["user_personas"] = knowledge.user_personas.model_dump(mode="json")
            digest[competitor] = item
        return digest
```

- [ ] **Step 6: Run tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\tests\unit\test_writer_evidence_pack.py
git commit -m "feat: preserve writer kb context"
```

Expected: commit succeeds.

---

### Task 4: Writer Context Integration And Preflight Telemetry

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing test that initial writer prompt uses evidence pack and emits telemetry**

Append to `backend/tests/unit/test_run_service.py` near existing writer tests:

```python
@pytest.mark.asyncio
async def test_writer_uses_evidence_pack_context_and_emits_preflight(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=10,
        ),
    )
    detail = RunDetail(
        id="run-writer-pack",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(topic="AI coding agent", competitors=["Cursor"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="cursor-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                snippet="Cursor Pro costs $20 per month.",
                content_hash="cursor-pricing-hash",
                confidence=0.96,
            )
        ],
    )
    record = RunRecord(detail=detail)
    captured: dict[str, str] = {}

    async def fake_trace_llm_text(*args, **kwargs):
        captured["user"] = kwargs["user"]
        return (
            "# Report\n\n"
            "## Executive Summary\nCursor has visible pricing. [source:cursor-pricing]\n\n"
            "## Evidence Appendix\n- [source:cursor-pricing] Cursor pricing\n"
        )

    monkeypatch.setattr(service, "_trace_llm_text", fake_trace_llm_text)

    await service._real_writer_step(record)

    assert "Writer Evidence Pack JSON:" in captured["user"]
    assert "Writer Context JSON:" not in captured["user"]
    assert "source_registry" in captured["user"]
    assert any(
        event.event_type == "writer_preflight"
        and event.payload["raw_source_count"] == 1
        for event in record.events
    )
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_uses_evidence_pack_context_and_emits_preflight -q
```

Expected: FAIL because writer still uses `Writer Context JSON`.

- [ ] **Step 3: Import evidence pack helpers and replace initial writer context**

At the top of `backend/packages/agents/writer/logic.py`, add:

```python
from packages.agents.writer.evidence_pack import (
    SINGLE_CALL_CONTEXT_TARGET_CHARS,
    build_writer_evidence_pack,
)
```

In `_real_writer_step()`, replace:

```python
            writer_context_json = json.dumps(
                self._writer_context_package(detail),
                ensure_ascii=False,
            )
```

with:

```python
            evidence_pack_result = build_writer_evidence_pack(detail)
            writer_context_json = evidence_pack_result.to_prompt_json()
            await self.emit(
                detail.id,
                "writer_preflight",
                "writer",
                None,
                "Writer evidence pack prepared.",
                evidence_pack_result.telemetry_payload(),
            )
```

In the LLM prompt string, replace:

```python
                            f"Writer Context JSON: {writer_context_json}\n\n"
```

with:

```python
                            f"Writer Evidence Pack JSON: {writer_context_json}\n\n"
```

- [ ] **Step 4: Run focused test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_uses_evidence_pack_context_and_emits_preflight -q
```

Expected: PASS.

- [ ] **Step 5: Run nearby writer tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "writer_source_digest or writer_uses_evidence_pack_context or writer_budget_timeout" -q
```

Expected: PASS. Existing old digest helper tests may still pass because helper remains for non-writer call sites until cleanup.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add backend\packages\agents\writer\logic.py backend\tests\unit\test_run_service.py
git commit -m "feat: use evidence pack for writer prompt"
```

Expected: commit succeeds.

---

### Task 5: Section Repair Context Uses Evidence Pack

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing test for section repair context**

Append:

```python
@pytest.mark.asyncio
async def test_writer_section_repair_uses_evidence_pack_context(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-repair-pack",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(topic="AI coding agent", competitors=["Cursor"], dimensions=["persona"]),
        raw_sources=[
            RawSource(
                id="cursor-persona",
                competitor="Cursor",
                dimension="persona",
                source_type="interview_record",
                title="Cursor persona interview",
                snippet="Enterprise buyers evaluate Cursor for security and onboarding.",
                content_hash="cursor-persona-hash",
                confidence=0.82,
            )
        ],
    )
    record = RunRecord(detail=detail)
    captured: dict[str, str] = {}

    async def fake_trace_llm_text(*args, **kwargs):
        captured["user"] = kwargs["user"]
        return "## User Review Themes\nEnterprise buyers cite onboarding. [source:cursor-persona]"

    monkeypatch.setattr(service, "_trace_llm_text", fake_trace_llm_text)

    await service._writer_section_repair_markdown(
        record,
        sections=["review_theme_summary"],
        previous_report="## User Review Themes\nThin.",
    )

    assert "Writer Evidence Pack JSON:" in captured["user"]
    assert "Writer Context JSON:" not in captured["user"]
    assert "cursor-persona" in captured["user"]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_section_repair_uses_evidence_pack_context -q
```

Expected: FAIL because section repair still says `Writer Context JSON`.

- [ ] **Step 3: Replace section repair context**

In `_writer_section_repair_markdown()`, replace:

```python
        writer_context_json = json.dumps(
            self._writer_context_package(detail),
            ensure_ascii=False,
        )
```

with:

```python
        evidence_pack_result = build_writer_evidence_pack(detail)
        writer_context_json = evidence_pack_result.to_prompt_json()
```

Replace:

```python
                f"Writer Context JSON: {writer_context_json}\n\n"
```

with:

```python
                f"Writer Evidence Pack JSON: {writer_context_json}\n\n"
```

- [ ] **Step 4: Run focused test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_section_repair_uses_evidence_pack_context -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add backend\packages\agents\writer\logic.py backend\tests\unit\test_run_service.py
git commit -m "fix: use evidence pack for writer repair"
```

Expected: commit succeeds.

---

### Task 6: Deterministic Source Appendix From Registry

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing unit test for appendix rows**

Append to `test_writer_evidence_pack.py`:

```python
def test_source_appendix_rows_are_generated_from_registry() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
        confidence=0.96,
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    rows = result.source_appendix_rows()

    assert rows == [
        {
            "source_id": "cursor-pricing",
            "title": "Cursor pricing",
            "url": "https://cursor.com/pricing",
            "source_type": "webpage_verified",
            "competitor": "Cursor",
            "dimension": "pricing",
            "confidence": 0.96,
            "represented_by": result.pack.source_registry[0].represented_by,
            "no_signal_reason": None,
        }
    ]
```

- [ ] **Step 2: Implement appendix rows helper**

Add to `WriterEvidencePackResult`:

```python
    def source_appendix_rows(self) -> list[dict[str, object]]:
        return [
            {
                "source_id": item.id,
                "title": item.title,
                "url": item.url,
                "source_type": item.source_type,
                "competitor": item.competitor,
                "dimension": item.dimension,
                "confidence": item.confidence,
                "represented_by": list(item.represented_by),
                "no_signal_reason": item.no_signal_reason,
            }
            for item in self.pack.source_registry
        ]
```

- [ ] **Step 3: Add writer backfill test**

Append to `test_run_service.py`:

```python
def test_writer_source_appendix_backfill_uses_registry_rows() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-appendix-pack",
        topic="AI coding agent",
        status="running",
        execution_mode="demo",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(topic="AI coding agent", competitors=["Cursor"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="cursor-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.com/pricing",
                snippet="Cursor Pro costs $20 per month.",
                content_hash="cursor-pricing-hash",
                confidence=0.96,
            )
        ],
    )

    appendix = service._writer_source_appendix_lines(detail)

    assert any("[source:cursor-pricing]" in line for line in appendix)
    assert not any("Cursor Pro costs $20 per month." in line for line in appendix)
```

- [ ] **Step 4: Implement deterministic appendix lines in writer logic**

Add method to `WriterAgentMixin`:

```python
    def _writer_source_appendix_lines(self, detail: RunDetail) -> list[str]:
        evidence_pack_result = build_writer_evidence_pack(detail)
        lines = ["", f"## {report_label(detail.output_language, 'evidence_appendix')}"]
        for row in evidence_pack_result.source_appendix_rows():
            source_id = row["source_id"]
            title = row["title"] or source_id
            source_type = row["source_type"]
            competitor = row["competitor"]
            dimension = row["dimension"]
            confidence = row["confidence"]
            url = row["url"] or "no url"
            lines.append(
                f"- [source:{source_id}] {title} | {source_type} | "
                f"{competitor}/{dimension} | confidence={confidence} | {url}"
            )
        return lines
```

Do not wire this into hardening yet if an existing appendix backfill already exists; this task only adds a deterministic helper and verifies it avoids raw snippets.

- [ ] **Step 5: Run tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py::test_writer_source_appendix_backfill_uses_registry_rows -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py
git commit -m "feat: add registry source appendix"
```

Expected: commit succeeds.

---

### Task 7: Segmented Writer Routing, Segment Retry, And Citation Validation

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add unit test for segment planning**

Append to `test_writer_evidence_pack.py`:

```python
def test_evidence_pack_builds_segment_inputs_with_allowed_source_ids() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-pricing-hash",
            confidence=0.96,
        ),
        RawSource(
            id="cursor-persona",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona",
            snippet="Enterprise buyers evaluate Cursor for security review.",
            content_hash="cursor-persona-hash",
            confidence=0.82,
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    segments = result.segment_inputs()

    by_name = {segment["segment_name"]: segment for segment in segments}
    assert "decision_summary" in by_name
    assert "user_research" in by_name
    assert "cursor-pricing" in by_name["decision_summary"]["allowed_source_ids"]
    assert "cursor-persona" in by_name["user_research"]["allowed_source_ids"]
```

- [ ] **Step 2: Implement segment input helper**

Add to `WriterEvidencePackResult`:

```python
    def segment_inputs(self) -> list[dict[str, object]]:
        return [
            self._segment(
                "decision_summary",
                dimensions={"pricing", "feature", "persona"},
            ),
            self._segment("user_research", dimensions={"persona"}),
            self._segment("competitor_deep_dives", dimensions={"pricing", "feature", "persona"}),
            self._segment("swot_matrix", dimensions={"pricing", "feature", "persona"}),
            self._segment("support_appendix", dimensions={"pricing", "feature", "persona"}),
        ]

    def _segment(self, name: str, *, dimensions: set[str]) -> dict[str, object]:
        groups = [group for group in self.pack.groups if group.dimension in dimensions]
        allowed_source_ids = _unique(
            source_id
            for group in groups
            for source_id in group.source_ids
        )
        payload = {
            "schema_version": self.pack.schema_version,
            "segment_name": name,
            "source_registry": [
                item.model_dump(mode="json")
                for item in self.pack.source_registry
                if item.id in allowed_source_ids
            ],
            "groups": [group.model_dump(mode="json") for group in groups],
            "matrix": self.pack.matrix,
            "allowed_source_ids": allowed_source_ids,
        }
        payload["segment_input_chars"] = len(json.dumps(payload, ensure_ascii=False))
        return payload
```

- [ ] **Step 3: Add citation validation helper and tests**

Append test:

```python
def test_segment_citation_validation_rejects_unsupplied_source_id() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
        confidence=0.96,
    )
    result = build_writer_evidence_pack(_detail_with_sources([source]))

    errors = result.validate_segment_citations(
        "Cursor is priced clearly. [source:missing-source]",
        allowed_source_ids={"cursor-pricing"},
    )

    assert errors == ["missing-source"]
```

Add to evidence pack module:

```python
SOURCE_TOKEN_RE = re.compile(r"\[source:([^\]\s]+)\]")


    def validate_segment_citations(
        self,
        markdown: str,
        *,
        allowed_source_ids: set[str],
    ) -> list[str]:
        invalid: list[str] = []
        registry_ids = {item.id for item in self.pack.source_registry}
        for match in SOURCE_TOKEN_RE.finditer(markdown or ""):
            source_id = match.group(1)
            if source_id not in registry_ids or source_id not in allowed_source_ids:
                invalid.append(source_id)
        return _unique(invalid)
```

- [ ] **Step 4: Add failing RunService test for segmented writer path**

Append to `test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_writer_routes_large_evidence_pack_to_segmented_writer(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=10,
        ),
    )
    sources = [
        RawSource(
            id=f"cursor-source-{index}",
            competitor="Cursor",
            dimension="persona" if index % 2 else "pricing",
            source_type="interview_record",
            title=f"Cursor source {index}",
            snippet=(
                "Enterprise buyers evaluate Cursor for security review, onboarding, "
                "budget control, repository-aware coding, rollout governance, and "
                f"developer adoption signal {index}. "
            )
            * 6,
            content_hash=f"cursor-source-{index}-hash",
            confidence=0.82,
        )
        for index in range(40)
    ]
    detail = RunDetail(
        id="run-segmented-pack",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(topic="AI coding agent", competitors=["Cursor"], dimensions=["pricing", "persona"]),
        raw_sources=sources,
    )
    record = RunRecord(detail=detail)
    calls: list[str] = []

    async def fake_trace_llm_text(*args, **kwargs):
        user = kwargs["user"]
        calls.append(kwargs["name"])
        if "segment_name=decision_summary" in user:
            return "## Executive Summary\nCursor has clear evidence. [source:cursor-source-0]"
        if "segment_name=user_research" in user:
            return "## User Review Themes\nEnterprise buyers cite rollout concerns. [source:cursor-source-1]"
        if "segment_name=competitor_deep_dives" in user:
            return "## Competitor Deep Dives\nCursor has repository-aware workflows. [source:cursor-source-2]"
        if "segment_name=swot_matrix" in user:
            return "## SWOT Analysis\nStrengths include adoption signal. [source:cursor-source-3]"
        return "## Evidence Appendix\n- [source:cursor-source-0] Cursor source 0"

    monkeypatch.setattr(service, "_trace_llm_text", fake_trace_llm_text)
    monkeypatch.setattr("packages.agents.writer.logic.SINGLE_CALL_CONTEXT_TARGET_CHARS", 100)

    await service._real_writer_step(record)

    assert "report_writer_segment" in calls
    assert "report_writer" not in calls
    assert "## Executive Summary" in record.detail.report_md
    assert any(event.event_type == "writer_segment_preflight" for event in record.events)
```

- [ ] **Step 5: Implement segmented writer methods**

In `logic.py`, before the single-call LLM section, branch on `evidence_pack_result.metrics.segmented_writer_required`:

```python
            if evidence_pack_result.metrics.segmented_writer_required:
                report_md = await self._writer_segmented_report_markdown(
                    record,
                    evidence_pack_result=evidence_pack_result,
                    timeout_seconds=timeout_seconds,
                    language_guidance=language_guidance,
                    memory_context=memory_context,
                    layer_context=layer_context,
                    required_sections=required_sections,
                )
                self._require_writer_report_output(report_md)
                hardened_report = self._harden_report_markdown(detail, report_md)
                detail.report_md = hardened_report
                writer_mode = "real segmented LLM call"
            else:
                report_md = await asyncio.wait_for(
                    ...
                )
```

Add method:

```python
    async def _writer_segmented_report_markdown(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ) -> str:
        detail = record.detail
        sections: list[str] = []
        for segment in evidence_pack_result.segment_inputs():
            payload = {
                "segment_name": segment["segment_name"],
                "segment_input_chars": segment["segment_input_chars"],
                "segment_source_count": len(segment["allowed_source_ids"]),
                "segment_group_count": len(segment["groups"]),
                "segment_allowed_source_ids": list(segment["allowed_source_ids"]),
                "segment_retry_count": 0,
            }
            await self.emit(
                detail.id,
                "writer_segment_preflight",
                "writer",
                None,
                f"Writer segment prepared: {segment['segment_name']}",
                payload,
            )
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=0,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=set(segment["allowed_source_ids"]),
            )
            if invalid_sources:
                segment_md = await self._writer_segment_markdown(
                    record,
                    segment=segment,
                    timeout_seconds=timeout_seconds,
                    language_guidance=language_guidance,
                    memory_context=memory_context,
                    layer_context=layer_context,
                    required_sections=required_sections,
                    retry_count=1,
                    citation_error_ids=invalid_sources,
                )
            sections.append(segment_md.strip())
        return "\n\n".join(section for section in sections if section)
```

Add method:

```python
    async def _writer_segment_markdown(
        self,
        record: RunRecord,
        *,
        segment: dict[str, object],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
        retry_count: int,
        citation_error_ids: list[str] | None = None,
    ) -> str:
        detail = record.detail
        segment_json = json.dumps(segment, ensure_ascii=False)
        citation_warning = ""
        if citation_error_ids:
            citation_warning = (
                "Previous segment cited source IDs outside this segment: "
                f"{', '.join(citation_error_ids)}. Rewrite using only allowed_source_ids.\n"
            )
        return await asyncio.wait_for(
            self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="report_writer_segment",
                system=(
                    "You are a senior enterprise competitive-intelligence analyst writing "
                    "one section group of a larger markdown report. Return only markdown "
                    "for this segment. Cite factual claims only with source IDs in "
                    "allowed_source_ids. Do not invent source IDs. "
                    f"{language_guidance}"
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                    f"segment_name={segment['segment_name']}\n"
                    f"retry_count={retry_count}\n"
                    f"{citation_warning}"
                    f"Confirmed Memory Preferences:\n{memory_context}\n"
                    f"Layer Report Context: {layer_context}\n"
                    f"{self._writer_community_policy_text()}\n"
                    f"Segment Evidence Pack JSON: {segment_json}\n\n"
                    f"Required sections for full report:\n{required_sections}\n"
                    "Write with consulting depth for this segment. Keep support material "
                    "concise and preserve [source:ID] citation syntax."
                ),
            ),
            timeout=timeout_seconds,
        )
```

- [ ] **Step 6: Run segmented tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py::test_evidence_pack_builds_segment_inputs_with_allowed_source_ids backend\tests\unit\test_writer_evidence_pack.py::test_segment_citation_validation_rejects_unsupplied_source_id backend\tests\unit\test_run_service.py::test_writer_routes_large_evidence_pack_to_segmented_writer -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py
git commit -m "feat: segment large writer prompts"
```

Expected: commit succeeds.

---

### Task 8: Preflight Failure For Impossible Oversize Packs

**Files:**
- Modify: `backend/packages/agents/writer/evidence_pack.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add pack preflight validation test**

Append:

```python
def test_evidence_pack_preflight_flags_unrepresented_source() -> None:
    source = RawSource(
        id="cursor-empty",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor empty",
        snippet="",
        content_hash="cursor-empty-hash",
        confidence=0.9,
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))

    assert result.pack.source_registry[0].no_signal_reason == "no_clean_business_signal"
    assert result.preflight_errors() == []
```

- [ ] **Step 2: Implement preflight errors helper**

Add to `WriterEvidencePackResult`:

```python
    def preflight_errors(self) -> list[str]:
        errors: list[str] = []
        for item in self.pack.source_registry:
            if not item.represented_by and not item.no_signal_reason:
                errors.append(f"source_not_represented:{item.id}")
        if self.metrics.dropped_source_count:
            errors.append(f"dropped_source_count:{self.metrics.dropped_source_count}")
        if self.metrics.dropped_kb_slice_count:
            errors.append(f"dropped_kb_slice_count:{self.metrics.dropped_kb_slice_count}")
        return errors
```

- [ ] **Step 3: Add RunService preflight failure test**

Append:

```python
@pytest.mark.asyncio
async def test_writer_fails_before_llm_when_evidence_pack_preflight_has_errors(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=10,
        ),
    )
    detail = RunDetail(
        id="run-pack-preflight-fail",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at=_now(),
        updated_at=_now(),
        plan=AnalysisPlan(topic="AI coding agent", competitors=["Cursor"], dimensions=["pricing"]),
    )
    record = RunRecord(detail=detail)

    class FakeResult:
        def telemetry_payload(self):
            return {"raw_source_count": 1, "preflight_warnings": ["source_not_represented:bad"]}

        def preflight_errors(self):
            return ["source_not_represented:bad"]

        def to_prompt_json(self):
            return "{}"

    monkeypatch.setattr("packages.agents.writer.logic.build_writer_evidence_pack", lambda detail: FakeResult())

    with pytest.raises(RuntimeError, match="writer evidence pack preflight failed"):
        await service._real_writer_step(record)

    assert any(event.event_type == "run_failed" for event in record.events)
```

- [ ] **Step 4: Implement writer preflight failure handling**

After emitting `writer_preflight`, add:

```python
            preflight_errors = evidence_pack_result.preflight_errors()
            if preflight_errors:
                await self._fail_writer_without_report(
                    record,
                    "writer evidence pack preflight failed: " + ", ".join(preflight_errors),
                    writer_repair_mode=writer_repair_mode,
                    writer_repair_sections=writer_repair_sections,
                    writer_repair_decision=writer_repair_decision,
                    anti_regression_reason=anti_regression_reason,
                    previous_report_protected=previous_report_protected,
                )
```

- [ ] **Step 5: Run tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py::test_evidence_pack_preflight_flags_unrepresented_source backend\tests\unit\test_run_service.py::test_writer_fails_before_llm_when_evidence_pack_preflight_has_errors -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 8**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py
git commit -m "fix: fail writer on evidence preflight errors"
```

Expected: commit succeeds.

---

### Task 9: Replace Or Retire Old Writer Digest Tests

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`

- [ ] **Step 1: Identify old tests that enforce full source digest behavior**

Run:

```powershell
rg -n "writer_source_digest|writer_competitor_digest|includes_all_raw_sources|preserves_all_kb_slices|Writer Context JSON" backend\tests\unit\test_run_service.py
```

Expected: output includes old tests such as `test_writer_source_digest_includes_all_raw_sources` and `test_writer_competitor_digest_preserves_all_kb_slices`.

- [ ] **Step 2: Keep helper tests only when still used outside prompt path**

For old tests that directly assert `_writer_source_digest()` preserves all raw source snippets, replace the assertion target with evidence pack behavior. Example replacement:

```python
def test_writer_evidence_pack_includes_all_raw_sources() -> None:
    sources = [
        RawSource(
            id=f"raw-source-{index:02d}",
            competitor="A",
            dimension="persona" if index > 24 else "pricing",
            source_type="interview_record" if index > 24 else "webpage_verified",
            title=f"A source {index}",
            url=None,
            snippet=(
                f"Source {index} contains decision-relevant buyer, pricing, and adoption "
                "evidence for the report writer."
            ),
            content_hash=f"source-{index}-hash",
            confidence=0.9,
        )
        for index in range(1, 31)
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))

    assert len(result.pack.source_registry) == 30
    assert result.pack.source_registry[-1].id == "raw-source-30"
    assert result.metrics.represented_source_count == 30
```

Do not delete old helper functions from `logic.py` yet unless `rg "_writer_source_digest|_writer_competitor_digest" backend\packages backend\tests` shows they are unused. If unused, remove them in a separate cleanup commit after all integration tests pass.

- [ ] **Step 3: Run writer test subset**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py -k "writer_evidence_pack or writer_uses_evidence_pack or writer_section_repair_uses_evidence_pack or segmented_writer" -q
```

Expected: PASS.

- [ ] **Step 4: Commit Task 9**

Run:

```powershell
git add backend\tests\unit\test_run_service.py backend\tests\unit\test_writer_evidence_pack.py
git commit -m "test: align writer tests with evidence pack"
```

Expected: commit succeeds.

---

### Task 10: End-To-End Verification Against Large Synthetic Run Shape

**Files:**
- Modify: `backend/tests/unit/test_writer_evidence_pack.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add regression test for run-58 style source shape**

Append to `test_writer_evidence_pack.py`:

```python
def test_run_58_style_pricing_source_stays_below_prompt_budget() -> None:
    quote = "Standard Batch Flex Priority Standard Short context Long context Model Input Cached input Output. " * 80
    source = RawSource(
        id="raw-source-openai-pricing",
        competitor="OpenAI Codex",
        dimension="pricing",
        source_type="webpage_verified",
        title="Pricing | OpenAI API",
        snippet="OpenAI API pricing table.",
        content_hash="openai-pricing-run58-hash",
        confidence=0.96,
        metadata={
            "normalized_fields": [
                {
                    "kind": "pricing",
                    "dimension": "pricing",
                    "competitor": "OpenAI Codex",
                    "model_type": "api_usage_based",
                    "tier_name": f"gpt-5.{index}",
                    "price": f"${index}.00",
                    "billing_cycle": "per 1m",
                    "usage_limit": "short context",
                    "enterprise_condition": "enterprise_available",
                    "source_quote": quote,
                }
                for index in range(65)
            ]
        },
    )
    detail = _detail_with_sources([source])
    detail.plan.competitors = ["OpenAI Codex"]
    detail.plan.dimensions = ["pricing"]

    result = build_writer_evidence_pack(detail)

    assert result.metrics.raw_source_count == 1
    assert result.metrics.represented_source_count == 1
    assert result.metrics.writer_evidence_pack_chars < 90_000
    assert result.metrics.largest_quote_projection_chars < 900
    assert result.metrics.deduped_quote_count == 64
```

- [ ] **Step 2: Run regression test**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py::test_run_58_style_pricing_source_stays_below_prompt_budget -q
```

Expected: PASS.

- [ ] **Step 3: Run full relevant unit suites**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py -q
```

Expected: PASS, except any pre-existing unrelated failures must be copied exactly into the final handoff with file/test names and failure reasons.

- [ ] **Step 4: Inspect writer context size with a one-off reconstruction script**

Run:

```powershell
@'
import json
import sqlite3
import sys
sys.path.insert(0, r"D:\codex_workspace\plan_a\backend")
from packages.agents.writer.evidence_pack import build_writer_evidence_pack
from packages.schema.api_dto import RunDetail

run_id = "run-58dd1b8df825ffcba52fbdd1433b5956"
con = sqlite3.connect(r"runs\run_journal.db")
row = con.execute("select detail_json from runs where id=?", (run_id,)).fetchone()
if row is None:
    raise SystemExit("run not found")
detail = RunDetail.model_validate(json.loads(row[0]))
result = build_writer_evidence_pack(detail)
print(json.dumps(result.telemetry_payload(), ensure_ascii=False, indent=2))
'@ | D:\Anaconda\envs\bd-competiscope-v2\python.exe -
```

Expected: output shows `raw_source_count` as 82, `dropped_source_count` as 0, and `writer_evidence_pack_chars` materially below the previous 512k writer context. If `runs\run_journal.db` is missing in the executing environment, record that this optional local run reconstruction was skipped.

- [ ] **Step 5: Commit Task 10**

Run:

```powershell
git add backend\tests\unit\test_writer_evidence_pack.py
git commit -m "test: cover large writer evidence pack"
```

Expected: commit succeeds if the regression test was added or adjusted. If no file changed because the test was already present, do not create an empty commit.

---

### Task 11: Final Review And Cleanup

**Files:**
- Inspect: `backend/packages/agents/writer/evidence_pack.py`
- Inspect: `backend/packages/agents/writer/logic.py`
- Inspect: `backend/tests/unit/test_writer_evidence_pack.py`
- Inspect: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Search for old prompt labels**

Run:

```powershell
rg -n "Writer Context JSON|_writer_context_package\\(|_writer_source_digest\\(|_writer_competitor_digest\\(" backend\packages\agents\writer backend\tests\unit
```

Expected:

- No writer LLM prompt path uses `Writer Context JSON`.
- `_writer_context_package`, `_writer_source_digest`, or `_writer_competitor_digest` may remain only if tests or non-prompt code still use them. If no references remain outside their definitions, remove them in this task.

- [ ] **Step 2: Remove unused old helper methods if safe**

If `rg` shows `_writer_context_package`, `_writer_source_digest`, `_writer_competitor_digest`, `_writer_normalized_fields_digest`, `_writer_competitor_digest`, or dependent helpers have no references outside definitions and obsolete tests, delete the unused methods from `backend/packages/agents/writer/logic.py`.

After deletion, run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k writer -q
```

Expected: PASS. If deletion causes failures in unrelated writer hardening helpers, revert only the deletion and leave cleanup for a later refactor.

- [ ] **Step 3: Run final focused verification**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py -k "writer" -q
```

Expected: PASS or only documented pre-existing unrelated failures.

- [ ] **Step 4: Review git diff**

Run:

```powershell
git diff --stat HEAD
git diff -- backend\packages\agents\writer\evidence_pack.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py
```

Expected: diff contains only planned implementation and tests.

- [ ] **Step 5: Commit final cleanup**

Run:

```powershell
git add backend\packages\agents\writer\evidence_pack.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_evidence_pack.py backend\tests\unit\test_run_service.py
git commit -m "chore: clean writer evidence pack integration"
```

Expected: commit succeeds if cleanup changed files. If no files changed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Raw sources remain persisted and represented by `source_registry`.
  - Normalized fields become facts with quote IDs.
  - Quotes are bounded and deduplicated.
  - Residual clean snippets become `unstructured_signals`.
  - KB slices, structured knowledge, and comparison matrix remain writer-visible.
  - Initial writer and section repair use evidence pack context.
  - Preflight telemetry is emitted before LLM calls.
  - Oversized packs route to segmented writer.
  - Segment outputs are citation-validated.
  - Source appendix is deterministic and does not require full raw snippets in the prompt.

- Placeholder scan:
  - Search for prohibited placeholder markers from the writing-plans skill and remove them if found.

- Type consistency:
  - Main builder function is `build_writer_evidence_pack(detail: RunDetail)`.
  - Result object is `WriterEvidencePackResult`.
  - Prompt serialization method is `to_prompt_json()`.
  - Telemetry method is `telemetry_payload()`.
  - Registry field is `represented_by`.
  - Unusable source field is `no_signal_reason`.
  - Segment helper is `segment_inputs()`.
  - Citation helper is `validate_segment_citations(...)`.

---

## Execution Notes

Use the conda Python explicitly:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest ...
```

Keep commits small. Do not batch multiple tasks into one commit unless a task produced no file changes.

Before final handoff, run:

```powershell
git status --short
```

Expected tracked files are clean. Untracked generated artifacts may remain and should not be staged.
