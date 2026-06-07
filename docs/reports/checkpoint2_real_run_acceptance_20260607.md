# Real Run Quality Comparison

- Current run: run-d7e3e0f28b9d416ea0b0f11a7552ef17
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
| Report chars | +22424 |
| Raw sources | -6 |
| Claims | 0 |
| QA findings | +3 |
| Trace spans | -194 |
| Fallback report regressed | no |

## Current Evidence

| Field | Value |
|---|---:|
| Raw sources | 21 |
| Enterprise evidence | 21 |
| Claims | 0 |
| Enterprise claims | 36 |
| QA findings | 21 |
| Agent messages | 36 |
| Tool calls | 122 |
| Trace spans | 170 |
| Report chars | 31382 |

## Quality Metrics

| Metric | Target | Baseline | Delta | Status |
|---|---:|---:|---:|---|
| evidence_count | 21 | 27 | -6 | regressed |
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
| warning_count | 21 | 18 | +3 | regressed |

## QA Issue Diagnostics

| ID | Severity | Agent | Dimension | Competitor | Problem |
|---|---|---|---|---|---|
| qc-issue-7be955c24bcd2722 | warn | collector | persona | GitHub Copilot | Persona dimension cell values for both Cursor and GitHub Copilot are truncated, missing full use case descriptions, complete pain point data, and full segment details required by the persona aligned_fields schema |
| qc-issue-7d7607b5866b3e9a | warn | collector | pricing | GitHub Copilot | GitHub Copilot's Pro ($15) pricing tier has no documented limits value, failing to meet the pricing dimension's required aligned field coverage for tier limits |
| qc-issue-153bde7afd007108 | warn | collector | persona | GitHub Copilot | Cursor's persona cell omits the full 'Enterprise engineering teams' segment referenced in the comparison summary, while GitHub Copilot's persona cell omits 2 of its 3 documented segments from the summary |
| qc-issue-de3ac339dea0ba71 | warn | collector | persona | Cursor | Cursor persona cell confidence (0.58) is 0.3+ lower than all non-persona dimension cells which have confidence >=0.908 |
| qc-issue-6208436270cbee76 | warn | collector | persona | GitHub Copilot | GitHub Copilot persona cell confidence (0.58) is 0.3+ lower than all non-persona dimension cells which have confidence >=0.932 |
| qc-issue-219119cb689fd14c | warn | comparator | persona |  | The persona dimension does not have fully populated, side-by-side aligned cells for both competitors, with no complete matching segment, role, company_size, use_case, and pain_point data to support valid cross-competitor persona comparison |
| qc-release-gate-bc5e0cf96e89422b | warn | collector | pricing | Cursor | claim_self_consistency_required: Claim ad5974fd37679f375198a6586cafc44f86eeaaf9255ad6a3c1c91dd7ffede8da validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=71, text=54, evidence=100, triangulation=70; f |
| qc-release-gate-b1ac2dbec4308ef8 | warn | collector | pricing | Cursor | claim_self_consistency_required: Claim 56a9fc3597cf44efe6eaf8945f4f4424ff090b84aa6d968b5c1239b9bc19fcdb validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=74, text=59, evidence=100, triangulation=70; f |
| qc-release-gate-2b5f8766368396e1 | warn | collector | feature | Cursor | claim_self_consistency_required: Claim 98d34ed7e3e512627221fbb2c5cf2dd02ccb268bb43be641e9d7ef8daab7b98c validation is weak; risk_status=weak_support; recommended_action=downgrade_claim; self-consistency=94, text=100, evidence=100, triangula |
| qc-release-gate-65b4072d97253b0c | warn | collector | feature | Cursor | claim_self_consistency_required: Claim 8178f1a6bd2da2ba07477942c82e29ec7e6ed3dc1412fef50d4ffa0202c8e0dd validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=74, text=55, evidence=100, triangulation=85; f |
| qc-release-gate-8c0b304e7c873813 | warn | collector | feature | Cursor | claim_self_consistency_required: Claim 7ca9b9725f873ba05efb8f8431c1ac4851ae9441b0faab8f2bd3d66610f0ae1d validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=70, text=45, evidence=100, triangulation=85; f |
| qc-release-gate-aaafc1c963d02630 | warn | collector | pricing | GitHub Copilot | claim_self_consistency_required: Claim 8640f7cb2b0d1d9a5fa6813e9c3af0957ddecd3204c6ca6fc8c76b986b0e5486 validation is weak; risk_status=not_applicable; recommended_action=none; self-consistency=70, text=46, evidence=100, triangulation=85; f |

## Retained Warning Actions

Every retained warning below has a typed unresolved reason, a typed required action, and an acceptance rule.

| ID | Reason code | Action | Acceptance rule | Next action |
|---|---|---|---|---|
| quality-finding-2846190abcfe76fbd3b6 | persona_field_incomplete | add_evidence | Accepted verified evidence supports the affected field or claim. | Persona dimension cell values for both Cursor and GitHub Copilot are truncated, missing full use case descriptions, complete pain point data, and full segment details required by the persona aligned_fields schema |
| quality-finding-d2c6e0e851ccfbec45fb | reflector | add_evidence | Accepted verified evidence supports the affected field or claim. | GitHub Copilot's Pro ($15) pricing tier has no documented limits value, failing to meet the pricing dimension's required aligned field coverage for tier limits |
| quality-finding-c79e02091ea239c5c8ab | persona_evidence_depth | add_evidence | Accepted verified evidence supports the affected field or claim. | Cursor's persona cell omits the full 'Enterprise engineering teams' segment referenced in the comparison summary, while GitHub Copilot's persona cell omits 2 of its 3 documented segments from the summary |
| quality-finding-b915d329aa0073065298 | persona_evidence_depth | add_evidence | Accepted verified evidence supports the affected field or claim. | Cursor persona cell confidence (0.58) is 0.3+ lower than all non-persona dimension cells which have confidence >=0.908 |
| quality-finding-efa27bef4742b28af91f | persona_evidence_depth | add_evidence | Accepted verified evidence supports the affected field or claim. | GitHub Copilot persona cell confidence (0.58) is 0.3+ lower than all non-persona dimension cells which have confidence >=0.932 |
| quality-finding-97a32a58e264811d29a9 | persona_evidence_depth | rerun_scope | Scoped redo completes and the finding is no longer blocking. | The persona dimension does not have fully populated, side-by-side aligned cells for both competitors, with no complete matching segment, role, company_size, use_case, and pain_point data to support valid cross-competitor |
| quality-finding-aff24efb0f762f993198 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=ad5974fd37679f375198a6586cafc44f86eeaa |
| quality-finding-0afb57d7b6e1b342cf33 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=56a9fc3597cf44efe6eaf8945f4f4424ff090b |
| quality-finding-b2514782b895463f6c08 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=add_evidence. fields=claim_evidence. claim_ids=98d34ed7e3e512627221fbb2c5cf2dd02ccb268 |
| quality-finding-9f17c85b78afb8282b49 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=8178f1a6bd2da2ba07477942c82e29ec7e6ed3 |
| quality-finding-9903cbb8e336078add51 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=7ca9b9725f873ba05efb8f8431c1ac4851ae94 |
| quality-finding-3ad192b6643d4f6d6ef4 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=8640f7cb2b0d1d9a5fa6813e9c3af0957ddecd |
| quality-finding-307ac4eedc8caeebd57d | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=7b84ad4ffa8bded4c8e8d668cf460a6e44be14 |
| quality-finding-5cc9ad57a676a154aaa3 | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=cde73cbe1cbeb7ad11b42cd493dfe0096ff0b8 |
| quality-finding-da2225bb02e027951ace | claim_validation_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Collect stronger independent evidence, resolve the listed claim-validation issue types, or downgrade the claim before release. action=rewrite_claim. fields=claim_evidence. claim_ids=e90561be465e0644ff815e3b946290baa9f4e4 |
| quality-finding-73fbdf82b6e13792b301 | release_gate_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Persona dimension cell values for both Cursor and GitHub Copilot are truncated, missing full use case descriptions, complete pain point data, and full segment details required by the persona aligned_fields schema action= |
| quality-finding-e8027ee3e4cdb4b2a466 | release_gate_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | GitHub Copilot's Pro ($15) pricing tier has no documented limits value, failing to meet the pricing dimension's required aligned field coverage for tier limits action=rerun_scope. query_hints=GitHub Copilot official pric |
| quality-finding-c8c9463dd8576cd65683 | release_gate_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Cursor's persona cell omits the full 'Enterprise engineering teams' segment referenced in the comparison summary, while GitHub Copilot's persona cell omits 2 of its 3 documented segments from the summary action=rerun_sco |
| quality-finding-9ca10bf76b7c808a9925 | release_gate_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | Cursor persona cell confidence (0.58) is 0.3+ lower than all non-persona dimension cells which have confidence >=0.908 action=rerun_scope. query_hints=Cursor customer story use case official; Cursor case study enterprise |
| quality-finding-475d292bb930cd472821 | release_gate_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | GitHub Copilot persona cell confidence (0.58) is 0.3+ lower than all non-persona dimension cells which have confidence >=0.932 action=rerun_scope. query_hints=GitHub Copilot customer story use case official; GitHub Copil |
| quality-finding-472e8631ec571bf14f48 | release_gate_followup | add_evidence | Accepted verified evidence supports the affected field or claim. | The persona dimension does not have fully populated, side-by-side aligned cells for both competitors, with no complete matching segment, role, company_size, use_case, and pain_point data to support valid cross-competitor |

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
