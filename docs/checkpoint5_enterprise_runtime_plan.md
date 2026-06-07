# Checkpoint 5 Enterprise Runtime Plan

Last updated: 2026-06-07

## Position

Checkpoint 5 starts after Checkpoint 4 architecture contracts are code-complete.
It is not another data-collection patch and not another single-run quality
cleanup. Its goal is to make `plan_a` behave like an enterprise competitive
intelligence product that can be operated, audited, governed, and improved over
time.

Authoritative inputs:

- `docs/enterprise_execution_master_plan.md`
- `docs/reports/checkpoint4_architecture_contract_audit_20260607.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/architecture_first_execution_plan_20260607.md`
- `docs/checkpoint4_architecture_contract_consolidation_plan.md`

Current baseline:

- Checkpoint 1 report quality closure is accepted.
- Checkpoint 2 high-score backlog core is accepted.
- Checkpoint 3 enterprise product hardening core is accepted.
- Checkpoint 4 architecture contracts are complete.
- Checkpoint 4 runtime smoke is accepted by
  `docs/reports/checkpoint4_runtime_smoke_report_20260607.md`.

## Goal

Create a clean enterprise runtime architecture around the existing core:

```text
User / Operator
  -> Enterprise Workbench
  -> Runtime Command Layer
  -> Temporal business workflows
  -> LangGraph agent DAG
  -> Clean Research Pipeline
  -> Enterprise Store / Artifact Store / Memory / RAG / EvalOps
  -> Audit / Decision Replay / Telemetry
```

The important rule:

```text
Temporal owns business lifecycle.
LangGraph owns agent reasoning.
Research Pipeline owns evidence acquisition and repair proposals.
Enterprise Store owns durable records and publication state.
Runtime Command Layer owns user/operator commands and policy checks.
Observability owns trace, audit, replay, cost, and regression evidence.
```

## Non-Goals

Checkpoint 5 does not:

- Rewrite LangGraph.
- Force Temporal into every agent node.
- Add more source-specific logic inside collector.
- Make writer responsible for source resolution.
- Treat Langfuse absence as missing observability.
- Add SSO/SAML/OIDC before internal enterprise runtime boundaries are stable.
- Build defense PPT, video, or presentation material.

## Workstream Summary

| ID | Name | Main Purpose | Primary Backlog Source |
|---|---|---|---|
| C5.0 | Runtime smoke gate | Prove Checkpoint 4 contracts work in real runtime | Checkpoint 4 audit |
| C5.1 | Runtime command layer | Unify approval, publish, correction, redo, and review commands | Phase 5A, H8 |
| C5.2 | Artifact lifecycle | Make snapshots, PDFs, transcripts, exports, and source materials durable assets | H10 |
| C5.3 | Tenant governance boundary | Harden workspace isolation, RBAC, RLS readiness, audit scopes | Phase 5A |
| C5.4 | Advisory context governance | Govern Memory/RAG as advisory context, not hidden report scope | H4, H5 |
| C5.5 | EvalOps release contract | Turn EvalOps into a release/regression gate, not just metrics | H9 |
| C5.6 | Cost/model/tool policy runtime | Centralize model routing, tool policy, quotas, and cost decisions | H10, Phase 5A |
| C5.7 | Monitor operations | Productize scheduled scans and monitor jobs as enterprise operations | Phase 5A |

Current status:

```text
C5.0 Runtime smoke gate: complete
C5.1 Runtime command layer: next
C5.2-C5.7: pending
```

## C5.0 Runtime Smoke Gate

Purpose:

Prove the Checkpoint 4 contracts work outside unit tests before building more
enterprise runtime layers on top.

Implementation:

- Run one Temporal-mode real run with `HITL_ENABLED=false`.
- Run one HITL-enabled fixture-backed or real run to verify planner and QA
  lifecycle events.
- Verify `/api/runtime` telemetry status.
- Verify the produced run has:
  - resolvable report source tokens;
  - report-version-scoped release gate;
  - unified quality finding matrix;
  - decision replay events;
  - local trace and cost signals.

Acceptance:

- A new report can be reviewed without missing source-token drift.
- HITL lifecycle events are visible in decision replay.
- Runtime status clearly separates local observability from hosted Langfuse/OTel.
- Any failed smoke result becomes a targeted C5.x blocker, not an ad hoc patch.

Suggested commit:

```text
docs(runtime): record checkpoint 4 smoke validation
```

## C5.1 Runtime Command Layer

Purpose:

Stop routing enterprise actions directly through scattered router/service
methods. Create one explicit command boundary for operator actions.

Commands:

```text
create_run
request_review
resume_review
request_redo
revise_report
request_approval
approve_report
reject_report
publish_report
archive_report
```

Implementation direction:

- Add `backend/packages/runtime/commands.py` and
  `backend/packages/runtime/service.py`.
- Define typed command models and result models.
- Keep FastAPI routers thin: parse request, call runtime command service,
  return DTO.
- Runtime command service coordinates:
  - RBAC policy check;
  - workspace/project/run scope check;
  - Temporal or direct service path selection;
  - audit and decision replay event correlation;
  - HITL lifecycle event creation.
- Do not move LangGraph reasoning into this layer.
- Do not move report publication rules into LangGraph.

Acceptance:

- Approval, publish, manual revision, HITL resume, and redo use the same command
  result shape.
- Every operator command produces an audit/replay correlation key.
- Tests prove routers cannot bypass approval/publish/HITL policy by calling
  store upsert paths directly.

Suggested commits:

```text
feat(runtime): add enterprise command layer
refactor(api): route review and publish actions through runtime commands
```

## C5.2 Artifact And Source Material Lifecycle

Purpose:

Turn source snapshots and user research materials into first-class enterprise
assets, not loose metadata attached to evidence.

Runtime lifecycle:

```text
captured/imported
  -> stored
  -> linked_to_source_or_evidence
  -> governed
  -> retained_or_expired
  -> replayable
```

Implementation direction:

- Keep `backend/packages/artifacts/` as the storage boundary.
- Keep source snapshot construction in `backend/packages/enterprise/source_snapshots.py`.
- Add a small lifecycle service if current artifact operations are scattered.
- Make the lifecycle record:
  - storage backend;
  - media type;
  - content hash;
  - retention policy;
  - PII/redaction status;
  - source policy status;
  - linked raw source id;
  - linked evidence id;
  - linked report version id.
- Ensure Clean Research Pipeline can create or request snapshots through this
  boundary, but does not own retention or compliance policy.

Acceptance:

- Webpage snapshot, imported survey/interview material, and report export share
  the same artifact lifecycle vocabulary.
- Artifact records are workspace-scoped and audit-visible.
- Decision replay can explain which artifact supported a source or report
  version.
- Tests cover local and external artifact backends without requiring S3/OSS.

Suggested commit:

```text
feat(artifacts): formalize source material lifecycle
```

## C5.3 Tenant Governance Boundary

Purpose:

Move from application-level workspace checks toward production-ready tenant
governance without pretending full SSO/RLS is already live.

Implementation direction:

- Keep current RBAC policy in `backend/packages/auth/rbac.py`.
- Add a governance readiness report that checks:
  - every enterprise route has workspace scope;
  - every durable record carries workspace identity;
  - audit reads are workspace-filtered;
  - report publication checks role and scope;
  - memory and artifact access are workspace-filtered;
  - SQL migrations contain RLS-ready columns and policy notes.
- Add Postgres RLS smoke tests when a live Postgres instance is available, but
  keep them opt-in so local unit tests remain stable.
- Do not add SSO before these internal boundaries pass.

Acceptance:

- A single endpoint or report exposes RBAC/RLS readiness by domain.
- Negative tests cover cross-workspace read and mutation paths.
- Production gaps are explicitly labeled as readiness gaps, not claimed as done.

Suggested commits:

```text
feat(governance): report tenant isolation readiness
test(auth): guard enterprise runtime command scope
```

## C5.4 Memory And RAG Advisory Context Governance

Purpose:

Make MemoryAgent and RAG useful without letting old project state pollute the
current report scope.

Rules:

```text
ReportVersion scope = publishable facts for this report.
Memory = advisory preference or historical context.
RAG = retrievable evidence context with explicit citation and admission.
Project history = planning context, not automatic release scope.
```

Implementation direction:

- Add a typed `AdvisoryContext` contract with:
  - memory candidates used;
  - RAG retrieval records used;
  - historical evidence consulted;
  - whether each item entered report scope;
  - reason for inclusion or exclusion.
- Planner may use memory to choose dimensions and source preferences.
- Collector/research may use source preference memory to rank candidates.
- Writer may use user-preference memory only if it is visible in report metadata.
- ReleaseGate must evaluate ReportVersion scope, not advisory context.

Acceptance:

- A run can show which memory/RAG records influenced it.
- Advisory records do not create release blockers unless admitted into current
  report scope.
- Tests cover stale historical evidence, recalled memory, and current report
  scope staying separate.

Suggested commit:

```text
feat(memory): govern advisory context usage
```

## C5.5 EvalOps Release Contract

Purpose:

Turn EvalOps into a product release signal instead of a separate score page.

Implementation direction:

- Define an EvalOps release contract:
  - required metrics;
  - regression thresholds;
  - run cohort;
  - judge mode;
  - release decision;
  - quality finding mappings;
  - audit/replay correlation.
- Connect EvalOps findings into the existing Quality Finding Matrix.
- Make report publish optionally require the latest EvalOps gate for selected
  environments.
- Keep deterministic/heuristic EvalOps as the local baseline.
- Add model-backed judging only behind explicit configuration.

Acceptance:

- EvalOps can produce pass/warn/fail release status for a run cohort.
- Regression gate issues appear in the unified finding matrix.
- Publish flow can explain whether EvalOps is advisory or blocking.
- Tests cover both advisory and blocking modes.

Suggested commits:

```text
feat(evalops): define release gate contract
feat(quality): map evalops regressions into findings
```

## C5.6 Cost, Model, And Tool Policy Runtime

Purpose:

Make provider selection, tool use, cost, quotas, and compliance policy one
runtime decision surface.

Implementation direction:

- Keep ModelRouter in `backend/packages/governance/model_router.py`.
- Keep ToolRegistry in `backend/packages/governance/tool_registry.py`.
- Add a runtime policy decision object with:
  - selected model;
  - fallback model;
  - tool allow/deny result;
  - estimated cost;
  - quota pressure;
  - compliance constraints;
  - audit reason.
- Ensure LLM and tool calls emit the policy decision into trace and decision
  replay.
- Avoid scattering provider fallback rules inside agents.

Acceptance:

- `/api/runtime` or enterprise governance routes explain current model/tool
  policy.
- A model fallback is traceable to policy, not hidden exception handling.
- Quota blocking and monitor mode are visible before a run starts.
- Tests cover allowed, denied, fallback, and quota-pressure decisions.

Suggested commits:

```text
feat(governance): unify model tool and quota policy decisions
refactor(llm): trace model router decisions
```

## C5.7 Monitor Jobs And Scheduled Scans

Purpose:

Make recurring competitive intelligence monitoring a product workflow, not just
an available Temporal shell.

Implementation direction:

- Define monitor job records with:
  - workspace;
  - project;
  - competitors;
  - dimensions;
  - schedule;
  - last run;
  - next run;
  - alert policy;
  - release policy;
  - notification target.
- Temporal owns schedule and retry.
- Runtime command layer owns create/update/pause/resume monitor commands.
- LangGraph still only owns each individual agent run.
- EvalOps and ReleaseGate decide whether a monitor result is publishable or
  needs review.

Acceptance:

- A scheduled scan can create a run under the same runtime command, audit, and
  release policies as a manual run.
- Monitor job status is visible in enterprise projection.
- Failed monitor runs produce audit and telemetry events.
- Tests cover create, pause, resume, and triggered run scope.

Suggested commit:

```text
feat(monitors): productize scheduled intelligence scans
```

## Execution Order

Recommended order:

```text
1. C5.0 Runtime smoke gate
2. C5.1 Runtime command layer
3. C5.6 Cost/model/tool policy runtime
4. C5.3 Tenant governance boundary
5. C5.2 Artifact lifecycle
6. C5.4 Memory/RAG advisory context governance
7. C5.5 EvalOps release contract
8. C5.7 Monitor operations
```

Why this order:

- Runtime smoke prevents building on broken assumptions.
- Command layer gives every later enterprise action one doorway.
- Policy and tenant governance must be stable before more automation.
- Artifacts and advisory context then become durable and reviewable.
- EvalOps and monitors come after the lifecycle, policy, and scope boundaries
  are firm.

## Validation Strategy

Every C5 implementation step must include:

- Focused unit tests for the new contract.
- One boundary test that prevents bypassing the intended owner.
- Changelog entry in the relevant plan or report.
- A scoped commit with one clear purpose.

Checkpoint-level acceptance requires:

```text
ruff:
  backend/packages/runtime
  backend/packages/governance
  backend/packages/enterprise
  backend/packages/artifacts
  backend/packages/memory
  backend/packages/rag
  backend/packages/evals
  backend/packages/observability

pytest:
  runtime command tests
  governance/RBAC tests
  artifact lifecycle tests
  memory/RAG advisory scope tests
  EvalOps release gate tests
  monitor workflow tests
```

Runtime acceptance requires:

```text
1. Manual real run.
2. HITL-enabled review flow.
3. Report approval and publish flow.
4. Advisory memory/RAG trace inspection.
5. EvalOps release decision inspection.
6. Scheduled monitor dry run or fixture-backed smoke.
```

## Immediate Next Step

Start with C5.1. C5.0 is complete and recorded in:

```text
docs/reports/checkpoint4_runtime_smoke_report_20260607.md
```

Do not add new enterprise actions directly to routers or `RunService`; route
new review, redo, approval, publish, and monitor actions through the runtime
command layer.
