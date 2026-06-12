# Writer Redo Tiered Repair Design

Date: 2026-06-12
Status: User-approved design, pending written-spec review

## Purpose

Prevent `writer_only` redo from flattening an otherwise useful report. The system should preserve a good previous draft when QA only found local report defects, repair thin sections without rewriting the whole report, and still allow full regeneration when the previous report is structurally poor or upstream data has changed.

This design targets the report-thinning failure observed in `run-810891b31e133f4ee49a97b979ae5554`: a good pre-redo report had enough core analysis to support local repair, but a later writer-only redo rewrote the full report and compressed the user review section into a short caveat.

## Current Problem

`writer_only` is currently a single route. Once QA assigns a finding to `writer_only`, the graph routes back to the writer node and `_real_writer_step()` performs a full report writer call. The writer receives `previous_report`, but that draft is only preserved on timeout or exception. A successful but weaker LLM rewrite can replace richer previous content.

The confirmed run-810 issue had two important facts:

- The final QA blocker was line-level `text_quality` on Markdown table separator rows.
- Those separator rows were a false positive and did not require full report regeneration.

The table separator false positive has already been fixed separately. This design covers the broader redo behavior so future local writer issues do not trigger unnecessary full rewrites.

## Scope

In scope:

- Add a deterministic pre-redo report quality assessment for writer-only redo.
- Split writer-only handling into internal repair modes: `line`, `section`, and `full`.
- Preserve the existing five `RedoScope.kind` values. This does not add a sixth graph-level redo scope.
- Add post-rewrite anti-regression checks so a full writer rewrite cannot replace a good previous draft with a much thinner report.
- Keep upstream-data redo behavior distinct from pure writer-only repair.

Out of scope:

- Redesigning collector, analyst, comparator, or survey/interview generation.
- Relaxing QA gates for unsupported claims or weak evidence.
- Changing Markdown source citation syntax.
- Creating a full patch-planning subsystem with arbitrary multi-section diffs.
- Frontend changes, except for surfacing existing revision metadata if already available.

## Design Direction

Use a tiered writer repair gate:

1. Local text repair for small, isolated report-line issues.
2. Section repair for reports whose main structure is good but one or a few sections are thin or defective.
3. Full rewrite for reports whose structure, citations, language, or core content are broadly inadequate.
4. Full or broad rewrite when upstream data changed, with an anti-shrink guard.

This keeps the current graph simple: `writer_only` remains the routed redo kind, and the writer/orchestrator decide the internal repair mode from the selected QA findings and previous report quality.

## Repair Mode 1: Line Repair

Use line repair when all of these are true:

- The selected writer-only findings are report-line issues such as `report_md.line[x]`.
- The number of affected lines is small.
- The previous report passes the report quality threshold for core structure and citation coverage.
- The issue is local text noise, malformed citation token, obvious mojibake, or a similarly isolated publishability defect.

Behavior:

- Apply a deterministic local patch to the affected lines.
- Preserve the rest of the previous report byte-for-byte where practical.
- Re-run report hardening and QA after the patch.
- Do not call the full report writer unless the local patch cannot clear the issue.

The already-fixed Markdown table separator case should not reach this mode because the QA detector should ignore valid separator rows.

## Repair Mode 2: Section Repair

Use section repair when all of these are true:

- The previous report is mostly valid and has the required core structure.
- One or a few sections are thin, incomplete, duplicated, or missing required substance.
- The issue can be mapped to a known report section such as user review themes, SWOT, competitor deep dives, battlecard, source quality, claim risk, or RAG gap fill.
- Other core sections are already good enough to preserve.

Behavior:

- Ask the writer to regenerate only the targeted section content using the current structured context and previous report as context.
- Replace only the targeted Markdown section.
- Preserve all other sections from the previous report.
- Re-run hardening and QA after the section patch.

If section mapping is ambiguous or multiple core sections fail at once, escalate to full rewrite.

## Repair Mode 3: Full Rewrite

Use full rewrite when any of these are true:

- Multiple required sections are missing.
- Core analysis depth is below threshold across the report.
- Citation coverage or citation validity is too low.
- The report is not recognizable Markdown.
- The output language is wrong or heavily mojibake-corrupted.
- The report conflicts broadly with the comparison matrix or structured knowledge.
- Local or section repair already failed.

Behavior:

- Call the full writer, but instruct it to preserve useful previous content and rewrite around the defects.
- Do not treat the rewrite as a blank-page generation unless the previous report is genuinely unusable.
- After generation, compare the candidate against the previous report when the previous report was good enough to protect.
- If the candidate significantly shrinks core analysis or removes substantive cited sections, keep the previous report plus any safe local repair, then surface a writer repair warning.

## Upstream Data Changed

If the redo path reran collector, analyst, or comparator, the factual basis may have changed. In that case, the writer may need a full or broad rewrite because new evidence, matrix cells, review themes, SWOT items, or reflections can legitimately change the report.

Even then, the final report should not become materially thinner without cause. Apply a softer anti-shrink guard:

- Compare core analysis length and section presence before and after.
- Allow changes caused by new data, removed claims, or corrected evidence.
- Block or warn on unexplained collapse of core sections such as user review themes, SWOT, competitor deep dives, or battlecard.

## Pre-Redo Quality Assessment

Before writer-only repair, compute a compact deterministic assessment of the previous report:

- Required section coverage.
- Core analysis depth before support/appendix sections.
- Citation token count and citation validity.
- Report source coverage against collected sources.
- Count and location of report text-noise findings.
- Thin-section signals for known sections.
- Duplicate-section count.
- Markdown recognizability and output-language sanity.

The implementation should reuse `compare_run_quality()` where possible rather than inventing a parallel quality system. Additional writer-specific helpers may wrap its metrics to classify the previous report as:

- `protectable`: good enough for line or section repair.
- `section_repairable`: mostly good, but one or a few sections need replacement.
- `rewrite_required`: too poor for local repair.

## Routing Rules

Writer-only routing should follow this order:

1. Ignore valid Markdown table separators in text-quality QA. This is already completed.
2. If selected findings are only a small number of `report_md.line[x]` issues and the previous report is protectable, use line repair.
3. If selected findings map to a small number of sections and the previous report is section-repairable, use section repair.
4. If broad quality metrics fail, use full rewrite.
5. If upstream redo changed evidence, matrix, or structured analysis, allow full or broad rewrite with anti-shrink checks.

When in doubt, prefer section repair over full rewrite only if the previous report has enough substance to preserve.

## Anti-Regression Checks

For a protectable previous report, a candidate rewrite should not be accepted if it causes material unexplained regression, including:

- Core analysis content shrinks substantially.
- A previously substantive user review, SWOT, competitor deep dive, or layer-specific section becomes a one-line caveat.
- Citation count drops sharply while source data is still available.
- Required sections disappear.
- The report becomes support-heavy again, with evidence/QA material dominating the body.

The guard should compare section-level metrics, not only total character count. The run-810 failure would not be reliably caught by total length alone because the final report was still long, but one core section collapsed.

## Audit And Observability

Revision records should remain compatible with existing redo auditing. Add lightweight metadata where the existing event or agent-message payload allows it:

- writer repair mode: `line`, `section`, or `full`
- selected issue IDs
- protected previous report flag
- anti-regression decision
- repaired section names when applicable

This should help future run audits explain why a writer redo preserved, patched, or fully regenerated a report.

## Error Handling

- If line repair fails to remove the target issue, escalate to section or full repair depending on report quality.
- If section repair output is empty, uncited, malformed, or thinner than the original section, keep the original section and escalate or warn.
- If full rewrite times out or errors, keep the existing previous-report preservation behavior.
- If full rewrite succeeds but fails anti-regression checks, keep the previous report with safe local patches and record the rejection reason.
- If the previous report is already poor, do not preserve it merely because the new report is also imperfect; continue normal QA and redo flow.

## Testing Strategy

Add tests before implementation:

- QA does not flag Markdown table separators as text noise. This is already covered by the preceding fix.
- A protectable previous report with only a local `report_md.line[x]` text issue uses local repair and preserves unrelated sections.
- A protectable previous report with a thin user review or SWOT section uses section repair and preserves unrelated sections.
- A poor previous report with multiple missing required sections uses full rewrite instead of local repair.
- A full rewrite candidate that collapses a substantive user review section is rejected when the previous report is protectable.
- A full rewrite after upstream collector/analyst/comparator changes is allowed, but still records or enforces anti-shrink checks.
- Existing writer timeout behavior still preserves the previous report.
- Existing five `RedoScope.kind` routes remain unchanged.

Use the conda environment already used for this project:

- `D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -q`
- `D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -q`
- `D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check <changed files>`

## Acceptance Criteria

- `writer_only` redo no longer defaults to full report rewrite for small line-level issues.
- Good previous drafts are preserved when QA only identifies local text defects.
- Thin but isolated report sections can be regenerated without replacing the full report.
- Poor previous drafts still trigger full rewrite.
- Upstream data changes still allow full or broad rewrite.
- A successful full writer call cannot replace a protectable previous report with a materially thinner core report.
- Revision or agent-message metadata explains which writer repair mode was used.
- The existing five-level `RedoScope` contract remains intact.

## Later Work

Later phases can deepen this system with:

- More precise section-to-QA issue mapping.
- A reusable Markdown section patch library.
- Frontend diff visualization for repaired sections.
- Collector improvements for real review, forum, customer voice, and case-study evidence.
- A richer report-quality dashboard showing why a previous report was protectable or rewrite-required.
