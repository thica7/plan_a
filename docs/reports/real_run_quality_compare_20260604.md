# Real Run Quality Comparison

- Current run: run-ad193be0e25d93f45608916f352a28bb
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: fail

## Score

| Metric | Value |
|---|---:|
| Target score | 94 |
| Baseline score | 77 |
| Delta score | +17 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +13763 |
| Raw sources | -10 |
| Claims | 0 |
| QA findings | -3 |
| Trace spans | -106 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 17 |
| Enterprise evidence | 16 |
| Claims | 0 |
| Enterprise claims | 16 |
| QA findings | 15 |
| Agent messages | 60 |
| Tool calls | 184 |
| Trace spans | 258 |
| Report chars | 22721 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 17 | 27 | -10 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.588 | 0.815 | -0.227 | regressed |
| claim_citation_rate | 1 | 1 | 0 | unchanged |
| citation_validity_rate | 1 | 1 | 0 | unchanged |
| real_source_rate | 0.765 | 1 | -0.235 | regressed |
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
| unverified-persona-claude-code-persona-b0d15e48 | warn | collector | persona | Claude Code | Source persona-b0d15e48 for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-feature-cursor-feature-b32b9ba8 | warn | collector | feature | Cursor | Source feature-b32b9ba8 for feature is not fetched webpage evidence and should be recollected or verified. |
| unverified-feature-windsurf-feature-2a3d0250 | warn | collector | feature | Windsurf | Source feature-2a3d0250 for feature is not fetched webpage evidence and should be recollected or verified. |
| reflector-coverage-1-no-valid-feature-coverage-for-the-cursor-ai-codi | warn | collector | feature | Cursor | No valid feature coverage for the Cursor AI coding editor, existing feature source references an unrelated generic pagination utility named Cursor Extractor that has no connection to the Cursor IDE product |
| reflector-coverage-2-no-valid-official-windsurf-pricing-coverage-exis | warn | collector | pricing | Windsurf | No valid official Windsurf pricing coverage, existing pricing source incorrectly points to Devin.ai (a separate AI coding tool) pricing page instead of Windsurf's official pricing |
| reflector-coverage-3-claude-code-pricing-data-is-incomplete-existing- | warn | collector | pricing | Claude Code | Claude Code pricing data is incomplete, existing snippet cuts off mid-sentence with no full individual, team, and enterprise tier pricing details |
| reflector-coverage-4-github-copilot-feature-coverage-is-partial-exist | warn | collector | feature | GitHub Copilot | GitHub Copilot feature coverage is partial, existing snippet only covers a small subset of security features with no full core coding feature set details |
| reflector-coverage-5-4-synthetic-persona-interview-records-have-zero- | warn | collector | persona |  | 4 synthetic persona interview records have zero actual covered competitors, no actionable real user persona insights |
| reflector-confidence-1-4-synthetic-persona-interview-records-for-all-4- | warn | collector | persona |  | 4 synthetic persona interview records for all 4 competitors with 0.62 confidence, no valid covered competitor data |
| reflector-confidence-2-off-topic-cursor-feature-web-search-result-with- | warn | collector | feature | Cursor | Off-topic Cursor feature web search result with 0.68 confidence, unrelated to the Cursor AI editor product |
| reflector-confidence-3-low-quality-claude-code-persona-medium-article-s | warn | collector | persona | Claude Code | Low-quality Claude Code persona Medium article source with 0.68 confidence, no verified official persona data |
| reflector-confidence-4-partial-windsurf-feature-aws-review-snippet-with | warn | collector | feature | Windsurf | Partial Windsurf feature AWS review snippet with 0.68 confidence, no complete verified feature coverage |

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

- core metric regression: verified_source_rate -0.23, real_source_rate -0.24

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
