# Real Run Quality Comparison

- Current run: run-ad9d5ddc52517a6005739ffc404df17f
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: pass

## Score

| Metric | Value |
|---|---:|
| Target score | 100 |
| Baseline score | 77 |
| Delta score | +23 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +22799 |
| Raw sources | +5 |
| Claims | 0 |
| QA findings | +5 |
| Trace spans | +10 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 32 |
| Enterprise evidence | 32 |
| Claims | 0 |
| Enterprise claims | 26 |
| QA findings | 23 |
| Agent messages | 88 |
| Tool calls | 275 |
| Trace spans | 374 |
| Report chars | 31757 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 32 | 27 | +5 | improved |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 1 | 0.815 | +0.185 | improved |
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
| qc-issue-0ac099f8bf4e2eef | warn | collector | persona |  | All 3 competitor persona dimension cell values are truncated, missing full required aligned field data (segment, role, company_size, use_cases, pain_points) for both SMB/startup and enterprise user segments |
| qc-issue-fa78289bd3ab3def | warn | collector | pricing | GitHub Copilot | Pricing dimension lacks complete usage/feature limit data for nearly all paid tiers across all 3 competitors, plus unstated billing cycles for GitHub Copilot's $10 Pro tier and Claude Code's Free tier |
| qc-issue-c9ad57e26fef5600 | warn | collector | feature | GitHub Copilot | Feature dimension has no documented coverage for Cursor's IDE integration and Tool and terminal use features, which are explicitly listed for GitHub Copilot and Claude Code |
| qc-issue-614ef09fe17d2d87 | warn | collector | pricing | GitHub Copilot | All 3 persona dimension cells for Cursor, GitHub Copilot, and Claude Code have abnormally low 0.58 confidence scores, ~40% lower than the 0.96+ confidence scores for all pricing and feature dimension cells |
| qc-issue-1b1745e6b2e43dff | warn | comparator | feature |  | No aligned side-by-side feature comparison coverage for IDE integration and Tool and terminal use across all 3 competitors, as Cursor has no populated data for these two features |
| qc-issue-bfe941451a9b5d3b | warn | comparator | persona |  | No complete aligned side-by-side persona segment comparison across all 3 competitors, as every competitor's persona cell value is cut off mid-entry |
| qc-issue-a49bb66621256cb3 | warn | comparator | pricing |  | No standardized aligned billing cycle comparison across all pricing tiers, as GitHub Copilot's $10 Pro tier and Claude Code's Free tier have unpopulated billing cycle values |
| qc-release-gate-5a6474460901d0be | warn | collector | persona | Cursor | claim_self_consistency_required: Claim 889ef90b82ec48a1b867eb7d150850c20c5d2df31976761566cda5401be650ea validation is weak; self-consistency=72, text=57, evidence=100, triangulation=70; failed_checks=text_support. |
| qc-release-gate-971ae82e6dee18ef | warn | collector | persona | Cursor | claim_self_consistency_required: Claim 8593abee9354a6d1daa0df84c3e8492f576acfc51c6349af38903fc5edd5fdd7 validation is weak; self-consistency=72, text=57, evidence=100, triangulation=70; failed_checks=text_support. |
| qc-release-gate-66ba7aff94fdb7e7 | warn | collector | persona | Cursor | claim_self_consistency_required: Claim 901226d546aa0ee8857b044d7fdb8453a7aa8db85ffeeb0e25946b18f9e9484e validation is weak; self-consistency=69, text=50, evidence=100, triangulation=70; failed_checks=text_support. |
| qc-release-gate-b99c7f764ec08288 | warn | collector | persona | GitHub Copilot | claim_self_consistency_required: Claim eecbb397abf8e410ead0e22698c19d74e4d7e29c064a7d251fba571738651d31 validation is weak; self-consistency=70, text=52, evidence=100, triangulation=70; failed_checks=text_support. |
| qc-release-gate-1c585dba61b17d1b | warn | collector | persona | GitHub Copilot | claim_self_consistency_required: Claim 3363cab258f1dc4692226aa7c5ee5485ffbae4f37b8423f11d0a3e64c9906386 validation is weak; self-consistency=72, text=57, evidence=100, triangulation=70; failed_checks=text_support. |

## Last Agent Messages

| From | To | Type | Status | Detail |
|---|---|---|---|---|
| analyst_dispatch | analyst | analysis_task | consumed |  |
| kb_cache | analyst_join | kb_cache_hit | consumed |  |
| analyst_join | qa | analyst_join_completed | consumed |  |
| qa | comparator | analyst_qa_result | consumed |  |
| comparator | reflector | comparison_matrix_ready | consumed |  |
| reflector | writer | reflection_ready | consumed |  |
| writer | qa | report_ready | consumed | writer_mode=real LLM call |
| qa | redo_router | final_qa_result | queued |  |

## Gate Reasons

- Quality gate passed against real-chain and baseline thresholds.

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
