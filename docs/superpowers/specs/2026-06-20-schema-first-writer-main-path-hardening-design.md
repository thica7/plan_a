# Schema-First Writer Main Path Hardening Design

Date: 2026-06-20
Status: User-approved direction, pending written-spec review

## Purpose

Finish the schema-first writer transition by making structured report generation the real main path for real runs. The current branch already added structured report models, rendering, validation, publication checks, and telemetry. However, `run-b6048b0a1a18b1b5bf3857cb924637b3` shows that the old Markdown path can still take over the user-facing report when the structured path fails.

That fallback behavior defeats the schema-first goal. It allows the model to directly author final Markdown again, which reintroduces the exact problems this branch is meant to remove:

- Full-report rewrite after a scoped upstream redo changed the core recommendation from GitHub Copilot plus Cursor to Windsurf, even though only Claude Code persona evidence was refreshed.
- The structured writer failed at `decision_matrix`, then the system silently fell back to Markdown segmented writer.
- `detail_json.revisions[0]` and the `revision_recorded` event disagreed on `issue_count_after` and `convergence_ratio`.
- Final deterministic QA reported 0 issues while release gate still exposed 13 warnings.
- The published report still contained English structural headings in a Chinese report, citations on section marker lines, and citations inside many table rows.
- Writer quality preflight only checked broad H2 structure, so publication hygiene and recommendation consistency passed unchecked.

The design goal is to make schema-first generation authoritative, targeted, auditable, and fail-closed for real reports.

## Relationship To The Existing Schema-First Spec

This spec extends `2026-06-19-schema-first-writer-report-design.md`. It does not replace the existing structured models, renderer, validation, or publication contract work.

The earlier spec allowed Markdown fallback to remain available while structured generation stabilized. This hardening spec narrows that fallback:

- Markdown fallback may remain for legacy, demo, feature-flag-disabled, or explicitly diagnostic paths.
- Markdown fallback must not silently become the final user-facing report for a real run when schema-first is enabled.
- Real schema-first failures must be repaired at the structured section level or reported as writer failure, with previous report preservation when available.

## Non-Goals

- No frontend report redesign.
- No database migration in this hardening phase.
- No source collection, analyst, comparator, or community triangulation redesign.
- No weakening of source ID validation.
- No generated run outputs, DB packages, report exports, or local artifacts committed.
- No removal of the legacy Markdown writer code if tests or old flows still depend on it.
- No broad refactor outside writer, quality status, and revision accounting boundaries.

## Current Evidence

The target failure pattern is grounded in `run-b6048b0a1a18b1b5bf3857cb924637b3`:

- Run status: `completed`
- Release gate: `pass`, readiness score 88, blocker count 0, warn count 13
- Initial deterministic QA after the first writer pass: 1 issue, Claude Code persona confidence 0.62 below threshold 0.70
- Redo scope: collector, persona, Claude Code
- Writer redo behavior: structured writer completed several sections, failed at `decision_matrix`, then used Markdown segmented fallback
- Final report length: 55,559 characters, 584 lines
- Final report hygiene issues:
  - 67 English H3/H4 headings
  - 45 table rows with citations
  - 17 section marker lines with citations
- Revision inconsistency:
  - Run detail revision: `issue_count_after=13`, `convergence_ratio=13.0`
  - Event revision payload: `issue_count_after=0`, `convergence_ratio=0.0`

This is not a missing-source-only problem. It is a writer ownership, repair routing, quality status, and audit consistency problem.

## Design Summary

The hardened real-run writer path becomes:

```text
Writer Evidence Pack
  -> Structured Section Planner
  -> Structured Section Writers
  -> StructuredReportAssembler
  -> StructuredReportValidator
  -> PublicationContract
  -> Deterministic MarkdownRenderer
  -> Unified Post-Report Quality Result
  -> report_md
```

The LLM owns only structured section content. Deterministic code owns final Markdown shape, headings, citation placement, section markers, core/support ordering, and publishability.

For real runs with schema-first enabled, a structured section failure must not fall through to Markdown report generation. The system must either:

1. Repair only the failed structured section.
2. Preserve the previous valid report for redo runs and record the writer error.
3. Fail the writer for new runs without a previous valid report.

## Main Path Rules

### Rule 1: No Silent Markdown Fallback For Real Schema-First Runs

When `writer_structured_report_enabled` is true and the run execution mode is real:

- A structured generation exception must emit a structured failure event.
- It must not call `_writer_markdown_report_from_evidence_pack()` as the next default step.
- If there is no previous valid report, the run should fail at writer with a clear error.
- If there is a previous valid report, the service may preserve that report, mark the writer repair as failed, and keep the run auditable.

Markdown fallback remains allowed only when one of these is true:

- The structured writer feature flag is disabled.
- The run is explicitly demo or legacy compatibility mode.
- A test path explicitly requests Markdown fallback.
- A developer diagnostic path requests Markdown output and records that it is not schema-first.

### Rule 2: Structured Sections Are The Repair Unit

The repair unit is no longer "whole Markdown report" by default. It is the structured section or field that owns the failed claim, formatting contract, or release-gate warning.

Examples:

- Persona text-support warning maps to `core.user_review_themes` and the affected competitor deep dive persona fields.
- Pricing single-source warning maps to `core.decision_matrix`, the affected competitor deep dive pricing field, or support claim-risk notes.
- English structural heading in a Chinese report maps to renderer or publication contract, usually no LLM call needed.
- Citation in table header maps to renderer, no LLM call needed.
- Battlecard template-only issue maps to `core.battlecard`.
- Executive summary template-only issue maps to `core.executive_summary`.

Full structured rewrite is allowed only when multiple essential core sections are missing, schema generation repeatedly fails across several unrelated essential sections, or there is no previous structured report and no safe partial output exists.

### Rule 3: Scoped Upstream Redo Cannot Freely Change Global Recommendation

When a scoped upstream redo changes only one competitor and one dimension, the writer must not freely rewrite the global recommendation.

The system should compute a recommendation delta before accepting a repaired report:

- Extract previous recommendation posture from the previous structured report or rendered report summary.
- Extract candidate recommendation posture from the candidate structured report.
- Compare top recommendation, excluded products, and key risk-adjusted rationale.
- If the recommendation changes, require a structured justification tied to the exact new evidence from the scoped redo.
- If no such justification exists, preserve the previous recommendation and only update affected sections.

This does not freeze the recommendation forever. It makes recommendation changes evidence-driven and auditable.

### Rule 4: Unified Post-Report Quality Result

The system must stop presenting conflicting QA narratives.

After final report rendering, one unified quality result becomes authoritative for:

- Revision `issue_count_after`
- Revision `convergence_ratio`
- Run detail `qa_findings`
- Run metrics `qa_issue_count`
- Completion event release summary
- User-visible status wording

This unified result must include deterministic QA and release-gate warnings. Deterministic QA showing 0 issues cannot erase release-gate warnings.

Status semantics:

- Execution status may remain `completed` when the graph finishes.
- Quality status must distinguish clean pass from pass with warnings.
- Release-gate warnings must be visible in trace, run detail, and revision accounting.

### Rule 5: Publication Contract Blocks Reader-Facing Hygiene Regressions

Publication contract must check the rendered Markdown, not just the structured object.

It must reject or deterministically repair:

- Citations on `<!-- report-section:... -->` marker lines.
- Citations in H2/H3/H4 headings.
- Citations in table header rows.
- Markdown source tokens outside legal citation positions.
- English structural headings in Chinese reports, except product names, API names, and technical nouns.
- Internal implementation terms such as `source_registry`, `allowed_source_ids`, `Segment Evidence Pack`, `fact:`, `signal:`, or process instructions.
- Template-only battlecards.
- Template-only executive summaries.
- Core recommendations that conflict with risk warnings without an explicit risk-adjusted rationale.

Renderer-owned issues should be fixed in the renderer before any LLM retry.

## Component Design

### Structured Section Planner

Add or harden a planner that maps evidence-pack groups to required structured sections.

Responsibilities:

- Create exactly one target for each essential core section.
- Create one deep-dive target per requested competitor.
- Attach allowed source IDs per section.
- Attach scoped redo metadata to each affected target.
- Mark essential versus optional targets.
- Emit telemetry with target count, section ids, competitor ownership, and source counts.

The planner should make later fallback decisions explicit. If an essential target fails, the writer knows exactly which section failed.

### Structured Section Writer

The section writer keeps the current JSON-only LLM behavior but must handle section failures locally:

- Try initial section JSON.
- Validate Pydantic schema and allowed source IDs.
- Retry the same section with the exact validation error.
- If still failing, return a typed `StructuredSectionFailure` instead of raising directly into a broad Markdown fallback.

For `CitedText`, a non-gap claim with empty `source_ids` remains invalid. The clean fix is section retry or evidence-gap downgrade, not loosening the schema.

### Structured Report Assembler

The assembler merges successful section payloads and failures.

Responsibilities:

- Preserve previous structured sections when redo scope does not affect them.
- Replace only affected sections after scoped upstream redo.
- Refuse to assemble if a required section has neither a successful candidate nor a previous valid section.
- Emit telemetry about preserved sections, replaced sections, failed sections, and missing essential sections.

This is the key change that prevents a Claude Code persona redo from rewriting the whole report.

### Structured Validator

The validator should keep existing schema-level checks and add decision consistency checks:

- Every competitor has deep dive, SWOT, and matrix coverage.
- Executive summary recommendation is concrete and not template-only.
- Battlecard has competitor-specific attack, defense, objection, rebuttal, and proof-needed fields.
- Strong recommendation is not based only on simulated research or weak community evidence.
- Recommendation delta after scoped redo has explicit new-evidence justification.
- Direct user signals and simulated research are separated.
- Evidence gaps remain explicit when direct user evidence is missing.

### Publication Contract

The publication contract owns rendered Markdown hygiene:

- Marker lines must contain only section marker comments.
- Renderer must put section-level citations into the body, not marker lines.
- Table headers must not contain source tokens.
- Chinese output must use localized structural headings.
- Internal terms and process instructions must not appear.
- Support material must come after core sections.

Publication failures produce structured repair targets:

- `renderer` for deterministic layout mistakes.
- Specific structured section path for content mistakes.
- `quality_status` for accounting mismatches.

### Unified Quality Result

Add a small quality result boundary after final report rendering.

Inputs:

- Deterministic QA findings.
- Release gate findings and warnings.
- Publication contract result.
- Writer structured validation result.
- Optional repair result.

Outputs:

- `final_quality_findings`
- `blocker_count`
- `warn_count`
- `issue_count`
- `quality_status`
- `readiness_score`
- `revision_issue_count_after`
- `revision_convergence_ratio`

The same object must feed detail, events, metrics, and revision records.

## Error Handling

### New Run, No Previous Report

If an essential structured section fails after retry:

- Emit `writer_structured_section_failed`.
- Emit `writer_schema_first_failed_closed`.
- Do not call Markdown fallback.
- Fail writer with a clear message naming the section and validation error.

### Redo Run, Previous Report Exists

If a structured repair fails:

- Preserve the previous valid report.
- Emit `writer_structured_repair_failed_preserved_previous`.
- Record the quality status as not clean.
- Do not mark the repair as converged unless unified quality result proves improvement.

### Renderer Or Publication Hygiene Failure

If the issue is deterministic:

- Repair in renderer or publication sanitizer.
- Re-run publication contract.
- Do not call LLM.

### Release-Gate Warnings

Release-gate warnings are not hidden by deterministic QA.

- If the warning maps to one structured section, repair that section.
- If repair is not attempted or not enough, keep the warning visible.
- Completed execution with warnings must not be presented as a clean pass.

## Telemetry

Add or harden these events:

- `writer_structured_plan_prepared`
- `writer_structured_section_started`
- `writer_structured_section_completed`
- `writer_structured_section_failed`
- `writer_structured_report_assembled`
- `writer_structured_repair_applied`
- `writer_structured_repair_failed_preserved_previous`
- `writer_schema_first_failed_closed`
- `writer_publication_contract_validated`
- `writer_unified_quality_result_recorded`

Existing `writer_markdown_fallback_used` remains only for allowed legacy/demo/flag-disabled paths. If it appears in a real schema-first run, that is a test failure.

## Testing Strategy

Use the conda environment:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest ...
```

Focused tests:

- Structured main path does not call Markdown fallback for real schema-first runs.
- Structured section validation failure retries only that section.
- Repeated essential section failure fails closed for new real runs.
- Redo with previous report preserves unaffected structured sections.
- Scoped Claude Code persona redo cannot change top recommendation without new-evidence justification.
- Revision record and revision event use the same unified issue counts.
- Deterministic QA 0 plus release-gate warnings yields quality status with warnings.
- Renderer never emits citations on section marker lines.
- Renderer never emits citations in table headers.
- Chinese report rendering uses localized structural headings.
- Publication contract catches internal term leakage.
- Publication contract catches template-only battlecard and template-only executive summary.
- Markdown fallback remains available when the structured feature flag is disabled.

Regression fixture tests should model the observed `run-b6048...` shape without committing full generated reports or database artifacts.

## Acceptance Criteria

The hardening is complete when:

- Real schema-first writer path cannot silently fall back to Markdown.
- A structured failure has a targeted section failure, preservation, or fail-closed outcome.
- Scoped upstream redo updates only affected structured sections unless recommendation delta is explicitly justified by new evidence.
- Final run detail, revision event, metrics, and completion event agree on issue counts.
- Release-gate warnings remain visible after deterministic QA passes.
- Publication contract blocks marker-line citations, heading citations, table-header citations, English structural headings in Chinese output, internal term leakage, template-only battlecards, and template-only executive summaries.
- Existing Markdown writer remains available for feature-flag-disabled, demo, legacy, or diagnostic flows.
- Focused unit tests pass in the conda environment.
- After implementation, the developer restarts backend and frontend services, runs one real run, and audits trace, redo behavior, final quality result, and report body.

## Implementation Phasing

Phase 1: Fail-closed structured main path

- Replace broad structured exception fallback with typed section failures and fail-closed behavior for real schema-first runs.
- Keep Markdown fallback only for allowed modes.

Phase 2: Structured repair and recommendation delta guard

- Preserve unaffected structured sections on scoped redo.
- Add recommendation delta validation.
- Route release-gate warnings to structured section repair targets.

Phase 3: Unified quality result and revision accounting

- Create one final quality result object.
- Use it for detail, metrics, revision records, and completion events.

Phase 4: Publication contract hardening

- Add rendered Markdown hygiene checks.
- Move deterministic layout fixes into renderer.

Phase 5: Verification with real run

- Restart backend and frontend.
- Run one real AI Coding Agent report.
- Audit structured events, absence of real-run Markdown fallback, QA/release-gate consistency, redo behavior, and report quality.

## Open Decisions Resolved

- The schema-first writer is the authoritative real-run path.
- Markdown fallback remains in code but is no longer a silent real-run safety net.
- No database migration is required for this hardening phase.
- No frontend changes are required in this hardening phase, though quality status display may be a later frontend improvement.
- Real run verification is required before claiming the full objective complete.
