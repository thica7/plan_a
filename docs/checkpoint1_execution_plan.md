# Checkpoint 1 Execution Plan

Last updated: 2026-06-07

## Relationship To Master Plan

This file is the tactical execution plan for Checkpoint 1 only. The complete
route lives in `docs/enterprise_execution_master_plan.md`.

## Read-First Protocol

Before every Checkpoint 1 implementation turn, read this file and the following
authoritative plan files:

- `docs/enterprise_execution_master_plan.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/research_pipeline_refactor_changelog_20260606.md`

Do not rely on conversation memory alone. The current worktree and these files
are authoritative.

## Scope

Checkpoint 1 is the report-quality closure phase before moving deeper into
high-score backlog and enterprise hardening.

Target outcome:

- Real runs produce publishable business reports, not merely source-rich drafts.
- Source tokens remain valid.
- Release Gate, QA, report body, and run status use consistent semantics.
- Pricing, feature, and persona facts are normalized into business fields.
- Release Gate warnings can drive repair and targeted report-section rewrite.

Checkpoint 1 is not:

- A broad SSO/RLS/RBAC push.
- A new source-count race.
- A frontend redesign.
- A replacement of the Clean Research Pipeline architecture.

## Required Commits

### 1. `fix(research): reject noisy extracted claim text`

Status: partially completed by:

- `fda6d9a fix(research): enforce evidence quote quality`
- `c34d229 fix(research): unify source text for claims`
- `4bbc052 feat(qa): gate publishable text quality`

Completed capabilities:

- Shared quote quality boundary for extracted evidence.
- Raw source text no longer flows directly into deterministic claims or writer
  context.
- Final QA flags noisy publishable report/claim text.
- Warning-only report status renders as `passed with warnings`, not
  `blocked for review`.

Remaining acceptance:

- Verify with a fresh real run that report/claim text no longer contains page
  chrome such as `Skip to content`, `Navigation Menu`, `curl install.cmd`, or
  truncated word fragments.

### 2. `feat(research): normalize pricing feature persona fields`

Status: completed by `feat(research): normalize pricing feature persona fields`.

Required behavior:

- Pricing normalization emits stable business fields:
  `model_type`, `tier_name`, `price`, `billing_cycle`, `usage_limit`,
  `enterprise_condition`, `source_quote`.
- Feature normalization emits:
  `slot`, `support_level`, `evidence_terms`, `evidence_quote`.
- Persona normalization emits:
  `segment`, `role`, `company_size`, `use_case`, `pain_point`,
  `confidence_reason`, `evidence_quote`.
- Normalized fields are generated from accepted evidence, not raw page chrome.
- Analyst deterministic fallback and writer context consume normalized fields
  where available.

Acceptance:

- Unit tests prove pricing/feature/persona normalized fields are present.
- A noisy source is rejected or bypassed by normalized fields before
  normalized claim creation.
- Existing tests for research pipeline, analyst deterministic payload, and
  writer digest pass.

### 3. `feat(release): apply warning repair to report sections`

Status: completed by `feat(release): apply warning repair to report sections`.

Required behavior:

- Release Gate warning/follow-up tasks are converted into typed repair tasks.
- Repair tasks target specific competitor/dimension/claim/report section.
- Targeted rewrite updates only the affected report section when possible.
- Re-evaluation records before/after warning counts.

Acceptance:

- Unit tests cover warning -> repair task -> report section rewrite.
- Warning repair records before/after warning counts and explicitly retains
  unresolved warnings with rationale.
- No recursive release-gate warning loop.

### 4. `fix(writer): align pass-with-warnings report status`

Status: ready for fresh-run verification.

Required behavior:

- Run status, Release Gate status, and report `Final QA Gate Status` agree.
- Warning-only runs are not described as blocked in report body.
- Blocker runs still clearly say blocked.

Acceptance:

- Unit tests pass.
- Fresh real run report body has no contradictory status wording.

## Final Checkpoint 1 Real-Run Acceptance

Run one fresh real run after commits 2-4 are complete.

Status: completed by final real-run audit
`run-ad9d5ddc52517a6005739ffc404df17f`.

Acceptance metrics:

- `missing_source_tokens = 0`: pass via `citation_validity_rate=1.0`.
- Release Gate blockers = 0: pass via `qa_blocker_count=0`.
- Warning count closure: pass as non-blocking retained follow-up warnings; the
  final real run still has evidence-depth warnings that are mapped to
  Checkpoint 2 H3/H4/H6/H7.
- Report body has no webpage chrome/noisy claim text: pass at gate level.
- Pricing/feature/persona sections use normalized business fields: pass through
  research normalized fields, RawSource metadata, analyst fallback, and writer
  digest.
- Report status text matches backend run and Release Gate status: pass at gate
  level.
- Changelog records each completed step: pass.

## Work Discipline

- Keep commits small and named after the required checkpoint item where
  possible.
- Do not stage unrelated frontend/review dirty files unless the user explicitly
  asks.
- Run targeted tests and ruff before each commit.
- Update `docs/research_pipeline_refactor_changelog_20260606.md` for each
  completed implementation step.
- Keep this plan current when scope/status changes.
