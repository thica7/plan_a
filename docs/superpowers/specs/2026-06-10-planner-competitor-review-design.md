# Planner Competitor Review Design

## Summary

Planner Competitor Review v1 upgrades planner HITL from weak confirmation into a pre-collection run control point. When a run reaches `planner_hitl`, reviewers can quickly correct the competitor set before collector and analyst branches are created. The first version uses a compact table editor for competitors and keeps the existing dimensions edit path.

This design covers P0, P1-lite, and P2:

- P0: planner HITL can modify competitors.
- P1-lite: automatically discovered competitors become reviewable candidates with keep, remove, rename, and add actions.
- P2: competitor confirmation happens before collection so incorrect competitors do not pollute evidence, claims, reports, or enterprise projections.

Temporal remains an outer orchestration shell in this version. The design does not split the LangGraph DAG into planner, collector, analyst, writer, and QA Temporal activities.

## Goals

- Let reviewers remove inaccurate automatically discovered competitors before collection starts.
- Let reviewers add missed competitors before collection starts.
- Let reviewers lightly rename competitors, such as replacing an adjacent candidate with a direct competitor.
- Keep dimensions editing working in the same review surface.
- Persist reviewer edits in HITL lifecycle metadata, run events, and memory feedback candidates.
- Ensure collector and analyst task decomposition uses the corrected competitor list.
- Preserve current direct LangGraph and Temporal outer-shell run paths.

## Non-Goals

- Do not add QA blocker selection or redo-scope override in this version.
- Do not support post-collection competitor rename or evidence migration.
- Do not merge already collected evidence, claims, or report output between competitor names.
- Do not move planner HITL waiting into Temporal signals in this version.
- Do not replace the current LangGraph interrupt/resume protocol.

## User Experience

`PlanReviewModal` becomes a compact review table. It initializes rows from `detail.competitor_discovery.candidates` when available and falls back to `detail.plan.competitors` otherwise.

The table includes:

- Competitor: editable display name.
- Confidence: candidate confidence, or `Manual` for reviewer-added rows.
- Why: candidate rationale with optional reviewer note.
- Evidence: the first one or two candidate evidence links.
- Decision: keep, remove, or mark unrelated.
- Note: reviewer reason or source note.

Reviewer actions:

- Keep an existing candidate.
- Remove an existing candidate from the final plan.
- Mark a candidate as unrelated, which removes it from the final plan and preserves that decision as review metadata.
- Rename a candidate by editing the name cell.
- Add a new competitor manually.
- Edit dimensions using the existing dimensions input behavior.
- Continue as planned, which sends the existing `accept` resume payload.
- Save edited plan, which sends `modify_plan` with dimensions, competitors, and competitor edits.

Save is disabled when no competitor or dimension changes exist. Save is also disabled when the final competitor list is empty.

## API Contract

Extend `HitlResumeRequest` without breaking existing clients.

Current fields remain:

- `decision`: `accept | modify_plan | force_pass | redo`
- `note`
- `dimensions`

New fields:

- `competitors`: optional final competitor list after reviewer edits.
- `competitor_edits`: optional structured edit history.

`CompetitorEdit`:

- `action`: `add | remove | rename | keep | mark_unrelated`
- `name`: original or current competitor name.
- `new_name`: optional renamed competitor name.
- `reason`: optional reviewer reason.
- `source_note`: optional reviewer source or context note.

Example:

```json
{
  "decision": "modify_plan",
  "dimensions": ["pricing", "feature"],
  "competitors": ["Cursor", "GitHub Copilot", "Windsurf"],
  "competitor_edits": [
    {
      "action": "rename",
      "name": "Replit",
      "new_name": "Windsurf",
      "reason": "Reviewer considers Windsurf the direct AI IDE competitor.",
      "source_note": "Manual reviewer correction"
    },
    {
      "action": "remove",
      "name": "Replit",
      "reason": "Not the target market for this analysis."
    }
  ]
}
```

The backend only accepts `competitors` during a pending planner interrupt. Sending competitor edits during QA or outside an active planner interrupt returns a conflict response so the user is not misled into thinking the plan changed.

## Backend Behavior

When `RunService.resume()` receives a `modify_plan` request during `planner_hitl`:

1. Normalize and validate `request.dimensions` using the existing dimension normalization path.
2. Normalize and validate `request.competitors`.
3. Reject an empty final competitor list.
4. Reject a final competitor list over the existing `RunCreateRequest` max of 8.
5. Update `record.detail.plan.competitors`.
6. Update `record.detail.plan.dimensions` when dimensions are present.
7. Refresh `record.detail.plan.task_decomposition`.
8. Update `record.detail.competitor_discovery.selected_competitors`.
9. Preserve discovery candidates and set candidate selection state from the final competitor list.
10. Add or update manual candidates for reviewer-added competitors.
11. Set removed or unrelated candidates to `selected=false`.
12. Lightly migrate `plan.homepage_hints` and `plan.homepage_verified` for rename edits.
13. Drop homepage hint keys for competitors that are no longer in the final list.
14. Record `competitor_edits` in HITL lifecycle metadata.
15. Emit run event metadata that includes final competitors and edit history.
16. Include edit history in memory feedback candidate capture.

The lightweight rename rule applies only before collection starts. It migrates planner metadata such as homepage hints. It does not migrate raw sources, claims, report versions, or enterprise evidence because none should exist yet for the corrected plan branch.

## Data Flow

1. User creates a run.
2. Planner creates or verifies `AnalysisPlan` and may produce `CompetitorDiscovery`.
3. The run enters `planner_hitl` before collector dispatch.
4. Run Detail receives an interrupt event and displays the compact plan review table.
5. Reviewer edits competitors and dimensions.
6. Frontend submits `POST /runs/{run_id}/resume`.
7. Backend validates that the run is waiting at planner review.
8. Backend applies final competitors and dimensions.
9. Backend refreshes task decomposition.
10. LangGraph resumes from the planner checkpoint and collector dispatch uses the corrected competitor set.
11. Collector, analyst, writer, QA, and enterprise projection use the corrected plan.

## Trigger Policy

The feature uses the existing `hitl_enabled` mechanism. Planner competitor review is shown when a planner interrupt is active.

Recommended first-version defaults:

- Keep explicit `hitl_enabled=true` behavior unchanged.
- Enable planner review by default for real-mode topic-only runs where `competitors=[]`.
- Enable planner review when planner produced `CompetitorDiscovery`.
- Preserve opt-out through request or settings so demos, smoke tests, and automation can continue without forced manual intervention.

## Error Handling

- Empty final competitor list: reject with 400 and disable save in the frontend.
- More than 8 final competitors: reject with 400 and show the existing max limit in the frontend.
- Duplicate names after rename: frontend collapses duplicates; backend deduplicates deterministically and records a warning in metadata.
- Competitor edits outside planner HITL: reject with 409.
- Resume without changes: frontend sends existing `accept` payload through Continue as planned.
- HITL timeout: existing timeout auto-accept remains unchanged and applies no competitor edits.
- Temporal route: no special handling. The outer workflow continues to observe the existing LangGraph activity result and state.

## Frontend Implementation Shape

The frontend changes are centered on `PlanReviewModal` and `useRunDetailController`.

`PlanReviewModal` should become a controlled component that receives:

- current dimensions text
- candidate rows
- row edit callbacks
- add/remove/rename callbacks
- final competitor validity
- save eligibility
- continue callback
- save edited plan callback

`useRunDetailController` should derive initial rows from `detail.competitor_discovery` and fall back to `detail.plan.competitors`. It owns the temporary review state and serializes the final payload for `resumeRun()`.

The existing `canApplyPlanDimensions()` and `parsePlanDimensionsInput()` helpers can remain, but competitor-specific helpers should be added near the run-detail plan review code rather than embedded in the component.

## Backend Implementation Shape

The backend changes are centered on:

- `packages/schema/api_dto.py` for `CompetitorEdit` and extended `HitlResumeRequest`.
- `packages/orchestrator/service.py` for applying competitor edits during planner resume.
- Existing task decomposition refresh logic.
- Existing HITL lifecycle and memory feedback capture.

Implementation should use small helper methods:

- normalize requested competitors
- apply competitor edits to discovery
- migrate planner homepage metadata
- build HITL competitor edit metadata

These helpers keep `RunService.resume()` from growing another large inline block.

## Testing

Backend tests:

- `HitlResumeRequest` accepts new fields and remains compatible with old payloads.
- Planner resume updates plan competitors, dimensions, task decomposition, and discovery selection.
- Add, remove, rename, and mark unrelated edits are recorded in lifecycle metadata.
- Rename migrates homepage hints and homepage verification state.
- Removed competitors no longer appear in collector and analyst task decomposition.
- Empty competitor list is rejected.
- More than 8 competitors is rejected.
- Competitor edits outside planner HITL are rejected.
- Existing dimensions-only planner HITL tests still pass.

Frontend tests:

- Plan review rows initialize from discovery candidates.
- Plan review rows fall back to plan competitors.
- Add creates a manual row and final competitor.
- Remove excludes a row from final competitors.
- Rename produces a `rename` edit and final renamed competitor.
- Mark unrelated excludes the row and records the correct edit action.
- Save is disabled when final competitors are empty.
- Save is disabled when no competitor or dimension change exists.
- Save sends `decision=modify_plan`, `dimensions`, `competitors`, and `competitor_edits`.
- Continue as planned sends the existing accept payload.

Acceptance criteria:

- In a topic-only real run, planner review appears before collector starts.
- Reviewer can remove a wrong automatically discovered competitor.
- Reviewer can add a missed competitor.
- Reviewer can lightly rename a candidate.
- The resumed run collector and analyst branches target only the corrected competitor list.
- The final report and enterprise projection use the corrected competitor set.
- Run events and HITL lifecycle show the human edits.
- Current Temporal outer-shell behavior is not broken.

## Risks and Mitigations

- Risk: reviewers expect post-collection rename to merge old evidence.
  Mitigation: first-version UI appears only at planner review and copy indicates changes apply before collection.

- Risk: competitor edits increase `RunService.resume()` complexity.
  Mitigation: use helper functions and focused tests around competitor edit application.

- Risk: automatic HITL default interrupts demo or CI paths.
  Mitigation: preserve explicit opt-out and avoid forcing review in demo/test scenarios unless requested.

- Risk: Temporal remains hard to perceive.
  Mitigation: treat Temporal visibility as a later UI enhancement. This feature strengthens the user-facing HITL control without changing the current Temporal boundary.

## Open Implementation Notes

- Keep the first UI compact and table-based, matching the selected design direction.
- Store reviewer edits as metadata and memory feedback, but do not create a separate durable competitor-edit table in v1.
- Prefer compatibility with current run journal persistence before adding new storage.
- QA redo selection and Temporal deep HITL should be designed separately after planner competitor review is stable.
