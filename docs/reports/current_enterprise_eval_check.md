# Enterprise Eval Report

- Generated at: 2026-06-02T12:21:22.485825+00:00
- Eval mode: demo
- Judge mode: heuristic
- Case count: 50
- Passed count: 50
- Pass rate: 100.00%
- Average observability score: 1.00
- Compliance fail count: 0
- Regression gate: PASS
- Overall: PASS

## Regression Gate

| Check | Passed | Actual | Threshold |
|---|---:|---:|---:|
| case_count | yes | 50 | 1 |
| pass_rate | yes | 1.0 | 0.8 |
| average_observability_score | yes | 1.0 | 0.8 |
| compliance_fail_count | yes | 0 | 0 |

## Cases

| Case | Status | Evidence | Claims | Obs | Compliance | Judge |
|---|---:|---:|---:|---:|---:|---:|
| gold_001 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_002 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_003 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_004 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_005 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_006 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_007 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_008 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_009 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_010 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_011 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_012 | completed | 9 | 8 | 1.00 | pass | 100 |
| gold_013 | completed | 6 | 6 | 1.00 | pass | 100 |
| gold_014 | completed | 9 | 8 | 1.00 | pass | 100 |
| gold_015 | completed | 6 | 6 | 1.00 | pass | 100 |
| gold_016 | completed | 6 | 6 | 1.00 | pass | 100 |
| gold_017 | completed | 5 | 5 | 1.00 | pass | 100 |
| gold_018 | completed | 8 | 7 | 1.00 | pass | 100 |
| gold_019 | completed | 15 | 14 | 1.00 | pass | 100 |
| gold_020 | completed | 5 | 5 | 1.00 | pass | 100 |
| gold_021 | completed | 1 | 1 | 1.00 | pass | 100 |
| gold_022 | completed | 4 | 4 | 1.00 | pass | 100 |
| gold_023 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_024 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_025 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_026 | completed | 6 | 5 | 1.00 | pass | 100 |
| gold_027 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_028 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_029 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_030 | completed | 8 | 7 | 1.00 | pass | 100 |
| gold_031 | completed | 4 | 4 | 1.00 | pass | 100 |
| gold_032 | completed | 4 | 4 | 1.00 | pass | 100 |
| gold_033 | completed | 6 | 5 | 1.00 | pass | 100 |
| gold_034 | completed | 9 | 8 | 1.00 | pass | 100 |
| gold_035 | completed | 9 | 8 | 1.00 | pass | 100 |
| gold_036 | completed | 6 | 6 | 1.00 | pass | 100 |
| gold_037 | completed | 4 | 4 | 1.00 | pass | 100 |
| gold_038 | completed | 12 | 11 | 1.00 | pass | 100 |
| gold_039 | completed | 4 | 4 | 1.00 | pass | 100 |
| gold_040 | completed | 3 | 3 | 1.00 | pass | 100 |
| gold_041 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_042 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_043 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_044 | completed | 4 | 3 | 1.00 | pass | 100 |
| gold_045 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_046 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_047 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_048 | completed | 6 | 5 | 1.00 | pass | 100 |
| gold_049 | completed | 2 | 2 | 1.00 | pass | 100 |
| gold_050 | completed | 4 | 4 | 1.00 | pass | 100 |

## Method

The enterprise eval runs golden cases through the product pipeline and checks evidence, claims, report output, audit actions, OpenTelemetry trace readiness, and compliance blockers. `--judge-mode llm` adds an external model judge when credentials are available; `heuristic` is the deterministic CI gate.
