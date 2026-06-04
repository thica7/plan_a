# Real Run Quality Comparison

- Current run: run-4c23bf2ea8b349d76a28ec9e36419329
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
| Report chars | +13522 |
| Raw sources | -9 |
| Claims | 0 |
| QA findings | -10 |
| Trace spans | -184 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 18 |
| Enterprise evidence | 18 |
| Claims | 0 |
| Enterprise claims | 17 |
| QA findings | 8 |
| Agent messages | 60 |
| Tool calls | 115 |
| Trace spans | 180 |
| Report chars | 22480 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 18 | 27 | -9 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.778 | 0.815 | -0.037 | regressed |
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
| reflector-coverage-1-pricing-dimension:-github-copilot-cell-value-tru | warn | collector | pricing | GitHub Copilot | Pricing dimension: GitHub Copilot cell value truncates full paid tier pricing details, Cursor cell value omits explicit individual/Pro tier full pricing, Claude Code cell value does not capture explicit public subscription pricing numbers, Windsurf cell value lacks individual tier pricing data, only Teams/Enterprise credit allocation is documented. |
| reflector-coverage-2-persona-dimension:-github-copilot-cursor-claude- | warn | collector | persona | GitHub Copilot | Persona dimension: GitHub Copilot, Cursor, Claude Code cells do not populate required aligned fields with verified data, all three are marked as unknown segment. |
| reflector-coverage-3-feature-dimension:-all-4-competitors-feature-cel | warn | collector | feature |  | Feature dimension: all four feature cells are truncated partial snippets, no standardized aligned fields are fully populated for side-by-side comparison. |
| reflector-confidence-1-persona-aggregated-cell-confidence-values-0.76-0 | warn | collector | persona |  | Persona aggregated cell confidence values are still judged inflated relative to the 0.62 confidence of synthetic interview persona sources. |
| reflector-confidence-2-majority-vote-pricing-result-incorrectly-lists-c | warn | collector | pricing | GitHub Copilot | Majority-vote pricing result incorrectly lists confidence value as `GitHub Copilot` instead of a numeric or valid categorical confidence score. |
| reflector-cross-competitor-1-pricing-dimension-has-no-fully-aligned-complete- | warn | comparator | pricing |  | Pricing dimension still lacks a complete side-by-side tier pricing comparison across all four competitors. |
| reflector-cross-competitor-2-persona-dimension-has-no-aligned-complete-side-b | warn | comparator | persona |  | Persona dimension still lacks aligned target segment, role, company size, and pain point data across all four competitors. |
| reflector-cross-competitor-3-feature-dimension-has-no-standardized-comparable | warn | comparator | feature |  | Feature dimension still lacks a standardized comparable feature-set mapping across all four competitors. |

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
- After raising the default LLM and writer timeout to 90 seconds, the latest run kept `writer_mode=real LLM call` instead of falling back to deterministic writing.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around aligned pricing, persona, feature extraction, and comparator confidence formatting, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
