# Enterprise Eval Report

- Generated at: 2026-05-31T12:40:56.596716+00:00
- Eval mode: demo
- Judge mode: heuristic
- Case count: 1
- Passed count: 1
- Pass rate: 100.00%
- Average observability score: 1.00
- Compliance fail count: 0
- Overall: PASS

| Case | Status | Evidence | Claims | Obs | Compliance | Judge |
|---|---:|---:|---:|---:|---:|---:|
| gold_001 | completed | 2 | 2 | 1.00 | pass | 100 |

## Method

The enterprise eval runs golden cases through the product pipeline and checks evidence, claims, report output, audit actions, OpenTelemetry trace readiness, and compliance blockers. `--judge-mode llm` adds an external model judge when credentials are available; `heuristic` is the deterministic CI gate.
