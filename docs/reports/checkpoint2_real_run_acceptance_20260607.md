# Real Run Quality Comparison

- Current run: run-7b96eddb0b1a7613a9d5074bb5443fb6
- Baseline run: 411d3a19-7049-4a7e-aa9f-c5b63e74a69e
- Current status: completed
- Current node: none
- Execution mode: real
- Quality verdict: pass
- Regression gate: pass

## Score

| Metric | Value |
|---|---:|
| Target score | 95 |
| Baseline score | 76 |
| Delta score | +19 |

## Shape Delta

| Field | Delta |
|---|---:|
| Report chars | +19734 |
| Raw sources | -7 |
| Claims | 0 |
| QA findings | 0 |
| Trace spans | -200 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 20 |
| Enterprise evidence | 20 |
| Claims | 0 |
| Enterprise claims | 41 |
| QA findings | 18 |
| Agent messages | 36 |
| Tool calls | 115 |
| Trace spans | 164 |
| Report chars | 28692 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 20 | 27 | -7 | regressed |
| source_coverage_rate | 1 | 1 | 0 | unchanged |
| verified_source_rate | 1 | 0.815 | +0.185 | improved |
| claim_citation_rate | 1 | 1 | 0 | unchanged |
| citation_validity_rate | 1 | 1 | 0 | unchanged |
| real_source_rate | 1 | 1 | 0 | unchanged |
| gap_resolution_rate | 0 | 0 | 0 | unchanged |
| field_support_rate | 1 | 1 | 0 | unchanged |
| validated_claim_rate | 1 | 1 | 0 | unchanged |
| llm_call_signal | 1 | 1 | 0 | unchanged |
| report_length_score | 1 | 1 | 0 | unchanged |
| report_structure_score | 1 | 0.3 | +0.7 | improved |
| claim_risk_section_score | 1 | 0 | +1 | improved |
| scenario_checklist_section_score | 1 | 0 | +1 | improved |
| memory_context_section_score | 1 | 1 | 0 | unchanged |
| user_research_section_score | 1 | 0 | +1 | improved |
| rag_gap_fill_section_score | 1 | 0 | +1 | improved |
| qa_blocker_count | 0 | 0 | 0 | unchanged |
| warning_count | 13 | 18 | -5 | improved |

## QA Issue Diagnostics

| ID | Severity | Agent | Dimension | Competitor | Problem |
|---|---|---|---|---|---|
| qc-issue-6a71fee64043c58c | warn | collector | persona | Cursor | Cursor persona dimension cell value is truncated mid-text, missing full use cases, pain points, and complete segment/role/company_size details per aligned persona fields |
| qc-issue-46e11195df43bfe2 | warn | collector | persona | GitHub Copilot | GitHub Copilot persona dimension cell value is truncated mid-text, missing full use cases, pain points, and complete segment/role/company_size details per aligned persona fields |
| qc-issue-f24be682b029dbe5 | warn | collector | pricing | GitHub Copilot | GitHub Copilot pricing Pro ($15) tier has no documented limits data in collected sources, missing required aligned field value for that tier |
| qc-issue-7f96dd75fe508e1b | warn | collector | persona | GitHub Copilot | Both Cursor and GitHub Copilot persona dimension cell confidence scores (0.58) are ~0.35 lower than all other dimension cell confidence scores (0.931 to 0.973), falling far below the verified data confidence threshold |
| qc-issue-31a37aa8f6bebb39 | warn | comparator | persona |  | No complete side-by-side aligned comparison of all required persona dimension fields (segment, role, company_size, use_cases, pain_points) exists for Cursor and GitHub Copilot, as both competitor persona entries are incomplete and truncated |
| qc-release-gate-f9345a60667d400e | warn | collector | feature | Cursor | claim_self_consistency_required: Claim 6283e030ec05a01b4c7c4163ce72928b4c10a76b5c2fd1d1e05649ecef54c8ce validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=71, text=54, evidence=100, triangulation=70; f |
| qc-release-gate-28cf3843b8d21de4 | warn | collector | feature | Cursor | claim_self_consistency_required: Claim 358adbdbafd2518f448a915ef983d9d135cf65bf311bc6423f7e49332884da41 validation is weak; risk_status=weak_support; recommended_action=downgrade_claim; self-consistency=85, text=82, evidence=100, triangulat |
| qc-release-gate-7ec035f147e4817d | warn | collector | feature | Cursor | claim_self_consistency_required: Claim e220c791f8a1eedc4b9a6ea893bf88c72af4239892bbd9d7f957faace26f40da validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=66, text=39, evidence=100, triangulation=85; i |
| qc-release-gate-1fbd6650d9c0ebed | warn | collector | feature | Cursor | claim_self_consistency_required: Claim 16316b6f03e12cb5eff42794213e9ce863ccc7244b9d94bc6e68669dc8acc723 validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=58, text=29, evidence=100, triangulation=70; i |
| qc-release-gate-3b302fbd3926bfc3 | warn | collector | persona | Cursor | claim_self_consistency_required: Claim 192bcee1692c818f96a2d38ed59e3cd6c5abd429758dd447343bb3202702e600 validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=71, text=48, evidence=100, triangulation=85; f |
| qc-release-gate-6bba024810af1e0d | warn | collector | persona | Cursor | claim_self_consistency_required: Claim 112e013757fec30839de2ea0b022ad20798a8cfae292ed40077499354c42b2fa validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=66, text=44, evidence=100, triangulation=70; f |
| qc-release-gate-9258885bccbc5a63 | warn | collector | pricing | GitHub Copilot | claim_self_consistency_required: Claim 10cb2202d321f343961c6f750e1c13851fb8a382a836b86773f8fb8fd8bf6bc0 validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=69, text=44, evidence=100, triangulation=85; f |

## Retained Warning Actions

Every retained warning below has a typed unresolved reason, a typed required action, and an acceptance rule.

| ID | Reason code | Action | Acceptance rule | Next action |
|---|---|---|---|---|
| quality-finding-d27711107294cc8b5e70 | persona_field_incomplete | add_evidence | Accepted verified evidence supports the affected field or claim. | Cursor persona dimension cell value is truncated mid-text, missing full use cases, pain points, and complete segment/role/company_size details per aligned persona fields |
| quality-finding-33a9b59626b5955e6c30 | persona_field_incomplete | add_evidence | Accepted verified evidence supports the affected field or claim. | GitHub Copilot persona dimension cell value is truncated mid-text, missing full use cases, pain points, and complete segment/role/company_size details per aligned persona fields |
| quality-finding-3a392e808f635d045e96 | reflector | add_evidence | Accepted verified evidence supports the affected field or claim. | GitHub Copilot pricing Pro ($15) tier has no documented limits data in collected sources, missing required aligned field value for that tier |
| quality-finding-525f8eb982820e11ff28 | persona_evidence_depth | add_evidence | Accepted verified evidence supports the affected field or claim. | Both Cursor and GitHub Copilot persona dimension cell confidence scores (0.58) are ~0.35 lower than all other dimension cell confidence scores (0.931 to 0.973), falling far below the verified data confidence threshold |
| quality-finding-177c491fa850982dadc1 | persona_field_incomplete | rerun_scope | Scoped redo completes and the finding is no longer blocking. | No complete side-by-side aligned comparison of all required persona dimension fields (segment, role, company_size, use_cases, pain_points) exists for Cursor and GitHub Copilot, as both competitor persona entries are inco |
| quality-finding-681c7309ded87f8f7fa7 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=6283e030ec05a01b4c7c4163ce72928b4c10a7 |
| quality-finding-b29b72ba5c5427e8ff67 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=add_evidence. fields=claim_evidence. claim_ids=358adbdbafd2518f448a915ef983d9d135cf65b |
| quality-finding-463422ae639c9d4268cc | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=e220c791f8a1eedc4b9a6ea893bf88c72af423 |
| quality-finding-dab7111b55a2959a015e | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=16316b6f03e12cb5eff42794213e9ce863ccc7 |
| quality-finding-d6ef29105338cdde955b | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=192bcee1692c818f96a2d38ed59e3cd6c5abd4 |
| quality-finding-1503bc59a2627fcd1201 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=112e013757fec30839de2ea0b022ad20798a8c |
| quality-finding-53053da9b1bbaef6985b | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=10cb2202d321f343961c6f750e1c13851fb8a3 |
| quality-finding-cc740d9b96888315201d | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=0e804a0de5d632d70e2ab75dc76075db78bb7c |

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

## Method

This card is generated by `backend/scripts/compare_real_run_quality.py` from the current run, the selected old plan_a baseline, and the same RunQualityComparison gate used by the API.
