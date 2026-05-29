# Golden Eval Report

- Generated at: 2026-05-29T05:32:09.919096+00:00
- Case count: 30
- Passed count: 30
- Coverage lift count: 30
- Coverage lift rate: 100.00%
- Overall: PASS

| Case | Status | Evidence | Claims | Report chars | Audit actions |
|---|---:|---:|---:|---:|---:|
| gold_001 | completed | 2 | 2 | 240 | 8 |
| gold_002 | completed | 2 | 2 | 234 | 8 |
| gold_003 | completed | 2 | 2 | 235 | 8 |
| gold_004 | completed | 2 | 2 | 240 | 8 |
| gold_005 | completed | 2 | 2 | 221 | 8 |
| gold_006 | completed | 2 | 2 | 234 | 8 |
| gold_007 | completed | 2 | 2 | 232 | 8 |
| gold_008 | completed | 2 | 2 | 230 | 8 |
| gold_009 | completed | 2 | 2 | 220 | 8 |
| gold_010 | completed | 2 | 2 | 232 | 8 |
| gold_011 | completed | 2 | 2 | 229 | 8 |
| gold_012 | completed | 6 | 6 | 262 | 8 |
| gold_013 | completed | 6 | 6 | 255 | 8 |
| gold_014 | completed | 6 | 6 | 259 | 8 |
| gold_015 | completed | 6 | 6 | 268 | 8 |
| gold_016 | completed | 6 | 6 | 260 | 8 |
| gold_017 | completed | 5 | 5 | 266 | 8 |
| gold_018 | completed | 4 | 4 | 248 | 8 |
| gold_019 | completed | 10 | 10 | 264 | 8 |
| gold_020 | completed | 5 | 5 | 258 | 8 |
| gold_021 | completed | 1 | 1 | 227 | 8 |
| gold_022 | completed | 4 | 4 | 265 | 8 |
| gold_023 | completed | 2 | 2 | 240 | 8 |
| gold_024 | completed | 2 | 2 | 220 | 8 |
| gold_025 | completed | 2 | 2 | 221 | 8 |
| gold_026 | completed | 3 | 3 | 239 | 8 |
| gold_027 | completed | 2 | 2 | 244 | 8 |
| gold_028 | completed | 2 | 2 | 239 | 8 |
| gold_029 | completed | 2 | 2 | 237 | 8 |
| gold_030 | completed | 6 | 6 | 252 | 8 |

## Method

Each golden case is run through the deterministic demo pipeline and compared against an LLM-only fixture with no structured evidence store, claim store, report version, or audit actions. A case passes only when the run completes, produces enterprise evidence and claims, and records at least five audit action types.

## Phase 3 Exit Check

The v2.0 system shows coverage lift when it produces more evidence, claims, and report content than the fixture baseline. This report is intended as the strict artifact for the Phase 3 golden-set requirement.
