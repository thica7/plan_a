# Checkpoint 3 Execution Plan

Last updated: 2026-06-07

## Relationship To Master Plan

This file is the tactical execution plan for Checkpoint 3 only. The complete
route lives in `docs/enterprise_execution_master_plan.md`.

Checkpoint 1 closed report quality. Checkpoint 2 closed the high-score backlog
core and was accepted by:

- `docs/reports/checkpoint2_real_run_acceptance_20260607.md`

Checkpoint 3 now moves `plan_a` from a strong prototype toward an enterprise
business product.

## Read-First Protocol

Before every Checkpoint 3 implementation turn, read this file and the following
authoritative plan files:

- `docs/enterprise_execution_master_plan.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/research_pipeline_refactor_changelog_20260606.md`

Do not rely on conversation memory alone. The current worktree and these files
are authoritative.

## Scope

Checkpoint 3 is enterprise product hardening. It makes the system behave like a
controlled enterprise workflow rather than a single-run demo.

Target outcome:

- Reports move through draft -> in_review -> approved/rejected -> published.
- Publishing is gated by approval, ReleaseGate, audit, and workspace policy.
- Human corrections produce draft ReportVersion revisions, memory signals, and
  audit records.
- Artifacts such as webpage snapshots, PDFs, screenshots, exports, and imported
  interview materials have stable records and evidence/report linkage.
- Workspace isolation and RBAC are enforceable through tests.
- Observability presents trace, prompt/output, token/cost, quality, compliance,
  and regression signals as product review surfaces.

Checkpoint 3 is not:

- A broad collector rewrite.
- A new LLM reasoning framework.
- A defense/PPT/video task.
- Full SSO/SAML/OIDC before the internal approval and isolation loop is solid.

## Current Baseline

Final Checkpoint 2 run:

- Run ID: `run-7b96eddb0b1a7613a9d5074bb5443fb6`
- Terminal status: `completed`
- Quality verdict: `pass`
- Regression gate: `pass`
- Target score: 95
- Baseline score: 76
- Citation validity rate: 1.0
- Verified source rate: 1.0
- Real source rate: 1.0
- QA blocker count: 0
- Warning count: 13 versus baseline 18

Existing enterprise product surface:

- `ReportVersionRecord.status` already supports draft, in_review, approved,
  rejected, published, and archived.
- Temporal `ReportApprovalWorkflow` exists as a shell.
- Manual report revision exists and creates draft versions.
- ReleaseGate exists and blocks weak reports.
- AuditLog exists and already records many enterprise actions.
- ArtifactStore exists for local/external artifacts and report exports.
- RBAC exists as application-layer role policy, but production isolation is not
  yet complete.

Closed in Checkpoint 3 step 2:

- Plain report upsert can no longer move a report into review, approval,
  rejection, or published states.
- Approval metadata is attached to report versions by the approval activity.
- Publishing records publication metadata, ReleaseGate snapshot, and audit trail.

Remaining strict gaps:

- ArtifactStore exists, but source snapshots and imported research materials
  are not yet uniformly promoted into artifact records.
- RBAC is application-level only; database RLS and cross-workspace negative
  tests need hardening.
- Manual report correction exists, but the rejection/approval-to-draft revision
  loop needs stronger tests and product-facing review evidence.
- Observability exists, but approval, publish, manual revision, artifact, and
  regression signals need to be easier to inspect as one product review surface.

## Implementation Order

### 1. `docs(plan): start checkpoint 3 execution plan`

Status: completed by `bd132e8`.

Required behavior:

- Create this file.
- Update the master plan so the active checkpoint is Checkpoint 3.
- Preserve Checkpoint 1 and Checkpoint 2 acceptance references.

Acceptance:

- `docs/checkpoint3_execution_plan.md` exists.
- `docs/enterprise_execution_master_plan.md` points to Checkpoint 3 as active.
- No unrelated dirty files are staged.

### 2. `feat(reports): enforce approval-gated publishing`

Status: completed in the current implementation step.

Backlog: Phase 5A enterprise governance.

Required behavior:

- Plain report upsert cannot directly move a report to `approved` or
  `published`.
- Approval workflow or approval activity is the allowed path to `approved`.
- Publishing requires current status `approved` or `published`.
- Publishing requires ReleaseGate `allowed=true`.
- Approval and publish transitions update report quality metadata with actor,
  note, timestamp, decision, and gate snapshot.
- Approval and publish transitions create audit records.

Acceptance:

- Draft publish returns 409 with `report_approval_required`.
- Direct upsert to `approved` returns 409 with `report_approval_workflow_required`.
- Approval activity can move an in-review report to `approved` only if
  ReleaseGate passes.
- Publish moves an approved report to `published` and records audit metadata.
- Tests prove the bypass is blocked.

Validation:

- `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/enterprise/report_lifecycle.py backend/packages/enterprise/store.py backend/packages/enterprise/postgres.py backend/packages/workflows/activities.py backend/packages/workflows/report_approval.py backend/app/routers/enterprise.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_temporal_workflows.py`
- `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_exposes_projection backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_report_approval_status_when_gate_fails backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_direct_publish_status_without_approval backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_update_report_version_status backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_use_report_scope_not_stale_project_competitors backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_block_weak_report_version backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_can_reject_report_version -q`

### 3. `feat(reports): expose human correction review loop`

Backlog: HITL enterprise product loop.

Required behavior:

- Manual report revision keeps parent version, draft status, editor, note, and
  created_at metadata.
- Manual correction emits memory feedback and an audit log.
- Manual correction can be used after rejection or approval without overwriting
  the previous version.
- Report diff shows the correction delta.

Acceptance:

- A rejected or draft report can be manually revised into a new draft.
- The new version is not publishable until approval.
- Audit log shows who edited it and why.
- Memory feedback stores correction context.

### 4. `feat(artifacts): promote source snapshots and research materials`

Backlog: ArtifactStore / SourceSnapshot / compliance.

Required behavior:

- Webpage snapshots, PDFs, screenshots, report exports, survey responses,
  interview records, and manual transcripts use one artifact record contract.
- Artifact records link to workspace, project, run, evidence, report version,
  source URL, hash, media type, retention policy, and compliance metadata.
- Report export is already present; extend the same boundary to source and
  user-research artifacts.

Acceptance:

- At least one webpage snapshot artifact can be linked to evidence.
- At least one imported interview/manual transcript can be linked to both
  evidence and artifact metadata.
- Artifact lookup is workspace-scoped.
- Compliance report can identify artifact retention and source policy state.

### 5. `feat(security): harden workspace isolation and RBAC`

Backlog: Phase 5A enterprise governance.

Required behavior:

- Add negative tests for cross-workspace project, report, evidence, artifact,
  memory, audit, and source registry access.
- Keep application-layer policy as the current implementation boundary.
- Document the future DB RLS migration rather than pretending it is already
  done.

Acceptance:

- Reviewer/analyst/viewer role boundaries are enforced by tests.
- A user from workspace A cannot read or mutate workspace B resources through
  API routes.
- Audit reads are workspace-scoped.

### 6. `feat(observability): productize review and regression signals`

Backlog: OTel/Langfuse/dashboard/regression gate productization.

Required behavior:

- Decision replay surfaces approval, publish, manual revision, artifact, gate,
  and quality events.
- Trace/replay shows prompt/output/token/cost where available.
- EvalOps/regression gate output is visible as a product review signal.
- Compliance/redaction events are included in audit-grade review.

Acceptance:

- A product reviewer can inspect why a report was blocked or published.
- Approval/publish/manual-revision events can be traced to audit and report
  version metadata.
- Regression gate result is available beside the report version.

## Work Discipline

- Keep commits small and named after the checkpoint item where possible.
- Update this plan when status changes.
- Update `docs/research_pipeline_refactor_changelog_20260606.md` after each
  completed implementation step.
- Do not stage unrelated dirty files.
- Run ruff and targeted tests before each implementation commit.
- Do not touch existing frontend/review dirty files unless the current task
  explicitly owns them.
