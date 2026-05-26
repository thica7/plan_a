# Debug Log

This log records the concrete issues checked during the final demo hardening pass.
It is intentionally short and tied to observable run behavior rather than broad
implementation notes.

## 2026-05-26 10:00 - QA Redo Triage

- Checked that final QA findings preserve `redo_scope` so the router can choose
  collector, analyst, comparator, writer, or planner redo paths.
- Confirmed blocker findings are eligible for automatic redo when HITL is off.
- Confirmed warn findings only trigger redo when the run option enables warn-level
  redo.

## 2026-05-26 10:25 - Writer Timeout Fallback

- Replayed the writer timeout path after real runs showed slow report generation.
- Confirmed timeout spans stay visible as `error` trace spans instead of being
  swallowed by the report fallback.
- Confirmed fallback report generation keeps source IDs and QA-visible findings
  available for the final review panel.
