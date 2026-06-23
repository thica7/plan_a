# Collector v2 Phase 1 Design

Date: 2026-06-22

## Goal

Improve collector information gathering by replacing source-count completion with evidence-intent coverage, traceable candidate lifecycle diagnostics, intent-aware candidate selection, source fitness gating, and coverage-driven repair.

This phase is a minimal implementable loop. It does not attempt to rewrite the full collector, pricing extractor, browser fetch stack, search provider stack, or report writer.

## Problem Summary

The current collector can mark a competitor-dimension branch complete after collecting enough apparently valid sources, even when those sources do not support the dimension-specific claim. The Windsurf pricing failure showed this clearly:

- trusted docs, changelog, and product docs were accepted as pricing evidence;
- the current official pricing page was not fetched;
- `len(sources) >= target_source_count` prevented ReAct repair from running;
- QA found a warning later, after bad evidence had already moved downstream.

The core issue is not one missing URL. It is an end-to-end evidence flow problem:

```text
candidate discovery
-> ranking / selection
-> fetch
-> extraction
-> evidence admission
-> RawSource admission
-> collector completion
-> QA
```

Phase 1 makes that flow observable and changes collector completion from "enough sources" to "required evidence intents satisfied".

## Scope

In scope:

- Candidate ledger / trace diagnostics.
- KB warm-start source diagnostics and coverage evaluation.
- Coverage contract for collector completion.
- Intent-bucket discovery and selection.
- Adaptive backfill from overflow candidates.
- Deterministic source fitness classification.
- Collector QA gate and coverage-driven repair trigger.

Out of scope for Phase 1:

- Full pricing extractor rewrite.
- Default browser or network-capture fetching.
- Multiple search providers.
- New claims / conflicts schema.
- Major report writer changes.
- RAG KB retrieval redesign.
- Full Collector v2 migration beyond the branch-level collection loop.

## Current Code Touchpoints

Primary modules:

- `backend/packages/research/models.py`
- `backend/packages/research/pipeline.py`
- `backend/packages/research/capture/selection.py`
- `backend/packages/research/discovery/ranking.py`
- `backend/packages/research/evidence/admission.py`
- `backend/packages/agents/collectors/logic.py`

Suggested new modules:

- `backend/packages/research/coverage_contract.py`
- `backend/packages/research/source_fitness.py`

Relevant current behavior:

- `run_research_pipeline()` returns `ResearchResult` with candidates, captured pages, extractions, evidence, gaps, and metrics.
- collector now performs `_collect_competitor_from_kb()` before web search and can warm-start the branch with `RawSource` records whose `candidate_origin` is `rag_kb`.
- `_discover_candidates()` currently returns `rank_and_dedupe_candidates(... )[: brief.max_candidates]`.
- `select_capture_candidates()` currently selects preferred candidates first and may skip fallback candidates entirely when preferred count is high enough.
- `source_saturation_reached` currently depends on `len(ok_pages) >= brief.target_source_count and len(gaps) == 0`.
- collector ReAct repair is mainly gated by `len(sources) < target_source_count`.

## Recommended Approach

Use a Phase 1 "Quality Gate Loop":

```text
candidate ledger
-> intent-bucket discovery
-> adaptive backfill
-> source fitness
-> coverage contract
-> collector QA repair trigger
```

This directly addresses the unsafe path where wrong sources are accepted and collection stops early. It also absorbs the useful parts of evidence attrition diagnostics without relaxing evidence admission first.

## Data Model

Add literals in `backend/packages/research/models.py`.

```python
CandidateIntent = Literal[
    "official_pricing_page",
    "official_billing_or_usage_docs",
    "current_plan_price_support",
    "community_or_conflict_signal",
    "official_docs",
    "product_page",
    "third_party_context",
    "unknown",
]

CandidateLedgerStatus = Literal[
    "discovered",
    "deduped",
    "dropped_by_rank",
    "selected",
    "skipped",
    "fetch_failed",
    "fetched",
    "extracted",
    "evidence_rejected",
    "raw_source_rejected",
    "accepted",
]

SourceFitness = Literal[
    "official_pricing",
    "official_billing_docs",
    "official_usage_limits",
    "changelog",
    "product_docs",
    "community",
    "third_party",
    "irrelevant_or_stale",
    "unknown",
]
```

Add a candidate ledger entry:

```python
class CandidateLedgerEntry(ResearchBaseModel):
    candidate_id: str
    url: str
    origin: str
    intent: CandidateIntent = "unknown"
    status: CandidateLedgerStatus
    reason: str = ""
    selected: bool = False
    fetched: bool = False
    source_fitness: SourceFitness = "unknown"
    coverage_intent: CandidateIntent = "unknown"
    requested_url: str | None = None
    final_url: str | None = None
    page_status: CaptureStatus | None = None
    evidence_status: EvidenceStatus | None = None
    raw_source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Add a coverage contract result:

```python
class CoverageContractResult(ResearchBaseModel):
    dimension: str
    competitor: str
    required_intents: list[CandidateIntent] = Field(default_factory=list)
    satisfied_intents: list[CandidateIntent] = Field(default_factory=list)
    missing_intents: list[CandidateIntent] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list)
    passed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Extend `ResearchResult`:

```python
candidate_ledger: list[CandidateLedgerEntry] = Field(default_factory=list)
coverage: CoverageContractResult | None = None
```

Also mirror key values in `ResearchResult.metrics`:

- `coverage_contract_passed`
- `coverage_missing_intents`
- `candidate_ledger_count`
- `candidate_dropped_by_rank_count`
- `candidate_selected_by_intent_count`
- `source_fitness_counts`

`CandidateLedgerEntry.origin` is intentionally `str`, not `CandidateOrigin`, because Phase 1 must also represent sources that do not flow through `SourceCandidate`, especially KB warm-start sources with `candidate_origin="rag_kb"`.

## Candidate Ledger

The ledger records the final lifecycle state for every candidate that enters the pipeline.
It must also record branch sources that bypass `SourceCandidate`, such as KB warm-start `RawSource` records. Those entries can use the raw source id as `candidate_id`, `origin="rag_kb"`, and `status="accepted"` or `status="raw_source_rejected"` depending on source quality and coverage evaluation.

Required states:

- `discovered`: candidate was created from seed, registry, search, homepage, community, LLM, or ReAct.
- `deduped`: candidate was merged into another canonical URL.
- `dropped_by_rank`: candidate was valid but not retained after candidate budget.
- `selected`: candidate was selected for fetch.
- `skipped`: candidate failed policy or was left in overflow.
- `fetch_failed`: capture failed.
- `fetched`: capture succeeded.
- `extracted`: extraction produced fields.
- `evidence_rejected`: field evidence failed admission.
- `raw_source_rejected`: page did not become a usable `RawSource`.
- `accepted`: page became a `RawSource` or satisfied a coverage intent.

Ledger entries must include enough reason text to answer:

- Was this URL discovered?
- Why was it selected or skipped?
- Was it fetched?
- What final URL did it redirect to?
- What source fitness was assigned?
- Why did evidence or raw source admission fail?
- Which coverage intent did it satisfy?

## Coverage Contract

Collector completion should be based on a coverage contract, not source count.

Phase 1 implements strict pricing coverage and leaves other dimensions with a compatible, less strict fallback.

Pricing required intents:

- `official_pricing_page`
- `official_billing_or_usage_docs`
- `current_plan_price_support`

Optional but useful intent:

- `community_or_conflict_signal`

Pricing contract passes when:

```text
(official_pricing_page OR official_billing_or_usage_docs)
AND current_plan_price_support
AND no blocking source fitness failure for accepted pricing sources
```

Examples of blocking reasons:

- no current official pricing or billing source;
- only changelog or product docs support pricing;
- accepted pricing fields have no local quote or table support;
- source identity appears stale, redirected, or competitor-confused;
- official pricing page was never fetched and no explicit not-found result exists.

Non-pricing Phase 1 fallback:

- keep existing field/gap quality behavior;
- add coverage metadata and warnings when all accepted sources are low-fitness or non-official;
- do not block unless existing gap evaluation already blocks.

## Intent-Bucket Discovery

Candidate discovery should preserve required evidence intents instead of globally truncating by origin score.

Phase 1 keeps existing sources:

- seed candidates;
- KB warm-start raw sources;
- trusted registry;
- search results;
- homepage-derived candidates;
- repair/ReAct candidates.

Each candidate receives a deterministic `CandidateIntent` based on:

- dimension;
- URL path;
- origin;
- trusted domain / homepage host match;
- title and snippet terms;
- community/search origin;
- repair task hints.

For pricing, path and text signals include:

- `/pricing`
- `/plans`
- `/billing`
- `/enterprise`
- `/business`
- `/docs/pricing`
- `price`, `pricing`, `plans`, `billing`, `credits`, `seat`, `usage`, `free tier`, `contact sales`

Selection should reserve slots by intent before filling the rest globally. A suggested initial quota for pricing:

- 1-2 official pricing candidates;
- 1 official billing or usage docs candidate;
- 1 search result on the official domain;
- 1 community or conflict signal if available;
- remaining slots by global score.

Canonical pricing paths from homepage hints must be selected or recorded in the ledger as skipped / unreachable. They must not disappear silently because stale registry docs ranked higher.

## Adaptive Backfill

Selection should return:

```python
selected: list[SourceCandidate]
overflow_queue: list[SourceCandidate]
skipped_reasons: dict[str, str]
selected_intents: dict[str, list[str]]
```

The pipeline should continue fetching from `overflow_queue` when coverage is not satisfied and fetch budget remains.

Backfill loop:

```text
while coverage not passed
  and fetch_budget_remaining
  and overflow_queue not empty:
    fetch next candidate
    classify source fitness
    extract
    admit evidence
    update raw source admission diagnostics
    re-evaluate coverage
```

Backfill should stop when:

- coverage passes;
- fetch budget is exhausted;
- no candidates remain;
- repair round budget is exhausted;
- a non-recoverable exception occurs and is recorded.

## Source Fitness Gate

Add `backend/packages/research/source_fitness.py` with deterministic classification.

Inputs:

- `ResearchBrief`;
- `SourceCandidate`;
- `CapturedPage`;
- accepted/rejected evidence items when available.

Outputs:

- `SourceFitness`;
- reason string;
- coverage intents satisfied by the page.

Pricing rules:

- `official_pricing`: trusted/homepage host, pricing/plans/billing path or title, and pricing terms in content.
- `official_billing_docs`: trusted/homepage host, billing/usage/accounts/docs path, and billing or usage terms.
- `official_usage_limits`: trusted/homepage host with usage/limits/credits content but no current tier-price support.
- `changelog`: changelog/release notes path or title.
- `product_docs`: docs/product/plugin/API overview without pricing table or billing focus.
- `community`: Reddit, forum, community, social, review, discussion source.
- `third_party`: non-official article or listing.
- `irrelevant_or_stale`: competitor mismatch, soft 404, stale rebrand confusion, or page not about the requested dimension.

Admission policy for pricing:

- `official_pricing` can satisfy `official_pricing_page` and `current_plan_price_support` if evidence has price/table support.
- `official_billing_docs` can satisfy `official_billing_or_usage_docs` and may satisfy `current_plan_price_support` only if it includes current plan-price evidence.
- `official_usage_limits` can support usage context but not current plan pricing by itself.
- `changelog` cannot satisfy current pricing.
- `product_docs` cannot satisfy current pricing.
- `community` can satisfy only `community_or_conflict_signal`.
- `third_party` can provide context but cannot satisfy official pricing requirements.

## Collector QA Gate and Repair

Modify the collector branch flow in `backend/packages/agents/collectors/logic.py`.

Current behavior:

```python
if len(sources) < target_source_count:
    run ReAct
```

Phase 1 behavior:

```python
if coverage failed and repairable:
    run targeted ReAct using missing_intents, blocking_reasons, rejected reasons
elif len(sources) < target_source_count:
    run existing low-count fallback
```

Repair prompt context must include:

- competitor;
- dimension;
- homepage hint;
- missing coverage intents;
- source fitness failures;
- rejected candidates and reasons;
- already fetched URLs;
- explicit request for canonical official source when missing.

Collector output payload should include:

- `coverage_contract_passed`;
- `coverage_missing_intents`;
- `coverage_blocking_reasons`;
- `candidate_ledger_summary`;
- `repair_triggered_by_coverage`.

If repair fails, collector should output partial sources plus coverage gap metadata. It must not mark the branch as complete only because source count is high.

KB warm-start sources must be evaluated by the same coverage gate. They may satisfy a coverage intent only if source fitness and evidence support allow it. They must not satisfy pricing completion merely because `_collect_competitor_from_kb()` returned enough high-confidence `RawSource` records.

## Error Handling

New quality gates should degrade structurally, not crash the run.

- Candidate ledger failures should not block collection; record `ledger_error` in metrics.
- Coverage contract errors should fall back to old source-count behavior and record `coverage_contract_error`.
- Source fitness `unknown` should not reject non-pricing sources in Phase 1.
- Pricing sources with `unknown` fitness should not satisfy official pricing intents unless source quality and URL/path evidence are strong.
- Repair budget exhaustion should produce partial coverage and explicit repair failure metadata.
- ReAct errors should preserve existing deterministic fallback behavior.

## Expected Windsurf Pricing Behavior

Given the previous failed pattern:

```text
docs.devin.ai/desktop/accounts/usage
docs.devin.ai/windsurf/plugins/changelog
docs.devin.ai/windsurf/plugins/cascade/cascade-overview
```

Expected Phase 1 classification:

- `docs.devin.ai/desktop/accounts/usage`
  - fitness: `official_billing_docs` or `official_usage_limits`
  - can support billing/usage context
  - cannot alone satisfy current plan price support unless current tier-price evidence is present

- `docs.devin.ai/windsurf/plugins/changelog`
  - fitness: `changelog`
  - cannot satisfy current pricing

- `docs.devin.ai/windsurf/plugins/cascade/cascade-overview`
  - fitness: `product_docs`
  - cannot satisfy pricing

The official pricing page candidate, such as `https://devin.ai/pricing/` or an equivalent official pricing/plans URL, must be selected/fetched or recorded in the ledger as unavailable.

If no official pricing page is found:

```text
coverage.passed = false
missing_intents = ["official_pricing_page", "current_plan_price_support"]
repair_hints = ["Find current official pricing or plans page for Windsurf/Devin."]
```

Collector should then trigger targeted repair/ReAct even if it already has three sources.

## Testing Plan

Add focused unit tests before broad integration work.

### Candidate Ledger

Given candidates that are deduped, dropped, selected, fetched, rejected, and accepted, the ledger records final status and reason for each candidate.

Assertions:

- every discovered candidate has a ledger entry or dedupe parent;
- selected candidates are marked selected;
- fetch failures include requested URL and reason;
- raw source rejection diagnostics are attached.
- KB warm-start sources appear in the ledger with `origin="rag_kb"` and either accepted or rejected status.

### Intent-Bucket Selection

For pricing, when trusted docs rank above homepage-derived `/pricing`, selection still includes `/pricing` or places it in overflow with an explicit reason.

Assertions:

- canonical pricing candidate is not silently dropped;
- selected intents include official pricing or billing intent when available;
- global ranking still fills remaining slots.

### Adaptive Backfill

When selected candidates fail fetch/admission and overflow candidates remain, pipeline continues fetching until coverage passes or budget is exhausted.

Assertions:

- fetch count increases beyond initial selected set when needed;
- overflow candidates move to selected/fetched in ledger;
- backfill stops once coverage passes.

### Source Fitness Gate

For pricing:

- changelog cannot satisfy current plan pricing;
- product docs cannot satisfy official pricing page;
- official pricing path with tier-price evidence can satisfy pricing intent;
- official billing docs can satisfy billing intent.

### Coverage Contract

When `len(sources) >= target_source_count` but sources lack official pricing/current price support, coverage fails.

Assertions:

- `coverage_contract_passed` is false;
- missing intents include official pricing/current price support;
- source saturation metric does not report success based only on count.
- KB warm-start source count alone does not make pricing coverage pass.

### Collector Repair Trigger

When source count is high but coverage fails, collector triggers coverage-driven repair.

Assertions:

- ReAct/repair receives missing intents and rejected reasons;
- `repair_triggered_by_coverage` is true;
- existing low-count fallback still works.

### Windsurf Regression

Construct the old failure pattern with docs, changelog, and product docs. Confirm the branch does not complete pricing coverage unless an official pricing/billing source with current plan support is present.

## Rollout Plan

Phase 1 should be behind a feature flag or settings toggle until tests and one replay run pass.

Suggested setting:

```text
COLLECTOR_COVERAGE_CONTRACT_ENABLED=true
```

Default can be true in development and false in production-like replay until evaluated.

Metrics to inspect during rollout:

- coverage contract pass rate;
- missing intent counts;
- repair trigger count;
- accepted source count before and after repair;
- false positive pricing completion rate;
- candidate dropped by rank count;
- backfill fetch count;
- source fitness distribution.

## Acceptance Criteria

Implementation is complete when:

- the candidate ledger shows lifecycle status for discovered candidates;
- KB warm-start sources are visible in the ledger and covered by the same coverage contract;
- pricing coverage does not pass solely because source count is high;
- canonical pricing/plans/billing candidates are selected or explicitly logged as unavailable;
- failed candidates can be replaced by overflow backfill within budget;
- pricing source fitness blocks changelog/product docs from satisfying current pricing;
- collector triggers repair when coverage fails despite enough sources;
- Windsurf-style regression no longer marks pricing complete with docs/changelog/product docs only;
- tests cover ledger, selection, backfill, fitness, coverage, repair trigger, and regression behavior.
