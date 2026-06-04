# Real Run Quality Comparison

- Current run: run-51b8f5cb8c133c0e36917f0a4fec909f
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
| Report chars | +13085 |
| Raw sources | -10 |
| Claims | 0 |
| QA findings | -9 |
| Trace spans | -178 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 17 |
| Enterprise evidence | 17 |
| Claims | 0 |
| Enterprise claims | 17 |
| QA findings | 9 |
| Agent messages | 63 |
| Tool calls | 117 |
| Trace spans | 186 |
| Report chars | 22043 |

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
| reflector-coverage-1-pricing-dimension:-most-paid-tiers-across-all-4- | warn | collector | pricing |  | Free tier duplication is resolved; remaining paid tiers still need billing-cycle labels and usage limits. |
| reflector-coverage-2-claude-code-pricing-has-3-unlabeled-duplicate-en | warn | collector | pricing | Claude Code | Claude Code still has duplicate unlabeled Enterprise tier entries with conflicting unvalidated price points. |
| reflector-coverage-3-feature-dimension:-github-copilot-and-claude-cod | warn | collector | feature | GitHub Copilot | GitHub Copilot and Claude Code still lack documented IDE integration coverage compared with Cursor/Windsurf. |
| reflector-coverage-4-persona-dimension:-all-4-competitors-have-nearly | warn | collector | persona |  | Persona pain points remain too generic and product-independent. |
| reflector-coverage-5-persona-dimension:-no-coverage-of-individual-hob | warn | collector | persona |  | Persona coverage still lacks individual, hobbyist, and startup segments. |
| reflector-confidence-1-all-4-persona-dimension-competitor-cells-have-co | warn | collector | persona |  | Persona confidence remains capped at 0.62 even with high-confidence webpage support. |
| reflector-cross-competitor-1-pricing:-no-aligned-cross-competitor-comparison- | warn | comparator | pricing |  | Pricing still lacks annual-discount and normalized per-user monthly alignment across competitors. |
| reflector-cross-competitor-2-feature:-missing-aligned-cross-competitor-covera | warn | comparator | feature |  | Feature coverage still lacks enterprise administration for Claude Code/Windsurf and chat/Q&A for several competitors. |
| reflector-cross-competitor-3-persona:-no-aligned-cross-competitor-differentia | warn | comparator | persona |  | Persona comparison still lacks non-enterprise differentiation. |

## Last Agent Messages

| From | To | Type | Status | Detail |
|---|---|---|---|---|
| qa | comparator | analyst_qa_result | consumed |  |
| comparator | reflector | comparison_matrix_ready | consumed |  |
| reflector | writer | reflection_ready | consumed |  |
| writer | qa | report_ready | consumed | writer_mode=real LLM call |
| qa | redo_router | final_qa_result | queued |  |
| qa | writer_only | redo_request | consumed |  |
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
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier completeness, feature source coverage parity, and persona source quality/differentiation, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
