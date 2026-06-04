# Real Run Quality Comparison

- Current run: run-c62978a929706fe1a36c882affd6f7d5
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: pass

## Score

| Metric | Value |
|---|---:|
| Target score | 98 |
| Baseline score | 77 |
| Delta score | +21 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +12328 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -10 |
| Trace spans | -199 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 16 |
| Enterprise evidence | 16 |
| Claims | 0 |
| Enterprise claims | 16 |
| QA findings | 8 |
| Agent messages | 60 |
| Tool calls | 102 |
| Trace spans | 165 |
| Report chars | 21286 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 16 | 27 | -11 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.75 | 0.815 | -0.065 | regressed |
| claim_citation_rate | 1 | 1 | 0 | unchanged |
| citation_validity_rate | 1 | 1 | 0 | unchanged |
| real_source_rate | 1 | 1 | 0 | unchanged |
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
| reflector-coverage-1-pricing-cell-values-are-truncated-for-all-compet | warn | collector | pricing | GitHub Copilot | Pricing cell values are truncated for all competitors: Cursor full tier pricing, Claude Code full subscription pricing, Windsurf individual plan pricing, and GitHub Copilot full business tier pricing are not fully extracted. |
| reflector-coverage-2-all-persona-cell-values-use-irrelevant-snippets- | warn | collector | persona |  | All persona cell values use irrelevant snippets that contain no valid data for standardized persona fields. |
| reflector-coverage-3-all-feature-cell-values-are-partial-truncated-sn | warn | collector | feature |  | All feature cell values are partial truncated snippets with no structured, comparable feature attributes extracted. |
| reflector-confidence-1-persona-dimension-cell-confidences-0.76-0.79-are | warn | collector | persona |  | Persona dimension cell confidences are still judged inflated by reflector because persona webpages are weak and interview records are synthetic. |
| reflector-confidence-2-pricing-majority-vote-winner-confidence-for-gith | warn | collector | pricing | GitHub Copilot | Pricing majority-vote winner confidence for GitHub Copilot is judged too high while other competitors lack complete pricing data. |
| reflector-cross-competitor-1-pricing-dimension-lacks-fully-aligned-complete-s | warn | comparator | pricing |  | Pricing dimension lacks complete standardized tier_name/price/billing_cycle data across all four competitors. |
| reflector-cross-competitor-2-persona-dimension-has-zero-populated-standardize | warn | comparator | persona |  | Persona dimension lacks populated standardized aligned fields across all four competitors. |
| reflector-cross-competitor-3-feature-dimension-lacks-consistent-aligned-struc | warn | comparator | feature |  | Feature dimension lacks consistent aligned structured feature attributes across all four competitors. |

## Last Agent Messages

| From | To | Type | Status | Detail |
|---|---|---|---|---|
| analyst | analyst_join | competitor_knowledge_ready | consumed |  |
| analyst | analyst_join | competitor_knowledge_ready | consumed |  |
| analyst_join | qa | analyst_join_completed | consumed |  |
| qa | comparator | analyst_qa_result | consumed |  |
| comparator | reflector | comparison_matrix_ready | consumed |  |
| reflector | writer | reflection_ready | consumed |  |
| writer | qa | report_ready | consumed | writer_mode=real LLM call |
| qa | redo_router | final_qa_result | queued |  |

## Gate Reasons

- Quality gate passed against real-chain and baseline thresholds.

## Verification Notes

- The previous failed audit stopped at `collect_qa` with `missing-source-feature-windsurf`.
- After updating Windsurf feature collection to official Cascade docs, the run reached writer and final QA.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
