# Real Run Quality Comparison

- Current run: run-4d0da6aac04fc490ff8e22918e402917
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed_with_blockers
- Current node: none
- Execution mode: real
- Quality verdict: warn
- Regression gate: fail

## Score

| Metric | Value |
|---|---:|
| Target score | 89 |
| Baseline score | 77 |
| Delta score | +12 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +11530 |
| Raw sources | -3 |
| Claims | 0 |
| QA findings | -8 |
| Trace spans | -130 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 24 |
| Enterprise evidence | 24 |
| Claims | 0 |
| Enterprise claims | 20 |
| QA findings | 10 |
| Agent messages | 60 |
| Tool calls | 156 |
| Trace spans | 234 |
| Report chars | 20488 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 24 | 27 | -3 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 0.542 | 0.815 | -0.273 | regressed |
| claim_citation_rate | 1 | 1 | 0 | unchanged |
| citation_validity_rate | 1 | 1 | 0 | unchanged |
| real_source_rate | 0.667 | 1 | -0.333 | regressed |
| llm_call_signal | 1 | 1 | 0 | unchanged |
| report_length_score | 1 | 1 | 0 | unchanged |
| report_structure_score | 1 | 0.3 | +0.7 | improved |
| claim_risk_section_score | 1 | 0 | +1 | improved |
| scenario_checklist_section_score | 1 | 0 | +1 | improved |
| memory_context_section_score | 1 | 1 | 0 | unchanged |
| user_research_section_score | 1 | 0 | +1 | improved |
| rag_gap_fill_section_score | 0 | 0 | 0 | unchanged |
| qa_blocker_count | 0 | 0 | 0 | unchanged |

## QA Issue Diagnostics

| ID | Severity | Agent | Dimension | Competitor | Problem |
|---|---|---|---|---|---|
| unverified-feature-github-copilot-feature-1c6fe651 | warn | collector | feature | GitHub Copilot | Source feature-1c6fe651 for feature is not fetched webpage evidence and should be recollected or verified. |
| unverified-persona-claude-code-persona-8fdc9bb5 | warn | collector | persona | Claude Code | Source persona-8fdc9bb5 for persona is not fetched webpage evidence and should be recollected or verified. |
| unverified-feature-cursor-feature-f5529cd2 | warn | collector | feature | Cursor | Source feature-f5529cd2 for feature is not fetched webpage evidence and should be recollected or verified. |
| reflector-coverage-1-no-valid-complete-feature-coverage-for-cursor:-t | warn | collector | feature | Cursor | No valid complete feature coverage for Cursor: the only collected feature source for Cursor describes an unrelated database pagination utility, not the target AI IDE product |
| reflector-coverage-2-feature-dimension-is-severely-incomplete:-github | warn | collector | feature | GitHub Copilot | Feature dimension is severely incomplete: GitHub Copilot's feature snippet is truncated, Claude Code's feature snippet contains no concrete product feature details, only Windsurf has partial valid feature data |
| reflector-coverage-3-pricing-dimension-gaps:-windsurf-s-official-veri | warn | collector | pricing | Claude Code | Pricing dimension gaps: Windsurf's official verified pricing data is missing, the collected pricing source incorrectly points to Devin.ai (a separate AI coding tool) domain, Claude Code's pricing snippet is truncated with no full plan tier  |
| reflector-coverage-4-github-copilot-s-persona-data-lacks-explicit-cle | warn | collector | persona | GitHub Copilot | GitHub Copilot's persona data lacks explicit clear target user segmentation, only partial usage context is provided |
| reflector-confidence-1-8-low-confidence-0.58-0.62-synthetic-simulated-s | warn | collector | persona |  | 8 low-confidence (0.58-0.62) synthetic simulated survey and interview persona records with no real verified user data, far below the average 0.9+ confidence of verified webpage sources |
| reflector-confidence-2-three-0.68-confidence-low-value-sources:-truncat | warn | collector | feature | GitHub Copilot | Three 0.68 confidence low-value sources: truncated GitHub Copilot partial feature snippet, vague Claude Code persona use case list, irrelevant Cursor feature snippet, all carry insufficient valid information |
| reflector-cross-competitor-1-no-cross-competitor-comparative-data-across-all- | warn | comparator | pricing |  | No cross-competitor comparative data across all 3 required dimensions (pricing, feature, persona), all collected sources only cover a single individual competitor, no side-by-side relative positioning, benchmarking or comparison data betwee |

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

- report_quality signal is below release threshold.
- core metric regression: verified_source_rate -0.27, real_source_rate -0.33

## Recommendations

- Increase report depth, citation coverage, and competitor coverage so conclusions are supported by an evidence chain.
- Add a RAG Gap Fill section with retrieval queries or grounded context for open collector evidence gaps.

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
