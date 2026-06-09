# Competiscope Frontend Redesign Master Plan

Date: 2026-06-09

Status: planning only. Do not implement until the user explicitly approves this plan.

## Purpose

This document locks the frontend redesign direction so later implementation does not drift into small patchwork changes. The redesign target is a coherent enterprise AI competitive intelligence product UI, not a local restyle of individual pages.

The implementation must follow the generated concepts below and preserve the same information architecture, layout model, density, typography, and component system unless the user approves a change.

## Accepted Concept Candidates

These are the current design references to review before implementation.

### New Research Run

Concept path:

```text
C:\Users\888\.codex\generated_images\019e6951-7e89-7ee3-a253-f40f2d414eb0\ig_0fce516f7154945c016a27ac76e4408191978b01b6a35dea29.png
```

Target experience:

- First screen for creating a new research run.
- Left grouped dark navigation.
- Top workspace/product context bar.
- Main two-column run builder.
- Right run readiness rail with runtime, source policy, cost estimate, HITL checkpoints, and Start Run.

### Enterprise Workbench

Concept path:

```text
C:\Users\888\.codex\generated_images\019e6951-7e89-7ee3-a253-f40f2d414eb0\ig_0fce516f7154945c016a27ad13043c819185ade4a0fcba2b2f.png
```

Target experience:

- Main operating dashboard for a competitive intelligence project.
- Project title and top status strip.
- Left project rail.
- Center work area with tabs and dense analytical modules.
- Right Inspector rail for selected evidence/source context.

### Run Report Review Studio

Concept path:

```text
C:\Users\888\.codex\generated_images\019e6951-7e89-7ee3-a253-f40f2d414eb0\ig_0fce516f7154945c016a27b0c290988191b95910af0a84aa14.png
```

Target experience:

- Report review and approval workspace for a completed run.
- Report outline on the left.
- Central report reader with tables and citation tokens.
- Right Source Trace inspector.
- Compact revision loop, approval, and export actions.

## Non-Negotiable Design Direction

The frontend must feel like an enterprise operational product, not a marketing site and not a collection of unrelated cards.

Rules:

- Use a dark navy grouped sidebar.
- Use a white top context bar.
- Use a restrained teal accent.
- Use white surfaces on a very light neutral background.
- Use compact but readable enterprise typography.
- Keep border radius at 8px.
- Use subtle borders and light shadows.
- Do not use decorative gradient blobs, bokeh, or oversized hero composition.
- Do not use nested cards inside cards.
- Do not let each page invent its own layout grammar.
- Do not replace tables and ledgers with card grids when the data is tabular.
- Do not hide the right-side Inspector on desktop widths where the concept shows it.

## Product Information Architecture

The sidebar navigation should be reorganized into groups:

```text
Research
  New Run
  Runs
  Workbench

Evidence
  Sources / Evidence Center
  Reports
  Source Registry / Ingestion Jobs, if exposed later

Analysis
  Competitors
  Dimensions / Feature Matrix, if exposed later
  Benchmarks / Activity

Quality
  Quality Gate / Governance
  Red Team, if exposed later
  Trace Explorer / Activity

Admin
  Workspaces
  Members / Users & Roles
  Settings
```

Current routes stay valid:

```text
/               New Research Run
/history        Runs
/enterprise     Workbench
/evidence       Evidence Center
/reports        Report Studio
/competitors    Competitor Library
/governance     Governance
/activity       Activity
/runs/:runId    Run Detail / Report Review
```

## Global Layout Contract

All major product pages should use this global layout:

```text
AppShell
  Sidebar
    Brand
    NavGroup
    NavItem
    RuntimeStatus
    UserProfile

  ContentShell
    Topbar
      WorkspaceSwitcher
      ProductContextSwitcher
      RuntimeBadges
      CommandSearch
      UserActions

    MainPane
      Page-specific workspace
```

Enterprise pages should use this workspace layout:

```text
WorkspaceLayout
  ProjectHeader
  StatusStrip
  WorkspaceBody
    ProjectRail
    WorkArea
    InspectorRail
```

Report pages should use this review layout:

```text
RunReportReviewStudio
  RunStatusHeader
  ReportWorkspace
    ReportOutline
    ReportReader
    SourceTraceInspector
  ReviewActions
```

## Component Architecture

Shared shell:

```text
components/app-shell/
  Sidebar.tsx
  Topbar.tsx
  nav.ts
  useRuntimeStatus.ts
```

New shared layout/components to create or consolidate:

```text
components/product-shell/
  WorkspaceLayout.tsx
  ProjectHeader.tsx
  StatusStrip.tsx
  InspectorRail.tsx
  MetricTile.tsx
  SectionTabs.tsx
  DataPanel.tsx
  ActionToolbar.tsx
```

New Run:

```text
features/new-run/
  NewRunWorkspace.tsx
  RunScopeForm.tsx
  ScenarioSelector.tsx
  CompetitorPicker.tsx
  DimensionGrid.tsx
  ExecutionModePanel.tsx
  RunReadinessRail.tsx
```

Enterprise Workbench:

```text
features/workbench/
  EnterpriseWorkspace.tsx
  ProjectRail.tsx
  WorkbenchStatusStrip.tsx
  CoverageHeatmap.tsx
  TraceTimeline.tsx
  ReportReviewCard.tsx
  ContextInspector.tsx
```

Run Report:

```text
features/run-detail/
  RunReportReviewStudio.tsx
  ReportOutline.tsx
  ReportReaderWorkspace.tsx
  ReportStatusStrip.tsx

features/report/
  ReportView.tsx
  ReportSourceTrace.tsx
  sourceTokens.ts
```

## Implementation Phases

### Phase 1: Design System Foundation

Goal:

Make every page use the same visual system before page-specific work.

Tasks:

- Consolidate design tokens in `foundation.css`.
- Define colors, spacing, typography, shadows, radii, focus states.
- Normalize button, chip, panel, table, tab, input, and rail styles.
- Remove one-off page-specific styles where they conflict with the concept system.

Suggested commit:

```text
feat(frontend): establish product design system
```

### Phase 2: Global AppShell

Goal:

Opening any page should immediately resemble the concept shell.

Tasks:

- Rebuild `Sidebar.tsx` into grouped navigation.
- Rebuild `Topbar.tsx` into workspace/product context bar.
- Rework `shell.css`.
- Ensure mobile shell does not overflow and remains usable.

Suggested commit:

```text
feat(frontend): rebuild application shell
```

### Phase 3: New Research Run

Goal:

`/` should match the New Research Run concept.

Tasks:

- Rebuild `NewRun.tsx` around a run builder workspace.
- Preserve current submit logic and backend contracts.
- Move runtime readiness, source policy, HITL status, and cost estimate into a right rail.
- Make scenario, competitors, dimensions, depth, and execution mode feel like one coherent builder.

Suggested commit:

```text
feat(frontend): redesign new research run builder
```

### Phase 4: Enterprise Workbench

Goal:

`/enterprise` should match the Enterprise Workbench concept.

Tasks:

- Create shared enterprise workspace layout.
- Keep `ProjectRail` left, work area center, `ContextInspector` right.
- Implement status strip: Scope, Evidence, Report, Release Gate.
- Rework overview modules: Quality score, Coverage heatmap, Trace timeline, Report Review Studio.
- Keep Evidence, Reports, Competitors, Governance, and Activity as tabs within the same layout grammar.

Suggested commit:

```text
feat(frontend): redesign enterprise workbench
```

### Phase 5: Run Report Review Studio

Goal:

`/runs/:runId?view=report` should match the Run Report Review Studio concept.

Tasks:

- Add report outline.
- Keep central report reader wide and readable.
- Move source trace into right inspector rail.
- Keep citation token click behavior.
- Make revision loop compact and review-oriented.
- Keep approval/export actions visible.

Suggested commit:

```text
feat(frontend): redesign report review studio
```

### Phase 6: Secondary Workspaces

Goal:

No old-looking page remains.

Tasks:

- `/history`: Runs table, filters, status/quality summary.
- `/evidence`: Sources ledger with inspector context.
- `/reports`: Report versions, gate, claims, evidence scope.
- `/competitors`: competitor score, coverage matrix, asset cards.
- `/governance`: policy/runtime/compliance control center.
- `/activity`: event stream and benchmark panel.

Suggested commit:

```text
feat(frontend): align secondary workspaces
```

### Phase 7: Fidelity QA

Goal:

Confirm implementation matches the concepts rather than drifting into local fixes.

Required checks:

```text
pnpm -C frontend build
pnpm -C frontend test
```

Screenshot viewports:

```text
1600x1100
1440x900
390x1100
```

Pages to screenshot:

```text
/
/enterprise
/evidence
/reports
/competitors
/runs/:runId?view=report
```

Acceptance criteria:

- No page-level horizontal overflow.
- No text overlap.
- No clipped buttons or chips.
- Right Inspector visible on desktop where concept shows it.
- Mobile layout readable and not just a squeezed desktop.
- Page shell matches concept before individual page details are judged.
- `view_image` comparison is performed between accepted concept and latest implementation screenshot.

## Drift Prevention Rules

Before making any frontend implementation change, check this file first.

Do not:

- Make isolated visual patches without mapping them to a phase above.
- Create a new layout pattern for one page unless the concept requires it.
- Move business logic while doing visual refactor unless absolutely necessary.
- Change backend API contracts as part of this redesign.
- Commit generated screenshot QA artifacts.
- Touch unrelated dirty files.

Each implementation commit should correspond to one phase or one clear page surface.

## Current Approval State

The user has requested the plan and effect images first. Implementation is not approved yet.

Next allowed action after this document:

```text
Wait for user approval.
If approved, start Phase 1: Design System Foundation.
```
