# Schema Contract Segment Writer Design

Date: 2026-06-20
Status: User-approved direction, written spec pending user review

## Purpose

Recover the reader-facing quality seen in `run-6c48aaee39e1f4401ae0577b251bde0f`
while keeping the hard validation work already built on
`codex/schema-first-writer-20260619`.

The current branch moved too far toward a "typed JSON field writer" model. Real
runs now ask the LLM to generate many small structured section payloads, then
render those payloads into Markdown. That improves control, but recent runs show
a worse reader experience:

- Reports feel mechanical and audit-heavy.
- Writer calls are slower and more numerous.
- Citations can become dense or repetitive.
- Support and claim-review material can leak into the user-facing report.
- Scoped redo can preserve or repair structure, but the final prose can still
  regress.

The goal is not to abandon schema-first. The goal is to move schema-first from
"LLM must fill many small JSON sections" to "the report has a strict publication
contract, while the LLM writes natural report segments inside that contract."

## Core Decision

Use the current `codex/schema-first-writer-20260619` branch as the base.

Do not restart from `codex/stable-report-backup-20260619`. That branch has a
better natural writer shape, but weaker publication guarantees. Instead, keep
the current branch's useful hardening and replace the real-run main writer shape.

## Design Summary

Target pipeline:

```text
Writer Evidence Pack
  -> Segment Planner
  -> Natural Segment Writers
  -> Segment Contract Validator
  -> Keyed Report Assembler
  -> Publication Contract
  -> Final Quality Result
  -> report_md
```

The LLM writes natural Markdown fragments, but each fragment is scoped by an
explicit segment contract. Deterministic code owns section identity, core/support
ordering, citation hygiene, publishability, and final quality accounting.

This keeps the useful part of stable backup:

- Fewer, larger writing units.
- More coherent narrative.
- More natural executive summary, deep dives, and battlecard prose.

It keeps the useful part of the schema-first branch:

- Fail-closed real-run behavior.
- Publication contract.
- Citation hygiene.
- Internal-term leakage checks.
- Scoped redo and recommendation-delta protection.
- Unified quality accounting.

## Non-Goals

- Do not reintroduce silent Markdown fallback for real schema-first runs.
- Do not remove source ID validation.
- Do not reduce collector breadth or evidence pack richness.
- Do not add a frontend redesign in this phase.
- Do not add a database migration in this phase.
- Do not commit generated reports, run outputs, database packages, logs, zip
  files, or local document exports.
- Do not keep the 13-section JSON writer as the default real-run path.
- Do not solve upstream claim-quality policy in this spec, except where writer
  routing must preserve warnings and evidence limits.

## Current State

The current branch has two writer shapes in the codebase:

1. Structured JSON writer
   - Builds section plans such as `executive_summary`, `decision_summary`,
     `competitive_findings`, `user_review_themes`, one deep dive per competitor,
     `decision_matrix`, `swot`, `battlecard`, `community_triangulation`, and
     `support`.
   - Requires JSON payloads using Pydantic models in `structured_report.py`.
   - Renders final Markdown through `structured_renderer.py`.

2. Segmented Markdown writer
   - Builds larger Markdown fragments through `report_writer_segment`.
   - Uses `segment_contract.py` and `assembler.py`.
   - This resembles the stable backup writer shape and produced better reader
     quality in `run-6c48...`.

The new design makes the second shape the real-run authoring path, but hardens
it with the schema-first publication layer from the first shape.

## Target Segment Model

The real-run writer should use these canonical segment groups:

1. `decision_summary`
   - Owns executive summary, decision summary, and competitive findings.

2. `user_research`
   - Owns user review themes, direct community signals, simulated research
     labels, adoption blockers, switching triggers, and user-evidence limits.

3. `competitor_deep_dives`
   - One segment per competitor.
   - Owns positioning, pricing, feature capability, persona/adoption, community
     feedback, risks, and competitive plays for that competitor.

4. `swot_matrix`
   - Owns decision matrix, matrix interpretation, SWOT, and cross-competitor
     implications.

5. `battlecard`
   - Owns competitor-specific attack points, defense points, objections,
     rebuttals, use-when guidance, and proof-needed caveats.

6. `support_appendix`
   - Owns evidence support, source quality, user research evidence support, RAG
     gap fill, scenario QA, claim risk, next collection, and evidence appendix.

This is intentionally closer to stable backup than to the current 13-section JSON
writer. The key difference is that each segment has machine-readable identity and
must pass deterministic publication checks before the report can be accepted.

## Segment Contract

Each segment input must include:

- `segment_name`
- `segment_kind`
- `section_key`
- `layer`: `core` or `support`
- `allowed_h2_keys`
- `required_h2_keys`
- `forbidden_h2_keys`
- `allowed_source_ids`
- `competitor`, when scoped
- `redo_scope`, when generated after an upstream redo

The LLM may write natural Markdown, but it must obey:

- Only allowed H2 sections.
- Required section content for the segment.
- No support sections inside core segments.
- No new core recommendations inside support segments.
- No internal implementation language.
- No source IDs outside `allowed_source_ids`.
- No citations in headings, section markers, or table headers.
- No English structural headings in Chinese reports, except product names,
  API names, model names, standards, and unavoidable technical nouns.

## Keyed Assembly

Stable backup used heading recognition heavily. The new design should avoid
making heading text the source of truth.

The assembler should use segment metadata first:

```text
segment.section_key -> canonical report section group
segment.layer       -> core/support placement
segment.competitor  -> scoped deep-dive ownership
```

Heading matching can remain as a compatibility fallback, but it must not be the
primary way to determine whether a fragment is core or support.

Assembler responsibilities:

- Merge fragments by canonical section key.
- Preserve one deep dive per competitor.
- Keep core sections before support sections.
- Keep support and audit material after the business report.
- Remove duplicate H2 sections deterministically where possible.
- Emit telemetry for missing, duplicate, moved, preserved, and repaired
  sections.
- Refuse to publish when an essential core segment is missing and cannot be
  recovered from a previous valid report.

## Publication Contract

The publication contract remains a hard gate. It validates the final rendered
Markdown, regardless of whether content came from natural segments or structured
objects.

It must reject or route repair for:

- Citation on section marker lines.
- Citation in headings.
- Citation in table headers.
- Invalid or unknown source IDs.
- Internal terms such as `source_registry`, `allowed_source_ids`,
  `represented_by`, `Segment Evidence Pack`, `Writer Evidence Pack`, `fact:`,
  `signal:`, or raw process instructions.
- English structural headings in Chinese reports.
- Template-only executive summary.
- Template-only battlecard.
- Support/audit sections before core analysis.
- Claims that conflict with the recommendation without a risk-adjusted
  explanation.

Renderer-owned or assembler-owned mistakes should be fixed deterministically
before any LLM retry.

## Structured Models After This Change

The existing structured report models are not thrown away, but they are no
longer the default authoring format for real runs.

They should be used as:

- Validation vocabulary.
- Publication contract metadata.
- Optional adapter target for tests and diagnostics.
- Future persistence shape if a database-backed dual-layer report is added.

They should not force every real report paragraph to be authored as many small
Pydantic JSON objects.

## Redo And Repair Routing

Redo should operate at segment scope:

- Persona or user-signal warnings target `user_research` and the affected
  competitor deep-dive segment.
- Pricing warnings target the affected competitor deep dive, matrix/SWOT, and
  support claim-risk notes.
- Battlecard issues target `battlecard`.
- Executive-summary issues target `decision_summary`.
- Citation placement and marker/header problems target renderer or publication
  contract repair, not the LLM.
- Duplicate or misplaced sections target assembler repair.

Full rewrite is allowed only when:

- Multiple essential core segments are missing.
- The evidence basis materially changed across several dimensions.
- The previous report is unavailable and the current assembled report is not
  publishable.
- A scoped repair repeatedly fails its own segment contract.

## Recommendation Delta Guard

Scoped redo must not freely change the global recommendation.

When only one competitor or one dimension changed upstream:

- Preserve the previous recommendation by default.
- Allow recommendation changes only when the changed evidence explicitly
  supports the new recommendation.
- Record the justification in telemetry.
- If justification is absent, accept the scoped section update but preserve the
  previous recommendation posture.

This directly addresses the observed failure where a scoped persona repair could
move the global recommendation without enough new evidence.

## Support Layer

Support material stays in the Markdown report for now, but it must be visibly
separate and reader-facing.

Support appendix must not include:

- Raw `source_registry` dumps.
- Internal QA status contradictions.
- `Wait/Recheck` style labels.
- Prompt or evidence-pack implementation text.
- Raw claim-review rows that read like system logs.

Support appendix may include:

- Source quality summary.
- User research evidence limitations.
- RAG gap fill summary.
- Scenario QA checklist.
- Claim-risk summary in reader-facing language.
- Next collection recommendations.
- Evidence appendix with source IDs.

## Error Handling

For real runs:

- Natural segment generation failure in an essential segment should retry that
  segment with exact contract errors.
- If retry fails and no previous valid report can cover the missing segment, the
  writer fails closed.
- If a previous valid report exists, preserve unaffected segments and record the
  failed segment repair.
- Do not silently call the old full Markdown fallback.

For feature-flag-disabled, demo, legacy, or diagnostic modes:

- Legacy Markdown fallback may remain available.
- Fallback must be trace-visible.

## Telemetry

Add or harden trace events:

- `writer_segment_plan_prepared`
  - segment count, section keys, layer counts, competitor scope.

- `writer_segment_started`
  - segment name, section key, layer, competitor, input chars, source count.

- `writer_segment_validated`
  - contract status, retry count, citation status, heading status.

- `writer_keyed_assembly_completed`
  - input fragment count, output section count, merged duplicates, missing
    essentials, first support section.

- `writer_publication_contract_validated`
  - passed, issue codes, repair targets.

- `writer_segment_repair_selected`
  - target segment, reason, redo scope, LLM required or deterministic.

- `writer_recommendation_delta_checked`
  - previous posture, candidate posture, accepted or preserved, justification.

## Migration Path

Phase 1: Make natural segment authoring the real-run main path behind the
existing structured-writer feature flag.

- Keep current structured JSON writer code available for tests and diagnostics.
- Use current evidence pack and segment inputs.
- Route real-run writing through canonical natural segments.

Phase 2: Harden keyed assembly.

- Add explicit section keys and layers to segment payloads.
- Make assembler consume keys first and heading text second.
- Add duplicate/support ordering tests.

Phase 3: Route publication and repair through the contract.

- Keep publication contract as final gate.
- Map publication issues to segment, assembler, renderer, or quality-status
  repair targets.

Phase 4: Real-run verification.

- Restart backend/frontend from current branch.
- Run one real AI Coding Agent report.
- Audit trace, segment routing, redo behavior, publication contract, final
  quality result, and report body.

## Testing Strategy

Use the conda environment:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest ...
```

Focused unit tests:

- Segment planner produces the canonical segment set.
- Each segment includes section key, layer, allowed headings, and allowed source
  IDs.
- Core segment cannot emit support headings.
- Support segment cannot emit new core recommendations.
- Keyed assembler orders core before support without relying only on heading
  text.
- Duplicate section fragments are merged deterministically.
- Publication contract rejects marker-line citations, heading citations,
  table-header citations, internal terms, and English structural headings in
  Chinese reports.
- Scoped redo only rewrites affected segments.
- Recommendation delta guard preserves previous recommendation when scoped
  evidence does not justify a change.
- Real schema-contract segment writer does not emit `writer_markdown_fallback_used`.
- Legacy/flag-disabled fallback remains available and trace-visible.

Regression checks against recent runs:

- `run-6c48...` remains the reader-quality baseline for natural segment shape.
- Current-branch failures such as citation spam, internal leakage, QA/support
  pollution, and slow 13-section generation are represented by focused fixtures.

## Acceptance Criteria

The work is complete when:

- Real runs use natural segment authoring rather than the 13-section JSON writer
  as the default main path.
- Schema-first remains active as a publication contract and repair-routing
  system.
- Final reports read more like `run-6c48...` while preserving hard gates from the
  current branch.
- Core/support separation is based on segment keys and layers, not only heading
  text.
- Publication contract blocks citation hygiene and internal-leak regressions.
- Scoped redo cannot change global recommendation without evidence-backed
  justification.
- Focused unit tests pass in the conda environment.
- A restarted real run is audited and shows no silent Markdown fallback, no
  internal leakage, no marker/header citation noise, and a coherent business
  report body.

## Risks And Mitigations

### Risk: This becomes a full rollback to stable backup

Mitigation: keep fail-closed real-run behavior, publication contract, citation
validation, scoped repair, and unified quality accounting from the current
branch. The stable shape is used for authoring, not for loose publication.

### Risk: Segment Markdown reintroduces formatting drift

Mitigation: segment contract validation plus publication contract. Formatting
mistakes route to deterministic assembler/renderer repair before LLM retry.

### Risk: Structured JSON tests become obsolete

Mitigation: keep structured models and tests where they validate publication
vocabulary, renderer behavior, and compatibility. Add tests for the new segment
main path instead of deleting all structured coverage.

### Risk: Reports improve in prose but lose auditability

Mitigation: support appendix remains, source IDs remain required, release-gate
warnings remain visible, and final quality accounting remains unified.

### Risk: Implementation touches too much at once

Mitigation: implement in phases: planner/main-path switch, keyed assembly,
publication routing, redo repair, real-run verification.
