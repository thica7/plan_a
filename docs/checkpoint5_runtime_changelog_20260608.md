# Checkpoint 5 Runtime Changelog

Last updated: 2026-06-08

## 2026-06-08 - C5.1 Runtime Command Layer

Implemented the first Runtime Command Layer slice.

Changed:

- Added `backend/packages/runtime/commands.py` with typed command/result
  contracts for create run, report revision, and report publication.
- Added `backend/packages/runtime/service.py` to own create-run orchestration
  routing, report manual revision, report publication, RBAC checks, release gate
  enforcement, memory feedback capture, and audit/replay correlation IDs.
- Changed `/api/runs` so Temporal cutover and direct LangGraph run creation are
  delegated through `RuntimeCommandService`.
- Changed report manual revision and report publish endpoints so protected
  report lifecycle transitions are delegated through `RuntimeCommandService`.
- Changed `get_runtime_command_service` into a composed FastAPI dependency so
  tests and runtime overrides receive the active store, memory, workflow, and
  run service dependencies.
- Updated architecture boundary tests so routers are guarded as thin command
  adapters and runtime owns orchestration decisions.

Validation:

- `ruff check` passed for runtime, affected routers, deps, and focused tests.
- Focused pytest passed for architecture boundaries, Temporal create-run
  headers, model-policy blocking, report publish approval gating, and manual
  report revision audit/memory behavior.

Next C5.1 follow-up:

- Move HITL resume/redo and report approval request/approve/reject/archive into
  runtime commands.
- Add command-level events to Decision Replay/SSE once the remaining commands
  are centralized.

## 2026-06-08 - C5.1 HITL And Approval Commands

Implemented the second Runtime Command Layer slice.

Changed:

- Added typed commands for HITL resume, manual scoped redo, report approval
  request, report approval signal, and report rejection signal.
- Changed `/api/runs/{run_id}/resume` so HITL resume requests delegate to
  `RuntimeCommandService.resume_review`.
- Changed `/api/runs/{run_id}/redo` so manual scoped redo requests delegate to
  `RuntimeCommandService.request_redo`.
- Changed report approval workflow start/approve/reject endpoints so user
  approval actions are validated and routed through `RuntimeCommandService`.
- Added runtime command run events for HITL resume and manual redo requests.
- Added architecture boundary tests that prevent HITL and approval routers from
  directly owning command logic again.

Validation:

- `ruff check` passed for runtime, HITL/workflow routers, affected routers,
  deps, and focused tests.
- Focused pytest passed for runtime architecture boundaries, report approval
  workflow routing, and HITL manual redo guard behavior.

Remaining C5.1 scope:

- Archive has a command contract but no public route yet; do not add a route
  until the product has a real archive workflow.
- Decision Replay/SSE still need a dedicated command event view beyond the run
  event emitted by HITL commands.

## 2026-06-08 - C5.2 Artifact Lifecycle Vocabulary

Implemented the first Artifact And Source Material Lifecycle slice.

Changed:

- Added `backend/packages/artifacts/lifecycle.py` with one lifecycle vocabulary
  for captured/imported, stored, linked, governed, retained, and replayable
  source materials.
- Local artifact storage and external/S3/OSS pointer storage now add
  `artifact_lifecycle` metadata to every `ArtifactRecord`.
- Source snapshots now copy linked `evidence_id`, `raw_source_id`,
  `source_registry_id`, `report_version_id`, source policy status, and PII
  redaction status into lifecycle links.
- Web snapshots, survey imports, interview/manual transcript artifact types,
  and report exports share the same lifecycle metadata shape.

Validation:

- `ruff check` passed for artifact lifecycle, source snapshots, and focused
  tests.
- Focused pytest passed for local artifact storage, external/S3 pointers,
  source snapshot links, and redacted survey snapshot lifecycle metadata.

Remaining C5.2 scope:

- Completed in the follow-up slice: `/api/enterprise/artifacts/lifecycle`
  summarizes artifact lifecycle status per workspace/project/evidence/report
  version.
- Completed in the follow-up slice: Decision Replay artifact audit events now
  include lifecycle summaries.

## 2026-06-08 - C5.2 Lifecycle Report And Replay

Completed the Artifact And Source Material Lifecycle read/replay closure.

Changed:

- Added `ArtifactLifecycleItem` and `ArtifactLifecycleReport` contracts.
- Added `build_artifact_lifecycle_report` for artifact lifecycle summaries.
- Added `/api/enterprise/artifacts/lifecycle` with the same workspace/project/
  evidence/report-version scope checks as `/api/enterprise/artifacts`.
- Added lifecycle summaries to Decision Replay artifact audit events.

Validation:

- `ruff check` passed for artifact lifecycle, source snapshots, decision replay,
  enterprise router, and focused tests.
- Focused pytest passed for artifact storage, source snapshots, lifecycle route,
  and enterprise audit decision replay.

## 2026-06-08 - C5.3 Tenant Governance Readiness

Implemented the first Tenant Governance Boundary slice.

Changed:

- Added `backend/packages/governance/tenant_readiness.py`.
- Added `TenantGovernanceReadinessReport` with RBAC, workspace identity, audit
  filtering, artifact filtering, report publication policy, and Postgres RLS
  migration checks.
- Added `/api/enterprise/governance/tenant-readiness`.
- Reused the existing Phase 5 Postgres tenant isolation guardrail in
  `backend/db/postgres/001_enterprise_core.sql` as readiness evidence.

Validation:

- `ruff check` passed for governance, enterprise router, and focused tests.
- Focused pytest passed for tenant readiness report and enterprise route
  coverage.

## 2026-06-08 - C5.3 Runtime Command Isolation Tests

Closed the local negative-isolation coverage for the new command layer.

Changed:

- Extended the enterprise RBAC/workspace-scope test to cover the Checkpoint 5
  runtime command routes:
  - tenant readiness report access,
  - manual report revision,
  - report publish,
  - report approval start,
  - report approval signal.
- Kept the existing artifact, audit, evidence, source registry, project, report,
  and memory negative checks in the same test so tenant isolation remains one
  coherent contract instead of scattered route-specific assertions.

Validation:

- `ruff check backend/tests/unit/test_enterprise_store.py`
- `pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_enforces_rbac_workspace_scope`

## 2026-06-08 - C5.3 Opt-In Postgres RLS Smoke

Closed the Postgres RLS verification hook for C5.3.

Changed:

- Added `backend/tests/integration/test_postgres_rls_smoke.py`.
- The test is disabled by default and only runs when
  `ENTERPRISE_RLS_SMOKE_DATABASE_URL` points to a real Postgres test database.
- The smoke test runs inside a rollback-only transaction, temporarily forces RLS
  on workspace-scoped tables, inserts two test workspaces, and checks that
  workspace-scoped visibility is enforced for:
  - workspaces,
  - projects,
  - artifacts,
  - report versions,
  - audit logs.

Validation:

- `ruff check backend/tests/integration/test_postgres_rls_smoke.py`
- `pytest backend/tests/integration/test_postgres_rls_smoke.py` skipped as
  expected without `ENTERPRISE_RLS_SMOKE_DATABASE_URL`.

## 2026-06-08 - C5.4 Advisory Context Governance

Completed the first Memory/RAG advisory governance contract.

Changed:

- Added `backend/packages/enterprise/advisory_context.py`.
- Added `AdvisoryContextReport` and `AdvisoryContextItem` so report versions can
  explain memory, RAG retrieval, and project-history context through one typed
  contract.
- ReportVersion projection now writes `quality_metadata.advisory_context` with:
  - report-scope evidence IDs,
  - report-scope claim IDs,
  - MemoryAgent candidate IDs,
  - explicit memory/RAG/project-history policy labels.
- Added `/api/enterprise/report-versions/{version_id}/advisory-context`.
- Added cross-workspace negative coverage for the new advisory context route.

Validation:

- `ruff check` passed for advisory context, projection, enterprise router, and
  focused tests.
- Focused pytest passed for advisory context scope separation, projection
  metadata, and enterprise RBAC/workspace route isolation.

## 2026-06-08 - C5.5 EvalOps Release Contract

Completed the EvalOps release contract slice.

Changed:

- Added `EvalOpsReleaseContract` and `EvalOpsReleaseMetricRequirement`.
- Added `backend/packages/evals/release_contract.py`.
- Added `/api/evals/enterprise/release-contract`.
- Added `EVALOPS_RELEASE_MODE=advisory|blocking` and `EVALOPS_RELEASE_LIMIT`.
- Report publish now records the EvalOps release contract in publication
  metadata, command metadata, and audit metadata.
- In `blocking` mode, publish returns a 409 when the EvalOps release contract is
  not allowed.
- Enterprise Quality Matrix now has an `EvalOps` entry backed by
  `quality_findings_from_evalops`, so regression gate issues enter the same
  QualityFinding surface as BusinessQA, EvidenceGap, RedTeam, ClaimValidator,
  BenchmarkAgent, ReleaseGate, and MemoryAgent.

Validation:

- `ruff check` passed for schema, evals, evals router, enterprise router,
  runtime service, and focused tests.
- Focused pytest passed for release-contract route output, advisory vs blocking
  behavior, publish metadata, and enterprise quality matrix integration.

## 2026-06-08 - C5.6 Runtime Policy Decision

Completed the unified model/tool/quota/cost policy decision surface.

Changed:

- Added `backend/packages/governance/runtime_policy.py`.
- Added `RuntimePolicyDecision` and `RuntimeToolPolicyDecision`.
- Added `/api/enterprise/governance/runtime-policy`.
- The decision now explains, through one typed contract:
  - selected provider/model,
  - fallback provider/model,
  - model policy status,
  - tool allow/guard/deny results,
  - estimated cost,
  - workspace quota pressure,
  - compliance constraints,
  - audit reason.
- Runtime create-run commands now attach the same policy decision to command
  metadata.
- `/api/runs` creation responses expose `X-Runtime-Policy-Status` and
  `X-Runtime-Policy-Reason` headers so pre-run blocking and fallback reasons are
  visible at the API boundary.

Validation:

- `ruff check` passed for governance runtime policy, enterprise router, runs
  router, runtime command service, and focused tests.
- Focused pytest passed for allowed, denied, fallback, quota-pressure, and
  enterprise route decisions.

## 2026-06-08 - C5.7 Monitor Job Command Boundary

Implemented the first monitor operations product boundary.

Changed:

- Added `MonitorJobRecord`, `MonitorJobCreateRequest`, and
  `MonitorJobUpdateRequest`.
- Added in-memory enterprise store support for:
  - listing monitor jobs,
  - getting a monitor job,
  - upserting monitor jobs,
  - updating monitor jobs,
  - recording monitor run outcomes.
- Added runtime commands for:
  - create monitor job,
  - update monitor job,
  - pause monitor job,
  - resume monitor job,
  - trigger monitor job.
- Added enterprise routes for monitor job list/create/update/pause/resume/trigger.
- Monitor trigger now starts the existing Temporal `MonitorWorkflow` through the
  runtime command layer and records workflow/running status on the monitor job.
- Monitor cycle activities now write completed/interrupted/failed run and report
  outcomes back to the monitor job record.

Validation:

- `ruff check` passed for schema, enterprise store, runtime commands, runtime
  service, enterprise router, workflow activities, and monitor job tests.
- Focused pytest passed for monitor job lifecycle commands, paused-trigger
  blocking, Temporal trigger request shape, audit events, and run outcome
  recording.

## 2026-06-08 - C5.7 Monitor Job Postgres Persistence

Completed the durable store slice for monitor jobs.

Changed:

- Added `monitor_jobs` to `backend/db/postgres/001_enterprise_core.sql`.
- Added workspace/project indexes for monitor job lookup.
- Added workspace RLS policy for `monitor_jobs`.
- Added Postgres-backed `EnterpriseStore` methods for:
  - listing monitor jobs,
  - getting a monitor job,
  - upserting monitor jobs,
  - updating monitor jobs,
  - recording monitor run outcomes.
- Updated strict Postgres schema tests so monitor jobs are part of the expected
  enterprise table set and tenant isolation surface.

Validation:

- `ruff check` passed for Postgres store, enterprise store, schema, runtime
  service, workflow activities, and monitor job tests.
- Focused pytest passed for strict Postgres schema checks and monitor job
  command tests.

## 2026-06-08 - C5.7 Scheduled Scan Runtime Command

Closed the scheduled scan API boundary so enterprise-triggered scans use the
same runtime command surface as manual runs and monitor triggers.

Changed:

- Added `StartScheduledScanCommand`.
- Added `RuntimeCommandService.start_scheduled_scan`.
- Added `/api/enterprise/scheduled-scans/trigger`.
- Scheduled scan triggers now include runtime policy metadata, project scope,
  and dimension scope in command metadata.
- The legacy `/api/workflows/scheduled-scan` route remains available as a
  low-level workflow/debug entry point.

Validation:

- `ruff check` passed for runtime commands, runtime service, enterprise router,
  and monitor job tests.
- Focused pytest passed for scheduled scan command routing, policy metadata, and
  project/dimension scope preservation.

## 2026-06-08 - Checkpoint 5 Runtime Closure

Checkpoint 5 implementation status is now complete across C5.0-C5.7.

Validated closure scope:

- C5.6 runtime policy decision:
  - allowed decisions,
  - denied tool decisions,
  - model fallback decisions,
  - quota-pressure decisions,
  - enterprise route response.
- C5.7 monitor operations:
  - monitor job create/update/pause/resume/trigger,
  - Temporal monitor trigger shape,
  - scheduled scan runtime command trigger,
  - Postgres monitor job table/index/RLS contract,
  - monitor cycle run outcome recording.

Validation:

- `ruff check backend/packages/governance/runtime_policy.py
  backend/packages/governance/__init__.py backend/app/routers/enterprise.py
  backend/app/routers/runs.py backend/packages/runtime
  backend/packages/enterprise/store.py backend/packages/enterprise/postgres.py
  backend/packages/workflows/activities.py backend/tests/unit/test_runtime_policy.py
  backend/tests/unit/test_monitor_jobs.py
  backend/tests/unit/test_enterprise_postgres_schema.py`
- `pytest backend/tests/unit/test_runtime_policy.py
  backend/tests/unit/test_monitor_jobs.py
  backend/tests/unit/test_enterprise_postgres_schema.py
  backend/tests/unit/test_workflow_service.py::test_workflow_router_exposes_scheduled_scan_start
  backend/tests/unit/test_workflow_service.py::test_workflow_router_exposes_monitor_start
  backend/tests/unit/test_h10_governance.py::test_h10_enterprise_routes_are_callable`
- Result: 22 focused tests passed.
