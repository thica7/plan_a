# Checkpoint 4 Architecture Changelog

## 2026-06-07 - Step 1: Identity Resolver And Report Scope Contract

Scope:

- Promoted source/evidence citation resolution into
  `backend/packages/identity/source_resolver.py`.
- Kept `backend/packages/sources/references.py` as a compatibility export layer
  so existing imports continue to work while identity becomes the canonical
  owner.
- Exported source resolver symbols from `packages.identity`.
- Preserved the canonical identity split:
  - reports cite `RawSource.id`;
  - enterprise report scope stores `EvidenceRecord.id`;
  - aliases resolve through one deterministic resolver boundary.
- Added source identity metadata to source-snapshot artifacts:
  `evidence_id`, `raw_source_id`, and accepted `source_tokens`.
- Added `ReportScope` and `build_report_scope()` so release decisions have a
  testable scope object rather than only a tuple of records.
- Added report-scope metadata explaining:
  - report-version-only release policy;
  - project history and memory as advisory context;
  - scoped competitors/evidence/claims;
  - excluded historical project competitors.
- Added report-scope metadata to ReleaseGate quality metadata when the run
  service attaches gate results.

Why:

- Checkpoint 4 is about preventing architecture drift, especially around source
  identity and project history.
- Source tokens, evidence records, artifacts, and release gates now point back
  to the same identity contract.
- ReleaseGate scope can now explain why stale project competitors or old
  evidence do not silently block the current report version.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/identity backend/packages/sources backend/packages/enterprise/source_snapshots.py backend/packages/enterprise/report_scope.py backend/packages/orchestrator/service.py backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_h10_governance.py backend/tests/unit/test_enterprise_store.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_h10_governance.py::test_source_snapshot_assets_external_s3_pointer_and_source_registry backend/tests/unit/test_h10_governance.py::test_manual_survey_snapshot_creates_research_evidence backend/tests/unit/test_enterprise_store.py::test_report_release_gate_scope_uses_version_competitors_not_stale_project_links -q`

## 2026-06-07 - Step 2: ReAct Collector Uses Research Pipeline Admission

Scope:

- Changed collector ReAct `finish` output from direct `RawSource` creation into
  `SourceCandidate` proposals.
- Routed ReAct-proposed URLs through Clean Research Pipeline capture,
  extraction, field-level admission, and RawSource assembly before they can
  enter `detail.raw_sources`.
- Applied the same boundary to the branch-level LLM fallback path: LLM output
  proposes seed candidates, and the research pipeline decides whether accepted
  evidence exists.
- Added explicit `ResearchBrief.include_trusted_sources` and
  `include_homepage_candidates` flags so seed-only admission really avoids
  registry/homepage discovery instead of relying on metadata.
- Removed the legacy `extract_facts` direct-admission trace from the ReAct
  finish path.
- Deduplicated evidence quote snippets so accepted field quotes do not produce
  repeated RawSource snippets when multiple fields cite the same sentence.

Why:

- ReAct can remain a model-driven candidate proposer, but Checkpoint 4 requires
  source discovery/capture/extraction/admission to stay inside the research
  pipeline boundary.
- This prevents a second collector-specific evidence admission path from
  drifting away from `SourceCandidate -> CapturedPage -> ExtractionResult ->
  EvidenceItem -> RawSource`.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/agents/collectors/logic.py backend/packages/research backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_run_service.py::test_collector_react_runner_searches_fetches_and_finishes backend/tests/unit/test_run_service.py::test_collector_react_finish_fetches_uninspected_urls -q`

## 2026-06-07 - Step 3: Quality Finding Matrix Contract

Scope:

- Added `report_section` and `repairable` to the unified `QualityFinding`
  schema.
- Made `repairable` deterministic from `redo_scope` or actionable
  `required_action` values.
- Updated adapters for RuntimeQA, BusinessQA/ReleaseGate, EvidenceGap, RedTeam,
  ClaimValidator, ResearchPipeline `QualityGap`, and EvalOps to populate a
  reviewable report section.
- Added tests proving the main quality agents share one display/repair contract
  without collapsing their native schemas.

Why:

- C4.4 requires one product surface for quality review while keeping each agent's
  native finding semantics.
- Frontend quality matrix and release review can now rely on typed fields for
  section targeting and repairability instead of parsing finding messages.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/schema/quality.py backend/packages/quality backend/tests/unit/test_quality_findings.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_quality_findings.py backend/tests/unit/test_enterprise_store.py::test_quality_finding_groups_cover_h7_axes -q`

## 2026-06-07 - Step 4: HITL Lifecycle Contract

Scope:

- Added `backend/packages/hitl/lifecycle.py` as the canonical typed contract for
  human intervention lifecycle events.
- Added the unified `HitlLifecycleEvent` states required by Checkpoint 4:
  `requested`, `accepted`, `modified`, `rejected`, `timed_out`, `resumed`,
  `redo_requested`, `revision_created`, `approved`, and `published`.
- Added `HitlLifecyclePayload` validation for agent messages so lifecycle
  records are traceable through the same message/trace channel as other agent
  contracts.
- Wired planner/QA HITL interrupts, reviewer resume decisions, auto-timeout
  acceptance, and manual redo requests through the lifecycle helper in
  `RunService`.
- Wired report approval request/approve/reject/publish transitions into the
  same lifecycle history while keeping the existing `report_lifecycle`,
  `approval_workflow`, and `publication` metadata for compatibility.
- Wired manual report revision to emit `revision_created` lifecycle metadata
  on the new draft report version, not the source version.
- Carried `hitl_lifecycle` through report transition audit metadata and
  decision replay payloads.

Why:

- HITL is now an architecture boundary instead of a set of isolated UI/API
  actions.
- Human review, redo, report revision, approval, and publication can be audited
  and replayed through one event shape.
- Memory feedback remains narrower than lifecycle: it is still captured only
  when the decision carries durable note/dimension/correction value.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/hitl backend/packages/schema/messages.py backend/packages/orchestrator/service.py backend/packages/enterprise/report_lifecycle.py backend/packages/workflows/activities.py backend/app/routers/enterprise.py backend/packages/observability/decision_replay.py backend/tests/unit/test_run_service.py backend/tests/unit/test_temporal_workflows.py backend/tests/unit/test_enterprise_store.py backend/tests/unit/test_observability.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py::test_hitl_uses_langgraph_command_resume_and_updates_plan backend/tests/unit/test_run_service.py::test_hitl_resume_creates_reviewable_memory_candidate backend/tests/unit/test_run_service.py::test_hitl_timeout_auto_accepts_interrupt -q`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_update_report_version_status backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_can_reject_report_version backend/tests/unit/test_enterprise_store.py::test_manual_report_revision_after_rejection_creates_audited_draft backend/tests/unit/test_observability.py::test_decision_replay_preserves_hitl_lifecycle_payload -q`

## 2026-06-07 - Step 5: Orchestration Ownership Boundary

Scope:

- Added `docs/orchestration_ownership_contract_20260607.md` as the C4.6
  ownership contract.
- Linked the contract from
  `docs/checkpoint4_architecture_contract_consolidation_plan.md`.
- Added architecture boundary tests in
  `backend/tests/unit/test_architecture_boundaries.py`.
- Guarded the intended layer split:
  - Temporal is the outer workflow lifecycle shell.
  - LangGraph is the inner Agent DAG.
  - Research Pipeline owns discovery/capture/extraction/admission.
  - Enterprise Store owns durable report/evidence/claim/artifact/audit state.
  - RunService coordinates but should not own publication or source-admission
    rules.

Why:

- C4.6 is about preventing drift. Static ownership tests make it harder for
  future work to accidentally move approval/publication into LangGraph or
  report-version state into the research pipeline.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/tests/unit/test_architecture_boundaries.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_architecture_boundaries.py -q`

## 2026-06-07 - Step 6: Observability And Governance Contract

Scope:

- Added `backend/packages/observability/telemetry_contract.py` as the C4.7
  telemetry contract builder.
- Added canonical telemetry event types:
  `trace_span`, `tool_call`, `model_call`, `token_cost`, `quality_finding`,
  `decision_event`, `audit_event`, `compliance_event`,
  `hitl_lifecycle_event`, and `workflow_event`.
- Added `TelemetryChannelStatus` and `TelemetryRuntimeContract` DTOs to runtime
  API schema.
- Extended `/api/runtime` with a `telemetry` object that explains local trace,
  decision replay, audit, compliance redaction, Langfuse, and OTel status.
- Added `OTEL_EXPORTER_OTLP_ENDPOINT` settings support.
- Added `docs/observability_governance_contract_20260607.md` and linked it
  from the Checkpoint 4 plan.

Why:

- Local observability is now explicitly the baseline.
- Langfuse and OTel are represented as optional hosted exporters rather than
  requirements for local review.
- Runtime status can explain why Langfuse/OTel are disabled while trace,
  decision replay, audit, and compliance remain enabled.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python -m ruff check backend/packages/observability backend/app/routers/runtime.py backend/packages/schema/api_dto.py backend/packages/config/settings.py backend/tests/unit/test_observability.py backend/tests/unit/test_health_router.py`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_observability.py::test_telemetry_contract_separates_local_baseline_from_hosted_exporters backend/tests/unit/test_health_router.py::test_runtime_reports_hitl_and_pydantic_ai_readiness -q`

## 2026-06-07 - Step 7: Runtime Smoke Closure

Scope:

- Restarted the local stack through `scripts/dev_start.ps1` so runtime checks
  used the current C4 code.
- Verified `scripts/dev_status.ps1` showed backend, frontend, Temporal UI,
  Postgres, and Temporal worker healthy, with no active runs.
- Ran the strict Temporal server smoke and wrote
  `docs/reports/checkpoint4_temporal_runtime_smoke_20260607.md`.
- Ran one live API demo smoke through `/api/runs` and verified Temporal 100%
  routing, source-token resolution, Release Gate, Quality Finding Matrix,
  trace observability, and Decision Replay.
- Ran one live API real smoke through `/api/runs` and verified the same C4
  runtime contracts on `execution_mode=real`.
- Ran HITL fixture-backed smoke tests for planner resume, memory feedback,
  timeout, decision replay payloads, and runtime readiness.
- Added `docs/reports/checkpoint4_runtime_smoke_report_20260607.md`.
- Updated the Checkpoint 4 audit and master plan so Checkpoint 4 is closed and
  Checkpoint 5 C5.1 is the next architecture step.

Why:

- C4.1-C4.7 were already code-complete, but the plan still required runtime
  validation before demo acceptance.
- The live smoke proves `/api/runs` uses Temporal, report source tokens resolve
  through the unified identity contract, Release Gate uses report scope, quality
  signals reach the unified matrix, and observability works without hosted
  Langfuse/OTel.

Validation:

- Passed:
  - `conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_server.py --report docs/reports/checkpoint4_temporal_runtime_smoke_20260607.md`
  - `conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py::test_hitl_uses_langgraph_command_resume_and_updates_plan backend/tests/unit/test_run_service.py::test_hitl_resume_creates_reviewable_memory_candidate backend/tests/unit/test_run_service.py::test_hitl_timeout_auto_accepts_interrupt backend/tests/unit/test_observability.py::test_decision_replay_preserves_hitl_lifecycle_payload backend/tests/unit/test_health_router.py::test_runtime_reports_hitl_and_pydantic_ai_readiness -q`
- Live API demo smoke:
  - `run-0f8e50e1c5f90e169912bb197252f561`
  - `status=completed`, `missing_source_tokens=0`,
    `trace_observability=pass`, `release_gate_status=pass`.
- Live API real smoke:
  - `run-ca789f449227ba3c930c722fe209e1ed`
  - `status=completed`, `missing_source_tokens=0`,
    `trace_observability=pass`, `release_gate_status=pass`.
