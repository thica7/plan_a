# Report Core Content Depth Design

Date: 2026-06-10
Status: User-approved, ready for implementation plan

## Objective

Rebalance generated competitive-intelligence reports so the main body reads like a decision-grade analysis report instead of an evidence and QA packet. The report should lead with conclusions, competitive findings, competitor implications, and recommended action. Evidence, QA, claim-risk, and gap-fill material must remain present, but should support the analysis from the back half of the report rather than dominate the reader experience.

## Current Problem

The current report pipeline has strong evidence and governance coverage, but the actual business analysis is too thin.

Observed shape:

- `WriterAgentMixin._writer_required_sections()` requires source quality, scenario QA, claim validation, next collection, and evidence appendix.
- `_ensure_report_required_sections()` appends missing governance and evidence sections after writer output.
- `_fallback_report_markdown()` creates matrix, source quality, scenario checklist, knowledge coverage, claim validation, next collection, evidence appendix, and generation notes, but its business-analysis sections are short bullet blocks.
- `report_quality.py` gives hard structural credit to evidence and QA sections, while the core analysis signal is mostly limited to executive summary, matrix, and a layer-specific heading.

This makes reports feel like audit artifacts. The traceability is useful, but it overwhelms the content that a decision-maker wants first: what changed, who wins where, what it means, and what to do next.

## Design Direction

Use a consulting-style report structure as the first implementation. Preserve a path for fuller investment or diligence-style reports later, especially for L3 market landscape runs, but do not attempt to build a full diligence report system in this change.

The first version should make the report body roughly:

- 60-70% core analysis, recommendations, competitive implications.
- 30-40% evidence support, QA, claim validation, source coverage, and gap closure.

This is a content and quality-contract change, not a frontend redesign.

## Goals

- Put core report content before evidence and QA appendices.
- Ensure every report has decision-oriented sections, not only source and QA sections.
- Make deterministic fallback output materially useful when the LLM writer times out or fails.
- Keep source citations and claim-risk discipline intact.
- Keep existing layer behavior:
  - L1: direct battlecard and response guidance.
  - L2: adjacent workflow, enterprise risk, switching cost, and integration exposure.
  - L3: market landscape, segmentation, trend signals, and strategic options.
- Add quality signals that reward core analysis depth and not only evidence appendix presence.
- Avoid broad frontend changes in v1.

## Non-Goals

- Do not remove evidence, QA, release-gate, claim-risk, or RAG gap-fill sections.
- Do not build a full investment memo or diligence report product in this change.
- Do not redesign the markdown reader or report studio unless a small label/order update is required.
- Do not change source citation syntax.
- Do not relax safety rules around weak sources, low-confidence evidence, or unsupported winner claims.
- Do not automatically lengthen every report without structure. Depth should come from better sections, not filler.

## Report Structure

The writer should target this order:

1. Executive Takeaway
   - Bottom-line judgment.
   - Confidence level.
   - Most important caveat before recommendations.

2. Decision Summary
   - Recommended action.
   - What not to do yet.
   - Immediate next move for product, GTM, sales, procurement, or strategy, depending on the selected scenario and layer.

3. Competitive Findings
   - 2-4 cited findings across the requested dimensions.
   - Explain why each finding matters, not only what the source says.
   - Separate confirmed findings from tentative signals.

4. Competitor Deep Dives
   - One compact subsection or bullet group per competitor.
   - Include wins, weaknesses, watchouts, and implication.
   - Cite factual claims with existing source IDs.

5. Layer-Specific Analysis
   - L1: Battlecard, pricing or packaging implications, sales objection handling, product/GTM response.
   - L2: Workflow overlap, ecosystem leverage, enterprise buying risk, switching cost, integration exposure, strategic watchlist.
   - L3: Market landscape, competitor clusters, segment view, benchmark or trend signals, strategic options with uncertainty separated from evidence gaps.

6. Evidence & QA Support
   - Source Quality & Coverage.
   - Scenario QA Checklist.
   - Claim Validation & Evidence Risk.
   - RAG Gap Fill when collector gaps exist.
   - Next Collection / Verification Plan.
   - Evidence Appendix.
   - Generation Notes when fallback was used.

The report may use localized labels through the existing i18n helper, but the semantic order should remain the same.

## Backend Implementation Shape

Most changes belong in `backend/packages/agents/writer/logic.py`.

Writer prompt changes:

- Replace "concise decision-grade markdown first draft" emphasis with "analysis-first decision-grade report."
- Tell the model that evidence and QA sections are support material and should appear after core analysis.
- Require Decision Summary, Competitive Findings, Competitor Deep Dives, and Layer-Specific Analysis before evidence support.
- Keep the existing grounded-evidence contract and source citation rules.
- Keep the character budget compact, but increase or rebalance it only if tests show the new structure is consistently truncated.

Required sections:

- Add core analysis sections to `_writer_required_sections()`.
- Keep current evidence and governance sections, but list them after core sections.
- Keep layer-specific requirements, but make them subrequirements of the Layer-Specific Analysis section.

Fallback generation:

- Add deterministic fallback helpers for:
  - decision summary
  - competitive findings
  - competitor deep dives
  - layer-specific analysis with more useful detail
- Reuse existing comparison matrix, competitor knowledge, source IDs, QA findings, reflections, and scenario metadata.
- Avoid inventing unsupported claims. Where evidence is thin, write a usable tentative readout with explicit gaps.
- Keep source references on factual lines through existing citation repair helpers.

Required-section hardening:

- `_ensure_report_required_sections()` should append missing core analysis sections before appending evidence support sections.
- Evidence support appendices should remain at the end.
- Do not let appended QA sections turn a short report into a mostly-QA artifact. If the writer output lacks core sections, fallback core sections should be inserted before support sections.

## Quality Scoring

Most changes belong in `backend/packages/business_intel/report_quality.py`.

Add core-analysis structure signals:

- `decision_summary_section_score`
- `competitive_findings_section_score`
- `competitor_deep_dive_section_score`
- `layer_analysis_section_score`

Add a lightweight content-depth signal:

- Count core-analysis body length or bullet/table rows before the first evidence-support heading.
- Require enough non-heading content in the core analysis area to pass report quality.
- Keep this heuristic simple and deterministic so tests remain stable.

Rebalance structure scoring:

- `report_structure_score` should include both core sections and support sections.
- Core sections should carry enough structural weight that a report with only source quality, QA, claim validation, and appendix cannot pass as high quality.
- Evidence and QA sections remain required when applicable, but should no longer be the dominant determinant of perceived completeness.

Keep hard safety gates:

- Minimum report length.
- Citation rate.
- Citation validity rate.
- Source coverage rate.
- Claim risk section.
- Scenario checklist.
- Conditional memory, user research, and RAG gap-fill requirements.

## Frontend Impact

No major frontend change is required in v1.

The existing report markdown reader should display the new order naturally. If the UI has outline or review navigation labels, it should inherit headings from markdown. If tests reveal that report review surfaces assume evidence sections appear early, update only those assumptions.

Future frontend work can add:

- Analysis/support split in the report outline.
- Collapsible evidence appendix.
- Reader anchors for Decision Summary, Competitive Findings, and Deep Dives.

Those are not part of this implementation.

## Data Flow

1. Planner and collector build the existing plan, source, matrix, knowledge, QA, and reflection data.
2. Writer receives the same context package plus revised report-structure instructions.
3. Writer produces analysis-first markdown.
4. Report hardening repairs citations and appends missing core sections before support sections.
5. Enterprise projection stores the final report markdown as before.
6. Report quality evaluates both analysis depth and evidence/governance support.
7. Frontend displays the markdown in the new analysis-first order.

## Error Handling

- If the LLM writer times out, deterministic fallback must still produce core analysis sections before evidence support.
- If evidence is insufficient for a winner claim, the core sections should state that the conclusion is tentative and identify the gap.
- If no comparison matrix exists, Decision Summary and Competitive Findings should use available source and competitor knowledge summaries, then call out the missing matrix as a gap.
- If no sources exist, the report should not pretend to be complete. It should still produce an analysis skeleton with clear collection requirements.
- If section hardening detects malformed or missing citations, existing source-token repair remains responsible for repair.

## Testing Strategy

Backend unit tests:

- Fallback report includes Decision Summary, Competitive Findings, Competitor Deep Dives, Layer-Specific Analysis, Source Quality, Claim Validation, and Evidence Appendix in that order.
- Fallback report places evidence and QA support after core analysis.
- L1 fallback includes battlecard-style response guidance.
- L2 fallback includes workflow, enterprise risk, switching cost, or integration exposure language.
- L3 fallback includes market landscape, segmentation, clusters, benchmark, or trend language.
- Report quality fails a report that has evidence/QA appendices but lacks core analysis sections.
- Report quality passes a sufficiently cited report with core analysis sections and required support sections.
- Citation repair still preserves valid `[source:ID]` tokens and repairs invalid ones.
- Conditional sections for memory, user research, and RAG gap fill still behave as before.

Existing tests in `backend/tests/unit/test_report_quality.py` should be extended rather than replaced.

## Acceptance Criteria

- A generated report begins with analysis and recommendations, not source quality or QA.
- Core analysis occupies the majority of the report body before evidence support begins.
- Evidence, QA, claim validation, and gap-fill material remain present and cited.
- A report containing mostly evidence appendix and QA sections no longer satisfies the report quality signal.
- Deterministic fallback output is useful as a business readout, not only a compliance appendix.
- L1, L2, and L3 reports preserve distinct analytical shapes.
- Existing source citation syntax and citation validation behavior are not broken.

## Risks and Mitigations

- Risk: Longer core analysis could encourage unsupported conclusions.
  Mitigation: Keep the grounded-evidence contract, citation repair, and weak-claim validation. Explicitly require tentative language when evidence is thin.

- Risk: The fallback writer could become too verbose or duplicate matrix content.
  Mitigation: Use compact helper sections and derive each section from existing matrix, knowledge, and source summaries.

- Risk: Report quality scoring becomes too brittle if it checks exact headings.
  Mitigation: Use heading synonym checks similar to the existing structure scoring pattern.

- Risk: Evidence and QA sections become hidden enough that reviewers miss blockers.
  Mitigation: Keep support sections in the report and preserve release-gate and QA surfaces outside the report body.

- Risk: Chinese and English labels drift.
  Mitigation: Use semantic `report_label()` keys where localized labels are needed, and test by section intent rather than exact prose where possible.

## Implementation Boundaries

Keep v1 focused on the writer and report quality contract:

- `backend/packages/agents/writer/logic.py`
- `backend/packages/business_intel/report_quality.py`
- focused backend tests

Only touch frontend code if existing tests or type assumptions require the old heading order. Do not redesign the report UI in this change.
