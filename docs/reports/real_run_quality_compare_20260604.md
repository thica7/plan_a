# Real Run Quality Comparison

- Current run: run-f6444b70c022eb7dfa22fe9314a46e30
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
| Report chars | +11588 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -9 |
| Trace spans | -180 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 16 |
| Enterprise evidence | 16 |
| Claims | 0 |
| Enterprise claims | 16 |
| QA findings | 9 |
| Agent messages | 60 |
| Tool calls | 119 |
| Trace spans | 184 |
| Report chars | 20546 |

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
| report_structure_score | 0.9 | 0.3 | +0.6 | improved |
| claim_risk_section_score | 1 | 0 | +1 | improved |
| scenario_checklist_section_score | 1 | 0 | +1 | improved |
| memory_context_section_score | 1 | 1 | 0 | unchanged |
| user_research_section_score | 1 | 0 | +1 | improved |
| rag_gap_fill_section_score | 1 | 0 | +1 | improved |
| qa_blocker_count | 0 | 0 | 0 | unchanged |

## QA Issue Diagnostics

| ID | Severity | Agent | Dimension | Competitor | Problem |
|---|---|---|---|---|---|
| reflector-coverage-1-all-pricing-dimension-cells-have-truncated-value | warn | collector | pricing |  | Pricing cells still expose incomplete billing-cycle, usage-limit, and subscription-vs-usage details. |
| reflector-coverage-2-github-copilot-feature-dimension-lacks-documente | warn | collector | feature | GitHub Copilot | GitHub Copilot feature coverage lacks IDE integration and tool/terminal-use evidence that exists for other competitors. |
| reflector-coverage-3-persona-dimension-has-no-coverage-of-non-enterpr | warn | collector | persona |  | Persona coverage lacks non-enterprise user segments and non-technical stakeholder roles for all competitors. |
| reflector-coverage-4-claude-code-and-windsurf-pricing-entries-have-du | warn | collector | pricing | Claude Code | Claude Code and Windsurf still include duplicate or unstandardized enterprise tier entries. |
| reflector-confidence-1-all-4-persona-dimension-cells-have-a-uniform-con | warn | collector | persona |  | Persona cells remain a low-confidence outlier cluster at 0.62 versus 0.90+ pricing/feature cells. |
| reflector-confidence-2-all-persona-webpage-source-snippets-do-not-conta | warn | collector | persona |  | Persona webpage snippets do not yet contain explicit segment, role, or pain-point data. |
| reflector-cross-competitor-1-no-fully-aligned-side-by-side-pricing-comparison | warn | comparator | pricing |  | Pricing still lacks complete aligned tier_name, price, and billing_cycle coverage across all public tiers. |
| reflector-cross-competitor-2-missing-cross-competitor-aligned-feature-coverag | warn | comparator | feature |  | Feature taxonomy is preserved, but GitHub Copilot is missing aligned IDE/tool coverage. |
| reflector-cross-competitor-3-no-differentiated-cross-competitor-persona-segme | warn | comparator | persona |  | Persona segmentation is still too similar across competitors and needs competitor-specific attributes. |

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
- Analyst feature extraction now maps source text into a shared taxonomy: code completion, agentic coding, chat, IDE integration, review/security, tool use, repository context, and enterprise administration.
- Comparator now prioritizes canonical taxonomy feature nodes over generic model-generated nodes, and writer/reflector digests preserve longer feature matrix cells.
- The previous feature warning about truncated feature cells is resolved; the remaining feature warning is about GitHub Copilot source coverage for IDE integration and tool/terminal use.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier completeness, feature source coverage parity, and persona source quality/differentiation, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
