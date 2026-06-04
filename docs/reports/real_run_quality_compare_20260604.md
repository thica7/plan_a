# Real Run Quality Comparison

- Current run: run-1fee83050280901bc535ff3b822a1cf1
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
| Report chars | +11232 |
| Raw sources | -11 |
| Claims | 0 |
| QA findings | -5 |
| Trace spans | -183 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 16 |
| Enterprise evidence | 16 |
| Claims | 0 |
| Enterprise claims | 16 |
| QA findings | 13 |
| Agent messages | 60 |
| Tool calls | 116 |
| Trace spans | 181 |
| Report chars | 20190 |

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
| unverified-pricing-claude-code-pricing-b7f43520 | warn | collector | pricing | Claude Code | Claude Code pricing fell back to a web_search_result in this run and should be recollected as verified webpage evidence. |
| reflector-coverage-1-claude-code-pricing-data-is-fully-incomplete-wit | warn | collector | pricing | Claude Code | Claude Code pricing extraction is incomplete in this run: tier names, prices, billing cycles, and usage limits are not validly populated. |
| reflector-coverage-2-github-copilot-pricing-value-contains-duplicate- | warn | collector | pricing | GitHub Copilot | GitHub Copilot pricing has duplicate Free tier entries and needs tier deduplication. |
| reflector-coverage-3-windsurf-pricing-is-missing-all-non-enterprise-i | warn | collector | pricing | Windsurf | Windsurf pricing still lacks individual/Pro tier details. |
| reflector-coverage-4-all-4-competitors-persona-entries-have-identical | warn | collector | persona |  | Persona entries remain non-differentiated with identical pain points. |
| reflector-coverage-5-multiple-paid-pricing-tiers-across-github-copilo | warn | collector | pricing | GitHub Copilot | Several paid tiers still have missing billing-cycle fields. |
| reflector-confidence-1-all-4-persona-dimension-cells-have-a-uniform-0.6 | warn | collector | persona |  | Persona cells remain uniformly low confidence at 0.62, lower than verified webpage source confidence. |
| reflector-confidence-2-claude-code-pricing-cell-has-a-0.68-confidence-s | warn | collector | pricing | Claude Code | Claude Code pricing confidence is an outlier because the source was not verified webpage evidence. |
| reflector-cross-competitor-1-pricing-dimension-lacks-complete-aligned-side-by | warn | comparator | pricing |  | Pricing lacks complete aligned comparable data because Claude Code pricing is incomplete. |
| reflector-cross-competitor-2-feature-dimension-lacks-aligned-cross-competitor | warn | comparator | feature |  | Enterprise administration feature coverage is missing for Claude Code and Windsurf. |
| reflector-cross-competitor-3-feature-dimension-lacks-aligned-cross-competitor | warn | comparator | feature |  | Chat and Q&A feature coverage is uneven across competitors. |
| reflector-cross-competitor-4-feature-dimension-lacks-aligned-cross-competitor | warn | comparator | feature |  | Tool and terminal use feature coverage is uneven across competitors. |

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
- This run regressed to 97 because Claude Code pricing collection returned one `web_search_result` and incomplete pricing extraction, not because of the source attribution fix.
- The report is no longer fallback-generated; it was produced by a real LLM call.
- Remaining warnings are quality-improvement work around normalized pricing tier completeness, feature source coverage parity, and persona source quality/differentiation, not release-gate blockers.

## Method

This card is generated from `backend/scripts/compare_real_run_quality.py` output for the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
