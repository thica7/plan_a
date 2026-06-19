# Perceptible Enterprise Capabilities Design

Date: 2026-06-10

## Purpose

The current project has several enterprise and orchestration capabilities that exist in backend code, API types, tests, or architecture documents, but are weakly visible during normal frontend use. This design makes those capabilities understandable and actionable without a major architecture rewrite.

The first implementation target is product perception and demo credibility:

- users can see where Temporal participates;
- users can correct planner mistakes during HITL;
- users can understand what ScenarioPack changes;
- users can see what RBAC controls;
- users can find and review schema evolution suggestions.

This design intentionally avoids rebuilding the whole orchestration model. It improves the visible product surface and adds only the small API changes needed to make the experience honest.

## Current Findings

### Temporal

`CompetitiveIntelWorkflow` is a thin Temporal wrapper around the existing LangGraph run path: create run, run LangGraph, load enterprise projection. This uses Temporal idempotency, activity retry, and query state, but it does not make Temporal's durable waiting and signal semantics obvious in the main run experience.

More Temporal-native workflows already exist:

- report approval waits for approve or reject signals;
- scheduled scan supports cron-driven workspace scans;
- monitor supports long-running cycles and workflow sleep.

The frontend exposes only small traces of this through status badges and report approval calls. Users cannot easily tell which workflow ran, which stage it is in, or why Temporal matters.

### HITL

Plan HITL currently lets a reviewer edit dimensions only. It does not let the reviewer correct automatically discovered competitors. This is a real product gap because competitor discovery is one of the riskiest automated decisions in the workflow.

The current request model also reflects that limitation: `HitlResumeRequest` accepts `dimensions` but not `competitors`.

### Dynamic Schema Evolution

Backend schema suggestion and review models exist, and the frontend API client has a schema suggestion review function. The user-facing product does not expose an inbox or review queue, so schema evolution is effectively invisible unless someone inspects API payloads or code.

The first visible version should treat schema evolution as a governed suggestion workflow, not as automatic skill-file generation.

### RBAC

Backend RBAC evaluates role, workspace scope, and action. Requests can use `X-User-Role`, `X-User-Id`, and `X-Workspace-Id`. The frontend, however, shows a fixed admin-like identity and does not explain which actions are controlled by RBAC or why a user may be blocked.

The first visible version should be a role and permissions panel, not a full authentication system.

### L1/L2/L3 and ScenarioPack

Layer inference is keyword and count based, with a bias toward L1 when topics or dimensions include pricing, feature, direct comparison, or focused competitor sets. This explains why real runs often classify as L1.

ScenarioPack currently functions as a scenario preset: seed competitors, required dimensions, optional dimensions, QA rules, analyst questions, and evidence requirements. The new run page uses some of this information, but the result page does not explain how the scenario affected collection, QA, or report shape.

## Goals

1. Make Temporal visible in normal run and report-review flows.
2. Let a human correct competitors and dimensions at the planner HITL checkpoint.
3. Explain ScenarioPack impact before and after a run.
4. Make RBAC understandable through current role, workspace scope, and key action permissions.
5. Show schema evolution suggestions in a reviewable inbox.
6. Keep changes incremental and aligned with existing frontend modules.

## Non-Goals

1. Do not replace LangGraph with a fully Temporal-native main workflow.
2. Do not implement a full login, SSO, or workspace switcher.
3. Do not automatically write new skill YAML files from schema suggestions.
4. Do not redesign the whole workbench navigation.
5. Do not rewrite the L1/L2/L3 classifier in this pass.
6. Do not build full scheduled scan or monitor job management UI in this pass.

## Recommended Approach

Use a "perceptible capabilities" pass across existing surfaces:

- New Run shows scenario and layer impact clearly.
- Run Detail shows orchestration state and supports stronger HITL correction.
- Governance shows RBAC and schema evolution.
- Activity or Operations shows workflow timeline and Temporal state.

This approach is faster and lower risk than a full orchestration rewrite, while directly addressing the user's current pain: backend capabilities do not feel present in the product.

## Frontend Design

### New Run Scenario Impact

Enhance the existing Scenario section and readiness rail with a compact ScenarioPack impact summary.

The summary should show:

- selected layer or `Auto`;
- selected ScenarioPack or dynamic scenario;
- seed competitors;
- required dimensions;
- optional dimensions;
- QA rule count;
- evidence requirement count.

When layer selection is `Auto`, the UI should say that the planner will infer L1/L2/L3 from topic, competitors, and dimensions. When the user explicitly selects L2 or L3, the UI should make clear that this is an override sent to the backend.

This keeps L1/L2/L3 honest without changing the classifier yet.

### Run Detail Orchestration Status

Add an orchestration status block near `RunDetailHeader` or `RunSummaryStrip`.

It should show:

- route: Temporal, LangGraph, or unknown;
- workflow id when available;
- task queue when available;
- current workflow state when available;
- current LangGraph node;
- HITL enabled;
- report approval workflow state when a report version has an approval workflow.

If workflow metadata is missing, the UI must say that workflow state is unavailable instead of implying Temporal was used.

### Plan HITL Correction

Upgrade `PlanReviewModal` from dimension-only review to plan review.

The modal should include:

- a comma-separated competitors editor;
- a comma-separated dimensions editor;
- current planner message;
- `Continue current plan`;
- `Apply edited plan`.

`Apply edited plan` is enabled only when competitors or dimensions differ from the current plan and the parsed arrays are non-empty.

The user-facing meaning is simple: if automatic discovery missed, added, or misclassified competitors, the reviewer can correct the plan before collection and analysis fan out.

### Governance RBAC Panel

Add an `Access & RBAC` panel to Governance.

The panel should show:

- current user id;
- role;
- workspace scope;
- policy engine;
- key actions and whether they are allowed.

Suggested key actions:

- project write;
- source write;
- source review;
- schema review;
- report review;
- report publish;
- audit read.

This panel may be read-only in the first version. A demo role switcher is optional only if it can be implemented without pretending to be real authentication.

### Schema Evolution Inbox

Add a `Schema Evolution Inbox` panel to Governance or Quality.

The inbox should show schema suggestions for the selected project or latest run:

- suggested dimension;
- normalized dimension;
- reason;
- source gap ids;
- proposed skill name and required dimension;
- review status when known.

If the backend has the project id and suggestion id, wire accept and reject to the existing schema suggestion review endpoint. If required data is unavailable, show the suggestions read-only with a clear disabled reason.

Empty state should explain the trigger: schema suggestions appear when evidence gaps indicate an emergent dimension outside the current accepted schema.

### Workflow Timeline

Add a lightweight workflow timeline to Activity or Operations.

For competitive-intel runs, display:

- creating run;
- running LangGraph;
- loading projection;
- completed, interrupted, or failed.

For report approval, display:

- approval requested;
- waiting for signal;
- approved, rejected, or timed out.

For scheduled scan and monitor, display "backend workflow available" when there is no active workflow state. Do not build a full management UI in this pass.

## Backend and API Design

### HITL Resume Request

Extend `HitlResumeRequest`:

```python
class HitlResumeRequest(BaseModel):
    decision: Literal["accept", "modify_plan", "force_pass", "redo"]
    note: str | None = None
    competitors: list[str] | None = None
    dimensions: list[str] | None = None
```

For `modify_plan`, the backend should:

- normalize competitors if provided;
- normalize dimensions if provided;
- require at least one competitor after normalization when competitors are provided;
- require at least one dimension after normalization when dimensions are provided;
- update `detail.plan.competitors` and `detail.plan.dimensions`;
- refresh task decomposition;
- continue the existing graph resume path.

Audit metadata should include:

- previous competitors;
- next competitors;
- previous dimensions;
- next dimensions;
- reviewer note presence;
- decision.

### Orchestration Metadata

Prefer deriving orchestration status from existing workflow responses, runtime config, trace events, and audit logs.

If existing data is insufficient, add a small optional field to run detail:

```python
orchestration: {
    "route": "temporal" | "langgraph" | "unknown",
    "workflow_id": str | None,
    "task_queue": str | None,
    "workflow_type": str | None,
    "workflow_status": str | None,
}
```

The field should be optional and backward compatible. The frontend must handle missing data.

### RBAC Context

Add a small endpoint or extend an existing governance endpoint to return the current access context:

```python
{
  "user_id": "system-user",
  "role": "owner",
  "workspace_id": "default-workspace",
  "policy_engine": "internal",
  "actions": [
    {"action": "report:review", "allowed": true, "required_role": "reviewer"},
    {"action": "audit:read", "allowed": true, "required_role": "admin"}
  ]
}
```

This endpoint should use the same `EnterpriseUserContext` and `evaluate_access_policy` path as protected actions.

### Schema Suggestions

Reuse existing schema suggestion payloads and review endpoint. Do not add automatic skill creation.

Frontend data loading can source suggestions from the latest run projection or from a project-level response if one already contains the needed report quality payload.

## Testing Strategy

### Backend Tests

1. `modify_plan` with competitors updates the plan and preserves normalized names.
2. `modify_plan` with dimensions still works as before.
3. `modify_plan` with competitors and dimensions refreshes task decomposition.
4. runtime command audit metadata records previous and next competitors and dimensions.
5. RBAC context endpoint returns allowed and denied actions for viewer, reviewer, analyst, admin, and owner roles.

### Frontend Tests

1. Plan HITL parses competitor and dimension edits and sends both in `resumeRun`.
2. `Apply edited plan` is disabled when no real change exists.
3. Scenario impact renders required dimensions, optional dimensions, seed competitors, QA rules, and evidence requirements.
4. Orchestration status renders Temporal metadata when present and an unavailable state when missing.
5. RBAC panel renders current role and key action decisions.
6. Schema Evolution Inbox renders suggestions, empty state, and disabled review reasons.
7. Workflow timeline renders competitive-intel and report-approval stages.

### Manual Acceptance

Run a demo or real workflow and verify that a user can answer these questions from the frontend alone:

1. Was this run routed through Temporal or LangGraph?
2. What workflow stage is active or completed?
3. Can I correct bad competitor discovery before collection?
4. What did the selected ScenarioPack change?
5. What can my current role do?
6. Did schema evolution suggest a new dimension?

## Rollout Plan

### Phase 1: Honest Visibility

Implement read-only ScenarioPack impact, orchestration status, RBAC panel, schema inbox empty/read-only state, and workflow timeline skeleton.

### Phase 2: HITL Correction

Extend backend HITL resume payload and frontend Plan HITL editing for competitors and dimensions.

### Phase 3: Review Actions

Wire schema suggestion accept and reject where project id and suggestion id are available. Add disabled reasons everywhere else.

### Phase 4: Polish and Demo Script

Add a short demo path that exercises:

- Auto layer with visible inference explanation;
- manual L2 or L3 override;
- Plan HITL competitor correction;
- report approval workflow status;
- RBAC panel;
- schema suggestion inbox.

## Risks and Mitigations

### Risk: Temporal Metadata Is Incomplete

If run detail does not reliably include workflow id, the UI could overclaim Temporal usage.

Mitigation: show explicit unavailable states and only label a run as Temporal when route or workflow metadata exists.

### Risk: HITL Plan Changes Break Downstream State

Changing competitors after planner output can invalidate task decomposition and later collection assumptions.

Mitigation: refresh task decomposition immediately after accepted plan edits and apply the change only before collection proceeds.

### Risk: RBAC Looks Like Authentication

A role panel can be mistaken for a real login system.

Mitigation: label it as access policy context and avoid pretending that the demo role switcher is production auth.

### Risk: Schema Evolution Looks Automatic

Users may expect accepted schema suggestions to immediately create executable extractors.

Mitigation: call the first version a governed suggestion inbox. Accepted suggestions become project memory/metadata, not generated runtime code.

## Success Criteria

The implementation succeeds when the frontend makes the existing enterprise capabilities legible without requiring code inspection.

Specifically:

- Temporal has a visible workflow status or honest unavailable state;
- HITL can correct competitors and dimensions;
- ScenarioPack impact is visible before and after run creation;
- RBAC explains current role and key permissions;
- schema suggestions have an inbox or clear empty state;
- automated tests cover the new contracts and UI states.
