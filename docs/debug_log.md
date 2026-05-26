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

## 2026-05-26 11:10 - Trace and Cost Sanity

- Compared trace span counts with frontend cost panel totals to make sure LLM,
  search, fetch, and local-tool spans are all counted from the same payload.
- Checked that agent messages keep their linked `trace_span_ids`, so decision
  replay can jump from a message to the underlying tool or LLM span.
- Verified skipped fetches and robots failures remain visible as trace entries
  instead of silently disappearing from the run timeline.
