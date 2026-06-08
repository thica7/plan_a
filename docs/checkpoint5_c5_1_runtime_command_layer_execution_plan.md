# Checkpoint 5 C5.1 Runtime Command Layer Execution Plan

Last updated: 2026-06-08

## Purpose

C5.1 creates one command boundary for enterprise operator actions. The goal is
to stop approval, publication, manual correction, redo, review, and run creation
from being implemented as scattered router logic.

This document implements the next step from:

- `docs/checkpoint5_enterprise_runtime_plan.md`
- `docs/enterprise_execution_master_plan.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- CC推进推荐, mapped into Checkpoint 5 on 2026-06-08

## Scope

Runtime Command Layer owns:

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

The first implementation pass focuses on the commands that currently have
production-impacting router logic:

```text
create_run
revise_report
publish_report
```

The second implementation pass will add the remaining review, HITL, redo,
approval, rejection, and archive commands.

## New Modules

```text
backend/packages/runtime/
  __init__.py
  commands.py
  service.py
```

`commands.py` defines typed command and result contracts.

`service.py` coordinates:

- RBAC and workspace scope checks;
- Temporal vs direct route selection for run creation;
- ReleaseGate checks for publication;
- manual revision lifecycle events;
- audit/replay correlation keys;
- future HITL and approval command hooks.

## Router Boundary

Routers should become thin:

```text
FastAPI request
  -> build command
  -> RuntimeCommandService.execute(...)
  -> unwrap typed result
  -> HTTP response
```

Routers should not:

- create publication lifecycle metadata directly;
- create manual revision lifecycle metadata directly;
- decide Temporal cutover directly once the command service owns create_run;
- bypass approval or release gate by calling `store.upsert_report_version`
  for protected state transitions.

## Result Contract

Every command result must include:

```text
command_id
command_type
status
resource_type
resource_id
workspace_id
project_id
run_id
report_version_id
audit_correlation_id
replay_correlation_id
route
payload
```

The returned business payload can still be the existing DTO, but the command
metadata must be generated in one place.

## Initial Acceptance

The first implementation pass is accepted when:

- `/api/runs` delegates create-run policy and Temporal/direct selection through
  `RuntimeCommandService`.
- `/api/enterprise/report-versions/{id}/manual-revision` delegates manual draft
  creation through `RuntimeCommandService`.
- `/api/enterprise/report-versions/{id}/publish` delegates publication through
  `RuntimeCommandService`.
- focused tests prove:
  - create-run command returns route metadata;
  - manual revision command creates a draft and audit correlation;
  - publish command blocks non-approved reports;
  - publish command records release-gate/audit correlation.

## Follow-up Acceptance

The second implementation pass is accepted when:

- HITL planner/QA resume and redo requests use runtime commands.
- approval request/approve/reject use runtime commands.
- archive uses runtime commands.
- Decision Replay can show command-level events for review, redo, revision,
  approval, publication, and monitor actions.

## Commit Plan

```text
docs(runtime): map cc recommendations into checkpoint 5
feat(runtime): add enterprise command layer
refactor(api): route run and report actions through runtime commands
test(runtime): guard command-layer publication and revision paths
```

