# Orchestration Ownership Contract

Last updated: 2026-06-07

## Purpose

This contract closes Checkpoint 4 C4.6. It defines which layer owns each
enterprise workflow responsibility so future work does not turn `RunService` or
the collector into a hidden owner of every business rule.

## Ownership Map

| Layer | Owns | Must Not Own |
|---|---|---|
| Temporal | Long-running lifecycle, retry policy, schedules, approval workflow, monitor workflow, notification hooks | Agent node DAG, source admission, report text generation |
| LangGraph | One-run agent reasoning DAG, planner, collector dispatch, analyst, comparator, reflector, writer, QA, HITL checkpoints, scoped redo routing | Enterprise approval/publication state, report-version persistence, source snapshot storage |
| Research Pipeline | Source discovery, capture, extraction, evidence admission, quality gaps, repair task proposals | Report publication, report approval, workspace/project persistence |
| Enterprise Store | Workspace/project/run/evidence/claim/report/artifact/audit/memory records | Agent reasoning, web fetching, LLM planning |
| Identity Resolver | RawSource/Evidence/Report/Artifact alias resolution and citation scope | Fetching, extraction, approval decisions |
| HITL Lifecycle | Human review, resume, redo request, manual draft creation, approval, publish event shape | Deciding source quality or rewriting reports |
| Observability | Trace, decision replay, metrics, audit replay, exporter status | Business policy decisions |
| RunService | API coordination, compatibility glue, run state assembly, invoking the correct owner | Source admission rules, report publication rules, workflow lifecycle rules |

## Required Flow

Single real run:

```text
/api/runs
  -> decide_temporal_cutover
  -> Temporal CompetitiveIntelWorkflow, when route=temporal
  -> create_run Activity
  -> run_langgraph_pipeline Activity
  -> LangGraph Agent DAG
  -> load_projection Activity
  -> Enterprise Store projection
```

Direct LangGraph route remains allowed only when cutover policy says
`route=langgraph`.

Report approval:

```text
ReportApprovalWorkflow
  -> request_report_approval Activity
  -> wait for approve/reject signal
  -> approve_report_version or reject_report_version Activity
  -> Enterprise Store report status + audit + HITL lifecycle metadata
```

Publication:

```text
Enterprise report publish endpoint
  -> release gate on ReportVersion scope
  -> mark_report_published
  -> Enterprise Store status + audit + HITL lifecycle metadata
```

LangGraph must never publish a report version directly.

Research:

```text
Collector node
  -> SourceCandidate proposal
  -> Research Pipeline capture/extraction/admission
  -> accepted EvidenceItem / RawSource for this run
```

Research modules must not own approval workflow or publication state.

## Boundary Tests

The static architecture guards live in:

```text
backend/tests/unit/test_architecture_boundaries.py
```

They intentionally check structural invariants rather than one runtime fixture:

- `CompetitiveIntelWorkflow` calls `RUN_LANGGRAPH_ACTIVITY` as an Activity and
  does not import LangGraph builders.
- `/api/runs` evaluates Temporal cutover before direct `RunService.create_run`.
- LangGraph and agent modules do not call report publication or approval
  workflow APIs.
- Research modules do not depend on report publication or approval workflow
  state.

These tests are not a substitute for runtime tests. They are guardrails against
the exact drift Checkpoint 4 is meant to prevent.

## Allowed Coordination

`RunService` may coordinate between owners when necessary:

- Create or load run state.
- Invoke LangGraph.
- Assemble `RunDetail`.
- Persist projection through `EnterpriseStore`.
- Emit events and trace messages.

But new business rules should be placed in the owning layer:

- New source rule -> `backend/packages/research`.
- New citation alias -> `backend/packages/identity`.
- New release rule -> `backend/packages/business_intel/release_gate.py`.
- New approval step -> `backend/packages/workflows` or
  `backend/packages/enterprise/report_lifecycle.py`.
- New HITL event type -> `backend/packages/hitl`.
- New replay/export behavior -> `backend/packages/observability`.

## Definition Of Done For C4.6

C4.6 is complete when:

- This ownership contract is present and linked from Checkpoint 4.
- Boundary tests pass.
- Temporal remains the outer lifecycle shell.
- LangGraph remains the inner Agent DAG.
- Research Pipeline remains the only data capture/extraction/admission owner.
- Enterprise Store remains the durable record owner.

