# Real Run Quality Comparison

- Current run: run-55efc833592365374a50f5edd3084fad
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
| Report chars | +11916 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -11 |
| Trace spans | -181 |
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
| Tool calls | 118 |
| Trace spans | 183 |
| Report chars | 20874 |

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
| reflector-coverage-1-pricing-dimension:-multiple-paid-tiers-across-al | warn | collector | pricing |  | Paid tiers still have unknown billing-cycle and usage-limit fields in several competitors. |
| reflector-coverage-2-persona-dimension:-no-coverage-of-individual-hob | warn | collector | persona |  | Persona coverage still lacks individual, hobbyist, and SMB segments. |
| reflector-coverage-3-claude-code-pricing-data-contains-unstandardized | warn | collector | pricing | Claude Code | Claude Code duplicate Enterprise entries are now labeled, but still need mapping to official public plan names such as Pro, Max, and Team. |
| reflector-coverage-4-feature-dimension:-no-explicit-documented-eviden | warn | collector | feature | GitHub Copilot | Feature coverage lacks explicit evidence for whether GitHub Copilot and Claude Code have IDE integration parity. |
| reflector-confidence-1-all-4-persona-dimension-cells-have-a-uniform-con | warn | collector | persona |  | Persona cells remain uniformly low confidence at 0.62. |
| reflector-cross-competitor-1-persona-dimension-has-no-aligned-side-by-side-no | warn | comparator | persona |  | Persona comparison lacks aligned non-enterprise coverage. |
| reflector-cross-competitor-2-pricing-dimension-lacks-fully-aligned-side-by-si | warn | comparator | pricing |  | Pricing comparison still lacks fully aligned billing-cycle and usage-limit fields. |

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
- Survey/interview sources now preserve `covered_competitors` attribution metadata; the previous persona interview metadata warning is resolved.
- Analyst pricing tier normalization now dedupes Free/Hobby/$0 tiers while preserving merged limits and claims.
- The previous GitHub Copilot duplicate Free tier warning is resolved; remaining pricing work is paid-tier billing/usage completeness and Claude Code enterprise tier naming.
- Analyst pricing tier normalization now labels duplicate paid/enterprise tiers with price qualifiers instead of leaving several bare `Enterprise` rows.
- The previous "unlabeled duplicate Enterprise" warning is resolved; remaining Claude Code pricing work is mapping those entries to official Pro/Max/Team plan names.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier completeness, feature source coverage parity, and persona source quality/differentiation, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
