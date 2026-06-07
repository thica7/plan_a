# Enterprise Execution Master Plan

Last updated: 2026-06-07

This is the top-level execution anchor for `plan_a`. It must be read before
continuing implementation, together with the latest checkpoint plan and the
source plan files listed below.

## Read-First Protocol

Before each implementation turn, read:

- `docs/enterprise_execution_master_plan.md`
- The latest checkpoint plan:
  `docs/checkpoint4_architecture_contract_consolidation_plan.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/architecture_first_execution_plan_20260607.md`
- `docs/checkpoint5_enterprise_runtime_plan.md` when continuing architecture
  runtime work after Checkpoint 4.
- `docs/research_pipeline_refactor_changelog_20260606.md`
- `docs/checkpoint4_architecture_changelog_20260607.md`

Do not rely on conversation memory alone.

## Current Position

The project is past the skeleton stage and is in:

```text
Phase 5 enterprise productization:
  Checkpoint 1 report quality closure complete
  Checkpoint 2 high-score backlog core complete
  Checkpoint 3 enterprise product hardening core complete
  Checkpoint 4 architecture contract and runtime smoke complete
  Checkpoint 5 enterprise runtime plan created; C5.0 smoke gate complete
```

Strict status:

- Phase 1 enterprise data skeleton: mostly complete.
- Phase 2 business intelligence capability: mostly complete, needs more
  cross-domain validation.
- Phase 3 agent capability and workbench: mostly complete, above 80%.
- Phase 4 Temporal shell and approval prototype: mostly complete for the
  planned "Temporal shell + LangGraph core" architecture, not full production.
- Phase 5A enterprise governance: Checkpoint 3 core complete; live Postgres RLS,
  SSO, and hosted observability remain later production hardening.
- Phase 5B high-score quality enhancement: Checkpoint 2 core is complete;
  continue only through targeted quality gates.
- Clean Research Pipeline: structure complete and accepted for Checkpoint 2;
  continue through enterprise artifact/source governance.
- Checkpoint 4 architecture consolidation: contract implementation complete for
  identity, scope, research boundary, quality, HITL, orchestration, and
  observability. Runtime smoke validation is complete.
- Architecture-first execution: use
  `docs/architecture_first_execution_plan_20260607.md` when the next request is
  about architecture rather than run-specific report quality.
- Checkpoint 5 enterprise runtime: use
  `docs/checkpoint5_enterprise_runtime_plan.md` for the next architecture-level
  implementation step.

## Full Route

The route now has five checkpoints. Checkpoint 1, Checkpoint 2, and Checkpoint
3 core are complete. Checkpoint 4 contract implementation and runtime smoke
validation are complete. Checkpoint 5 has a plan, and C5.0 runtime smoke gate
is complete.

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

Final acceptance:

- `docs/reports/checkpoint2_real_run_acceptance_20260607.md`

### Checkpoint 3: Enterprise Product Hardening

Goal:

- Move from a thesis/product prototype toward an enterprise-ready product.

Priority:

1. Report publish workflow + approval/HITL correction loop.
2. ArtifactStore for webpage snapshots, PDFs, screenshots, and interview
   materials.
3. RBAC/RLS/workspace isolation hardening.
4. OTel/Langfuse dashboards + regression gate productization.
5. SSO/OIDC/SAML last, after approval, artifacts, and isolation are stable.

Expected acceptance:

- Tenant/workspace boundaries are enforced and testable.
- Report publication is gated by approval, audit, compliance, and release
  checks.
- Non-structured artifacts have stable IDs, storage metadata, and evidence
  linkage.
- Observability covers traces, prompts, cost, quality, redaction, and regression
  signals.

Active detailed plan:

- `docs/checkpoint3_execution_plan.md`

Final acceptance:

- `docs/reports/checkpoint3_product_flow_verification_20260607.md`

### Checkpoint 4: Architecture Contract Consolidation

Goal:

- Keep the Phase 5 enterprise architecture clean as more capabilities are
  added.
- Consolidate identity, report scope, research pipeline, quality findings,
  HITL lifecycle, orchestration ownership, and observability contracts.
- Prevent future features from reintroducing ad hoc source IDs, scope drift,
  duplicated QA logic, or hidden orchestration ownership.

Priority:

1. Identity and resolver contract.
2. Report scope and enterprise read-model contract.
3. Clean Research Pipeline boundary hardening.
4. Quality finding matrix contract.
5. HITL lifecycle contract.
6. Temporal, LangGraph, Research Pipeline, and Enterprise Store ownership.
7. Observability and governance contract.

Active detailed plan:

- `docs/checkpoint4_architecture_contract_consolidation_plan.md`
- `docs/architecture_first_execution_plan_20260607.md`

Completion audit:

- `docs/reports/checkpoint4_architecture_contract_audit_20260607.md`
- `docs/reports/checkpoint4_runtime_smoke_report_20260607.md`

### Checkpoint 5: Enterprise Runtime Architecture

Goal:

- Turn the existing enterprise features into an operable runtime architecture.
- Add one command boundary for review, approval, publish, redo, correction, and
  monitor actions.
- Govern artifacts, tenant isolation, advisory memory/RAG context, EvalOps,
  cost/model/tool policy, and scheduled scans through explicit contracts.

Priority:

1. Runtime smoke gate.
2. Runtime command layer.
3. Cost/model/tool policy runtime.
4. Tenant governance boundary.
5. Artifact and source material lifecycle.
6. Memory/RAG advisory context governance.
7. EvalOps release contract.
8. Monitor operations.

Active detailed plan:

- `docs/checkpoint5_enterprise_runtime_plan.md`

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
Checkpoint 5 C5.1 Runtime Command Layer:
docs/checkpoint5_enterprise_runtime_plan.md
```

Checkpoint 2 final audit:

- `docs/reports/checkpoint2_real_run_acceptance_20260607.md`

Checkpoint 3 final product-flow verification:

- `docs/reports/checkpoint3_product_flow_verification_20260607.md`

## Work Discipline

- Keep one master plan and one current checkpoint or hardening plan.
- Update the current plan when the status changes.
- Update the changelog after each completed implementation step.
- Do not stage unrelated dirty files.
- Use commit names aligned with the checkpoint item whenever possible.
- Verify with ruff and targeted tests before commit.
- Checkpoint 3 core is complete only for the local enterprise product-flow
  boundary. Do not claim live production readiness until Postgres RLS, SSO, and
  hosted observability are verified in deployment-like environments.
