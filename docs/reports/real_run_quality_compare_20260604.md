# Real Run Quality Comparison

- Current run: run-ff59f88a0e8e1f9ac3511c5508a13f9a
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: fail

## Score

| Metric | Value |
|---|---:|
| Target score | 96 |
| Baseline score | 77 |
| Delta score | +19 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +14050 |
| Raw sources | -9 |
| Claims | 0 |
| QA findings | -5 |
| Trace spans | -103 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 18 |
| Enterprise evidence | 18 |
| Claims | 0 |
| Enterprise claims | 17 |
| QA findings | 13 |
| Agent messages | 60 |
| Tool calls | 186 |
| Trace spans | 261 |
| Report chars | 23008 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 18 | 27 | -9 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.611 | 0.815 | -0.204 | regressed |
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
| unverified-persona-claude-code-persona-e33cc67c | warn | collector | persona | Claude Code | Source persona-e33cc67c for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-persona-cursor-persona-1acfcf1a | warn | collector | persona | Cursor | Source persona-1acfcf1a for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-feature-cursor-feature-c8e4d17f | warn | collector | feature | Cursor | Source feature-c8e4d17f for feature is not fetched webpage evidence and should be recollected or verified. |
| reflector-coverage-1-windsurf-pricing-dimension-has-no-valid-official | warn | collector | pricing | Windsurf | Windsurf pricing dimension has no valid official coverage: existing Windsurf pricing source incorrectly links to Devin.ai (a separate competing AI coding product) pricing page, no actual Windsurf plan/tier pricing data is captured |
| reflector-coverage-2-cursor-feature-dimension-has-no-valid-coverage:- | warn | collector | feature | Cursor | Cursor feature dimension has no valid coverage: existing Cursor feature source describes a generic database pagination utility named 'Cursor Extractor' completely unrelated to the Cursor AI code editor product |
| reflector-coverage-3-claude-code-persona-dimension-has-no-verified-co | warn | collector | persona | Claude Code | Claude Code persona dimension has no verified coding-specific target user data: existing source only covers generic Claude LLM use cases unrelated to Claude Code's coding-focused user segments |
| reflector-coverage-4-github-copilot-persona-dimension-only-contains-a | warn | collector | persona | GitHub Copilot | GitHub Copilot persona dimension only contains a low-detail synthetic interview note with no concrete target user profile, use case or segment data |
| reflector-confidence-1-1.0-confidence-windsurf-persona-source-is-misatt | warn | collector | persona | Windsurf | 1.0 confidence Windsurf persona source is misattributed: it pulls content from Devin Desktop documentation (not Windsurf product content), the maximum confidence rating is unjustified |
| reflector-confidence-2-github-copilot-persona-source-with-0.56-confiden | warn | collector | persona | GitHub Copilot | GitHub Copilot persona source with 0.56 confidence is a low-value synthetic record that contains no specific, verifiable persona details |
| reflector-confidence-3-three-near-identical-synthetic-persona-interview | warn | collector | persona | Claude Code | Three near-identical synthetic persona interview records for Cursor, Claude Code, Windsurf (all 0.62 confidence) only contain generic repeated text with no unique, product-specific persona insights |
| reflector-cross-competitor-1-no-side-by-side-comparative-pricing-data-across- | warn | comparator | pricing |  | No side-by-side comparative pricing data across all 4 competitors, all existing pricing sources only cover one individual product with no aligned tier/feature-to-cost comparison |
| reflector-cross-competitor-2-no-standardized-cross-competitor-feature-compari | warn | comparator | feature |  | No standardized cross-competitor feature comparison across the 4 products, no aligned benchmark of core coding capabilities, agent performance, IDE integration or supported model sets |

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

- core metric regression: verified_source_rate -0.20

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
