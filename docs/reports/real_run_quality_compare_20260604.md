# Real Run Quality Comparison

- Current run: run-72ffab0f2bf0f3edc80a1c1a9000f654
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: fail

## Score

| Metric | Value |
|---|---:|
| Target score | 93 |
| Baseline score | 77 |
| Delta score | +16 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +13810 |
| Raw sources | -2 |
| Claims | 0 |
| QA findings | -7 |
| Trace spans | -104 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 25 |
| Enterprise evidence | 25 |
| Claims | 0 |
| Enterprise claims | 20 |
| QA findings | 11 |
| Agent messages | 60 |
| Tool calls | 186 |
| Trace spans | 260 |
| Report chars | 22768 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 25 | 27 | -2 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.6 | 0.815 | -0.215 | regressed |
| claim_citation_rate | 1 | 1 | 0 | unchanged |
| citation_validity_rate | 1 | 1 | 0 | unchanged |
| real_source_rate | 0.68 | 1 | -0.32 | regressed |
| llm_call_signal | 1 | 1 | 0 | unchanged |
| report_length_score | 1 | 1 | 0 | unchanged |
| report_structure_score | 1 | 0.3 | +0.7 | improved |
| claim_risk_section_score | 1 | 0 | +1 | improved |
| scenario_checklist_section_score | 1 | 0 | +1 | improved |
| memory_context_section_score | 1 | 1 | 0 | unchanged |
| user_research_section_score | 1 | 0 | +1 | improved |
| rag_gap_fill_section_score | 1 | 0 | +1 | improved |
| qa_blocker_count | 0 | 0 | 0 | unchanged |

## QA Issue Diagnostics

| ID | Severity | Agent | Dimension | Competitor | Problem |
|---|---|---|---|---|---|
| unverified-persona-claude-code-persona-86ae8e51 | warn | collector | persona | Claude Code | Source persona-86ae8e51 for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-feature-cursor-feature-d10ec3d2 | warn | collector | feature | Cursor | Source feature-d10ec3d2 for feature is not fetched webpage evidence and should be recollected or verified. |
| reflector-coverage-1-no-valid-product-relevant-feature-data-for-the-c | warn | collector | feature | Cursor | No valid product-relevant feature data for the Cursor AI editor, the only existing Cursor feature entry describes an unrelated database pagination design pattern |
| reflector-coverage-2-windsurf-pricing-data-is-incorrectly-sourced-fro | warn | collector | pricing | Windsurf | Windsurf pricing data is incorrectly sourced from Devin (a separate competing AI coding product) with no official Windsurf plan pricing details captured |
| reflector-coverage-3-claude-code-pricing-data-is-incomplete-missing-f | warn | collector | pricing | Claude Code | Claude Code pricing data is incomplete, missing full public breakdown of Pro, Max, Team and Enterprise subscription tier pricing |
| reflector-coverage-4-github-copilot-feature-coverage-is-partial-no-co | warn | collector | feature | GitHub Copilot | GitHub Copilot feature coverage is partial, no complete official feature set documented |
| reflector-confidence-1-low-confidence-0.68-cursor-feature-source-that-i | warn | collector | feature | Cursor | Low-confidence (0.68) Cursor feature source that is completely irrelevant to the Cursor AI coding editor product |
| reflector-confidence-2-8-low-confidence-0.58-0.62-simulated-survey-and- | warn | collector | persona |  | 8 low-confidence (0.58, 0.62) simulated survey and synthetic interview persona records that contain no unique, verifiable persona insights |
| reflector-cross-competitor-1-no-aligned-cross-competitor-pricing-comparison-a | warn | comparator | pricing |  | No aligned cross-competitor pricing comparison across all 4 tools, no consistent tier mapping for individual/team/enterprise plans |
| reflector-cross-competitor-2-no-cross-competitor-feature-parity-benchmark-dat | warn | comparator | feature |  | No cross-competitor feature parity benchmark data across GitHub Copilot, Cursor, Claude Code and Windsurf |
| reflector-cross-competitor-3-no-comparative-persona-data-that-contrasts-overl | warn | comparator | persona |  | No comparative persona data that contrasts overlapping and distinct target user segments across all 4 competitors |

## Last Agent Messages

| From | To | Type | Status | Detail |
|---|---|---|---|---|
| analyst | analyst_join | competitor_knowledge_ready | consumed |  |
| analyst | analyst_join | competitor_knowledge_ready | consumed |  |
| analyst_join | qa | analyst_join_completed | consumed |  |
| qa | redo_router | analyst_qa_result | queued |  |
| comparator | reflector | comparison_matrix_ready | consumed |  |
| reflector | writer | reflection_ready | consumed |  |
| writer | qa | report_ready | consumed | deterministic fallback after writer error |
| qa | redo_router | final_qa_result | queued |  |

## Gate Reasons

- core metric regression: verified_source_rate -0.21, real_source_rate -0.32

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
