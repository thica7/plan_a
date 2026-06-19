# Segmented Writer Contract and Report Assembler Design

Date: 2026-06-17
Status: User-approved design, pending written-spec review

## Purpose

Fix the report-quality failure mode exposed by `run-fd5b86355cff04844d92f1a15e197bfe`: the writer can collect enough evidence and produce a very long report, but the final Markdown can still be structurally poor, duplicated, support-heavy, and hard for release gates to recognize as decision-grade analysis.

This design keeps the current writer evidence pack direction, but separates three responsibilities that are currently mixed together:

1. Splitting large evidence inputs.
2. Writing report sections.
3. Assembling the final report.

The goal is not simply to pass a metric. The goal is a report that reads like one coherent competitive-intelligence document while preserving rich evidence, citations, and audit material.

## Observed Failure

In `run-fd5b86355cff04844d92f1a15e197bfe`, the initial writer used segmented generation and produced 10 writer segments:

| # | Segment | Scope | Input chars | Sources | Groups |
|---|---|---:|---:|---:|---:|
| 1 | `decision_summary` | `sources:1` | 90,611 | 41 | 9 |
| 2 | `decision_summary` | `sources:2` | 100,312 | 42 | 11 |
| 3 | `user_research` | all | 100,247 | 33 | 5 |
| 4 | `competitor_deep_dives` | Cursor | 97,179 | 16 | 3 |
| 5 | `competitor_deep_dives` | Claude Code | 125,338 | 17 | 3 |
| 6 | `competitor_deep_dives` | GitHub Copilot | 108,840 | 17 | 3 |
| 7 | `competitor_deep_dives` | Windsurf | 91,946 | 17 | 3 |
| 8 | `competitor_deep_dives` | OpenAI Codex | 147,283 | 16 | 3 |
| 9 | `swot_matrix` | all | 92,968 | 83 | 15 |
| 10 | `support_appendix` | all | 62,486 | 83 | 0 |

The final report had more than enough total characters, but quality comparison still failed on report quality:

- duplicate H2 sections, including duplicate decision summary and support sections
- competitor deep dives appearing after `Evidence and QA Support`
- `competitive_findings_section_score=0`
- `review_theme_section_score=0`
- `layer_analysis_section_score=0`
- `core_section_depth_score=0`
- `duplicate_section_count=4`
- unresolved QA blockers caused by citation parsing, which has since been fixed separately

Two writer-only redo attempts did not improve the report. Both preserved the previous report after writer error, with `before_issues=5`, `after_issues=5`, and `convergence_ratio=1.00`.

## Current Preflight Behavior

Current writer preflight is mostly an input evidence-pack check:

- every accepted source should be represented or have a no-signal reason
- dropped source count must be zero
- dropped KB slice count must be zero
- writer evidence pack size is recorded
- source registry, represented source count, raw source count, deduped quote/fact counts, and largest projections are recorded
- `segmented_writer_required` is set when prompt JSON exceeds `SINGLE_CALL_CONTEXT_TARGET_CHARS`
- large segments are split by source, group, dimension, or fact until they fit the input target where possible

Current segment output validation is much narrower:

- sanitize common source citation syntax problems
- validate cited source IDs against the segment's allowed source IDs
- retry once on invalid citations
- fail the writer segment if invalid citations remain

The current system does not validate:

- whether a segment used only the headings it is allowed to use
- whether evidence shards accidentally wrote final report sections
- whether a competitor deep-dive segment wrote a full report outline
- whether support content appeared before core analysis
- whether duplicate H2 sections were produced
- whether final report sections are unique and in canonical order
- whether section placement will satisfy report-quality gates before final QA

## Root Cause

`segment_inputs()` currently treats input-budget segmentation as report-section segmentation. When a logical writing area is split for budget reasons, each budget shard may still be asked to write Markdown. This causes duplicate sections.

For example, `decision_summary` was split into `sources:1` and `sources:2`; both shards could write their own `## Decision Summary`. The final writer path then joined segment markdown with `"\n\n".join(...)`. Later hardening can backfill missing sections and reorder known sections, but it does not perform true editorial assembly.

The system needs separate concepts for:

- an evidence shard that summarizes a portion of input evidence
- a section writer that produces one canonical report section or section group
- a final assembler that composes the complete report

## Goals

- Preserve evidence richness and source auditability.
- Keep all accepted raw sources represented in writer-visible data.
- Prevent input source batching from creating duplicate report sections.
- Make segment responsibilities explicit and testable.
- Keep core analysis before support and appendix material.
- Produce a final report with unique top-level H2 sections in canonical order.
- Keep citations valid and scoped.
- Route structural writer issues to deterministic assembly or section repair instead of full segmented rewrite.
- Add telemetry that explains segment splitting, validation, assembly, and quality preflight decisions.

## Non-Goals

- Do not reduce collector breadth.
- Do not make reports short again.
- Do not loosen source citation validity gates.
- Do not change front-end report display or export in this phase.
- Do not introduce database migrations unless implementation discovers a hard persistence requirement.
- Do not create a full two-tab core-report/support-appendix product experience in this phase.
- Do not solve every weak-source claim policy issue here; this design only ensures the assembler preserves and surfaces claim-risk sections correctly.

## Design Summary

Introduce a structured writer pipeline:

1. `EvidenceShard`
   - budget-split input unit
   - produces structured notes, not final Markdown
   - no H2 headings

2. `SectionFragment`
   - one canonical section or section group
   - produced by a section writer from one or more evidence shards
   - has allowed headings and forbidden headings

3. `ReportAssembler`
   - deterministic final assembly layer
   - orders sections, merges duplicates, moves core sections before support, preserves support material
   - runs final structural preflight before QA/release gate

4. `WriterRepairRouter`
   - maps writer-only issues to citation hygiene, assembler repair, section repair, or full rewrite
   - avoids full segmented rewrite for deterministic structure problems

## Segment Kinds

Add a first-class `segment_kind` field to segment payloads:

- `evidence_shard`
- `section_fragment`
- `support_fragment`
- `final_report`

This lets telemetry, validation, and prompt construction distinguish "input was split for budget" from "this is a report section."

Existing segment names can remain, but their meaning becomes more precise:

- `decision_summary_evidence_shard`
- `decision_summary_writer`
- `user_research_writer`
- `competitor_deep_dive_writer`
- `swot_matrix_writer`
- `support_appendix_writer`
- `final_assembler`

## Evidence Shards

Evidence shards are used when a logical writing task has too much input to fit in one prompt.

They must output structured JSON-like notes or tightly constrained Markdown bullet notes, not final report sections. The output should contain:

- `section_id`
- `shard_id`
- `covered_competitors`
- `covered_dimensions`
- `top_facts`
- `conflicts`
- `pricing_points`
- `feature_points`
- `user_signals`
- `community_triangulation`
- `claim_risks`
- `source_ids`
- `confidence_notes`

Evidence shards must not output:

- `##` top-level report headings
- full report outlines
- support appendix sections
- final recommendations unless the shard is specifically scoped to decision evidence notes

For run-fd, the two `decision_summary` source batches would become evidence shards. They would not each write `## Decision Summary`.

## Section Writers

Section writers consume one or more evidence shards plus compact structured context and produce a `SectionFragment`.

Each section writer has a strict output contract.

### Decision Summary Writer

Allowed output:

- `## Executive Summary` or localized equivalent, when needed
- `## Decision Summary`
- `## Competitive Findings`

Forbidden output:

- `## Competitor Deep Dives`
- `## Evidence and QA Support`
- `## Evidence Appendix`
- per-competitor full report sections

### User Research Writer

Allowed output:

- `## User Review Themes`
- user persona and buyer-signal subsections under that section
- adoption blockers and switching triggers
- community/user-signal triangulation when it is part of buyer feedback

Forbidden output:

- full report outline
- source appendix
- broad SWOT or matrix sections

### Competitor Deep-Dive Writer

Allowed output:

- one fragment under `## Competitor Deep Dives`
- competitor-scoped headings such as `### Cursor`, `### Claude Code`, or localized equivalents
- pricing, feature, persona, risks, and watchouts for the scoped competitor

Forbidden output:

- `## Decision Summary`
- `## Competitive Findings`
- `## SWOT Analysis`
- `## Evidence and QA Support`
- a full numbered report outline

### SWOT/Matrix Writer

Allowed output:

- `## Side-by-Side Decision Matrix`
- `## SWOT Analysis`
- compact winner/loser explanation

Forbidden output:

- support appendix
- duplicate competitor deep dives
- source audit table

### Support Appendix Writer

Allowed output:

- `## Evidence and QA Support`
- source quality
- memory context
- user research evidence support
- RAG gap fill
- scenario QA checklist
- claim validation and evidence risk
- next collection plan
- evidence appendix

Forbidden output:

- new core recommendations
- competitor deep dives
- hidden core analysis that should appear before support

## Segment Output Validator

After every segment call, validate the segment output before it can enter assembly.

Checks:

- output is non-empty
- citations are valid and scoped to allowed source IDs
- headings match the segment contract
- forbidden headings are absent
- evidence shards do not contain H2 headings
- support fragments do not contain core deep dives or final recommendations
- core section fragments do not contain support appendix headings

Validation outcomes:

- `pass`: segment can continue
- `sanitize`: deterministic heading/citation cleanup can fix it
- `retry`: prompt retry with explicit contract violation
- `quarantine`: keep the segment output as support notes but do not assemble it into core
- `fail`: stop if essential segment cannot be recovered

The retry prompt must cite the exact contract violation, not a generic "write better report" instruction.

## Report Assembler

Add a deterministic assembler, preferably outside the large writer mixin:

- `backend/packages/agents/writer/assembler.py`

Responsibilities:

- collect `SectionFragment`s
- normalize headings to canonical section IDs
- merge duplicate fragments for the same section ID
- order core sections before support sections
- ensure all competitor deep dives are before support
- preserve evidence/support material after core analysis
- insert deterministic backfill sections only when needed
- normalize citation formatting
- return assembly telemetry

The assembler should not call the LLM in its first version. If implementation later needs an LLM "editor", it must be a constrained optional pass after deterministic assembly, with anti-regression checks and no new facts.

Canonical top-level order:

1. Executive Summary
2. Decision Summary
3. Competitive Findings
4. User Review Themes
5. Competitor Deep Dives
6. Side-by-Side Decision Matrix
7. SWOT Analysis
8. Battlecard or layer-specific analysis
9. Product or Market Response
10. Evidence and QA Support
11. Source Quality and Coverage
12. User Research Evidence
13. RAG Gap Fill
14. Scenario QA Checklist
15. Claim Validation and Evidence Risk
16. Next Collection and Validation Plan
17. Evidence Appendix

Localized labels should continue to use `report_label()` and existing alias matching.

## Final Quality Preflight

Before final QA and release gate, run a deterministic quality preflight on the assembled report.

Checks:

- duplicate canonical H2 count is zero
- first support section appears after required core sections
- required core sections are present before support
- competitor deep-dive content for every planned competitor appears before support
- review theme/user research core section is present when user research evidence exists
- side-by-side matrix or comparison matrix is present before support
- layer-specific section is present before support
- citation tokens resolve
- core/support balance is above the existing threshold

If a check is deterministic to repair, call assembler repair. If the check requires more content, route to section repair. If the assembled report is broadly unusable, route to full rewrite.

## Redo Routing

Writer-only repair should no longer treat all writer issues as full segmented rewrite candidates.

Routing order:

1. Citation hygiene or phantom citation
   - deterministic citation repair or QA extractor correction
   - no full writer call

2. Duplicate sections or support-order violations
   - assembler repair
   - no full writer call

3. One or two thin sections
   - section writer repair for targeted section IDs
   - then assembler

4. Segment contract violation
   - retry only the failing segment
   - if still failing, quarantine non-essential support fragment or fail essential segment

5. Upstream evidence or matrix changed
   - allow broad regeneration
   - still assemble final report and apply anti-regression checks

6. Broad structural failure
   - full rewrite, but preserve useful previous report content if protectable

`release_gate.report_depth_required` should not automatically imply full rewrite. If the failed metric is caused by duplicate sections, support ordering, or section recognition, assembler repair should run first.

## Telemetry

Trace events should make the pipeline inspectable:

- `writer_preflight`
  - evidence pack metrics
  - segmented writer required
  - planned segment count by kind

- `writer_segment_preflight`
  - `segment_kind`
  - `section_id`
  - `segment_name`
  - competitor/dimension/batch
  - allowed heading IDs
  - forbidden heading IDs
  - allowed source count
  - input chars

- `writer_segment_validated`
  - validation status
  - forbidden headings found
  - invalid citations found
  - retry count

- `writer_assembly_completed`
  - fragment count
  - merged duplicate sections
  - moved sections
  - support start section
  - missing required sections backfilled

- `writer_quality_preflight`
  - duplicate section count
  - required section coverage
  - core/support balance
  - citation validity
  - routing decision if repair is needed

When writer errors occur, preserve the concrete exception reason in trace payload instead of only reporting "preserved previous report after writer error."

## Compatibility

Existing `WriterEvidencePack` models can remain. The implementation should extend segment payloads rather than replacing the full pack in one large rewrite.

Existing report hardening functions can be reused:

- required-section backfill
- citation repair
- source-token sanitation
- section ordering aliases
- quality metrics

However, final assembly should become the primary place where ordering, duplicate handling, and support placement are enforced.

No database migration is required unless the implementation decides to persist intermediate evidence shard notes. Initial implementation can keep shard notes in memory and expose them through trace events.

## Migration Path

The final architecture separates evidence shards from section writers, but the implementation does not need to land that separation in one risky rewrite.

Phase 1 can wrap current segment Markdown output with contracts, validation, deterministic assembly, and final quality preflight. This immediately addresses duplicate sections, support-order failures, and release-gate recognition issues.

Phase 2 can convert budget-split segments into true evidence shards. At that point, source batches such as `decision_summary:sources:1` and `decision_summary:sources:2` stop producing final Markdown and instead feed a single `decision_summary_writer`.

This phasing is intentional: assembler-first reduces user-visible report damage quickly, while shard/section separation removes the upstream cause.

## Testing Strategy

Add unit tests before implementation changes.

### Segment Contract Tests

- decision summary shard cannot output H2 final report sections
- competitor deep-dive writer rejects `## Decision Summary`
- support appendix writer rejects competitor deep-dive headings
- valid scoped citations pass
- invalid scoped citations still fail

### Assembler Tests

Use a run-fd-shaped fixture:

- duplicate `## Decision Summary`
- duplicate `## Evidence and QA Support`
- GitHub Copilot and Windsurf deep dives after support
- user review themes nested inside a competitor deep dive
- ordinary `raw-source:hash` metadata text

Expected output:

- no duplicate canonical H2 sections
- competitor deep dives before support
- support sections after core analysis
- citation tokens still resolve
- source appendix/support content preserved

### Quality Preflight Tests

- report with enough content but bad section order fails preflight before repair
- assembler-repaired report passes duplicate/support-order checks
- `core_section_depth_score` does not drop to zero due to support placement
- `review_theme_section_score` is recognized when user research section exists before support

### Redo Routing Tests

- phantom citation only routes to citation/assembler repair, not full rewrite
- duplicate sections route to assembler repair
- thin user review section routes to section repair
- upstream data changed can still route to broad rewrite

### Regression Tests

Use current passing tests as guardrails:

- writer evidence pack keeps all raw sources represented
- segmented writer citation sanitizer still normalizes spacing and combined citations
- source reconciliation still resolves aliases and raw source IDs
- writer repair anti-regression still protects useful previous reports

## Implementation Order

1. Add segment contract models and validators.
2. Add deterministic assembler over existing segment Markdown output.
3. Add final quality preflight using existing report-quality helpers.
4. Route duplicate/support-order failures to assembler repair.
5. Split evidence shard output from section writer output for budget-split cases.
6. Tighten segment prompts to match the new contracts.
7. Add telemetry events.
8. Re-run a real report and compare quality metrics against run-fd failure shape.

This order reduces risk. The assembler can first clean existing segment outputs, then later the input shard/section writer split can reduce the amount of cleanup needed.

## Open Decisions

The design makes one explicit product choice: support and audit material remain in the same Markdown report for now, but they must appear after core analysis. A future dual-layer report UI can reuse the assembler's core/support boundary, but this phase does not require front-end changes.

The first implementation should prefer deterministic assembly over an LLM final editor. An LLM editor may be added later only if deterministic assembly leaves the report readable but too mechanical.
