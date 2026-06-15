# Report Section Index Repair Design

## Problem

Recent real runs show that report quality gates can still misclassify good report content:

- The RAG gap-fill scorer recognizes English and mojibake Chinese phrases but misses normal Chinese table headers such as `建议检索/取证`, `需要的证据`, and `当前状态`.
- The SWOT scorer recognizes plain quadrant labels but misses common bilingual labels such as `Strengths (优势)`.
- The community-source official-commitment QA scans every report line as if it were core report prose. Audit/support sections such as `RAG 缺口补全` and `Final QA Gate Status` can repeat warnings or source ids and create self-reinforcing false blockers.

These are not three unrelated bugs. They share the same root cause: several modules parse Markdown structure independently with narrow local heuristics and no shared concept of core vs support/audit report layers.

## Scope

This repair is intentionally focused. It adds a lightweight shared section index and wires only the affected gates to it:

- Report quality scoring in `backend/packages/business_intel/report_quality.py`
- Community official-commitment QA in `backend/packages/agents/qa/logic.py`
- Unit tests in `backend/tests/unit/test_report_quality.py`, `backend/tests/unit/test_run_service.py`, and a small section-index test file if a new helper module is introduced

This repair does not change writer prompting, collector behavior, comparator behavior, or release-gate scoring weights.

## Design

Add a shared Markdown section parser under `backend/packages/business_intel/report_sections.py`.

The parser should:

- Parse Markdown headings at levels 1-6.
- Preserve heading text, normalized heading text, character span, line span, body, and heading level.
- Classify sections into `core`, `support`, or `audit`.
- Treat support/audit markers as sticky once the report enters an explicit support/audit layer heading, while still allowing individual support sections such as `RAG 缺口补全` or `Final QA Gate Status` to be recognized when no explicit layer heading exists.
- Expose helpers for:
  - iterating sections before support/audit material,
  - finding a section by heading aliases,
  - checking whether a report line belongs to support/audit material.

Use this shared index where it directly removes the current false positives:

- RAG gap-fill scoring should evaluate the matched RAG section body, not the entire report, and accept normal Chinese retrieval/evidence phrases.
- SWOT scoring should normalize bilingual labels by considering the full label, the label with parenthetical text removed, and the parenthetical text itself.
- Community official-commitment QA should skip lines located in support/audit sections. It should keep blocking core report lines that present community observations as official commitments.

## Success Criteria

- A report with collector gaps and a Chinese `RAG 缺口补全` table containing `建议检索/取证`, `需要的证据`, and `当前状态` scores `rag_gap_fill_section_score == 1.0`.
- A SWOT section using labels such as `**Strengths (优势):**` scores `swot_section_score == 1.0`.
- A core report line saying `Official Cursor pricing is $20... [source:reddit-pricing]` still produces a blocker.
- The same source id repeated inside `RAG 缺口补全`, `Release Gate Follow-up Repairs`, or `Final QA Gate Status` does not produce a community official-commitment blocker.
- Existing report quality and run-service tests remain green.

## Non-Goals

- Do not redesign writer report generation in this change.
- Do not remove claim self-consistency warnings from enterprise projections in this change.
- Do not change community-source confidence or triangulation policy in this change.
- Do not change competitor selection or Windsurf coverage policy in this change.

## Spec Self-Review

- No placeholders remain.
- The scope is small enough for one implementation pass.
- The parser is foundational but not a broad report-AST rewrite.
- The QA blocker behavior remains conservative for core report prose and only skips support/audit material.
