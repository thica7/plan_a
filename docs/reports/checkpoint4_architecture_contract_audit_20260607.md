# Checkpoint 4 Architecture Contract Audit

Generated: 2026-06-07

## Verdict

Checkpoint 4 architecture contract implementation is code-complete for the
planned contract workstreams:

- C4.1/C4.2 identity resolver and report scope.
- C4.3 Clean Research Pipeline boundary.
- C4.4 Quality Finding Matrix.
- C4.5 HITL lifecycle.
- C4.6 orchestration ownership.
- C4.7 observability/governance telemetry.

Runtime real-run smoke validation should still be performed before treating
this as a final demo acceptance checkpoint. The code-level contract tests pass.

## C4.1/C4.2 Identity Resolver And Report Scope

Status: complete.

Evidence:

- Canonical resolver: `backend/packages/identity/source_resolver.py`.
- Compatibility exports: `backend/packages/sources/references.py`.
- Report scope service: `backend/packages/enterprise/report_scope.py`.
- Release gate metadata uses report scope through
  `RunService._attach_release_gate_quality_metadata`.
- Source snapshots preserve `evidence_id`, `raw_source_id`, and
  `source_tokens`.

Verification:

- `backend/tests/unit/test_source_reconciliation.py`.
- `backend/tests/unit/test_enterprise_store.py::test_report_release_gate_scope_uses_version_competitors_not_stale_project_links`.
- `backend/tests/unit/test_h10_governance.py` source snapshot tests were used
  during Step 1 validation.

## C4.3 Research Pipeline Boundary

Status: complete.

Evidence:

- ReAct collector now proposes `SourceCandidate` objects.
- Clean Research Pipeline owns capture, extraction, admission, and RawSource
  assembly.
- Seed-only discovery is controlled through `ResearchBrief` flags.
- Collector no longer has a second direct `extract_facts -> RawSource`
  admission path.

Verification:

- `backend/tests/unit/test_research_pipeline.py`.
- `backend/tests/unit/test_run_service.py` ReAct collector tests were used
  during Step 2 validation.

## C4.4 Quality Finding Matrix

Status: complete.

Evidence:

- Unified schema: `backend/packages/schema/quality.py`.
- Adapters: `backend/packages/quality/findings.py`.
- Added `report_section` and deterministic `repairable` status.
- RuntimeQA, BusinessQA/ReleaseGate, EvidenceGap, RedTeam, ClaimValidator,
  Research QualityGap, and EvalOps map into the same review surface.

Verification:

- `backend/tests/unit/test_quality_findings.py`.
- `backend/tests/unit/test_enterprise_store.py::test_quality_finding_groups_cover_h7_axes`.

## C4.5 HITL Lifecycle

Status: complete.

Evidence:

- Canonical contract: `backend/packages/hitl/lifecycle.py`.
- Agent message validation: `HitlLifecyclePayload`.
- Run-level planner/QA review, resume, timeout, and manual redo events are
  written through `RunService._record_hitl_lifecycle_event`.
- Report approval request/approve/reject/publish transitions carry
  `hitl_lifecycle` metadata.
- Manual report revision creates a new draft version and records
  `revision_created` against the new draft.
- Decision replay preserves `hitl_lifecycle` payloads.

Verification:

- `backend/tests/unit/test_run_service.py::test_hitl_uses_langgraph_command_resume_and_updates_plan`.
- `backend/tests/unit/test_run_service.py::test_hitl_resume_creates_reviewable_memory_candidate`.
- `backend/tests/unit/test_run_service.py::test_hitl_timeout_auto_accepts_interrupt`.
- `backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_update_report_version_status`.
- `backend/tests/unit/test_temporal_workflows.py::test_report_approval_activities_can_reject_report_version`.
- `backend/tests/unit/test_enterprise_store.py::test_manual_report_revision_after_rejection_creates_audited_draft`.
- `backend/tests/unit/test_observability.py::test_decision_replay_preserves_hitl_lifecycle_payload`.

## C4.6 Orchestration Ownership

Status: complete.

Evidence:

- Contract document:
  `docs/orchestration_ownership_contract_20260607.md`.
- Boundary tests:
  `backend/tests/unit/test_architecture_boundaries.py`.
- Temporal remains outer workflow shell using `RUN_LANGGRAPH_ACTIVITY`.
- LangGraph remains inner Agent DAG and does not publish report versions.
- Research Pipeline does not own approval/publication state.
- `/api/runs` evaluates Temporal cutover before direct `RunService.create_run`.

Verification:

- `backend/tests/unit/test_architecture_boundaries.py`.

## C4.7 Observability And Governance

Status: complete.

Evidence:

- Contract builder:
  `backend/packages/observability/telemetry_contract.py`.
- Runtime DTOs:
  `TelemetryChannelStatus` and `TelemetryRuntimeContract`.
- `/api/runtime` now returns local trace, decision replay, audit,
  compliance redaction, Langfuse, and OTel status.
- `OTEL_EXPORTER_OTLP_ENDPOINT` is represented in settings.
- Contract document:
  `docs/observability_governance_contract_20260607.md`.

Verification:

- `backend/tests/unit/test_observability.py::test_telemetry_contract_separates_local_baseline_from_hosted_exporters`.
- `backend/tests/unit/test_health_router.py::test_runtime_reports_hitl_and_pydantic_ai_readiness`.

## Validation Commands

Passed:

```powershell
conda run -n bd-competiscope-v2 python -m ruff check backend/packages/identity backend/packages/research backend/packages/quality backend/packages/hitl backend/packages/workflows backend/packages/observability backend/packages/orchestrator backend/packages/enterprise/report_scope.py backend/packages/enterprise/source_snapshots.py backend/app/routers/runtime.py backend/app/routers/enterprise.py backend/tests/unit/test_architecture_boundaries.py
```

Passed:

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_source_reconciliation.py backend/tests/unit/test_research_pipeline.py backend/tests/unit/test_quality_findings.py backend/tests/unit/test_architecture_boundaries.py -q
```

Result: 42 passed.

Passed:

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_temporal_workflows.py backend/tests/unit/test_observability.py -q
```

Result: 38 passed.

Passed:

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py -q
```

Result: 41 passed.

## Runtime Smoke Still Recommended

Before using this as a live demo checkpoint, run:

```text
1. Temporal mode real run with HITL disabled.
2. HITL_ENABLED=true fixture-backed or real run to verify planner/QA review
   lifecycle in the UI.
3. Check /api/runtime telemetry status.
4. Check report source tokens, release gate scope, quality matrix, and decision
   replay on the produced run.
```

This is not a code gap in C4.1-C4.7, but it is the final runtime confidence
step before demo acceptance.

