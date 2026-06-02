# Submission Checklist

Use this checklist before packaging a deliverable, opening a demo machine, or creating an evaluation handoff.

## Must Not Ship

- `.env` or any file containing provider keys, backup LLM keys, bearer tokens, cookies, or private endpoints.
- `runs/`, `logs/`, `backups/`, `.claude/`, local screenshots, and temporary comparison scripts.
- Generated review HTML files unless they are intentionally part of the report appendix.
- Raw enterprise customer documents without explicit redaction and source approval.

## Required Checks

- `conda run -n bd-competiscope-v2 python -m pytest backend/tests`
- `pnpm.cmd --dir frontend build`
- `conda run -n bd-competiscope-v2 python backend\scripts\phase4_readiness_report.py --require-server`
- `conda run -n bd-competiscope-v2 python backend\scripts\eval_enterprise.py --limit 50 --judge-mode heuristic`

## Runtime Baseline

- `RUN_ORCHESTRATION_BACKEND=temporal`
- `TEMPORAL_TRAFFIC_PERCENT=100`
- `ENTERPRISE_STORE_BACKEND=postgres`
- `COMPLIANCE_REDACTION_ENABLED=true`
- `COMPLIANCE_REQUIRE_TRACE_CONTEXT=true`

## Product Quality Gates

- Claim validation has no blockers for reports intended to publish.
- Quality matrix has no blocker entries and explains any warning entries.
- Decision replay is available for the run and includes agent, QA, redo, report, and metric events.
- Report evidence anchors resolve to source records or artifacts.
- PII redaction and model policy checks pass for the target workspace.
