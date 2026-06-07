# Checkpoint 2 Execution Plan

Last updated: 2026-06-07

## Relationship To Master Plan

This file is the tactical execution plan for Checkpoint 2 only. The complete
route lives in `docs/enterprise_execution_master_plan.md`.

Checkpoint 1 is complete as a report-quality closure checkpoint. Checkpoint 2
continues from the final real-run acceptance report:

- `docs/reports/checkpoint1_acceptance_report_20260607.md`
- `docs/reports/checkpoint1_real_run_audit_final_20260607_045503.md`

## Read-First Protocol

Before every Checkpoint 2 implementation turn, read this file and the following
authoritative plan files:

- `docs/enterprise_execution_master_plan.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/research_pipeline_refactor_changelog_20260606.md`

Do not rely on conversation memory alone. The current worktree and these files
are authoritative.

## Scope

Checkpoint 2 is the high-score backlog core phase. Its job is to convert the
remaining non-blocking quality warnings into structured, actionable product
capabilities.

Target outcome:

- Evidence-depth warnings become typed gaps, not loose natural-language notes.
- Online Gap Fill can search, retrieve, chunk, rerank, admit, and mark gaps as
  resolved or unresolved.
- Persona evidence can come from imported survey/interview/manual transcript
  material, not only simulated survey evidence.
- High-risk claims have explicit validation status and evidence support.
- QA, RedTeam, EvidenceGap, ReleaseGate, and ClaimValidator findings are shown
  through one quality-finding schema.
- EvalOps can compare real runs against baseline/current quality metrics.

Checkpoint 2 is not:

- A full SSO/RLS/RBAC push.
- A Temporal production-hardening push.
- A frontend redesign.
- A new broad collector rewrite.
- A PPT, video, or defense-material task.

## Current Baseline

Final Checkpoint 1 run:

- Run ID: `run-ad9d5ddc52517a6005739ffc404df17f`
- Terminal status: `completed`
- Quality verdict: `pass`
- Regression gate: `pass`
- Raw sources: 32
- Enterprise evidence: 32
- Enterprise claims: 26
- Verified source rate: 1.0
- Citation validity rate: 1.0
- Real source rate: 1.0
- QA blocker count: 0

Remaining warning themes:

- Persona evidence is weaker than pricing and feature evidence.
- Some pricing tiers lack complete billing-cycle or usage-limit metadata.
- Some feature slots need stronger documented source coverage.
- Some high-risk or single-source claims need explicit validation or downgrade.

These warnings map to H3, H4, H6, and H7 in the high-score backlog.

## Authoritative Backlog Mapping

| Backlog item | Checkpoint 2 role |
|---|---|
| H3 Survey/Interview Agent | Upgrade persona evidence from simulated-only to imported/redacted/citable real materials. |
| H4 Real RAG + Online Gap Fill | Close evidence-depth gaps with typed retrieval, chunking, reranking, and admission records. |
| H6 ClaimValidator + Self-consistency | Validate high-risk claims and route weak claims to repair, downgrade, or human review. |
| H7 Quality Agent Matrix | Merge quality outputs into one product-visible issue schema. |
| H9 Baseline / EvalOps | Quantify quality lift and regression risk across real runs. |

## Implementation Order

The master plan lists H6 first as a strategic priority. The working order below
starts with the evidence-depth root cause from the final real run, while keeping
H6/H7 contracts in the foundation so the route stays aligned.

### 1. `docs(plan): add checkpoint 2 execution plan`

Status: completed by `7f323bc docs(plan): add checkpoint 2 execution plan`.

Required behavior:

- Create this file.
- Update the master plan so the active checkpoint is Checkpoint 2.
- Keep Checkpoint 1 acceptance references intact.

Acceptance:

- `docs/checkpoint2_execution_plan.md` exists.
- `docs/enterprise_execution_master_plan.md` points to Checkpoint 2 as active.
- No unrelated dirty files are staged.

### 2. `feat(quality): add unified quality finding contract`

Status: completed by `feat(quality): add unified quality finding contract`.

Backlog: H6 + H7 foundation.

Required behavior:

- Add a shared `QualityFinding` contract for QA, RedTeam, EvidenceGap,
  ReleaseGate, ClaimValidator, and EvalOps.
- Preserve source agent, severity, competitor, dimension, field path, claim id,
  evidence ids, issue type, required action, redo scope, acceptance rule, and
  status.
- Add adapters from existing issue objects into `QualityFinding`.

Acceptance:

- Existing QA/ReleaseGate findings can be converted without parsing report text.
- Unit tests cover at least QA, EvidenceGap, ReleaseGate, and ClaimValidator
  placeholders.
- Existing run/report behavior remains compatible.

Completed behavior:

- Added a shared `QualityFinding` contract and adapters for RuntimeQA,
  BusinessQA, EvidenceGap, RedTeam, ClaimValidator, ReleaseGate, Research
  `QualityGap`, and EvalOps regression issues.
- Extended the existing `QualityAgentMatrix` response with per-entry
  `findings`, `finding_ids`, and an aggregate matrix-level `findings` list
  while preserving existing score/summary/redo fields.
- Kept conversion deterministic and typed; no report-text parsing is required.

### 3. `feat(rag): close online gap fill loop`

Status: completed by `feat(rag): close quality-driven gap fill loop`.

Backlog: H4.

Required behavior:

- Convert `QualityFinding` or `QualityGap` records into targeted gap-fill
  retrieval tasks.
- Record retrieval query, provider, source candidate ids, captured page ids,
  chunk ids, rerank scores, admitted evidence ids, and resolved gap status.
- Keep gap fill inside the Clean Research Pipeline boundary:

```text
QualityGap
  -> RepairTask
  -> targeted discovery
  -> capture
  -> chunk
  -> retrieve/rerank
  -> extract/admit
  -> re-evaluate
```

Acceptance:

- Trace or quality metadata shows retrieval query, chunk ids, rerank scores, and
  resolved/unresolved status.
- A gap-fill unit test proves a missing field becomes resolved after new
  accepted evidence is admitted.
- Fresh real run keeps citation validity at 1.0 and reduces warning count from
  the Checkpoint 1 baseline.

Completed behavior:

- `QualityFinding` and Research `QualityGap` records can be converted into an
  `EvidenceGapReport` without parsing warning text.
- Gap Fill results now record retrieval providers, source candidate ids,
  captured page ids, admitted evidence ids, and per-gap resolved/unresolved
  status.
- Local RAG and online gap-fill decision events carry retrieval queries, chunk
  ids, rerank scores, admitted evidence, and resolution metadata.

Final fresh-run acceptance remains part of the overall Checkpoint 2 audit after
H3/H6/H7/H9 are complete.

### 4. `feat(survey): import real research materials`

Status: completed by `feat(survey): import real research materials`.

Backlog: H3.

Required behavior:

- Add import support for survey responses, interview notes, and manual
  transcripts as real research materials.
- Run PII redaction before admission.
- Mark source types explicitly:
  `survey_response`, `interview_record`, `manual_transcript`, or
  `survey_simulated`.
- Convert accepted materials into EvidenceRecord and KnowledgeClaim links with
  source ids.

Acceptance:

- At least one test imports a transcript containing PII and verifies redaction.
- Persona claims from imported materials carry source ids and source type.
- Simulated survey evidence remains clearly labeled and cannot masquerade as
  imported real material.

Completed behavior:

- Added a typed `UserResearchImportRequest` contract for survey responses,
  interview records, manual transcripts, manual notes, and manual research
  imports.
- Added a dedicated user-research importer that redacts PII before building
  `RawSource` and `SurveyEvidenceBundle` records.
- Added `POST /runs/{run_id}/user-research` and a `RunService` entry point that
  imports redacted materials into the current run, merges persona claim
  source_ids, writes trace/agent-message records, and syncs enterprise
  projection.
- Preserved `survey_simulated` as synthetic-only evidence; only imported real
  materials with `imported_user_research=true` can support release-scope persona
  claims.
- Preserved `RawSource.metadata` through enterprise projection so Evidence
  Center can distinguish imported real research from synthetic survey evidence.

### 5. `feat(claims): validate high-risk claims`

Status: completed by `feat(claims): validate high-risk claim status`.

Backlog: H6.

Required behavior:

- Add `ClaimValidationResult` for high-risk claims.
- Supported statuses:
  `supported`, `weak_support`, `conflicting`, `unsupported`,
  `not_applicable`.
- Run deterministic validation first; model-backed validation can be optional
  behind existing model policy.
- Route weak or unsupported claims to repair, downgrade, delete, or human
  review.

Acceptance:

- All high-risk report claims have validation status.
- Validation results include evidence ids and rationale.
- Weak/unsupported validation can trigger scoped redo or report caveat.

Completed behavior:

- Extended claim validation with H6 risk status fields while preserving the
  existing release-gate-compatible status:
  `supported`, `weak_support`, `conflicting`, `unsupported`, and
  `not_applicable`.
- Added deterministic high-risk classification, risk reasons, recommended
  action, rationale, and high-risk coverage counters to
  `ClaimValidationResult` / `ClaimValidationReport`.
- Added deterministic conflicting-evidence detection for positive high-risk
  security/compliance claims.
- Exposed H6 status metadata through unified `QualityFinding` records and
  quality decision events.

### 6. `feat(quality): expose quality agent matrix`

Backlog: H7.

Required behavior:

- Build a unified quality matrix from `QualityFinding` records.
- Group by competitor, dimension, source agent, severity, and required action.
- Keep the matrix available through backend API and report/run metadata.
- Frontend work can be minimal but must expose enough data for product review.

Acceptance:

- QA, RedTeam, EvidenceGap, ReleaseGate, and ClaimValidator findings appear in
  the same schema.
- Findings can link to source evidence, claim, trace, or RedoScope.
- No duplicate issue taxonomies are introduced.

### 7. `feat(eval): add real-run baseline regression gate`

Backlog: H9.

Required behavior:

- Persist or expose baseline vs current metrics for real runs.
- Include:
  `verified_source_rate`, `citation_validity_rate`, `real_source_rate`,
  `gap_resolution_rate`, `field_support_rate`, `validated_claim_rate`,
  `qa_blocker_count`, `warning_count`, and `regression_status`.
- Make regression gate reasons visible to backend and frontend consumers.

Acceptance:

- Eval output can compare the latest real run against a known baseline.
- A regression in citation validity, blocker count, or field support is
  detected by tests.
- Final Checkpoint 2 audit includes baseline/current numbers.

## Final Checkpoint 2 Real-Run Acceptance

Run one fresh real run after items 2-7 are complete.

Required final checks:

- Terminal status is `completed` or explicitly `passed_with_warnings`; blockers
  must be 0.
- Citation validity remains 1.0.
- Verified source rate remains at or above 0.95.
- Real source rate remains at or above 0.95.
- High-risk claim validation coverage is 1.0.
- Gap-fill metadata exists for every repaired gap.
- Warning count is materially lower than the Checkpoint 1 baseline or every
  retained warning has a typed unresolved reason and next action.
- Persona evidence includes at least one imported or public real-material path,
  not only simulated survey material.
- Quality findings are visible through one unified schema.
- EvalOps report records baseline/current comparison.

## Work Discipline

- Keep commits small and named after the checkpoint item where possible.
- Update this plan when status changes.
- Update `docs/research_pipeline_refactor_changelog_20260606.md` after each
  completed implementation step.
- Do not stage unrelated dirty files.
- Run ruff and targeted tests before each implementation commit.
- Run a fresh real run only after the relevant backend path is complete enough
  to produce meaningful evidence.
