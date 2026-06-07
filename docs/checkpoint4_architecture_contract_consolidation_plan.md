# Checkpoint 4 Architecture Contract Consolidation Plan

Last updated: 2026-06-07

## Relationship To Master Plan

Checkpoint 4 is the architecture consolidation checkpoint after Checkpoint 3.
It does not replace `dev_plan_final`. It tightens the contracts that make the
existing enterprise architecture clean enough to keep extending.

Authoritative inputs:

- `docs/enterprise_execution_master_plan.md`
- `docs/checkpoint3_execution_plan.md`
- `dev_plan_final/dev_plan_final/01_EXECUTION_ROADMAP_5_PHASES.md`
- `dev_plan_final/dev_plan_final/10_HIGH_SCORE_FUSION_BACKLOG.md`
- `D:/codex_workspace/websearch_v2/clean_research_pipeline_rewrite_plan.md`
- `docs/research_pipeline_refactor_changelog_20260606.md`

## Position

The project is already in Phase 5 enterprise productization. Checkpoint 1,
Checkpoint 2, and Checkpoint 3 core are complete. The next risk is not that the
system lacks modules; the risk is that identity, scope, quality, HITL, and
observability contracts drift across modules as more enterprise features are
added.

Checkpoint 4 therefore focuses on architecture contracts, not one-off report
quality fixes.

## Goal

Make the main architecture boundaries explicit, testable, and boring:

```text
Temporal            owns long-running business lifecycle
LangGraph           owns agent DAG reasoning and scoped redo
Research Pipeline   owns data discovery, capture, extraction, admission,
                    evaluation, and repair tasks
Enterprise Store    owns workspace/project/run/evidence/claim/report/artifact
                    records and publication state
Identity Resolver   owns cross-layer IDs, aliases, citation resolution, and
                    scope reconciliation
Observability       owns trace, decision events, cost, quality, and audit replay
HITL                owns review checkpoints, manual corrections, approval,
                    resume, and audit transitions
```

## Non-Goals

Checkpoint 4 is not:

- A broad UI redesign.
- A new collector rewrite.
- A replacement for LangGraph.
- A forced move to fine-grained Temporal activities.
- A defense/PPT/video task.
- A production SSO/RLS/Langfuse deployment task.
- A run-specific patch for a single bad claim.

Run quality defects discovered during validation can create follow-up tasks,
but they should not blur the architecture scope.

## Architecture Problems To Close

### 1. Identity Drift

Several IDs are valid but serve different purposes:

- `RawSource.id`: raw collected source lineage and report citation token.
- `EvidenceRecord.id`: enterprise evidence dedupe/governance record.
- `ClaimRecord.id`: structured assertion.
- `ReportVersionRecord.id`: publishable report snapshot.
- `ArtifactRecord.id`: stored blob or external pointer.
- `TraceSpan.id`: execution trace.
- Decision event ID or stable event key: audit/replay signal.

The project already has many of these records, but future work must not let
each module invent its own resolver behavior.

### 2. Scope Drift

A new run must use its current plan and report-version scope for release
readiness. Historical memory and project evidence can inform planning, source
preference, and gap fill, but they must not silently pollute the current
report's release gate.

### 3. Quality Signal Drift

Runtime QA, BusinessQA, RedTeam, EvidenceGap, ClaimValidator, ReleaseGate, and
EvalOps all produce related findings. They should stay semantically distinct,
but all must be convertible into one reviewable quality-finding surface and,
where applicable, into typed repair or redo requests.

### 4. HITL Is Mechanism-Complete But Not Yet Architecture-Complete

Planner review, QA review, manual report revision, and approval exist, but the
architecture should treat HITL as a first-class lifecycle boundary:

```text
review request -> decision -> resume/redo/revision -> audit -> memory feedback
-> decision replay
```

### 5. Observability Is Local-Strong But Deployment-Optional

Local trace, metrics, and decision replay exist. Langfuse and hosted OTel are
adapters, not currently a live dashboard in the local runtime. The contract
should make that explicit so the system can run cleanly with or without hosted
observability.

## Workstreams

### C4.1 Identity And Resolver Contract

Purpose:

Define and enforce a single cross-layer identity contract.

Implementation direction:

- Add or consolidate an identity contract under `backend/packages/identity/`.
- Document canonical owner, allowed aliases, and public display form for each
  entity type.
- Make report citations canonical to `RawSource.id`.
- Make enterprise storage scope canonical to `EvidenceRecord.id`.
- Keep alias resolution deterministic through one resolver boundary.
- Remove scattered frontend/backend source-token fallback logic once covered by
  the resolver.

Acceptance:

- A report source token resolves through the same backend contract used by
  ReportView, release gate, evidence center, and source snapshots.
- `RawSource.id`, `EvidenceRecord.id`, and aliases are not rewritten ad hoc.
- Tests prove:
  - report citations resolve to scoped evidence;
  - missing citations are detected;
  - enterprise evidence IDs remain storage IDs;
  - RawSource IDs remain report citation IDs;
  - artifact/source snapshot links preserve both identities.

Suggested commit:

```text
refactor(identity): consolidate source and evidence resolution
```

### C4.2 Report Scope And Enterprise Read Model Contract

Purpose:

Make the difference between current-run scope, project memory, and enterprise
history explicit.

Implementation direction:

- Treat `ReportVersionRecord` as the publishable scope snapshot.
- Keep `ReportVersionRecord.evidence_ids` and `claim_ids` as the release-gate
  scope.
- Keep project-level evidence and memory as advisory context, not automatic
  release scope.
- Create a small report-scope service if the current logic is scattered.
- Add explicit metadata that says which historical records were used as memory
  or advisory context.

Acceptance:

- Release gate evaluates the report-version scope, not every historical
  competitor attached to the project.
- Memory/history can be shown as context but cannot silently create blockers
  for a run that did not select those competitors.
- Tests cover stale project competitors and historical evidence contamination.

Suggested commit:

```text
refactor(reports): formalize report version scope
```

### C4.3 Research Pipeline Boundary Hardening

Purpose:

Keep Clean Research Pipeline as the data architecture layer, not collector
patchwork.

Implementation direction:

- Ensure collector calls the research pipeline as an adapter.
- Keep these stage boundaries:
  - Discovery outputs `SourceCandidate`.
  - Capture outputs `CapturedPage`.
  - Extraction outputs `ExtractionResult`.
  - Admission outputs `EvidenceItem`.
  - Evaluation outputs `QualityGap`.
  - Repair outputs `RepairTask`.
- Make release-gate issues convertible to `QualityGap`.
- Make `QualityGap -> RepairTask -> RedoScope` the only bridge into scoped
  redo.
- Keep field-level admission rules in research/evidence, not in writer or UI.

Acceptance:

- No new discovery/fetch/extraction/admission logic is added inside collector
  when a research stage already owns it.
- Tests prove quality gaps can drive repair without parsing natural-language
  warnings.
- A bad source quote can be rejected at admission without report-writer logic.

Suggested commit:

```text
refactor(research): enforce pipeline boundary contracts
```

### C4.4 Quality Finding Matrix Contract

Purpose:

Unify how quality findings are reviewed without collapsing all agents into one
schema.

Implementation direction:

- Keep native schemas for QA, RedTeam, EvidenceGap, ClaimValidator,
  ReleaseGate, and EvalOps.
- Add or tighten adapter functions that map each finding to a reviewable
  `QualityFinding` product surface.
- Ensure each finding can declare:
  - source agent;
  - severity;
  - competitor;
  - dimension;
  - field;
  - affected claim/source/report section;
  - repairability;
  - suggested RedoScope, if applicable.

Acceptance:

- Frontend quality matrix can show all major finding types through one product
  surface.
- ReleaseGate passing with warnings is explainable by the same matrix.
- RedTeam/EvidenceGap/ReleaseGate disagreement is visible instead of hidden.

Suggested commit:

```text
refactor(quality): normalize review finding adapters
```

### C4.5 HITL Lifecycle Contract

Purpose:

Make human intervention an architecture capability, not only UI modals.

Implementation direction:

- Define HITL lifecycle states:
  - requested;
  - accepted;
  - modified;
  - rejected;
  - timed_out;
  - resumed;
  - redo_requested;
  - revision_created;
  - approved;
  - published.
- Ensure PlanReview, QAReview, ManualCorrection, ReportApproval, and RedoScope
  use audit and decision replay consistently.
- Ensure memory feedback is written only when a human decision actually carries
  durable preference or correction value.

Acceptance:

- A `HITL_ENABLED=true` run can show planner review and QA review lifecycle
  events.
- Manual report revision creates a new draft, not an in-place mutation.
- Decision replay shows the human decision, resulting action, and audit link.

Suggested commit:

```text
feat(hitl): standardize review lifecycle events
```

### C4.6 Temporal, LangGraph, And Enterprise Store Boundary

Purpose:

Prevent orchestration responsibilities from blending together.

Detailed contract:

- `docs/orchestration_ownership_contract_20260607.md`

Implementation direction:

- Temporal owns workflow lifecycle:
  - create run;
  - start/await LangGraph execution;
  - approval workflow;
  - retry policy;
  - monitor schedule;
  - notification hooks.
- LangGraph owns agent reasoning:
  - planner;
  - collector dispatch;
  - analyst;
  - comparator;
  - reflector;
  - writer;
  - QA;
  - scoped redo.
- Enterprise Store owns durable state:
  - report versions;
  - evidence records;
  - claims;
  - artifacts;
  - audit logs;
  - memory.
- The run service is allowed to coordinate, but not to become the hidden owner
  of all business rules.

Acceptance:

- `RUN_ORCHESTRATION_BACKEND=temporal` still starts real runs through Temporal.
- LangGraph remains the inner agent DAG.
- Approval/report publication is not handled by LangGraph.
- Research pipeline is not responsible for report publication state.

Suggested commit:

```text
docs(architecture): define orchestration ownership boundaries
```

### C4.7 Observability And Governance Contract

Purpose:

Make observability stable with or without hosted Langfuse.

Detailed contract:

- `docs/observability_governance_contract_20260607.md`

Implementation direction:

- Define one telemetry contract for:
  - trace span;
  - tool call;
  - model call;
  - token/cost;
  - quality metric;
  - decision event;
  - audit event;
  - compliance/redaction event.
- Keep local trace and decision replay as the baseline.
- Keep Langfuse as a mirror adapter that is enabled only when configured.
- Expose runtime status clearly:
  - local tracing enabled;
  - Langfuse configured or not configured;
  - OTel export configured or not configured.

Acceptance:

- `/api/metrics` or runtime config explains Langfuse disabled/enabled state.
- A real run can be reviewed through local trace and decision replay even when
  Langfuse is not configured.
- Hosted observability work can proceed later without changing agent code.

Suggested commit:

```text
refactor(observability): formalize telemetry export contract
```

## Execution Order

Do not implement all workstreams in one commit. Use small architecture commits:

1. `docs(plan): add checkpoint 4 architecture plan`
2. `refactor(identity): consolidate source and evidence resolution`
3. `refactor(reports): formalize report version scope`
4. `refactor(research): enforce pipeline boundary contracts`
5. `refactor(quality): normalize review finding adapters`
6. `feat(hitl): standardize review lifecycle events`
7. `refactor(observability): formalize telemetry export contract`
8. `docs(architecture): record final checkpoint 4 contract map`

After each commit:

- Update `docs/research_pipeline_refactor_changelog_20260606.md` or a new
  checkpoint-specific changelog.
- Run targeted ruff and pytest.
- Do not stage unrelated dirty files.

## Validation Plan

Minimum validation for Checkpoint 4:

```text
ruff:
  backend/packages/identity
  backend/packages/sources
  backend/packages/research
  backend/packages/enterprise
  backend/packages/orchestrator
  backend/packages/observability

pytest:
  test_source_reconciliation.py
  test_enterprise_projection.py
  test_research_pipeline.py
  test_enterprise_store.py
  test_temporal_workflows.py
  test_trace_observability.py
  test_artifacts.py
```

Real-run validation:

```text
1. Start full stack with RUN_ORCHESTRATION_BACKEND=temporal.
2. Run one real analysis with HITL disabled to verify automated path.
3. Run one real analysis with HITL_ENABLED=true to verify review lifecycle.
4. Confirm:
   - Temporal workflow completed;
   - report source tokens resolve;
   - release gate evaluates report-version scope;
   - quality matrix explains warnings;
   - decision replay includes research, QA, HITL, approval, and publish events;
   - local trace works when Langfuse is not configured.
```

## Definition Of Done

Checkpoint 4 is complete only when:

- There is one documented identity/resolver contract.
- Report citations, evidence records, artifacts, source snapshots, and release
  gate use the same resolver boundary.
- Current run scope, project memory, and enterprise history are explicitly
  separated.
- Research Pipeline remains the only owner of data discovery/capture/extraction
  stage contracts.
- Quality findings from all major quality agents appear in one review surface.
- HITL decisions are visible in audit and decision replay.
- Temporal/LangGraph/Research Pipeline/Enterprise Store ownership is documented
  and tested.
- Local observability is sufficient without Langfuse, while Langfuse remains a
  clean optional adapter.

## Expected Outcome

After Checkpoint 4, future work should feel simpler:

- Adding a new source type should touch research/capture or artifact storage,
  not writer, release gate, and UI separately.
- Adding a new quality agent should add an adapter to the quality matrix, not a
  new parallel review system.
- Adding production Langfuse/OTel should configure exporters, not change agent
  logic.
- Adding SSO/RLS should harden enterprise boundaries, not redefine workspace
  scope.
- Fixing a bad claim should happen through extraction/admission/quality
  contracts, not report text patching.
