# Report Core Budget Layering Design

Date: 2026-06-12
Status: User-approved design, pending written-spec review

## Purpose

Increase the substance of generated competitive-intelligence reports without turning the report into a longer evidence packet. The writer should spend most of the report on decision-grade analysis, user review themes, competitor deep dives, SWOT, matrix interpretation, and layer-specific implications. Evidence, QA, claim risk, RAG gaps, and appendices remain required, but they should support the report rather than dominate it.

This is the Phase 2 follow-up to the earlier core-content-depth work. The current code already has core sections, support sections, and quality checks such as `core_analysis_depth_score`. The remaining problem is that the writer first-draft prompt still targets about 5,500 characters while requiring many sections, so the model can satisfy structure while compressing each core section into thin prose.

## Current Problem

The current writer pipeline has a structural conflict:

- `_writer_required_sections()` lists a large report surface: core analysis sections, layer-specific sections, and support/audit sections.
- `_real_writer_step()` still asks the writer to keep the first draft around 5,500 characters.
- `_ensure_report_required_sections()` backfills missing support and core sections, which improves structure but can still produce short fallback blocks.
- `compare_run_quality()` checks for core analysis presence and total depth, but it does not give the writer a first-draft budget or per-core-section depth contract.

The result is a report that can look compliant while feeling thin: QA, evidence, repair, and appendix material are present, but the main business analysis does not receive enough space.

## Goals

- Make the writer prompt explicitly budget the report as core analysis first.
- Target a medium-length first draft of about 8,500-10,000 characters.
- Require roughly 65-75% of the report body to be core analysis.
- Keep support/audit sections concise, complete, and clearly secondary.
- Add deterministic quality checks that catch short core sections, not only missing sections.
- Preserve the writer redo tiered repair behavior: thin core sections should route to section repair when the previous report is otherwise protectable.
- Keep the design compatible with a future split-view report where support/audit material can become an appendix, tab, or collapsed section.

## Non-Goals

- Do not remove evidence, QA, RAG gap, claim-risk, source-quality, or evidence appendix sections.
- Do not relax citation, source confidence, or unsupported-claim rules.
- Do not invent user reviews, SWOT claims, or competitive winners when evidence is thin.
- Do not build the future frontend split-view or separate report storage model in this phase.
- Do not make every support section long just because the total report budget increases.
- Do not replace the writer redo tiered repair design.

## Report Layering Contract

The Markdown report remains a single document in this phase, but the writer and quality checks should treat it as two semantic layers.

Core analysis layer:

1. Executive Takeaway
2. Decision Summary
3. Competitive Findings
4. User Review Themes
5. Competitor Deep Dives
6. SWOT Analysis
7. Side-by-Side Decision Matrix
8. Layer-specific analysis such as Battlecard, Workflow & Enterprise Risk, or Market Landscape

Support/audit layer:

1. Evidence & QA Support
2. Source Quality & Coverage
3. Memory Context
4. User Research Evidence
5. RAG Gap Fill
6. Scenario QA Checklist
7. Claim Validation & Evidence Risk
8. Next Collection / Verification Plan
9. Evidence Appendix

The support layer must stay after core analysis. If a future phase moves support/audit material into tabs or a separate appendix, this semantic split should be reusable.

## Writer Prompt Budget

Replace the current 5,500-character target with an explicit budget:

- Target 8,500-10,000 characters for normal first drafts.
- Use about 65-75% of the report on core analysis.
- Keep support/audit sections concise unless a blocker requires specific evidence-gap detail.
- Prefer more substance in core sections over repeating source IDs or QA boilerplate.
- If evidence is thin, write analytical implications and explicit evidence gaps rather than filler.

The prompt should name the core layer and support layer directly. It should also state that support/audit sections are an audit trail, not the main readout.

## Core Section Depth Contract

Each core section should have a minimum useful shape:

- Executive Takeaway: one bottom-line judgment, confidence caveat, and most important implication.
- Decision Summary: recommended action, what not to overstate, and immediate next move.
- Competitive Findings: at least 3-5 cited findings or evidence-gap findings, each with business implication.
- User Review Themes: praise, complaints, adoption blockers, switching triggers, and per-competitor gaps where review evidence is missing.
- Competitor Deep Dives: one compact subsection or bullet group per competitor covering wins, weaknesses, watchouts, and implication.
- SWOT Analysis: Strengths, Weaknesses, Opportunities, and Threats for each competitor, using cited items when available and explicit evidence-gap notes when not.
- Side-by-Side Matrix: every requested competitor and dimension should appear, with citations or explicit gaps.
- Layer-Specific Analysis: enough content to answer the selected layer intent, not just a heading and one sentence.

Evidence gaps can count as content only when they are specific and decision-useful. A generic sentence such as "more evidence is needed" should not satisfy depth.

## Support Section Compression Contract

Support/audit sections remain mandatory when applicable, but they should be compact:

- Source Quality & Coverage: summarize source types, confidence, and caveats without restating every claim.
- Scenario QA Checklist: list scenario, analyst questions, evidence requirements, and QA rules in short bullets.
- Claim Validation & Evidence Risk: prioritize high-risk claims and weak-source caveats.
- RAG Gap Fill: include only actionable retrieval gaps and next query/task hints.
- Evidence Appendix: list important source IDs with type and confidence; avoid long prose.

The writer should not spend newly added budget on longer appendices unless the run has many blocker-level gaps.

## Quality Scoring Changes

Strengthen report quality checks so a report cannot pass by having many support sections and thin core sections.

Add or refine deterministic signals:

- Per-core-section minimum depth for the main required core sections.
- Core/support balance signal based on substantive content before the first support heading.
- Core analysis character or row threshold above the current total-depth heuristic.
- Section-specific checks for User Review Themes, SWOT Analysis, and Competitor Deep Dives.

The checks should remain tolerant of evidence gaps. The goal is not to force unsupported claims; it is to require useful analysis or useful gap explanation.

## Writer Redo And Repair Interaction

This design should work with the existing writer redo tiered repair:

- If the report is structurally good but one core section is thin, route to section repair where possible.
- If only support/audit material has a local formatting issue, do not rewrite the full report.
- If the whole core layer is thin, allow full rewrite with the existing anti-regression guard.
- If upstream collector, analyst, or comparator data changed, allow full rewrite while preserving honest metadata.

The section classifier should recognize thinness in User Review Themes, SWOT Analysis, Competitor Deep Dives, Competitive Findings, Decision Summary, and layer-specific sections.

## Phase 3 Compatibility

This phase deliberately keeps a single Markdown report, but it should prepare for a later split-view design:

- Keep core/support classification centralized enough that future code can render support/audit separately.
- Avoid mixing support-only headings into the core layer.
- Keep support sections clearly named and ordered.
- Preserve report export compatibility by keeping the full Markdown document available.

Future Phase 3 can then move support/audit into a collapsed appendix, tabbed view, or separate export artifact without redefining report semantics.

## Testing Strategy

Add or update tests for:

- The writer prompt no longer asks for "around 5,500 characters".
- The writer prompt names the 8,500-10,000 target and core/support budget.
- Required sections expose the core layer before the support/audit layer.
- A support-heavy report with thin core analysis still fails quality.
- Individual thin core sections, especially User Review Themes, SWOT Analysis, and Competitor Deep Dives, fail or produce repair recommendations.
- A report with concise support sections and substantive core sections passes quality.
- Existing report hardening still inserts missing core sections before support sections.
- Writer redo section repair can target thin core sections without full rewrite when the previous report is otherwise protectable.

## Rollout

Implement this as a backend-only report quality and writer-prompt change.

Recommended order:

1. Update prompt and required-section wording.
2. Add centralized core/support section metadata if the existing helpers are too scattered.
3. Strengthen report quality metrics for per-core-section depth and core/support balance.
4. Add tests for prompt contract, quality metrics, hardening order, and repair routing.
5. Run the focused writer/report quality suites before using new real runs as validation.

## Risks And Mitigations

Risk: Reports become longer but not better.
Mitigation: Make the new budget core-weighted and test support-heavy failures.

Risk: Weak evidence causes invented analysis.
Mitigation: Require explicit evidence-gap analysis and keep citation/source rules unchanged.

Risk: Quality checks become too brittle for localized output.
Mitigation: Use existing localized heading aliases and body-depth heuristics rather than exact prose matching.

Risk: More reports trigger redo loops.
Mitigation: Prefer section repair for isolated thin sections and keep full rewrite for broad core failure.

Risk: Future Phase 3 needs different storage.
Mitigation: Keep semantic core/support classification reusable while preserving single Markdown output for now.
