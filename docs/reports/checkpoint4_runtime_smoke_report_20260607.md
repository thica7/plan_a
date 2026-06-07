# Checkpoint 4 Runtime Smoke Report

Generated: 2026-06-07

## Verdict

Checkpoint 4 runtime smoke passed.

This validates the architecture contracts after the code-level Checkpoint 4
audit:

- Temporal is the live run orchestration route.
- A real API run can complete through Temporal.
- HITL lifecycle contracts are covered through fixture-backed
  `interrupt -> Command(resume=...)` smoke tests.
- `/api/runtime` exposes the C4 telemetry contract.
- Report source tokens resolve without missing-source drift.
- Release Gate, Quality Finding Matrix, trace observability, and Decision
  Replay are available on the produced runtime runs.

## Environment

`scripts/dev_status.ps1` after restart:

```text
Backend health: 200
Frontend health: 200
Temporal UI: 200
run_orchestration_backend: temporal
temporal_traffic_percent: 100
default_execution_mode: real
demo_mode: false
web_search_provider: perplexity
active runs before smoke: none
```

Runtime telemetry from `/api/runtime`:

```text
local_trace.enabled: true
decision_replay.enabled: true
audit.enabled: true
compliance_redaction.enabled: true
langfuse.enabled: false, disabled_reason: not_configured
otel.enabled: false, disabled_reason: not_configured
hosted_exporters_configured: false
event_types include hitl_lifecycle_event and workflow_event
```

This confirms the intended C4.7 contract: local observability is the baseline;
Langfuse and OTel are optional hosted exporters.

## Temporal Server Replay Smoke

Command:

```powershell
conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_server.py --report docs/reports/checkpoint4_temporal_runtime_smoke_20260607.md
```

Result:

```text
ok: true
workflow_id: competitive-intel-0e68ddcdf73b519d5614320fe0f6b068
run_id: run-0e68ddcdf73b519d5614320fe0f6b068
status: completed
task_queue: competitive-intel-smoke-993967f2
report_version_id: report-version-c4823dad3d9ecf74e322
approval_workflow_id: report-approval-a3c4affaad1cda4bbcb84d29bfd8010a
approval_status: approved
workflow_replay_ok: true
workflow_replay_event_count: 23
approval_replay_ok: true
approval_replay_event_count: 21
evidence_count: 2
claim_count: 2
event_count: 30
```

Interpretation:

- CompetitiveIntelWorkflow executed on a real Temporal server.
- ReportApprovalWorkflow executed and approved the report version.
- Both workflow histories replayed successfully through the Temporal Python SDK.

## Live API Demo Smoke

Request:

```text
POST /api/runs
execution_mode: demo
hitl_enabled: false
```

Response:

```text
status_code: 202
X-Run-Orchestration-Route: temporal
X-Temporal-Traffic-Percent: 100
run_id: run-0f8e50e1c5f90e169912bb197252f561
```

Runtime result:

```text
status: completed
execution_mode: demo
project_id: project-eff556d50818a497
report_version_id: report-version-4ae8a3bdbc42be81314e
raw_sources: 2
source_tokens: 2
missing_source_tokens: 0
trace_events: 30
trace_spans: 21
trace_observability: pass
decision_replay_events: 31
quality_matrix_entries: 7
quality_findings: 0
quality_groups: 7
release_gate_allowed: true
release_gate_status: pass
release_gate_issues: 0
```

Interpretation:

- The live FastAPI route selected Temporal, not direct LangGraph.
- Source identity and report scope resolved correctly.
- Quality matrix, Release Gate, trace, and Decision Replay were available.

## Live API Real Smoke

Request:

```text
POST /api/runs
topic: Checkpoint 4 real runtime smoke
competitors: Cursor
dimensions: pricing
execution_mode: real
hitl_enabled: false
```

Response:

```text
status_code: 202
X-Run-Orchestration-Route: temporal
X-Temporal-Traffic-Percent: 100
run_id: run-ca789f449227ba3c930c722fe209e1ed
```

Runtime result:

```text
status: completed
execution_mode: real
project_id: project-0256241d6d188bee
report_version_id: report-version-024fe52ec05967d71e50
raw_sources: 3
source_types: webpage_verified
source_tokens: 3
missing_source_tokens: 0
qa_findings: 9
trace_events: 163
trace_spans: 153
trace_observability: pass
decision_replay_events: 164
quality_matrix_entries: 7
quality_findings: 5
quality_groups: 14
release_gate_allowed: true
release_gate_status: pass
release_gate_issues: 5
report_chars: 19820
```

Interpretation:

- A real execution-mode run completed through the live Temporal cutover.
- Source citation identity stayed consistent: no missing report source tokens.
- The release gate allowed the report, while still surfacing review issues.
- The run produced trace spans, decision replay events, and quality matrix
  entries for review.

## HITL Fixture-Backed Smoke

Command:

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_run_service.py::test_hitl_uses_langgraph_command_resume_and_updates_plan backend/tests/unit/test_run_service.py::test_hitl_resume_creates_reviewable_memory_candidate backend/tests/unit/test_run_service.py::test_hitl_timeout_auto_accepts_interrupt backend/tests/unit/test_observability.py::test_decision_replay_preserves_hitl_lifecycle_payload backend/tests/unit/test_health_router.py::test_runtime_reports_hitl_and_pydantic_ai_readiness -q
```

Result:

```text
5 passed in 2.64s
```

Coverage:

- Planner review can interrupt and resume through LangGraph `Command`.
- Resume decisions record `requested`, `modified`, and `resumed` lifecycle
  events.
- Timeout records `requested`, `timed_out`, and `resumed`.
- Manual HITL feedback can create reviewable MemoryAgent candidates.
- Decision Replay preserves the `hitl_lifecycle` payload.
- Runtime readiness exposes HITL checkpoints and telemetry event types.

## Final Assessment

Checkpoint 4 is now complete for both code contracts and runtime smoke:

- C4.1/C4.2 identity and report scope: passed in live source-token checks.
- C4.3 research boundary: exercised by the real run through live collection.
- C4.4 quality finding matrix: available on demo and real runs.
- C4.5 HITL lifecycle: fixture-backed lifecycle smoke passed.
- C4.6 orchestration ownership: live `/api/runs` routed to Temporal at 100%.
- C4.7 observability/governance: `/api/runtime`, trace observability, and
  decision replay passed.

Remaining work is no longer Checkpoint 4. The next architecture work should move
to Checkpoint 5, starting with the runtime command layer.
