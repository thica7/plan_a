# Real Run Quality Comparison

- Current run: run-8b1760b1ad2cb41bd185aafa19e8aa15
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: fail

## Score

| Metric | Value |
|---|---:|
| Target score | 91 |
| Baseline score | 77 |
| Delta score | +14 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +14010 |
| Raw sources | -5 |
| Claims | 0 |
| QA findings | -4 |
| Trace spans | -122 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 22 |
| Enterprise evidence | 22 |
| Claims | 0 |
| Enterprise claims | 20 |
| QA findings | 14 |
| Agent messages | 60 |
| Tool calls | 163 |
| Trace spans | 242 |
| Report chars | 22968 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 22 | 27 | -5 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.5 | 0.815 | -0.315 | regressed |
| claim_citation_rate | 1 | 1 | 0 | unchanged |
| citation_validity_rate | 1 | 1 | 0 | unchanged |
| real_source_rate | 0.636 | 1 | -0.364 | regressed |
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
| unverified-persona-cursor-persona-5725c5e2 | warn | collector | persona | Cursor | Source persona-5725c5e2 for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-persona-claude-code-persona-72c31066 | warn | collector | persona | Claude Code | Source persona-72c31066 for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-feature-cursor-feature-1a56f13a | warn | collector | feature | Cursor | Source feature-1a56f13a for feature is not fetched webpage evidence and should be recollected or verified. |
| reflector-coverage-1-no-valid-windsurf-pricing-data-as-the-associated | warn | collector | pricing | Windsurf | No valid Windsurf pricing data, as the associated pricing source incorrectly points to Devin.ai, a separate unrelated AI coding product |
| reflector-coverage-2-claude-code-pricing-data-is-incomplete-missing-e | warn | collector | pricing | Claude Code | Claude Code pricing data is incomplete, missing explicit paid tier pricing values, quota limits and full plan breakdown details |
| reflector-coverage-3-no-valid-verified-feature-data-for-cursor-as-the | warn | collector | feature | Cursor | No valid verified feature data for Cursor, as the only associated feature source describes a generic database pagination design pattern (Cursor Extractor) completely unrelated to the Cursor AI editor product |
| reflector-coverage-4-feature-dimension-coverage-for-github-copilot-cl | warn | collector | feature | GitHub Copilot | Feature dimension coverage for GitHub Copilot, Claude Code, Windsurf is fragmented, no complete structured full feature set details captured for any of the three competitors |
| reflector-coverage-5-no-verified-complete-target-user-persona-data-fo | warn | collector | persona | Claude Code | No verified complete target user persona data for Claude Code and Windsurf, existing non-synthetic persona snippets are unrelated to actual end-user profiles |
| reflector-confidence-1-8-synthetic-simulated-persona-survey-and-intervi | warn | collector | persona |  | 8 synthetic/simulated persona survey and interview entries across all 4 competitors have extremely low confidence scores (0.58 to 0.62) with no verified real user insights, and zero marked covered competitors |
| reflector-confidence-2-unverified-web-search-result-for-claude-code-per | warn | collector | persona | Claude Code | Unverified web search result for Claude Code persona has 0.68 confidence, no concrete validated persona segmentation data |
| reflector-confidence-3-unverified-unrelated-web-source-for-cursor-featu | warn | collector | feature | Cursor | Unverified unrelated web source for Cursor feature has 0.68 confidence, contains no valid product feature information for the Cursor AI editor |
| reflector-cross-competitor-1-no-unified-cross-competitor-comparative-data-acr | warn | comparator | pricing |  | No unified cross-competitor comparative data across pricing, feature, persona dimensions that covers all 4 target competitors, all existing sources only cover a single individual competitor |

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

- core metric regression: verified_source_rate -0.32, real_source_rate -0.36

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
