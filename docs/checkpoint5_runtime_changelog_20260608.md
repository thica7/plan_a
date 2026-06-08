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

Remaining C5.3 scope:

- Add an opt-in live Postgres RLS smoke test once a real Postgres test instance
  is configured.

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

Remaining C5.3 scope:

- Add an opt-in live Postgres RLS smoke test once a real Postgres test instance
  is configured.
