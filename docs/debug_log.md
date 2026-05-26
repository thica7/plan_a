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
