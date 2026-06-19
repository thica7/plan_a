# Structured Analyst Knowledge Design

Date: 2026-06-19

## Goal

Upgrade the analyst agent from a source summarization step into a schema-bound analysis producer while preserving the project requirement that competitor knowledge is structured and exchanged between agents through structured messages.

The writer should stay unchanged during this phase. The change should strengthen the analyst and make comparator inputs more reliable before reducing writer complexity later.

## Current Context

The current pipeline already has the right shape:

- Analyst branches run per competitor and dimension.
- Analyst consumes scoped raw sources.
- Analyst produces `CompetitorKnowledge`.
- `CompetitorKnowledge` already contains structured slices such as `feature_tree`, `pricing_model`, `user_personas`, and `review_summary`.
- QA already checks for missing structured claims, missing source IDs, unknown source IDs, and some schema shape issues.

The gap is that the current contract mostly guarantees structured factual claims. It does not clearly require the analyst to produce reusable analytical judgments, evidence gaps, or comparator-ready signals. Because of that, comparator and writer can still be forced to infer too much from raw facts.

## Requirements Fit

This design keeps the course/project requirements intact:

- Competitor knowledge remains schema-first.
- Feature tree, pricing model, and user persona structures remain canonical.
- Agent handoff remains structured JSON/function-call style payloads, not free-form markdown.
- Every factual or analytical output must cite known `source_ids`.
- Analyst outputs should be validated by QA before comparator depends on them.

The design explicitly avoids replacing the knowledge schema with loose prose.

## Proposed Schema Additions

Extend `CompetitorKnowledge` with structured analysis fields:

```python
class AnalystInsight(BaseModel):
    dimension: str
    insight: str
    rationale: str
    source_ids: list[str]
    confidence: float
    importance: Literal["high", "medium", "low"]
    stance: Literal[
        "strength",
        "weakness",
        "risk",
        "opportunity",
        "neutral",
    ]


class EvidenceGap(BaseModel):
    dimension: str
    missing_evidence: str
    impact: str
    blocks_conclusion: bool


class ComparatorSignal(BaseModel):
    dimension: str
    signal: Literal["strong", "medium", "weak", "unknown"]
    reason: str
    source_ids: list[str]
    confidence: float
```

Then add these fields to `CompetitorKnowledge`:

```python
analysis_insights: list[AnalystInsight] = Field(default_factory=list)
evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
comparator_signals: list[ComparatorSignal] = Field(default_factory=list)
```

These fields are intentionally general and dimension-scoped. The existing dimension-specific schema remains the source of typed product knowledge:

- `feature_tree` for feature and capability knowledge.
- `pricing_model` for pricing knowledge.
- `user_personas` for persona and buyer/user knowledge.
- `review_summary` for review and community/user research knowledge.

## Analyst Output Contract

Each analyst branch should produce one `CompetitorKnowledge` slice for exactly one competitor and dimension.

For dimensions with usable sources, the branch should produce:

- At least one dimension-appropriate structured fact in the existing schema.
- At least one `AnalystInsight`, unless the evidence is insufficient.
- At least one `ComparatorSignal`, unless the evidence is insufficient.
- One or more `EvidenceGap` entries when the analyst cannot support a meaningful conclusion.

Facts and insights have different roles:

- A fact states what the source supports.
- An insight explains what the facts imply for competitive position, buyer risk, product strength, weakness, or market interpretation.
- A comparator signal is a compact, structured hint that comparator can use without re-reading raw sources.

The analyst must not output high-confidence insights or strong comparator signals from weak evidence. Community, web search, or low-confidence sources cannot be the sole support for high-confidence competitive judgments.

## Prompt Changes

The analyst system prompt should be updated from "produce strict structured competitor knowledge" to a stricter analysis contract:

```text
You are not summarizing sources.
You are producing source-grounded structured competitor knowledge.
Separate factual claims from analytical insights.
Every factual claim and analytical insight must cite known source_ids.
If evidence is insufficient, emit evidence_gaps instead of guessing.
Do not declare a competitive strength, weakness, or strong comparator signal unless the cited evidence supports it.
Return only schema-valid CompetitorKnowledge for the requested competitor and dimension.
```

The schema hint should include the new fields so both one-shot and ReAct analyst paths are held to the same output contract.

## Merge And Storage Rules

The analyst merge path should:

- Validate new models with Pydantic.
- Keep only source IDs that exist in the run.
- Scope new fields to the current dimension.
- Merge by normalized text plus sorted `source_ids` to avoid duplicates.
- Recompute `knowledge.source_ids` from all structured facts, insights, and comparator signals.
- Recompute `knowledge.confidence` from valid source-backed claims and insights.

Legacy `CompetitorKB` sync can continue to mirror factual claims for backwards compatibility, but comparator should increasingly prefer `CompetitorKnowledge`.

## QA Rules

Add analyst QA checks:

- If a competitor/dimension has usable sources and factual claims, but no insight and no evidence gap, create an analyst warning or blocker.
- If an insight has no `source_ids`, create a blocker.
- If an insight references unknown source IDs, create a blocker.
- If a comparator signal has `signal != "unknown"` but no source IDs, create a blocker.
- If a comparator signal has high confidence but only weak/community/web-search sources, create a warning or blocker.
- If evidence is insufficient, require `EvidenceGap.blocks_conclusion=True` for dimensions where no insight or signal is produced.

Existing checks for structured claims should remain.

## Comparator Consumption

Comparator should keep consuming existing fields, but prefer the new structured fields when available:

1. Use `comparator_signals` as first-class dimension-level signals.
2. Use `analysis_insights` as rationale text for matrix cells and SWOT.
3. Use existing facts from `feature_tree`, `pricing_model`, `user_personas`, and `review_summary` as supporting evidence.
4. If signals are missing, fall back to current deterministic logic.

This allows the change to be incremental and does not require writer changes.

## Writer Impact

Writer should remain unchanged in this phase.

The current writer can continue to receive the existing evidence pack and raw-source-derived projections. That keeps report generation stable while analyst quality improves. A later phase can simplify writer input once analyst and comparator outputs are reliable.

## Implementation Boundaries

This design is a backend schema and agent-contract change. It should not change frontend UI, run creation, collector behavior, or writer behavior in the first implementation phase.

Primary files likely affected:

- `backend/packages/schema/models.py`
- `backend/packages/agents/analysts/logic.py`
- `backend/packages/agents/qa/logic.py`
- `backend/packages/agents/comparator/logic.py`
- Analyst, comparator, and QA unit tests.

## Test Strategy

Add or update tests for:

- Analyst one-shot output merges insights, evidence gaps, and comparator signals.
- Analyst ReAct output validates the same schema contract.
- Unknown source IDs in insights or comparator signals are rejected.
- Weak/community-only evidence cannot produce high-confidence strong signals.
- Deterministic fallback produces facts and evidence gaps, not high-confidence insights.
- Comparator prefers comparator signals when available.
- Existing feature tree, pricing model, user persona, and review summary behavior still passes.

## Rollout Plan

1. Add schema fields and tests for validation.
2. Update analyst schema hints and merge logic.
3. Update deterministic fallback behavior.
4. Add analyst QA checks for insights, gaps, and signals.
5. Update comparator to consume signals as preferred inputs.
6. Keep writer unchanged.
7. Evaluate report quality and input size before deciding whether to simplify writer.

## Non-Goals

- Do not remove raw source access from writer in this phase.
- Do not replace `CompetitorKnowledge` with an independent free-form analyst artifact.
- Do not make analyst generate long markdown reports.
- Do not let comparator rely on uncited prose.
- Do not weaken existing source ID validation.

## Success Criteria

The change is successful when:

- Analyst outputs remain schema-valid.
- Feature tree, pricing model, and user persona outputs still satisfy the structured knowledge requirement.
- Each usable competitor/dimension produces either source-backed insights/signals or explicit evidence gaps.
- Comparator can form matrix and SWOT rationale from structured analyst outputs more directly.
- Writer output quality does not regress while writer code remains unchanged.
