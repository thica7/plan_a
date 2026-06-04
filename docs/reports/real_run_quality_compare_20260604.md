# Real Run Quality Comparison

- Current run: run-42c16cb835055579f8166c06d80b76e1
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
| Report chars | +12281 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -11 |
| Trace spans | -187 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 16 |
| Enterprise evidence | 16 |
| Claims | 0 |
| Enterprise claims | 16 |
| QA findings | 7 |
| Agent messages | 60 |
| Tool calls | 112 |
| Trace spans | 177 |
| Report chars | 21239 |

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
| reflector-coverage-1-pricing-cells-have-truncated-values-missing-comp | warn | collector | pricing | Claude Code | Pricing now extracts multiple tiers, but some cells still have truncated values, incomplete billing cycle/limit fields, or duplicated unlabeled enterprise tiers. |
| reflector-coverage-2-feature-cells-have-truncated-incomplete-descript | warn | collector | feature |  | Feature cells still have one partial generic feature entry per competitor instead of a shared feature taxonomy. |
| reflector-coverage-3-all-persona-dimension-webpage-sources-do-not-con | warn | collector | persona |  | Persona attributes are still mostly supported by low-confidence synthetic interview records rather than verified persona-specific webpages. |
| reflector-confidence-1-all-4-persona-cells-have-uniform-0.62-confidence | warn | collector | persona |  | Persona cells are intentionally capped at 0.62 because interview records are low-confidence, but the report needs clearer rationale when verified webpages are also present. |
| reflector-confidence-2-the-windsurf-persona-webpage-source-has-0.88-nat | warn | collector | persona | Windsurf | Windsurf persona source confidence is higher than the merged persona cell confidence; the confidence-cap rationale needs to be explicit in matrix/report output. |
| reflector-cross-competitor-1-no-fully-aligned-standardized-pricing-comparison | warn | comparator | pricing |  | Pricing still needs a fully aligned plan taxonomy and normalized tier names across all four competitors. |
| reflector-cross-competitor-2-no-aligned-side-by-side-feature-comparison-acros | warn | comparator | feature |  | Feature comparison still needs consistent feature names and overlapping comparable feature entries across all competitors. |

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
- Comparator cell values now prefer structured pricing/persona/feature fields before falling back to snippets.
- Analyst pricing schema enrichment now fills price, billing cycle, and limits from verified source text when the model leaves fields unknown.
- Persona confidence is capped by low-confidence user-research sources, and persona segment names are now competitor-specific instead of a single generic label.
- Pricing winner selection now requires structural support from evidence or findings; confidence alone cannot break a pricing tie.
- Analyst pricing extraction now emits multiple pricing tiers from one source when the source contains Free/Pro/Team style plan evidence.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier taxonomy, shared feature taxonomy, and persona confidence rationale/source quality, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
