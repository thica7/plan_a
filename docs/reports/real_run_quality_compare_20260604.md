# Real Run Quality Comparison

- Current run: run-51d722d7257935d9c0ac7b33d97ff873
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
| Report chars | +10777 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -11 |
| Trace spans | -180 |
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
| Tool calls | 119 |
| Trace spans | 184 |
| Report chars | 19735 |

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
| reflector-coverage-1-all-feature-dimension-cell-values-are-truncated- | warn | collector | feature |  | Feature taxonomy now exists, but all feature dimension cells are still truncated mid-description and do not expose complete standardized feature data in the matrix. |
| reflector-coverage-2-pricing-dimension-has-missing-billing-cycle-and- | warn | collector | pricing | Claude Code | Pricing still has missing billing cycle and usage-limit fields for some tiers; Claude Code and Windsurf include duplicate or unclear enterprise tier labels. |
| reflector-coverage-3-persona-dimension-lacks-verified-non-enterprise- | warn | collector | persona |  | Persona coverage still lacks verified non-enterprise user segments; synthetic interview records remain directional rather than primary evidence. |
| reflector-confidence-1-all-4-persona-dimension-cells-have-a-uniform-0.6 | warn | collector | persona |  | Persona cells all sit at 0.62 confidence because low-confidence interview evidence dominates the merged persona model. |
| reflector-cross-competitor-1-pricing-dimension-lacks-aligned-cross-competitor | warn | comparator | pricing |  | Pricing needs stronger aligned tier naming across competitors, especially Claude Code and Windsurf. |
| reflector-cross-competitor-2-feature-dimension-lacks-full-aligned-cross-compe | warn | comparator | feature |  | Feature comparison has shared taxonomy names, but source coverage is still uneven across competitors. |
| reflector-cross-competitor-3-no-cross-competitor-aligned-differentiated-perso | warn | comparator | persona |  | Persona coverage is still too similar across competitors and needs differentiated individual, team, enterprise, and buyer segments. |

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
- The old feature warning about "no shared feature taxonomy" is resolved; the remaining feature warning is about matrix/report cell truncation and uneven competitor coverage.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier coverage, feature matrix rendering/completeness, and persona source quality/differentiation, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
