# Real Run Quality Comparison

- Current run: run-d0d94bb39d3f6369cd5be532c27f9a56
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
| Report chars | +11780 |
| Raw sources | -10 |
| Claims | 0 |
| QA findings | -9 |
| Trace spans | -184 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 17 |
| Enterprise evidence | 17 |
| Claims | 0 |
| Enterprise claims | 17 |
| QA findings | 9 |
| Agent messages | 60 |
| Tool calls | 115 |
| Trace spans | 180 |
| Report chars | 20738 |

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
| reflector-coverage-1-pricing-dimension:-multiple-tiers-across-all-4-c | warn | collector | pricing |  | Pricing truncation is resolved; remaining issue is missing billing-cycle and usage-limit values across equivalent tiers. |
| reflector-coverage-2-pricing-dimension:-claude-code-has-duplicate-unl | warn | collector | pricing | Claude Code | Claude Code still has duplicate unlabeled enterprise tier entries and no clear public individual/Pro tier. |
| reflector-coverage-3-persona-dimension:-no-coverage-of-non-enterprise | warn | collector | persona |  | Persona coverage lacks non-enterprise user segments such as solo developers and SMB teams. |
| reflector-coverage-4-feature-dimension:-github-copilot-and-claude-cod | warn | collector | feature | GitHub Copilot | GitHub Copilot and Claude Code lack documented IDE integration entries compared with Cursor/Windsurf. |
| reflector-confidence-1-all-4-persona-dimension-competitor-cells-have-un | warn | collector | persona |  | Persona cells remain a low-confidence outlier cluster at 0.62 because interview sources dominate. |
| reflector-confidence-2-persona-interview-source-records-have-empty-cove | warn | collector | persona |  | Persona interview source records still have empty covered_competitors metadata. |
| reflector-cross-competitor-1-no-fully-aligned-cross-competitor-pricing-datase | warn | comparator | pricing |  | Pricing needs consistently populated billing-cycle and usage-limit fields for Free, Individual/Pro, Team, and Enterprise levels. |
| reflector-cross-competitor-2-no-aligned-cross-competitor-persona-dataset:-all | warn | comparator | persona |  | Persona segmentation is still too generic and similar across competitors. |
| reflector-cross-competitor-3-no-aligned-cross-competitor-feature-dataset:-the | warn | comparator | feature |  | Enterprise administration is not yet represented for Claude Code and Windsurf. |

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
- Comparator and writer/reflector digests now preserve longer pricing matrix cells; the previous pricing truncation warning is resolved.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier completeness, feature source coverage parity, and persona source quality/differentiation, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
