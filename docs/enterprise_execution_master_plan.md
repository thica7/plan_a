# Enterprise Execution Master Plan

Last updated: 2026-06-07

This is the top-level execution anchor for `plan_a`. It must be read before
continuing implementation, together with the active checkpoint plan and the
source plan files listed below.

## Read-First Protocol

Before each implementation turn, read:

- `docs/enterprise_execution_master_plan.md`
- The active checkpoint plan, currently:
  `docs/checkpoint2_execution_plan.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/research_pipeline_refactor_changelog_20260606.md`

Do not rely on conversation memory alone.

## Current Position

The project is past the skeleton stage and is in:

```text
Phase 5 early stage:
  real-run report quality closure
  plus enterprise productization hardening
```

Strict status:

- Phase 1 enterprise data skeleton: mostly complete.
- Phase 2 business intelligence capability: mostly complete, needs more
  cross-domain validation.
- Phase 3 agent capability and workbench: mostly complete, above 80%.
- Phase 4 Temporal shell and approval prototype: mostly complete for the
  planned "Temporal shell + LangGraph core" architecture, not full production.
- Phase 5A enterprise governance: partial.
- Phase 5B high-score quality enhancement: in progress.
- Clean Research Pipeline: structure complete, real business quality still
  needs closure.

## Full Route

The route has three checkpoints. Checkpoint 1 is complete, Checkpoint 2 is
active now, and Checkpoint 3 must not be forgotten.

### Checkpoint 1: Report Quality Closure

Goal:

- Turn real runs from "pass with warnings" into high-quality pass candidates.
- Remove webpage chrome and fragmented extraction text from claims/reports.
- Normalize evidence into business fields.
- Make Release Gate warnings drive repair and report-section rewrite.
- Keep run status, Release Gate status, and report body wording consistent.

Required work:

1. Extraction Anti-Garbage Gate.
2. Claim Normalizer.
3. Release Gate Warning -> Repair -> Rewrite.
4. Writer status semantics alignment.
5. Fresh real-run validation.

Active detailed plan:

- `docs/checkpoint1_execution_plan.md`

Final acceptance:

- `docs/reports/checkpoint1_acceptance_report_20260607.md`
- `docs/reports/checkpoint1_real_run_audit_final_20260607_045503.md`

### Checkpoint 2: High-Score Backlog Core

Goal:

- Improve grading and real report quality using the high-score fusion backlog.

Priority:

1. H6 ClaimValidator + Self-consistency full integration.
2. H4 real RAG + Online Gap Fill closure.
3. H3 Survey/Interview upgrade from simulated-only to real material import.
4. H7 Quality Agent Matrix unified product surface.
5. H9 EvalOps real-run vs baseline page/gate.

Expected acceptance:

- High-risk claims have validation status.
- Gap Fill records retrieval query, chunk ids, rerank scores, and resolved gap
  status.
- Survey/interview data can be imported, redacted, cited, and marked with
  source type.
- Quality findings are shown through one matrix schema and can trigger
  RedoScope.
- EvalOps exposes baseline vs current system metrics and regression gate
  signals.

Active detailed plan:

- `docs/checkpoint2_execution_plan.md`

### Checkpoint 3: Enterprise Product Hardening

Goal:

- Move from a thesis/product prototype toward an enterprise-ready product.

Priority:

1. RBAC/RLS/workspace isolation hardening.
2. Report publish workflow + approval UI.
3. ArtifactStore for webpage snapshots, PDFs, screenshots, and interview
   materials.
4. OTel/Langfuse dashboards + regression gate.
5. SSO/OIDC/SAML last, after quality closure and core product loop.

Expected acceptance:

- Tenant/workspace boundaries are enforced and testable.
- Report publication is gated by approval, audit, compliance, and release
  checks.
- Non-structured artifacts have stable IDs, storage metadata, and evidence
  linkage.
- Observability covers traces, prompts, cost, quality, redaction, and regression
  signals.

## Already Completed On Checkpoint 1

Recent commits:

- `fda6d9a fix(research): enforce evidence quote quality`
- `c34d229 fix(research): unify source text for claims`
- `4bbc052 feat(qa): gate publishable text quality`
- `e7c9e7f docs(plan): add checkpoint 1 execution plan`
- `feat(research): normalize pricing feature persona fields`
- `feat(release): apply warning repair to report sections`

These cover the anti-garbage foundation, QA text quality gate, normalized
business fields, warning repair artifacts, and the final real-run acceptance.

## Active Next Work

Do next:

```text
Execute Checkpoint 2: High-Score Backlog Core.
```

Checkpoint 1 final audit:

- `docs/reports/checkpoint1_acceptance_report_20260607.md`
- `docs/reports/checkpoint1_real_run_audit_final_20260607_045503.md`

## Work Discipline

- Keep one master plan and one active checkpoint plan.
- Update the active checkpoint plan when the status changes.
- Update the changelog after each completed implementation step.
- Do not stage unrelated dirty files.
- Use commit names aligned with the checkpoint item whenever possible.
- Verify with ruff and targeted tests before commit.
- Do not mark the full goal complete until Checkpoint 1 is implemented and
  verified with a fresh real run.
