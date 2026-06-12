# Writer Redo Regression Hardening Design

Date: 2026-06-13
Status: User-approved design, pending written-spec review

## Purpose

Prevent writer redo from making a useful report materially worse. The system should treat collector, analyst, and comparator redo as a reason to refresh impacted sections, not as an unconditional license to replace the full report with a thinner LLM rewrite.

This design responds to the behavior observed in recent runs:

- Initial drafts were often the richest reports.
- Later redo passes repeatedly used full rewrite.
- Some rewrites reduced user review themes, SWOT, competitor deep dives, or core analysis even when the previous report was protectable.
- A preserved previous report could retain stale citation tokens after upstream sources changed.

## Current Problem

`build_writer_repair_plan()` currently returns a full rewrite plan whenever `upstream_data_changed=True`. That plan disables anti-regression checks:

```python
if upstream_data_changed:
    return WriterRepairPlan(
        mode="full",
        reason="upstream data changed; full rewrite allowed",
        previous_report_protectable=protectable,
        anti_regression_required=False,
    )
```

This means a redo that only refreshed persona, feature, or pricing evidence can replace the whole report. Because the candidate report is accepted without comparing it to the previous report, a successful LLM call can still be a product-quality regression.

The preservation fallback also needs hardening. When timeout, exception, or anti-regression keeps the previous report, the preserved report must still pass source-token hardening so old source IDs do not become unknown citations after upstream sources changed.

## Scope

In scope:

- Change upstream-data writer redo routing from unconditional full rewrite to scoped repair when possible.
- Keep full rewrite available for genuinely broad or structurally unsafe cases.
- Require anti-regression checks whenever a protectable previous report could be replaced.
- Strengthen section and whole-report regression thresholds for core report content.
- Harden preserved previous reports before accepting them.
- Add unit tests that reproduce the recent failure shape.

Out of scope:

- Changing collector evidence gathering.
- Changing simulated survey or interview generation.
- Changing QA severity policy for weak source coverage.
- Frontend report rendering changes.
- Adding new graph-level redo scope types.

## Design Direction

Use a conservative acceptance model:

1. A protectable previous report is valuable state.
2. Upstream redo should identify impacted report sections.
3. Section repair is preferred when the impacted area is narrow.
4. Full rewrite is allowed only when the previous report is not protectable, the issue mapping is broad, or the report structure is broken.
5. Any candidate that would replace a protectable report must pass anti-regression.

## Upstream Redo Routing

When `upstream_data_changed=True`, `build_writer_repair_plan()` should still inspect selected QA issues and redo scopes.

For a protectable previous report:

- If the selected issues map to one to four report sections, return `mode="section"` with `anti_regression_required=True`.
- If the selected issues are line-only report defects, return `mode="line"` when line repair is safe.
- If the issue mapping is broad or empty, return `mode="full"` with `anti_regression_required=True`.

For an unprotectable previous report:

- Return `mode="full"`.
- `anti_regression_required` can remain false because there is no useful previous draft to preserve.

The reason string should explain the routing decision, for example:

- `upstream data changed; scoped section repair selected`
- `upstream data changed; broad rewrite required with anti-regression`
- `upstream data changed; previous report is not protectable`

## Section Mapping

The existing `SECTION_REPAIR_HINTS` should remain the first routing source. It should cover the current redo themes:

- `persona`, `review`, `survey`, `interview`, `adoption blocker`, `switching trigger` -> `review_theme_summary`
- `feature`, `capability`, `workflow`, `dimension cell` -> `competitive_findings`, `competitor_deep_dives`, and when relevant `swot_analysis`
- `pricing`, `packaging`, `seat`, `enterprise` -> `decision_summary`, pricing response section, and matrix/layer section when available
- `SWOT`, `strength`, `weakness`, `opportunity`, `threat` -> `swot_analysis`
- `RAG`, `gap`, `retrieval` -> `rag_gap_fill`

The implementation should avoid over-expanding every upstream issue into every core section. A persona redo should not automatically rewrite SWOT and all competitor deep dives unless the issue text or redo scope explicitly names them.

## Anti-Regression Rules

`report_regression_problem()` should reject a candidate when a protectable previous report loses substantive content.

Minimum required checks:

- Protected section regression: if a protected section had at least 180 substantive characters, the candidate cannot drop below the larger of 120 characters or 55% of the previous section.
- User review collapse: if the previous user review section had at least 700 substantive characters, the candidate cannot drop below 60% of the previous section or below 600 characters.
- SWOT collapse: if the previous SWOT section had at least 900 substantive characters, the candidate cannot drop below 60% of the previous section or below 700 characters.
- Competitor deep dive collapse: if the previous section had at least 900 substantive characters, the candidate cannot drop below 60% of the previous section or below 700 characters.
- Whole report collapse: if the previous report had at least 12,000 substantive characters, the candidate cannot drop below 70% of the previous report unless the previous report is unprotectable.
- Quality comparison: keep using `compare_run_quality(candidate, baseline=previous)` and reject candidates whose regression gate fails.

The thresholds are intentionally conservative. They are designed to block obvious collapses like a user review section shrinking from a detailed section to a one-sentence caveat, not to prevent normal editing.

## Candidate Rejection Behavior

If a full rewrite candidate fails anti-regression:

- Preserve the previous report.
- Run report hardening on the preserved report before assigning it back to `detail.report_md`.
- Record the anti-regression reason in writer metadata.
- Continue normal QA/release flow so unresolved source-quality warnings remain visible.

If a section repair candidate fails anti-regression for its target section:

- Keep the original section.
- Harden the preserved full report.
- Record the section rejection reason.

This behavior means redo may fail to remove every warning, but it should not silently degrade the report the user reads.

## Preserved Report Hardening

Every path that assigns `previous_report` back to `detail.report_md` must call:

```python
self._harden_report_markdown(detail, previous_report)
```

This includes timeout, exception, anti-regression rejection, and empty/malformed section repair fallback paths.

## Observability

Writer metadata should continue to expose:

- `writer_repair_mode`
- `writer_repair_reason`
- `writer_repair_sections`
- `writer_repair_previous_report_protected`
- `writer_repair_anti_regression_required`
- `writer_repair_anti_regression_reason`

For upstream-data redo, these fields are especially important because audits need to explain whether the writer chose section repair or full rewrite.

## Testing Strategy

Add failing tests first:

- A protectable report with `upstream_data_changed=True` and a persona/review issue routes to section repair instead of full rewrite.
- A protectable report with `upstream_data_changed=True` and broad unmapped issues routes to full rewrite with anti-regression enabled.
- An unprotectable report with upstream changes still routes to full rewrite without requiring anti-regression.
- `report_regression_problem()` rejects a candidate whose user review section collapses from a detailed section to a short caveat.
- `report_regression_problem()` rejects whole-report collapse when the previous report is large and protectable.
- Writer fallback paths harden preserved previous reports before assignment.

Use the project conda environment:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\writer backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py
```

## Acceptance Criteria

- Upstream-data redo no longer automatically disables anti-regression.
- Protectable reports use section repair when upstream changes are narrow.
- Full rewrite remains possible but must pass anti-regression when replacing a protectable report.
- Candidate reports that collapse user review, SWOT, competitor deep dives, or total report substance are rejected.
- Preserved previous reports are hardened before they are accepted.
- Existing redo scope contracts and external API shapes remain compatible.

## Risks

This change may leave some QA warnings unresolved when the only available rewrite candidate is worse than the previous report. That is acceptable: visible unresolved warnings are better than silently accepting a thinner report as an improvement.

Section repair may need future tuning for issue-to-section mapping. The first implementation should stay conservative and only route to section repair when the mapping is reasonably clear.
