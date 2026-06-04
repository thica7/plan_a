# Real Run Quality Comparison

- Current run: run-704b6abff857d01b3bb722da5f96a047
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
| Report chars | +12003 |
| Raw sources | -10 |
| Claims | 0 |
| QA findings | -10 |
| Trace spans | -184 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 17 |
| Enterprise evidence | 17 |
| Claims | 0 |
| Enterprise claims | 17 |
| QA findings | 8 |
| Agent messages | 60 |
| Tool calls | 115 |
| Trace spans | 180 |
| Report chars | 20961 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 17 | 27 | -10 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.765 | 0.815 | -0.05 | regressed |
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
| reflector-coverage-1-pricing-dimension-missing-full-tiered-data:-gith | warn | collector | pricing | GitHub Copilot | Pricing dimension still misses full tiered data: GitHub Copilot Pro, Cursor paid tiers, and complete Claude Code/Windsurf usage-limit data are not fully captured. |
| reflector-coverage-2-feature-dimension-only-extracted-1-truncated-par | warn | collector | feature |  | Feature dimension only extracts one partial feature per competitor; a complete standardized shared feature taxonomy is still missing. |
| reflector-coverage-3-persona-dimension-lacks-coverage-of-non-enterpri | warn | collector | persona |  | Persona dimension still lacks non-enterprise user segments such as individual hobbyists and SMB/startup teams. |
| reflector-confidence-1-all-4-persona-dimension-competitor-cells-have-un | warn | collector | pricing |  | Persona confidence is now capped at 0.62 for low-confidence interview-backed cells, but the reflector asks for clearer rationale because verified persona webpages also exist. |
| reflector-confidence-2-pricing-majority-vote-declares-github-copilot-as | warn | collector | pricing | GitHub Copilot | Pricing majority vote still creates a weak winner when evidence and findings tie; winner confidence needs a stricter tie policy. |
| reflector-cross-competitor-1-no-side-by-side-aligned-full-tiered-pricing-indi | warn | comparator | pricing |  | No full aligned paid-tier pricing table across individual, pro, and enterprise tiers for all four competitors. |
| reflector-cross-competitor-2-no-cross-competitor-aligned-standardized-feature | warn | comparator | feature |  | No shared cross-competitor feature taxonomy has been applied to all four tools. |
| reflector-cross-competitor-3-no-aligned-cross-competitor-persona-coverage-for | warn | comparator | persona |  | Persona coverage still lacks aligned non-enterprise segment coverage across competitors. |

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
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around full paid-tier pricing, a shared feature taxonomy, non-enterprise persona coverage, and stricter tied-winner handling, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
