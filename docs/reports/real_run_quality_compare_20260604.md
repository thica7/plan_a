# Real Run Quality Comparison

- Current run: run-b8e528c7c39b32ef11a210da6da2d0eb
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: pass

## Score

| Metric | Value |
|---|---:|
| Target score | 97 |
| Baseline score | 77 |
| Delta score | +20 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +13889 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -8 |
| Trace spans | -127 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 16 |
| Enterprise evidence | 16 |
| Claims | 0 |
| Enterprise claims | 16 |
| QA findings | 10 |
| Agent messages | 60 |
| Tool calls | 171 |
| Trace spans | 237 |
| Report chars | 22847 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 16 | 27 | -11 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.688 | 0.815 | -0.127 | regressed |
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
| unverified-feature-cursor-feature-ce6d2b54 | warn | collector | feature | Cursor | Source feature-ce6d2b54 for feature is not fetched webpage evidence and should be recollected or verified. |
| reflector-coverage-1-cursor-feature-dimension-data-is-incomplete-sour | warn | collector | feature | Cursor | Cursor feature dimension data is incomplete, sourced from a non-official Medium article with only partial workflow functionality details, no official verified full feature set coverage |
| reflector-coverage-2-windsurf-persona-source-points-to-a-404-non-exis | warn | collector | persona | Windsurf | Windsurf persona source points to a 404 non-existent page, no valid verified target user/use case persona insights are captured |
| reflector-coverage-3-claude-code-pricing-data-is-incomplete-no-explic | warn | collector | pricing | Claude Code | Claude Code pricing data is incomplete, no explicit per-user subscription tier pricing values are provided, only vague reference to token-based billing and external pricing page |
| reflector-coverage-4-github-copilot-existing-persona-source-only-incl | warn | collector | persona | GitHub Copilot | GitHub Copilot existing persona source only includes partial usage policy snippets, no clear defined target user segments or core use case persona details |
| reflector-confidence-1-cursor-feature-entry-with-0.68-confidence-far-be | warn | collector | feature | Cursor | Cursor feature entry with 0.68 confidence, far below the 0.9+ baseline of all other official webpage verified sources |
| reflector-confidence-2-four-synthetic-un-sourced-persona-interview-reco | warn | collector | persona |  | Four synthetic un-sourced persona interview records for all 4 competitors with 0.62 confidence, no real verified user data and no valid covered competitors listed |
| reflector-cross-competitor-1-no-aligned-side-by-side-comparative-pricing-mapp | warn | comparator | pricing |  | No aligned side-by-side comparative pricing mapping across all 4 competitors for equivalent individual, team and enterprise subscription tiers |
| reflector-cross-competitor-2-no-cross-competitor-feature-benchmarking-that-ma | warn | comparator | feature |  | No cross-competitor feature benchmarking that maps overlapping capabilities and exclusive unique selling points across the 4 AI coding tools |
| reflector-cross-competitor-3-no-cross-competitor-persona-segmentation-analysi | warn | comparator | persona |  | No cross-competitor persona segmentation analysis that contrasts target user groups, core use cases and unique pain points across all 4 products |

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

- Quality gate passed against real-chain and baseline thresholds.

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
